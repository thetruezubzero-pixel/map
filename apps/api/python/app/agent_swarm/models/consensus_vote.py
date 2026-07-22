"""Consensus voting -- Phase 5 Step 3. Real, runnable implementations of
the three techniques the spec names:

- Bayesian belief updating: a standard Beta-Binomial conjugate update
  (see e.g. Gelman et al., "Bayesian Data Analysis") over each agent's
  observed success/failure history. Beta(alpha, beta)'s mean is the
  posterior estimate of that agent's reliability; alpha/beta grow by 1
  per observed success/failure, so the estimate sharpens with evidence
  and starts at an uninformative Beta(1,1) (uniform prior) for a new
  agent.
- Monte Carlo simulation: repeatedly sample each candidate output's
  supporting agents' reliabilities from their Beta posteriors, compute
  which output wins the weighted vote *in that sample*, and report the
  empirical win frequency across samples as a risk-aware confidence
  score -- not just the point-estimate weighted average.
- Weighted voting + tie-breaking: groups votes by output, scores each
  group by sum(weight), and on a tie defers to the actuarial-level
  agent with the highest raw weight (an actuarial agent's job per spec
  is exactly this: risk-weighted arbitration).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

DISSENT_CONFIDENCE_THRESHOLD = 0.75


@dataclass(frozen=True)
class Vote:
    agent_id: UUID
    agent_level: str  # 'amateur' | 'actuarial' | 'coordinator'
    weight: float  # effective weight, see credit_assigner.effective_weight
    confidence: float  # 0.0-1.0, this agent's self-reported confidence
    output: dict[str, Any]
    output_key: str  # hashable/comparable summary of `output`, used for grouping
    reasoning: str = ""


@dataclass(frozen=True)
class BayesianConfidence:
    """Beta(alpha, beta) posterior over one agent's reliability."""

    alpha: float = 1.0
    beta: float = 1.0

    @property
    def mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def observations(self) -> float:
        return self.alpha + self.beta - 2.0

    def update(self, success: bool) -> "BayesianConfidence":
        return BayesianConfidence(
            alpha=self.alpha + (1.0 if success else 0.0),
            beta=self.beta + (0.0 if success else 1.0),
        )

    def sample(self, rng: random.Random | None = None) -> float:
        r = rng or random
        return r.betavariate(self.alpha, self.beta)


@dataclass(frozen=True)
class ConsensusResult:
    consensus_output: dict[str, Any]
    consensus_output_key: str
    winning_agent_id: UUID | None
    agreement_ratio: float  # fraction of total vote weight behind the winning output
    escalate_to_human: bool
    escalation_reason: str | None = None


def weighted_consensus(
    votes: list[Vote],
    *,
    dissent_threshold: float = DISSENT_CONFIDENCE_THRESHOLD,
) -> ConsensusResult:
    """Groups votes by output_key, scores each group by
    sum(weight * confidence), and picks the top-scoring group. If the
    runner-up group's top voter is a dissenting agent with confidence
    above `dissent_threshold`, escalate_to_human is set -- a confident
    disagreement is exactly the spec's "if confidence > threshold,
    trigger human review" rule."""
    if not votes:
        return ConsensusResult(
            consensus_output={},
            consensus_output_key="",
            winning_agent_id=None,
            agreement_ratio=0.0,
            escalate_to_human=True,
            escalation_reason="no votes cast",
        )

    groups: dict[str, list[Vote]] = {}
    for v in votes:
        groups.setdefault(v.output_key, []).append(v)

    def group_score(group: list[Vote]) -> float:
        return sum(v.weight * v.confidence for v in group)

    total_weight = sum(v.weight for v in votes) or 1.0
    ranked = sorted(groups.items(), key=lambda kv: group_score(kv[1]), reverse=True)
    winning_key, winning_group = ranked[0]

    # _break_tie already only matters when winning_group has more than one
    # vote at (or near) the top weight -- gating it on len(ranked) == 1 (only
    # one output proposed at all) was wrong: a real multi-group scenario
    # (agents disagreeing) with a weight-tied top pair inside the winning
    # group fell through to "whichever agent the DB happened to return
    # first", silently bypassing the actuarial-arbiter guarantee the
    # docstring above promises. Confirmed live: an amateur vote beat an
    # equally-weighted actuarial vote purely by list order before this fix.
    winning_group_sorted = sorted(winning_group, key=lambda v: v.weight, reverse=True)
    winning_vote = _break_tie(winning_group_sorted)

    agreement_ratio = sum(v.weight for v in winning_group) / total_weight

    escalate = False
    reason = None
    if len(ranked) > 1:
        _, runner_up_group = ranked[1]
        top_dissenter = max(runner_up_group, key=lambda v: v.confidence)
        if top_dissenter.confidence >= dissent_threshold:
            escalate = True
            reason = (
                f"agent {top_dissenter.agent_id} dissented with confidence "
                f"{top_dissenter.confidence:.2f} >= threshold {dissent_threshold}"
            )

    return ConsensusResult(
        consensus_output=winning_vote.output,
        consensus_output_key=winning_key,
        winning_agent_id=winning_vote.agent_id,
        agreement_ratio=agreement_ratio,
        escalate_to_human=escalate,
        escalation_reason=reason,
    )


_ARBITER_PRIORITY = ("coordinator", "actuarial")


def _break_tie(candidates: list[Vote]) -> Vote:
    """Picks the vote credited as the winning group's representative
    (winning_agent_id/consensus_output). Despite the name, this is not
    conditioned on an actual weight tie -- it unconditionally prefers
    the most senior level present in `candidates` over every less-senior
    vote, tied or not (per spec, actuarial agents "can approve/reject
    amateur agent outputs" -- they're a designated arbiter; `coordinator`
    is the tier above that, only reachable via
    swarm_coordinator._maybe_spawn_coordinator's stricter, proven-track-
    record promotion bar, so it outranks actuarial the same way actuarial
    outranks amateur), falling back to highest raw weight only when
    neither senior level is present. `candidates` is always exactly the
    winning group (weighted_consensus never calls this with anything
    else), so this is "who gets credit for this win," not narrowly "who
    wins a tie.\""""
    for level in _ARBITER_PRIORITY:
        senior = [v for v in candidates if v.agent_level == level]
        if senior:
            return max(senior, key=lambda v: v.weight)
    return max(candidates, key=lambda v: v.weight)


def monte_carlo_consensus_risk(
    votes: list[Vote],
    reliabilities: dict[UUID, BayesianConfidence],
    *,
    n_trials: int = 10_000,
    seed: int | None = None,
) -> dict[str, float]:
    """For each of n_trials: sample every agent's reliability from its
    Beta posterior, treat that sample as the probability the agent's
    vote is "trustworthy" this trial (Bernoulli draw), and tally the
    weighted vote using only the trustworthy votes. Returns, per output
    key, the fraction of trials in which it won -- an empirical,
    simulation-based confidence estimate that accounts for uncertainty
    in each agent's reliability, not just a static point estimate.
    """
    rng = random.Random(seed)
    if not votes:
        return {}

    win_counts: dict[str, int] = {}
    for _ in range(n_trials):
        trial_groups: dict[str, float] = {}
        for v in votes:
            reliability = reliabilities.get(v.agent_id, BayesianConfidence())
            p_trustworthy = reliability.sample(rng)
            if rng.random() > p_trustworthy:
                continue  # this agent's vote is "noise" in this trial
            trial_groups[v.output_key] = trial_groups.get(v.output_key, 0.0) + v.weight * v.confidence

        if not trial_groups:
            continue
        trial_winner = max(trial_groups.items(), key=lambda kv: kv[1])[0]
        win_counts[trial_winner] = win_counts.get(trial_winner, 0) + 1

    total_decided = sum(win_counts.values()) or 1
    return {key: count / total_decided for key, count in win_counts.items()}
