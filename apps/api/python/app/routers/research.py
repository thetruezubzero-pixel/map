from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app import db
from app.agent_swarm.services import swarm_coordinator
from app.models import JobStatus, ResearchJobDetail, ResearchJobResponse, ResearchReport, ResearchRequest
from app.orchestrator import run_research_job

router = APIRouter(tags=["research"])


class ReviewDecision(BaseModel):
    decision: str  # "confirm" | "reject"
    reviewed_by: str | None = None


@router.post("/research", response_model=ResearchJobResponse)
async def create_job(payload: ResearchRequest, background_tasks: BackgroundTasks) -> ResearchJobResponse:
    row = await db.create_research_job(payload.query, payload.requested_by)
    background_tasks.add_task(run_research_job, row["id"], payload.query, payload.requested_by)
    return ResearchJobResponse(job_id=str(row["id"]), status=JobStatus(row["status"]))


@router.get("/research/{job_id}", response_model=ResearchJobDetail)
async def get_job(job_id: UUID) -> ResearchJobDetail:
    row = await db.get_research_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research job not found")

    result = row["result"]
    if isinstance(result, str):
        result = json.loads(result)

    status = JobStatus(row["status"])
    error = result.get("error") if status == JobStatus.failed and result else None
    report = ResearchReport.model_validate(result) if result and status != JobStatus.failed else None

    return ResearchJobDetail(
        job_id=str(row["id"]),
        status=status,
        query=row["query"],
        requested_by=row["requested_by"],
        result=report,
        error=error,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.post("/research/{job_id}/review")
async def review_job(job_id: UUID, decision: ReviewDecision) -> dict:
    """Human review of an `awaiting_review` job -- was the report
    correct enough to finalize? This is also the credit-assignment
    trigger (Phase 5): confirming or rejecting settles every
    task_history row this job produced, rewarding/penalizing the swarm
    agents that voted on it (app.agent_swarm.services.swarm_coordinator.
    finalize_task). A job that was never reviewed just stays in
    awaiting_review with its votes unrewarded -- there is no
    auto-finalization path, by design (see ROADMAP.md)."""
    if decision.decision not in ("confirm", "reject"):
        raise HTTPException(status_code=400, detail="decision must be 'confirm' or 'reject'")

    row = await db.get_research_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research job not found")
    if row["status"] != "awaiting_review":
        raise HTTPException(status_code=409, detail=f"job is '{row['status']}', not awaiting_review")

    succeeded = decision.decision == "confirm"
    new_status = "completed" if succeeded else "failed"

    pool = await db.get_pool()
    task_ids = await pool.fetch("SELECT id FROM task_history WHERE job_id = $1 AND NOT reward_applied", job_id)
    rewarded = 0
    for t in task_ids:
        rewarded += await swarm_coordinator.finalize_task(
            pool, t["id"], succeeded=succeeded, ground_truth={"reviewed_by": decision.reviewed_by}
        )

    # row["result"] is JSONB fetched raw by asyncpg (a string, not a
    # pre-parsed dict -- see get_job above) and update_research_job
    # re-json.dumps() whatever it's given, so pass it through parsed or
    # it gets double-encoded and corrupts the stored report.
    existing_result = row["result"]
    if isinstance(existing_result, str):
        existing_result = json.loads(existing_result)
    await db.update_research_job(job_id, new_status, existing_result)
    await db.write_audit_log(
        job_id, "orchestrator", "human_review", {"decision": decision.decision, "reviewed_by": decision.reviewed_by}
    )

    return {"job_id": str(job_id), "status": new_status, "agents_rewarded": rewarded}
