from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app import db
from app.models import JobStatus, ResearchJobDetail, ResearchJobResponse, ResearchReport, ResearchRequest
from app.orchestrator import run_research_job

router = APIRouter(tags=["research"])


@router.post("/research", response_model=ResearchJobResponse)
async def create_job(payload: ResearchRequest, background_tasks: BackgroundTasks) -> ResearchJobResponse:
    row = await db.create_research_job(payload.query, payload.requested_by)
    background_tasks.add_task(run_research_job, row["id"], payload.query)
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
