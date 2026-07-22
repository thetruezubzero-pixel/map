import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.agent_swarm.services.swarm_coordinator import _SPAWNABLE_ROLES, _maybe_spawn_amateur, shape_task_row


def test_shape_task_row_shapes_all_fields():
    agent_id = uuid4()
    job_id = uuid4()
    task_id = uuid4()
    row = {
        "id": task_id,
        "job_id": job_id,
        "role": "query_analyzer",
        "agents_involved": [agent_id],
        "votes": '[{"agent_id": "%s"}]' % agent_id,
        "winning_agent_id": agent_id,
        "reward_applied": False,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    shaped = shape_task_row(row)
    assert shaped["id"] == str(task_id)
    assert shaped["job_id"] == str(job_id)
    assert shaped["agent_count"] == 1
    assert shaped["votes"] == [{"agent_id": str(agent_id)}]
    assert shaped["winning_agent_id"] == str(agent_id)
    assert shaped["reward_applied"] is False


def test_shape_task_row_handles_null_job_and_winner():
    row = {
        "id": uuid4(),
        "job_id": None,
        "role": "data_retriever",
        "agents_involved": [],
        "votes": [],
        "winning_agent_id": None,
        "reward_applied": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    shaped = shape_task_row(row)
    assert shaped["job_id"] is None
    assert shaped["winning_agent_id"] is None
    assert shaped["agent_count"] == 0


def test_data_retriever_is_not_spawnable():
    # data_retriever has no amateur tier in _default_roster (deterministic
    # tool execution, no consensus/graduation concept) -- spawning an
    # amateur there would be inconsistent with that design.
    assert "data_retriever" not in _SPAWNABLE_ROLES
    assert "query_analyzer" in _SPAWNABLE_ROLES
    assert "result_synthesizer" in _SPAWNABLE_ROLES


class _NoQueryPool:
    """Pool double that raises if any query method is invoked -- proves
    _maybe_spawn_amateur's role gate short-circuits before touching the
    database at all for a non-spawnable role."""

    async def fetchval(self, *a, **k):
        raise AssertionError("should not query the DB for a non-spawnable role")

    async def fetchrow(self, *a, **k):
        raise AssertionError("should not query the DB for a non-spawnable role")

    async def execute(self, *a, **k):
        raise AssertionError("should not query the DB for a non-spawnable role")


def test_maybe_spawn_amateur_noops_for_non_spawnable_role():
    asyncio.run(_maybe_spawn_amateur(_NoQueryPool(), "data_retriever", None, None))
