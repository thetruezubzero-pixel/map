import uuid

from app.agent_swarm.models.consensus_vote import Vote
from app.agent_swarm.services.credit_assigner import compute_rewards, effective_weight

AGENT_WINNER = uuid.uuid4()
AGENT_AGREE = uuid.uuid4()
AGENT_DISSENT = uuid.uuid4()


def make_vote(agent_id, key, confidence=0.8, weight=1.0):
    return Vote(
        agent_id=agent_id,
        agent_level="amateur",
        weight=weight,
        confidence=confidence,
        output={"key": key},
        output_key=key,
    )


def test_compute_rewards_on_success_rewards_winner_most():
    votes = [
        make_vote(AGENT_WINNER, "business"),
        make_vote(AGENT_AGREE, "business"),
        make_vote(AGENT_DISSENT, "government_filing"),
    ]
    events = compute_rewards(votes, winning_agent_id=AGENT_WINNER, consensus_output_key="business", task_succeeded=True)
    by_agent = {e.agent_id: e for e in events}

    assert by_agent[AGENT_WINNER].reward > by_agent[AGENT_AGREE].reward > by_agent[AGENT_DISSENT].reward
    assert by_agent[AGENT_WINNER].reward > 0
    assert by_agent[AGENT_DISSENT].reward < 0


def test_compute_rewards_on_failure_penalizes_by_confidence():
    confident_vote = make_vote(AGENT_WINNER, "business", confidence=0.95)
    hedged_vote = make_vote(AGENT_AGREE, "business", confidence=0.2)
    events = compute_rewards(
        [confident_vote, hedged_vote], winning_agent_id=AGENT_WINNER, consensus_output_key="business", task_succeeded=False
    )
    by_agent = {e.agent_id: e for e in events}

    assert by_agent[AGENT_WINNER].reward < by_agent[AGENT_AGREE].reward < 0


def test_effective_weight_adds_exploration_bonus_for_new_agents():
    new_agent = effective_weight(current_weight=1.0, agent_total_tasks=0, swarm_total_tasks=50)
    veteran = effective_weight(current_weight=1.0, agent_total_tasks=1000, swarm_total_tasks=1000)
    assert new_agent > veteran
