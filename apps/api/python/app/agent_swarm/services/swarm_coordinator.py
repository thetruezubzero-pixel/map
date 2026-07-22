"""Swarm coordinator -- Phase 5 Step 4. Orchestrates multiple weighted
instances of the existing query_analyzer/result_synthesizer agents
(app/agents/) per research job, combines their outputs via
consensus_vote.weighted_consensus, and records the vote for later credit
assignment.

Scope note, stated plainly rather than glossed over: `data_retriever` is
deterministic tool execution (call these public APIs, return what they
return) -- there's no judgment call for multiple instances to disagree
about, so it runs as a single agent, same as before Phase 5. The
consensus/voting machinery below applies to query_analyzer (which
entity types/sources to search -- a real categorical decision multiple
models can genuinely disagree on) and result_synthesizer (free-text
summarization, where "agreement" mostly means "pick the
highest-weighted-confidence output" rather than true multi-way voting,
since two independent LLM calls essentially never produce identical
prose -- documented here rather than pretended otherwise).

Amateur agents run in shadow mode until they graduate
(agent_weight.meets_graduation_criteria): they make real calls and their
output is recorded and reward-eligible (so they build a track record),
but their vote weight is forced to 0 for the actual consensus decision,
matching the spec's "observe senior agents before acting."
"""

from __future__ import annotations

import logging
from uuid import UUID

from app.agent_swarm.models.agent_weight import meets_graduation_criteria
from app.agent_swarm.models.consensus_vote import BayesianConfidence, ConsensusResult, Vote, weighted_consensus
from app.agent_swarm.services.credit_assigner import effective_weight
from app.agents.query_analyzer import QueryAnalyzerAgent
from app.agents.result_synthesizer import ResultSynthesizerAgent
from app.config import get_settings
from app.models import ResearchPlan, ResearchReport, SourcedRecord

logger = logging.getLogger("aether.agent_swarm.swarm_coordinator")

query_analyzer_agent = QueryAnalyzerAgent()
result_synthesizer_agent = ResultSynthesizerAgent()


def _default_roster(settings) -> dict[str, list[tuple[str, str]]]:
    """(level, model) pairs seeded per role when a user has no agents
    registered yet. Two amateurs give the swarm someone to actually be
    in shadow mode; one actuarial agent is the senior voice whose vote
    counts from day one -- matching "each amateur assigned to one
    actuarial agent" mentorship pairing (wired in ensure_default_agents)."""
    return {
        "query_analyzer": [
            ("amateur", settings.openrouter_fast_model),
            ("amateur", settings.openrouter_fast_model),
            ("actuarial", settings.openrouter_default_model),
        ],
        "result_synthesizer": [
            ("amateur", settings.openrouter_fast_model),
            ("amateur", settings.openrouter_fast_model),
            ("actuarial", settings.openrouter_default_model),
        ],
        "data_retriever": [
            ("actuarial", settings.openrouter_default_model),
        ],
    }


async def ensure_default_agents(pool, user_id: str | None = None) -> dict[str, list[UUID]]:
    """Idempotent: if agents already exist for (role, user_id), leaves
    them alone. Returns the agent ids per role, existing or newly
    created. user_id=None seeds the shared/platform-default roster."""
    settings = get_settings()
    roster = _default_roster(settings)
    result: dict[str, list[UUID]] = {}

    for role, instances in roster.items():
        existing = await pool.fetch(
            "SELECT id FROM agent_registry WHERE role = $1 AND user_id IS NOT DISTINCT FROM $2",
            role,
            user_id,
        )
        if existing:
            result[role] = [r["id"] for r in existing]
            continue

        ids: list[UUID] = []
        mentor_id: UUID | None = None
        for level, model in instances:
            row = await pool.fetchrow(
                """
                INSERT INTO agent_registry (name, role, level, model, user_id, mentor_agent_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                f"{role}-{level}-{model}",
                role,
                level,
                model,
                user_id,
                mentor_id if level == "amateur" else None,
            )
            ids.append(row["id"])
            if level == "actuarial" and mentor_id is None:
                mentor_id = row["id"]  # first actuarial agent mentors this role's amateurs

        # Backfill mentor_agent_id for amateurs registered before the
        # actuarial agent existed in this loop iteration.
        if mentor_id is not None:
            await pool.execute(
                "UPDATE agent_registry SET mentor_agent_id = $1 WHERE role = $2 AND user_id IS NOT DISTINCT FROM $3 "
                "AND level = 'amateur' AND mentor_agent_id IS NULL",
                mentor_id,
                role,
                user_id,
            )

        result[role] = ids

    return result


async def _load_agents(pool, role: str, user_id: str | None) -> list:
    return await pool.fetch(
        """
        SELECT id, level, model, current_weight, total_tasks, total_successes, consecutive_successes
        FROM agent_registry
        WHERE role = $1 AND user_id IS NOT DISTINCT FROM $2
        """,
        role,
        user_id,
    )


def _agent_confidence(agent) -> float:
    """Beta(1 + successes, 1 + failures) posterior mean -- the Bayesian
    belief-updating step. A brand-new agent (0 tasks) gets the
    uninformative-prior mean of 0.5."""
    successes = agent["total_successes"]
    failures = agent["total_tasks"] - successes
    return BayesianConfidence(alpha=1 + successes, beta=1 + failures).mean


def _vote_weight(agent, swarm_total_tasks: int) -> float:
    if agent["level"] == "amateur" and not meets_graduation_criteria(
        agent["total_successes"], agent["total_tasks"], agent["consecutive_successes"]
    ):
        return 0.0  # shadow mode: real vote recorded, zero influence on consensus
    return effective_weight(float(agent["current_weight"]), agent["total_tasks"], swarm_total_tasks)


async def _persist_task(
    pool, job_id: UUID | None, role: str, votes: list[Vote], result: ConsensusResult
) -> UUID:
    import json as _json

    # asyncpg has no default Python-object -> jsonb codec (confirmed
    # live -- passing a raw list/dict for a jsonb column raised an
    # encoding error before this was fixed); every other jsonb write in
    # this codebase (see app/db.py) goes through json.dumps() first.
    row = await pool.fetchrow(
        """
        INSERT INTO task_history (job_id, role, agents_involved, votes, consensus_output, winning_agent_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        job_id,
        role,
        [v.agent_id for v in votes],
        _json.dumps(
            [
                {
                    "agent_id": str(v.agent_id),
                    "agent_level": v.agent_level,
                    "weight": v.weight,
                    "confidence": v.confidence,
                    "output_key": v.output_key,
                    "reasoning": v.reasoning,
                }
                for v in votes
            ]
        ),
        _json.dumps(result.consensus_output),
        result.winning_agent_id,
    )
    if result.escalate_to_human:
        logger.info(
            "swarm_coordinator: task %s (%s) escalated to human review: %s",
            row["id"],
            role,
            result.escalation_reason,
        )
    return row["id"]


async def run_query_analyzer_swarm(
    pool, query: str, job_id: UUID | None = None, user_id: str | None = None
) -> tuple[ResearchPlan, UUID]:
    await ensure_default_agents(pool, user_id)
    agents = await _load_agents(pool, "query_analyzer", user_id)
    swarm_total_tasks = sum(a["total_tasks"] for a in agents) or 1

    votes: list[Vote] = []
    plans_by_agent: dict[UUID, ResearchPlan] = {}
    for agent in agents:
        try:
            plan = await query_analyzer_agent.run(query, job_id=job_id, model=agent["model"])
        except Exception as exc:  # noqa: BLE001 -- one agent instance failing must not sink the swarm
            logger.warning("query_analyzer agent %s (%s) failed: %s", agent["id"], agent["model"], exc)
            continue
        plans_by_agent[agent["id"]] = plan
        votes.append(
            Vote(
                agent_id=agent["id"],
                agent_level=agent["level"],
                weight=_vote_weight(agent, swarm_total_tasks),
                confidence=_agent_confidence(agent),
                output=plan.model_dump(mode="json"),
                output_key=",".join(sorted(t.value for t in plan.entity_types)) or "empty",
                reasoning=plan.notes or "",
            )
        )

    if not votes:
        # Every agent instance failed (e.g. OpenRouter unreachable) --
        # degrade to the plain single-agent path rather than raising, per
        # spec's "Cascading failure -> degrade to single senior agent
        # mode". This call uses the same default model the pre-swarm
        # pipeline always used.
        logger.warning("query_analyzer swarm: all agents failed, degrading to single-agent mode")
        plan = await query_analyzer_agent.run(query, job_id=job_id)
        return plan, await _persist_task(
            pool,
            job_id,
            "query_analyzer",
            [],
            ConsensusResult(
                consensus_output=plan.model_dump(mode="json"),
                consensus_output_key=",".join(sorted(t.value for t in plan.entity_types)) or "empty",
                winning_agent_id=None,
                agreement_ratio=0.0,
                escalate_to_human=True,
                escalation_reason="swarm degraded to single-agent mode (all agent instances failed)",
            ),
        )

    result = weighted_consensus(votes)
    task_id = await _persist_task(pool, job_id, "query_analyzer", votes, result)
    winning_plan = plans_by_agent.get(result.winning_agent_id) or next(iter(plans_by_agent.values()))
    return winning_plan, task_id


async def run_result_synthesizer_swarm(
    pool,
    plan: ResearchPlan,
    records: list[SourcedRecord],
    job_id: UUID | None = None,
    user_id: str | None = None,
) -> tuple[ResearchReport, UUID]:
    await ensure_default_agents(pool, user_id)
    agents = await _load_agents(pool, "result_synthesizer", user_id)
    swarm_total_tasks = sum(a["total_tasks"] for a in agents) or 1

    votes: list[Vote] = []
    reports_by_agent: dict[UUID, ResearchReport] = {}
    for agent in agents:
        try:
            report = await result_synthesizer_agent.run(plan, records, job_id=job_id, model=agent["model"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("result_synthesizer agent %s (%s) failed: %s", agent["id"], agent["model"], exc)
            continue
        reports_by_agent[agent["id"]] = report
        # Free-text summaries essentially never match verbatim -- see
        # module docstring. output_key is per-agent-unique on purpose so
        # weighted_consensus degrades to "pick highest weight*confidence"
        # rather than pretending prose agreement is meaningful here.
        votes.append(
            Vote(
                agent_id=agent["id"],
                agent_level=agent["level"],
                weight=_vote_weight(agent, swarm_total_tasks),
                confidence=_agent_confidence(agent),
                output=report.model_dump(mode="json"),
                output_key=str(agent["id"]),
                reasoning=report.summary[:200],
            )
        )

    if not votes:
        logger.warning("result_synthesizer swarm: all agents failed, degrading to single-agent mode")
        report = await result_synthesizer_agent.run(plan, records, job_id=job_id)
        return report, await _persist_task(
            pool,
            job_id,
            "result_synthesizer",
            [],
            ConsensusResult(
                consensus_output=report.model_dump(mode="json"),
                consensus_output_key="degraded",
                winning_agent_id=None,
                agreement_ratio=0.0,
                escalate_to_human=True,
                escalation_reason="swarm degraded to single-agent mode (all agent instances failed)",
            ),
        )

    result = weighted_consensus(votes)
    task_id = await _persist_task(pool, job_id, "result_synthesizer", votes, result)
    winning_report = reports_by_agent.get(result.winning_agent_id) or next(iter(reports_by_agent.values()))
    return winning_report, task_id


async def run_data_retriever_single(pool, plan: ResearchPlan, job_id: UUID | None, user_id: str | None = None):
    """No consensus round -- see module docstring for why. Still records
    a single-vote task_history row so the role shows up in the swarm
    dashboard/history consistently with the other two roles."""
    from app.agents.data_retriever import DataRetrieverAgent

    await ensure_default_agents(pool, user_id)
    agents = await _load_agents(pool, "data_retriever", user_id)
    agent = agents[0] if agents else None

    records = await DataRetrieverAgent().run(plan, job_id=job_id)

    if agent is not None:
        vote = Vote(
            agent_id=agent["id"],
            agent_level=agent["level"],
            weight=1.0,
            confidence=1.0,
            output={"record_count": len(records)},
            output_key="single",
            reasoning="deterministic tool execution, no consensus round",
        )
        await _persist_task(
            pool,
            job_id,
            "data_retriever",
            [vote],
            ConsensusResult(
                consensus_output={"record_count": len(records)},
                consensus_output_key="single",
                winning_agent_id=agent["id"],
                agreement_ratio=1.0,
                escalate_to_human=False,
            ),
        )

    return records


async def finalize_task(pool, task_id: UUID, *, succeeded: bool, ground_truth: dict | None = None) -> int:
    """Call once a task's outcome is known (a human confirms/rejects the
    research_jobs review, or the job fails outright). Applies
    credit_assigner rewards and marks the task as settled so a retry
    can't double-apply them. Returns the number of agents rewarded."""
    import json as _json

    from app.agent_swarm.models.consensus_vote import Vote as _Vote
    from app.agent_swarm.services.credit_assigner import apply_rewards, compute_rewards

    task = await pool.fetchrow(
        "SELECT votes, consensus_output, winning_agent_id, reward_applied FROM task_history WHERE id = $1",
        task_id,
    )
    if task is None or task["reward_applied"]:
        return 0

    # asyncpg returns JSONB columns as raw JSON text, not pre-parsed --
    # confirmed live (a naive `for v in task["votes"]` iterated the
    # string's characters, not JSON objects, before this was fixed).
    raw_votes = task["votes"]
    stored_votes = _json.loads(raw_votes) if isinstance(raw_votes, str) else raw_votes

    votes = [
        _Vote(
            agent_id=UUID(v["agent_id"]),
            agent_level=v["agent_level"],
            weight=v["weight"],
            confidence=v["confidence"],
            output={},
            output_key=v["output_key"],
            reasoning=v.get("reasoning", ""),
        )
        for v in stored_votes
    ]
    if not votes:
        await pool.execute("UPDATE task_history SET reward_applied = true, ground_truth = $2 WHERE id = $1", task_id, ground_truth)
        return 0

    winning_vote = next((v for v in votes if v.agent_id == task["winning_agent_id"]), votes[0])
    events = compute_rewards(votes, task["winning_agent_id"], winning_vote.output_key, succeeded)
    await apply_rewards(pool, task_id, events)
    await pool.execute(
        "UPDATE task_history SET reward_applied = true, ground_truth = $2 WHERE id = $1", task_id, ground_truth
    )
    return len(events)
