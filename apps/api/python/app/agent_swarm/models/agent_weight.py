"""Agent weight math -- Phase 5. Every function here is a named, citable
algorithm from online-learning / multi-armed-bandit theory, not an
invented formula:

- multiplicative_update: the Hedge / multiplicative-weights-update
  algorithm (Littlestone & Warmuth, "The Weighted Majority Algorithm",
  1994; Freund & Schapire's Hedge, 1997). Standard way to reward/penalize
  a pool of "experts" (here: agent instances) based on how their
  predictions compared to the outcome.
- decay: exponential decay of an agent's weight back toward the neutral
  prior (1.0) when it hasn't been active recently -- "prevent stale
  expertise dominance" from the spec, implemented as a real half-life
  decay rather than an unspecified "decay over time".
- exploration_bonus: UCB1, the upper-confidence-bound bandit algorithm
  (Auer, Cesa-Bianchi & Fischer, "Finite-time Analysis of the
  Multiarmed Bandit Problem", 2002). Gives new/rarely-used agents a
  temporary boost in the consensus weighting so the swarm doesn't
  permanently lock onto whichever agent happened to go first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

LEARNING_RATE = 0.15
DECAY_HALF_LIFE_DAYS = 30.0
MIN_WEIGHT = 0.05
NEUTRAL_WEIGHT = 1.0
EXPLORATION_CONSTANT = 1.0


@dataclass(frozen=True)
class AgentWeight:
    weight: float
    updated_at: datetime


def multiplicative_update(weight: float, reward: float, learning_rate: float = LEARNING_RATE) -> float:
    """reward is in [-1, 1] (+1 = this agent's output was fully
    responsible for a correct/confirmed outcome, -1 = fully responsible
    for a wrong one). weight *= exp(learning_rate * reward), floored at
    MIN_WEIGHT so no agent's vote is ever fully silenced (matches the
    standard Hedge algorithm's guarantee of bounded regret, which
    requires every expert to keep nonzero weight)."""
    if not -1.0 <= reward <= 1.0:
        raise ValueError(f"reward must be in [-1, 1], got {reward}")
    new_weight = weight * math.exp(learning_rate * reward)
    return max(MIN_WEIGHT, new_weight)


def decay(weight: float, elapsed_days: float, half_life_days: float = DECAY_HALF_LIFE_DAYS) -> float:
    """Pulls `weight` back toward NEUTRAL_WEIGHT by half every
    `half_life_days` of inactivity. An agent that won every vote a year
    ago but hasn't run since keeps less and less influence over time,
    rather than indefinitely outvoting agents with more recent track
    records."""
    if elapsed_days < 0:
        raise ValueError("elapsed_days must be >= 0")
    decay_factor = 0.5 ** (elapsed_days / half_life_days)
    return NEUTRAL_WEIGHT + (weight - NEUTRAL_WEIGHT) * decay_factor


def exploration_bonus(
    agent_total_tasks: int,
    swarm_total_tasks: int,
    c: float = EXPLORATION_CONSTANT,
) -> float:
    """UCB1 bonus added to an agent's effective weight when computing
    consensus -- large for an untried agent, shrinking as it accumulates
    tasks. `swarm_total_tasks` is the sum of total_tasks across every
    agent sharing this role, i.e. how many times this "arm" of the
    bandit could have been pulled."""
    if agent_total_tasks < 0 or swarm_total_tasks < 0:
        raise ValueError("task counts must be >= 0")
    if agent_total_tasks == 0:
        return c
    return c * math.sqrt(math.log(swarm_total_tasks + 1) / agent_total_tasks)


def elapsed_days(since: datetime, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    return max(0.0, (now - since).total_seconds() / 86400.0)


def meets_graduation_criteria(
    total_successes: int,
    total_tasks: int,
    consecutive_successes: int,
    *,
    min_accuracy: float = 0.90,
    min_consecutive: int = 50,
) -> bool:
    """Spec's graduation criteria: 90% accuracy AND 50 consecutive
    successful tasks. Both conditions, not either -- a lucky streak
    early on with a poor lifetime accuracy shouldn't graduate an
    amateur out of shadow mode."""
    if total_tasks == 0:
        return False
    accuracy = total_successes / total_tasks
    return accuracy >= min_accuracy and consecutive_successes >= min_consecutive
