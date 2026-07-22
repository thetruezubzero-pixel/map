import uuid

import pytest

from app.agent_swarm.models.consensus_vote import (
    BayesianConfidence,
    Vote,
    monte_carlo_consensus_risk,
    weighted_consensus,
)

AGENT_A = uuid.uuid4()
AGENT_B = uuid.uuid4()
AGENT_C = uuid.uuid4()


def make_vote(agent_id, level, weight, confidence, key, output=None):
    return Vote(
        agent_id=agent_id,
        agent_level=level,
        weight=weight,
        confidence=confidence,
        output=output or {"key": key},
        output_key=key,
    )


def test_weighted_consensus_picks_highest_scoring_group():
    votes = [
        make_vote(AGENT_A, "amateur", 1.0, 0.9, "business"),
        make_vote(AGENT_B, "actuarial", 2.0, 0.9, "business"),
        make_vote(AGENT_C, "amateur", 1.0, 0.9, "government_filing"),
    ]
    result = weighted_consensus(votes)
    assert result.consensus_output_key == "business"
    assert result.winning_agent_id == AGENT_B


def test_weighted_consensus_no_votes_escalates():
    result = weighted_consensus([])
    assert result.escalate_to_human is True
    assert result.winning_agent_id is None


def test_weighted_consensus_confident_dissent_escalates():
    votes = [
        make_vote(AGENT_A, "actuarial", 3.0, 0.6, "business"),
        make_vote(AGENT_B, "amateur", 1.0, 0.9, "government_filing"),
    ]
    result = weighted_consensus(votes, dissent_threshold=0.75)
    assert result.consensus_output_key == "business"
    assert result.escalate_to_human is True


def test_weighted_consensus_low_confidence_dissent_does_not_escalate():
    votes = [
        make_vote(AGENT_A, "actuarial", 2.0, 0.6, "business"),
        make_vote(AGENT_B, "amateur", 0.5, 0.3, "government_filing"),
    ]
    result = weighted_consensus(votes, dissent_threshold=0.75)
    assert result.escalate_to_human is False


def test_weighted_consensus_tie_prefers_actuarial_agent():
    votes = [
        make_vote(AGENT_A, "amateur", 2.0, 1.0, "business"),
        make_vote(AGENT_B, "actuarial", 2.0, 1.0, "business"),
    ]
    result = weighted_consensus(votes)
    assert result.winning_agent_id == AGENT_B


def test_weighted_consensus_tie_prefers_actuarial_agent_with_a_dissenting_group():
    """Regression test: the tie-break used to only run when every agent
    proposed the same output (len(ranked) == 1). With a real second,
    losing group present (agents genuinely disagreeing -- the normal
    case this whole mechanism exists for), a weight tie inside the
    *winning* group fell through to list order instead of the actuarial
    arbiter, silently defeating the tie-break for exactly the scenario
    it was built for."""
    votes = [
        make_vote(AGENT_A, "amateur", 2.0, 1.0, "business"),
        make_vote(AGENT_B, "actuarial", 2.0, 1.0, "business"),
        make_vote(AGENT_C, "amateur", 1.0, 1.0, "government_filing"),
    ]
    result = weighted_consensus(votes)
    assert result.winning_agent_id == AGENT_B
    assert result.consensus_output_key == "business"


def test_bayesian_confidence_updates_toward_observed_reliability():
    prior = BayesianConfidence()
    assert prior.mean == pytest.approx(0.5)

    reliable = prior
    for _ in range(20):
        reliable = reliable.update(success=True)
    assert reliable.mean > 0.9

    unreliable = prior
    for _ in range(20):
        unreliable = unreliable.update(success=False)
    assert unreliable.mean < 0.1


def test_monte_carlo_consensus_risk_favors_more_reliable_agent():
    votes = [
        make_vote(AGENT_A, "actuarial", 1.0, 0.9, "business"),
        make_vote(AGENT_B, "amateur", 1.0, 0.9, "government_filing"),
    ]
    reliabilities = {
        AGENT_A: BayesianConfidence(alpha=50, beta=2),  # highly reliable
        AGENT_B: BayesianConfidence(alpha=2, beta=50),  # highly unreliable
    }
    risk = monte_carlo_consensus_risk(votes, reliabilities, n_trials=2000, seed=42)
    assert risk.get("business", 0) > risk.get("government_filing", 0)


def test_monte_carlo_consensus_risk_empty_votes():
    assert monte_carlo_consensus_risk([], {}, n_trials=100) == {}
