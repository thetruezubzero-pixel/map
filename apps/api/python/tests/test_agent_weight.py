import math
from datetime import datetime, timedelta, timezone

import pytest

from app.agent_swarm.models.agent_weight import (
    MIN_WEIGHT,
    NEUTRAL_WEIGHT,
    decay,
    elapsed_days,
    exploration_bonus,
    meets_graduation_criteria,
    multiplicative_update,
)


def test_multiplicative_update_positive_reward_increases_weight():
    assert multiplicative_update(1.0, reward=1.0) > 1.0


def test_multiplicative_update_negative_reward_decreases_weight():
    assert multiplicative_update(1.0, reward=-1.0) < 1.0


def test_multiplicative_update_zero_reward_is_a_noop():
    assert multiplicative_update(1.0, reward=0.0) == pytest.approx(1.0)


def test_multiplicative_update_never_drops_below_floor():
    weight = 1.0
    for _ in range(50):
        weight = multiplicative_update(weight, reward=-1.0)
    assert weight >= MIN_WEIGHT
    assert weight == pytest.approx(MIN_WEIGHT, abs=1e-9)


def test_multiplicative_update_rejects_out_of_range_reward():
    with pytest.raises(ValueError):
        multiplicative_update(1.0, reward=1.5)


def test_decay_pulls_weight_toward_neutral_over_one_half_life():
    decayed = decay(weight=2.0, elapsed_days=30.0, half_life_days=30.0)
    assert decayed == pytest.approx(1.0 + (2.0 - 1.0) * 0.5)


def test_decay_at_zero_elapsed_time_is_unchanged():
    assert decay(weight=1.7, elapsed_days=0.0) == pytest.approx(1.7)


def test_decay_converges_to_neutral_over_many_half_lives():
    decayed = decay(weight=5.0, elapsed_days=30.0 * 20, half_life_days=30.0)
    assert decayed == pytest.approx(NEUTRAL_WEIGHT, abs=1e-4)


def test_exploration_bonus_maximal_for_untried_agent():
    assert exploration_bonus(agent_total_tasks=0, swarm_total_tasks=100) == 1.0


def test_exploration_bonus_shrinks_as_agent_accumulates_tasks():
    early = exploration_bonus(agent_total_tasks=1, swarm_total_tasks=100)
    later = exploration_bonus(agent_total_tasks=50, swarm_total_tasks=100)
    assert early > later > 0


def test_elapsed_days_handles_naive_and_aware_datetimes():
    now = datetime(2026, 1, 31, tzinfo=timezone.utc)
    naive_since = datetime(2026, 1, 1)
    assert elapsed_days(naive_since, now) == pytest.approx(30.0)


def test_meets_graduation_criteria_requires_both_accuracy_and_streak():
    # High accuracy but short streak -- not graduated.
    assert meets_graduation_criteria(total_successes=95, total_tasks=100, consecutive_successes=10) is False
    # Long streak but poor lifetime accuracy -- not graduated.
    assert meets_graduation_criteria(total_successes=51, total_tasks=100, consecutive_successes=50) is False
    # Both satisfied.
    assert meets_graduation_criteria(total_successes=95, total_tasks=100, consecutive_successes=50) is True


def test_meets_graduation_criteria_no_tasks_yet():
    assert meets_graduation_criteria(total_successes=0, total_tasks=0, consecutive_successes=0) is False
