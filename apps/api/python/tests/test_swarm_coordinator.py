import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app.agent_swarm.services.swarm_coordinator import (
    _SPAWNABLE_ROLES,
    _maybe_spawn_amateur,
    _maybe_spawn_coordinator,
    shape_task_row,
)


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


class _FakeCoordinatorPool:
    """Simulates agent_registry's two relevant queries (the existing-
    coordinator count and the qualifying-actuarial lookup) plus the
    guarded INSERT, without touching a real database -- covers the
    guard logic a security review flagged as untested (unlike
    _maybe_spawn_amateur, _maybe_spawn_coordinator had zero test
    coverage before this)."""

    def __init__(self, existing_count, qualifying_row, insert_result):
        self.existing_count = existing_count
        self.qualifying_row = qualifying_row
        self.insert_result = insert_result
        self.qualifying_query_calls = 0
        self.insert_query_calls = 0

    async def fetchval(self, query, *args):
        return self.existing_count

    async def fetchrow(self, query, *args):
        if "INSERT INTO agent_registry" in query:
            self.insert_query_calls += 1
            return self.insert_result
        self.qualifying_query_calls += 1
        return self.qualifying_row


def test_maybe_spawn_coordinator_skips_when_one_already_exists():
    pool = _FakeCoordinatorPool(existing_count=1, qualifying_row=None, insert_result=None)
    asyncio.run(_maybe_spawn_coordinator(pool, "query_analyzer", None))
    assert pool.qualifying_query_calls == 0  # short-circuits before looking for a candidate at all
    assert pool.insert_query_calls == 0


def test_maybe_spawn_coordinator_skips_when_no_actuarial_agent_exists():
    pool = _FakeCoordinatorPool(existing_count=0, qualifying_row=None, insert_result=None)
    asyncio.run(_maybe_spawn_coordinator(pool, "query_analyzer", None))
    assert pool.qualifying_query_calls == 1
    assert pool.insert_query_calls == 0


def test_maybe_spawn_coordinator_skips_when_track_record_is_too_weak():
    weak_row = {"id": uuid4(), "total_successes": 95, "total_tasks": 100, "consecutive_successes": 50}
    pool = _FakeCoordinatorPool(existing_count=0, qualifying_row=weak_row, insert_result=None)
    asyncio.run(_maybe_spawn_coordinator(pool, "query_analyzer", None))
    assert pool.qualifying_query_calls == 1
    assert pool.insert_query_calls == 0  # 95/100 clears amateur graduation but not coordinator promotion


def test_maybe_spawn_coordinator_inserts_when_track_record_clears_the_bar(monkeypatch):
    strong_row = {"id": uuid4(), "total_successes": 245, "total_tasks": 250, "consecutive_successes": 200}
    pool = _FakeCoordinatorPool(
        existing_count=0, qualifying_row=strong_row, insert_result={"id": uuid4()}
    )

    audit_calls = []

    async def _fake_write_audit_log(job_id, agent_name, action, detail):
        audit_calls.append((agent_name, action, detail))

    import app.db as db_module

    monkeypatch.setattr(db_module, "write_audit_log", _fake_write_audit_log)

    asyncio.run(_maybe_spawn_coordinator(pool, "query_analyzer", None))

    assert pool.qualifying_query_calls == 1
    assert pool.insert_query_calls == 1
    assert len(audit_calls) == 1
    assert audit_calls[0][1] == "coordinator_spawned"


def test_maybe_spawn_coordinator_noops_silently_when_it_loses_the_insert_race(monkeypatch):
    """ON CONFLICT DO NOTHING (0012_coordinator_race_guard.sql) returns
    no row when a concurrent call already spawned the coordinator first
    -- confirmed this doesn't write an audit log entry for a spawn that
    didn't actually happen."""
    strong_row = {"id": uuid4(), "total_successes": 245, "total_tasks": 250, "consecutive_successes": 200}
    pool = _FakeCoordinatorPool(existing_count=0, qualifying_row=strong_row, insert_result=None)

    audit_calls = []

    async def _fake_write_audit_log(job_id, agent_name, action, detail):
        audit_calls.append((agent_name, action, detail))

    import app.db as db_module

    monkeypatch.setattr(db_module, "write_audit_log", _fake_write_audit_log)

    asyncio.run(_maybe_spawn_coordinator(pool, "query_analyzer", None))

    assert pool.insert_query_calls == 1
    assert audit_calls == []
