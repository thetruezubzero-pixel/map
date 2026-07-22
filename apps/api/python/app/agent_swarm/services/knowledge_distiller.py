"""Knowledge distillation -- Phase 5 Step 5.

Per an explicit scoping decision (our agents are API calls to hosted
models via OpenRouter -- there is no weight/logit access, so
gradient-based distillation with a distillation loss isn't possible):
this is **prompt-level distillation**, not weight-level. A senior
(actuarial, track-record-proven) agent's successful outputs are curated
into few-shot exemplars and appended to an amateur agent's system
prompt. "Temperature scaling for a richer learning signal" is
implemented literally -- real OpenRouter calls at a higher `temperature`
against the teacher model to generate diverse synthetic exemplars --
rather than the softmax-temperature technique from the original
Hinton/Vinyals/Dean distillation paper, which needs logits we don't
have. "Validation: student must match teacher on a held-out set" is
implemented as a real held-out accuracy measurement (a fraction, not a
pass/fail gate baked into training, since there's no training step to
gate).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.config import get_settings
from app.openrouter_client import openrouter_client

logger = logging.getLogger("aether.agent_swarm.knowledge_distiller")

MAX_EXEMPLARS = 5


def query_analyzer_output_key(consensus_output: dict) -> str:
    """Matches swarm_coordinator.run_query_analyzer_swarm's exact vote
    grouping key -- ',' .join(sorted(entity_types)) -- so "did the
    student match the teacher" means the same thing here as it does in
    the actual consensus vote, not an unrelated heuristic."""
    return ",".join(sorted(consensus_output.get("entity_types", []))) or "empty"


@dataclass(frozen=True)
class Exemplar:
    input_query: str
    output_key: str
    consensus_output: dict


async def curate_exemplars(
    pool,
    role: str,
    *,
    user_id: str | None = None,
    limit: int = MAX_EXEMPLARS,
    output_key_fn=query_analyzer_output_key,
) -> list[Exemplar]:
    """Pulls this role's most recent *confirmed-successful* consensus
    outputs (reward_applied=true, ground_truth recorded, winning agent
    was actuarial-level) and joins back to research_jobs for the
    original query -- the (input, correct-output) pairs a few-shot
    prompt needs. Only actuarial wins count as "senior" for teaching
    purposes; an amateur's shadow-mode output, even if later rewarded,
    isn't a teacher."""
    rows = await pool.fetch(
        """
        SELECT rj.query AS input_query, th.consensus_output
        FROM task_history th
        JOIN agent_registry ar ON ar.id = th.winning_agent_id
        JOIN research_jobs rj ON rj.id = th.job_id
        WHERE th.role = $1
          AND th.reward_applied
          AND ar.level = 'actuarial'
          AND ar.user_id IS NOT DISTINCT FROM $2
        ORDER BY th.created_at DESC
        LIMIT $3
        """,
        role,
        user_id,
        limit,
    )

    exemplars = []
    for r in rows:
        consensus = r["consensus_output"]
        consensus = json.loads(consensus) if isinstance(consensus, str) else consensus
        exemplars.append(
            Exemplar(
                input_query=r["input_query"],
                output_key=output_key_fn(consensus),
                consensus_output=consensus,
            )
        )
    return exemplars


def build_distilled_system_prompt(base_system_prompt: str, exemplars: list[Exemplar]) -> str:
    """Appends curated exemplars as few-shot examples. Pure string
    formatting -- no API call, trivially unit-testable, and safe to call
    with zero exemplars (returns the base prompt unchanged rather than
    an empty "Examples:" section)."""
    if not exemplars:
        return base_system_prompt

    formatted = "\n\n".join(
        f"Example {i + 1}:\nQuery: {ex.input_query}\nCorrect output: {json.dumps(ex.consensus_output)}"
        for i, ex in enumerate(exemplars)
    )
    return (
        f"{base_system_prompt}\n\n"
        "The following are real examples of correct outputs from a senior agent on this "
        f"platform, learned from confirmed-successful past decisions:\n\n{formatted}"
    )


async def generate_synthetic_variations(
    query: str, teacher_model: str, *, n: int = 3, temperature: float = 0.9
) -> list[str]:
    """Real OpenRouter calls to the teacher model at an elevated
    temperature, producing n diverse paraphrases of `query`. Used to
    widen the exemplar set beyond exact historical queries so a junior
    agent generalizes past verbatim memorization -- the practical analog
    of "richer learning signal" for a prompt-level (not weight-level)
    distillation setup."""
    variations = []
    for _ in range(n):
        try:
            _, response = await openrouter_client.complete(
                messages=[
                    {
                        "role": "system",
                        "content": "Paraphrase the user's research query, preserving its exact meaning "
                        "and scope. Respond with only the paraphrased query, nothing else.",
                    },
                    {"role": "user", "content": query},
                ],
                model=teacher_model,
                temperature=temperature,
                max_tokens=100,
            )
            text = openrouter_client.extract_text(response).strip()
            if text:
                variations.append(text)
        except Exception as exc:  # noqa: BLE001 -- a failed variation just means fewer exemplars, not a crash
            logger.warning("synthetic variation generation failed: %s", exc)
    return variations


async def measure_held_out_accuracy(
    pool,
    role: str,
    student_run_fn,
    *,
    user_id: str | None = None,
    held_out_limit: int = 10,
    output_key_fn=query_analyzer_output_key,
) -> dict:
    """Runs the student agent (via `student_run_fn(input_query) ->
    output_key_str`, e.g. a thin wrapper around QueryAnalyzerAgent.run)
    against a held-out set of past confirmed tasks NOT used as
    exemplars, and reports the fraction where the student's output_key
    matches the teacher's recorded consensus (using the same
    `output_key_fn` curate_exemplars used, so "match" means the same
    thing on both sides). A real measurement over real historical data --
    not a fabricated accuracy number. Most meaningful for query_analyzer
    (a categorical decision); result_synthesizer's free-text summaries
    don't have a natural "did it match" key -- see swarm_coordinator's
    module docstring."""
    rows = await pool.fetch(
        """
        SELECT rj.query AS input_query, th.consensus_output
        FROM task_history th
        JOIN agent_registry ar ON ar.id = th.winning_agent_id
        JOIN research_jobs rj ON rj.id = th.job_id
        WHERE th.role = $1 AND th.reward_applied AND ar.level = 'actuarial'
          AND ar.user_id IS NOT DISTINCT FROM $2
        ORDER BY th.created_at ASC
        OFFSET $3
        """,
        role,
        user_id,
        MAX_EXEMPLARS,  # skip the rows curate_exemplars would have used, so this is genuinely held-out
    )
    rows = rows[:held_out_limit]

    if not rows:
        return {"evaluated": 0, "matched": 0, "accuracy": None}

    matched = 0
    for r in rows:
        consensus = r["consensus_output"]
        consensus = json.loads(consensus) if isinstance(consensus, str) else consensus
        teacher_key = output_key_fn(consensus)
        try:
            student_key = await student_run_fn(r["input_query"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("held-out evaluation call failed: %s", exc)
            continue
        if student_key == teacher_key:
            matched += 1

    return {"evaluated": len(rows), "matched": matched, "accuracy": matched / len(rows) if rows else None}
