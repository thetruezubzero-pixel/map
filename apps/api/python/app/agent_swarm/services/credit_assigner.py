"""Credit assignment -- Phase 5 Step 2. Turns a task outcome (did the
consensus output match what a human reviewer / ground truth confirmed?)
into a per-agent reward, then applies agent_weight.multiplicative_update.

Reward design (spec's "Credit Assignment Algorithm", made concrete):
  1. Task succeeds -> every agent whose vote matched the consensus output
     gets a positive reward; the winning/highest-contribution agent (the
     one the consensus was built around) gets the largest one.
  2. Task fails (or a human rejects it) -> agents get penalized in
     proportion to how confident they were in the (wrong) consensus --
     a confident wrong vote is worse than a hedged wrong vote.
  3. Dissenting agents (voted against a *successful* consensus) get a
     small penalty, not the full penalty a task failure would apply --
     disagreeing isn't necessarily wrong, but it didn't help this time.
  4. Every reward call is followed by exploration_bonus (Step 2 above)
     and, separately, a periodic decay pass (`apply_decay`) run over the
     whole registry, not tied to any single task.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.agent_swarm.models.agent_weight import (
    elapsed_days as _elapsed_days,
)
from app.agent_swarm.models.agent_weight import (
    decay as _decay,
)
from app.agent_swarm.models.agent_weight import (
    exploration_bonus as _exploration_bonus,
)
from app.agent_swarm.models.agent_weight import (
    multiplicative_update as _multiplicative_update,
)
from app.agent_swarm.models.consensus_vote import Vote

logger = logging.getLogger("aether.agent_swarm.credit_assigner")

WIN_REWARD = 1.0
AGREE_REWARD = 0.4
DISSENT_ON_SUCCESS_PENALTY = -0.1
WRONG_VOTE_BASE_PENALTY = -0.6


@dataclass(frozen=True)
class RewardEvent:
    agent_id: UUID
    reward: float
    reason: str


def compute_rewards(
    votes: list[Vote],
    winning_agent_id: UUID | None,
    consensus_output_key: str,
    task_succeeded: bool,
) -> list[RewardEvent]:
    """Pure function: given the votes cast for one task_history row and
    whether the eventual outcome was confirmed correct, returns the
    reward each voting agent earned. Doesn't touch the database --
    apply_rewards below does that, so this stays trivially unit-testable.
    """
    events: list[RewardEvent] = []
    for vote in votes:
        agreed_with_consensus = vote.output_key == consensus_output_key

        if task_succeeded:
            if vote.agent_id == winning_agent_id:
                reward = WIN_REWARD
                reason = "win"
            elif agreed_with_consensus:
                reward = AGREE_REWARD
                reason = "agree"
            else:
                reward = DISSENT_ON_SUCCESS_PENALTY
                reason = "dissent_on_success"
        else:
            # Confident + wrong is worse than hedged + wrong -- scale the
            # base penalty by how sure this agent was.
            reward = WRONG_VOTE_BASE_PENALTY * max(vote.confidence, 0.1)
            reason = "wrong_on_failure"

        events.append(RewardEvent(agent_id=vote.agent_id, reward=reward, reason=reason))
    return events


async def apply_rewards(pool, task_id: UUID | None, events: list[RewardEvent]) -> None:
    """Writes each reward to weight_history and updates
    agent_registry.current_weight/consecutive_successes/total_* in one
    transaction per agent. Idempotent at the task level via
    task_history.reward_applied, checked by the caller (see
    swarm_coordinator.finalize_task) before this is invoked.

    `task_id` is nullable (weight_history.task_id is a nullable FK to
    task_history) for callers that don't have a task_history row at all --
    routers/architect.py uses this to reward project_architect's real,
    per-cycle proposal outcomes (see change_proposer.propose_change /
    architect_committer.sync_project_plan_doc), a single non-swarmed agent
    that never appears in task_history."""
    for event in events:
        async with pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT current_weight, total_tasks, total_successes, consecutive_successes "
                "FROM agent_registry WHERE id = $1 FOR UPDATE",
                event.agent_id,
            )
            if row is None:
                logger.warning("credit_assigner: agent %s not found, skipping reward", event.agent_id)
                continue

            old_weight = float(row["current_weight"])
            new_weight = _multiplicative_update(old_weight, event.reward)
            success = event.reward > 0
            new_consecutive = row["consecutive_successes"] + 1 if success else 0

            await conn.execute(
                """
                UPDATE agent_registry
                SET current_weight = $2,
                    total_tasks = total_tasks + 1,
                    total_successes = total_successes + $3,
                    consecutive_successes = $4,
                    updated_at = now()
                WHERE id = $1
                """,
                event.agent_id,
                new_weight,
                1 if success else 0,
                new_consecutive,
            )
            await conn.execute(
                """
                INSERT INTO weight_history (agent_id, weight, delta, reason, task_id)
                VALUES ($1, $2, $3, $4, $5)
                """,
                event.agent_id,
                new_weight,
                new_weight - old_weight,
                f"task:{event.reason}",
                task_id,
            )


async def apply_decay(pool, *, half_life_days: float = 30.0, now: datetime | None = None) -> int:
    """Periodic maintenance pass (not tied to any single task): pulls
    every agent's weight back toward the neutral prior in proportion to
    how long it's been since its last weight_history entry. Returns the
    number of agents updated. Call this from a scheduled job (Airflow or
    a simple cron), not from the request path."""
    rows = await pool.fetch(
        """
        SELECT ar.id, ar.current_weight, COALESCE(MAX(wh.created_at), ar.created_at) AS last_activity
        FROM agent_registry ar
        LEFT JOIN weight_history wh ON wh.agent_id = ar.id
        GROUP BY ar.id, ar.current_weight, ar.created_at
        """
    )
    updated = 0
    for row in rows:
        days = _elapsed_days(row["last_activity"], now)
        if days < 1.0:
            continue  # nothing meaningful decays in under a day
        old_weight = float(row["current_weight"])
        new_weight = _decay(old_weight, days, half_life_days)
        if new_weight == old_weight:
            continue
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                "UPDATE agent_registry SET current_weight = $2, updated_at = now() WHERE id = $1",
                row["id"],
                new_weight,
            )
            await conn.execute(
                "INSERT INTO weight_history (agent_id, weight, delta, reason) VALUES ($1, $2, $3, 'decay')",
                row["id"],
                new_weight,
                new_weight - old_weight,
            )
        updated += 1
    return updated


def effective_weight(current_weight: float, agent_total_tasks: int, swarm_total_tasks: int) -> float:
    """What consensus_vote.py actually weights each vote by: the agent's
    learned weight plus its current UCB1 exploration bonus. A brand-new
    agent (weight=1.0, zero tasks) gets a real say in its very first
    vote instead of being drowned out by agents with a head start."""
    return current_weight + _exploration_bonus(agent_total_tasks, swarm_total_tasks)
