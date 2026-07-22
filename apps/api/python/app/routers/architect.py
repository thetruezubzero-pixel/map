from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app import db
from app.agent_swarm.introspection import build_project_snapshot, summarize_snapshot
from app.agent_swarm.services.architect_committer import sync_project_plan_doc
from app.agent_swarm.services.change_proposer import propose_change
from app.agents.project_architect import ProjectArchitectAgent
from app.auth import require_user_id
from app.config import get_settings
from app.models import PlanItemCategory

router = APIRouter(tags=["architect"])

architect_agent = ProjectArchitectAgent()


async def _ensure_architect_agent(pool) -> UUID:
    """Single shared instance, not a multi-agent swarm like
    query_analyzer/result_synthesizer -- planning a whole project is one
    coherent judgment call per cycle, not something multiple independent
    instances vote on (same reasoning swarm_coordinator.py already
    documents for data_retriever)."""
    settings = get_settings()
    row = await pool.fetchrow(
        "SELECT id FROM agent_registry WHERE role = 'project_architect' AND user_id IS NULL"
    )
    if row is not None:
        return row["id"]
    row = await pool.fetchrow(
        """
        INSERT INTO agent_registry (name, role, level, model)
        VALUES ('project_architect-amateur', 'project_architect', 'amateur', $1)
        RETURNING id
        """,
        settings.openrouter_default_model,
    )
    return row["id"]


class RunResponse(BaseModel):
    snapshot_id: str
    plan_id: str
    items: list[dict]
    notes: str | None


@router.post("/architect/run", response_model=RunResponse)
async def run_architect_cycle(triggered_by: str = Depends(require_user_id)) -> RunResponse:
    """The only route in this feature gated behind JWT (see app/auth.py's
    module docstring for why this specific route needs its own check
    rather than relying on the gateway). Everything it triggers --
    snapshotting, planning, and the PROJECT_PLAN.md commit/PR pipeline --
    is real, not a dry run."""
    pool = await db.get_pool()
    agent_id = await _ensure_architect_agent(pool)
    agent_row = await pool.fetchrow("SELECT model, current_weight FROM agent_registry WHERE id = $1", agent_id)

    snapshot = await build_project_snapshot(pool)
    summary = summarize_snapshot(snapshot)
    snapshot_row = await pool.fetchrow(
        "INSERT INTO project_snapshots (snapshot, summary) VALUES ($1, $2) RETURNING id",
        json.dumps(snapshot, default=str),
        summary,
    )
    snapshot_id = snapshot_row["id"]

    plan = await architect_agent.run(snapshot, model=agent_row["model"])

    plan_row = await pool.fetchrow(
        """
        INSERT INTO project_plans (snapshot_id, agent_id, items, model)
        VALUES ($1, $2, $3, $4)
        RETURNING id
        """,
        snapshot_id,
        agent_id,
        json.dumps([item.model_dump(mode="json") for item in plan.items]),
        plan.reasoning_model,
    )
    plan_id = plan_row["id"]

    updated_row = await pool.fetchrow(
        "UPDATE agent_registry SET total_tasks = total_tasks + 1, updated_at = now() WHERE id = $1 RETURNING total_tasks",
        agent_id,
    )

    await sync_project_plan_doc(pool, plan_id, plan, summary)

    # Phase 5c: documentation items the model marked safe_to_autoimplement
    # (already defense-in-depth filtered by project_architect._parse to
    # require a target_file + content) each get proposed as their own PR
    # via change_proposer.py -- separate from the PROJECT_PLAN.md flow
    # above, since these touch other allowlisted doc files, not the
    # Architect's own status doc. agent_weight reuses this agent's own
    # tracked agent_registry.current_weight (the same credit_assigner
    # signal every swarm role earns), not a number the model can assert.
    for item in plan.items:
        if item.category == PlanItemCategory.documentation and item.safe_to_autoimplement:
            await propose_change(
                pool,
                agent_name="project_architect",
                role="project_architect",
                file_path=item.target_file,
                new_content=item.content,
                title=item.title,
                rationale=item.rationale,
                confidence=item.confidence,
                agent_weight=float(agent_row["current_weight"]),
                agent_total_tasks=updated_row["total_tasks"],
            )

    return RunResponse(
        snapshot_id=str(snapshot_id),
        plan_id=str(plan_id),
        items=[item.model_dump(mode="json") for item in plan.items],
        notes=plan.notes,
    )


@router.get("/architect/snapshots")
async def list_snapshots(limit: int = 20) -> list[dict]:
    pool = await db.get_pool()
    rows = await pool.fetch(
        "SELECT id, summary, created_at FROM project_snapshots ORDER BY created_at DESC LIMIT $1",
        min(limit, 100),
    )
    return [{"id": str(r["id"]), "summary": r["summary"], "created_at": r["created_at"].isoformat()} for r in rows]


@router.get("/architect/plans")
async def list_plans(limit: int = 20) -> list[dict]:
    pool = await db.get_pool()
    rows = await pool.fetch(
        """
        SELECT p.id, p.items, p.model, p.created_at, s.summary AS snapshot_summary
        FROM project_plans p JOIN project_snapshots s ON s.id = p.snapshot_id
        ORDER BY p.created_at DESC LIMIT $1
        """,
        min(limit, 100),
    )
    return [
        {
            "id": str(r["id"]),
            "items": json.loads(r["items"]) if isinstance(r["items"], str) else r["items"],
            "model": r["model"],
            "snapshot_summary": r["snapshot_summary"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/architect/actions")
async def list_actions(plan_id: UUID | None = None, limit: int = 50) -> list[dict]:
    pool = await db.get_pool()
    if plan_id is not None:
        rows = await pool.fetch(
            "SELECT * FROM project_plan_actions WHERE plan_id = $1 ORDER BY created_at DESC LIMIT $2",
            plan_id,
            min(limit, 200),
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM project_plan_actions ORDER BY created_at DESC LIMIT $1", min(limit, 200)
        )
    return [
        {
            "id": str(r["id"]),
            "plan_id": str(r["plan_id"]),
            "action": r["action"],
            "branch_name": r["branch_name"],
            "commit_sha": r["commit_sha"],
            "pr_url": r["pr_url"],
            "detail": json.loads(r["detail"]) if isinstance(r["detail"], str) else r["detail"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
