from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import db
from app.agent_swarm.models.agent_weight import meets_graduation_criteria
from app.agent_swarm.services import heirloom_sync
from app.agent_swarm.services.swarm_coordinator import ensure_default_agents, shape_task_row

router = APIRouter(tags=["agent_swarm"])


class AgentSummary(BaseModel):
    id: str
    name: str
    role: str
    level: str
    model: str
    current_weight: float
    consecutive_successes: int
    total_tasks: int
    total_successes: int
    accuracy: float | None
    graduated: bool
    parent_agent_id: str | None
    mentor_agent_id: str | None
    user_id: str | None


def _to_summary(row) -> AgentSummary:
    accuracy = row["total_successes"] / row["total_tasks"] if row["total_tasks"] else None
    return AgentSummary(
        id=str(row["id"]),
        name=row["name"],
        role=row["role"],
        level=row["level"],
        model=row["model"],
        current_weight=float(row["current_weight"]),
        consecutive_successes=row["consecutive_successes"],
        total_tasks=row["total_tasks"],
        total_successes=row["total_successes"],
        accuracy=accuracy,
        graduated=row["graduated"],
        parent_agent_id=str(row["parent_agent_id"]) if row["parent_agent_id"] else None,
        mentor_agent_id=str(row["mentor_agent_id"]) if row["mentor_agent_id"] else None,
        user_id=row["user_id"],
    )


@router.get("/agents", response_model=list[AgentSummary])
async def list_agents(user_id: str | None = None) -> list[AgentSummary]:
    """All registered agent instances. Pass `user_id` to scope to one
    user's roster (heirlooms/weights are per-user, see
    migrations/0008_agent_swarm.sql); omit it to see the shared/
    platform-default roster (user_id IS NULL) plus every per-user agent,
    for an operator-level view."""
    pool = await db.get_pool()
    if user_id is not None:
        await ensure_default_agents(pool, user_id)
        rows = await pool.fetch(
            "SELECT * FROM agent_registry WHERE user_id IS NOT DISTINCT FROM $1 ORDER BY role, level", user_id
        )
    else:
        rows = await pool.fetch("SELECT * FROM agent_registry ORDER BY role, level, created_at")
    return [_to_summary(r) for r in rows]


class AgentDetail(AgentSummary):
    recent_tasks: list[dict]
    weight_trajectory: list[dict]


@router.get("/agents/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID, task_limit: int = 20) -> AgentDetail:
    pool = await db.get_pool()
    row = await pool.fetchrow("SELECT * FROM agent_registry WHERE id = $1", agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent not found")

    tasks = await pool.fetch(
        """
        SELECT id, role, consensus_output, winning_agent_id, reward_applied, created_at
        FROM task_history
        WHERE $1 = ANY(agents_involved)
        ORDER BY created_at DESC LIMIT $2
        """,
        agent_id,
        min(task_limit, 100),
    )
    trajectory = await pool.fetch(
        "SELECT weight, delta, reason, created_at FROM weight_history WHERE agent_id = $1 ORDER BY created_at",
        agent_id,
    )

    summary = _to_summary(row)
    return AgentDetail(
        **summary.model_dump(),
        recent_tasks=[
            {
                "id": str(t["id"]),
                "role": t["role"],
                "consensus_output": json.loads(t["consensus_output"])
                if isinstance(t["consensus_output"], str)
                else t["consensus_output"],
                "was_winner": t["winning_agent_id"] == agent_id,
                "reward_applied": t["reward_applied"],
                "created_at": t["created_at"].isoformat(),
            }
            for t in tasks
        ],
        weight_trajectory=[
            {
                "weight": float(w["weight"]),
                "delta": float(w["delta"]),
                "reason": w["reason"],
                "created_at": w["created_at"].isoformat(),
            }
            for w in trajectory
        ],
    )


@router.get("/swarm")
async def swarm_activity(limit: int = 50, job_id: UUID | None = None) -> dict:
    """Live swarm activity feed -- recent consensus rounds, most recent
    first. Used by the /swarm dashboard route (all roles/jobs) and by the
    research job detail page (pass `job_id` to scope to one job's own
    chain -- see also GET /research/{job_id}/trace for that job's full
    reasoning timeline including audit-log entries)."""
    pool = await db.get_pool()
    if job_id is not None:
        rows = await pool.fetch(
            """
            SELECT id, job_id, role, agents_involved, votes, consensus_output,
                   winning_agent_id, reward_applied, created_at
            FROM task_history WHERE job_id = $1 ORDER BY created_at DESC LIMIT $2
            """,
            job_id,
            min(limit, 200),
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, job_id, role, agents_involved, votes, consensus_output,
                   winning_agent_id, reward_applied, created_at
            FROM task_history ORDER BY created_at DESC LIMIT $1
            """,
            min(limit, 200),
        )
    return {"tasks": [shape_task_row(r) for r in rows]}


@router.get("/training")
async def training_progress(user_id: str | None = None) -> dict:
    """Amateur agents' progress toward graduation (90% accuracy + 50
    consecutive successes, both required -- see agent_weight.py)."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT * FROM agent_registry WHERE level = 'amateur' AND user_id IS NOT DISTINCT FROM $1 ORDER BY role",
        user_id,
    )
    return {
        "amateurs": [
            {
                "id": str(r["id"]),
                "role": r["role"],
                "model": r["model"],
                "total_tasks": r["total_tasks"],
                "total_successes": r["total_successes"],
                "accuracy": r["total_successes"] / r["total_tasks"] if r["total_tasks"] else None,
                "consecutive_successes": r["consecutive_successes"],
                "consecutive_needed": 50,
                "accuracy_needed": 0.90,
                "graduated": meets_graduation_criteria(
                    r["total_successes"], r["total_tasks"], r["consecutive_successes"]
                ),
                "mentor_agent_id": str(r["mentor_agent_id"]) if r["mentor_agent_id"] else None,
            }
            for r in rows
        ]
    }


class ExportHeirloomRequest(BaseModel):
    user_id: str
    device_id: str


@router.post("/heirlooms/{agent_id}/export")
async def export_heirloom_endpoint(agent_id: UUID, payload: ExportHeirloomRequest) -> dict:
    pool = await db.get_pool()
    store = heirloom_sync.PostgresEncryptedHeirloomStore()
    try:
        manifest = await heirloom_sync.export_heirloom(pool, store, agent_id, payload.user_id, payload.device_id)
    except heirloom_sync.HeirloomError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": str(manifest.id),
        "agent_id": str(manifest.agent_id),
        "device_id": manifest.device_id,
        "backend": manifest.backend,
        "content_hash": manifest.content_hash,
        "verified": manifest.verified,
        "created_at": manifest.created_at.isoformat(),
    }


@router.get("/heirlooms")
async def list_heirlooms(user_id: str | None = None) -> dict:
    """Cross-device sync status / knowledge transfer log."""
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT hm.id, hm.agent_id, hm.device_id, hm.user_id, hm.backend, hm.content_hash,
               hm.verified, hm.created_at, ar.name AS agent_name, ar.role, ar.level
        FROM heirloom_manifest hm
        JOIN agent_registry ar ON ar.id = hm.agent_id
        WHERE $1::text IS NULL OR hm.user_id = $1
        ORDER BY hm.created_at DESC
        """,
        user_id,
    )
    return {
        "heirlooms": [
            {
                "id": str(r["id"]),
                "agent_id": str(r["agent_id"]),
                "agent_name": r["agent_name"],
                "role": r["role"],
                "level": r["level"],
                "device_id": r["device_id"],
                "backend": r["backend"],
                "content_hash": r["content_hash"],
                "verified": r["verified"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]
    }
