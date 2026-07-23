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
    """Create a new research job. Fire-and-forget enqueuing: returns immediately
    after queueing run_research_job as a background task, which spawns the full
    multi-agent swarm (query_analyzer → data_retriever → result_synthesizer),
    running multiple billed OpenRouter calls per job.

    Rate limit: 3 requests/minute per IP (apps/web/nginx.conf, research_zone).
    This route is unauthenticated, so the per-IP limit is the only defense.
    See nginx.conf's research_zone comment for the cost/rate justification.

    The frontend reaches this through the gateway (/api/research, which is gated
    by the gateway's own rate_limiter middleware), but direct calls bypass that,
    so nginx throttles here as defense-in-depth."""
    row = await db.create_research_job(payload.query, payload.requested_by)
    background_tasks.add_task(run_research_job, row["id"], payload.query, payload.requested_by)
    return ResearchJobResponse(job_id=str(row["id"]), status=JobStatus(row["status"]))


@router.get("/research/{job_id}", response_model=ResearchJobDetail)
async def get_job(job_id: UUID) -> ResearchJobDetail:
    """Fetch the status and result of a single research job. Cheap read-only
    query (single PK lookup, ~10ms on normal DB load) with no side effects.
    Not rate-limited at nginx level (falls through to the /py-api/ catch-all
    unthrottled). The frontend polls this frequently for job status; throttling
    would create artificial blocking on otherwise-fast reads. If this ever
    becomes a cost center (e.g. an expensive aggregation query is added to the
    result), move this to its own exact-match location in nginx.conf with a
    dedicated rate limit, following the pattern of /research (create) and
    /architect/run above it."""
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


@router.get("/research/{job_id}/trace")
async def get_job_trace(job_id: UUID) -> dict:
    """Full reasoning chain for one job in one place: every swarm consensus
    round (task_history -- analyzer votes, the winning plan, the retriever's
    single call, synthesizer votes) interleaved with every orchestrator/audit
    event (agent_audit_log -- cache hits, job failures, human review
    decisions), ordered by time. This doesn't change how the swarm votes --
    each role's instances still run independently, which is what makes
    weighted_consensus meaningful -- it just exposes the chain that already
    connects the roles (query_analyzer → data_retriever → result_synthesizer)
    for one job, which is otherwise scattered across two tables with no shared
    view. See GET /swarm for the equivalent feed across every job.

    Rate limit: None (falls through to /py-api/ catch-all). This is a DB join
    across two indexed tables (~50-100ms on normal load) with no side effects.
    The UI shows this on the job detail page for introspection; throttling
    would block legitimate debugging. If performance degrades (millions of
    events per job), add a specific limit here following the pattern of
    /research and /architect/run in nginx.conf."""
    row = await db.get_research_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="research job not found")

    pool = await db.get_pool()
    task_rows = await pool.fetch(
        """
        SELECT id, job_id, role, agents_involved, votes, consensus_output,
               winning_agent_id, reward_applied, created_at
        FROM task_history WHERE job_id = $1 ORDER BY created_at
        """,
        job_id,
    )
    audit_rows = await pool.fetch(
        "SELECT id, agent_name, action, detail, created_at FROM agent_audit_log WHERE job_id = $1 ORDER BY created_at",
        job_id,
    )

    events = [
        {"type": "consensus_round", **swarm_coordinator.shape_task_row(r)} for r in task_rows
    ] + [
        {
            "type": "audit_log",
            "id": str(r["id"]),
            "agent_name": r["agent_name"],
            "action": r["action"],
            "detail": json.loads(r["detail"]) if isinstance(r["detail"], str) else r["detail"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in audit_rows
    ]
    events.sort(key=lambda e: e["created_at"])

    return {"job_id": str(job_id), "events": events}


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

    pool = await db.get_pool()

    # Claim the job atomically instead of a plain SELECT-then-check: a
    # readiness review found the original version read `status`, checked
    # it in Python, and only wrote a new status at the very end of this
    # handler -- two review requests submitted for the same job_id before
    # either finished both passed the "== awaiting_review" check, both
    # re-fetched the same NOT reward_applied task_history rows, and both
    # drove finalize_task for each one. finalize_task now claims each row
    # atomically too, but this closes the job-status side of the same race
    # so a duplicate submission gets a clean 409 instead of silently
    # repeating the review.
    row = await pool.fetchrow(
        "UPDATE research_jobs SET status = 'reviewing', updated_at = now() "
        "WHERE id = $1 AND status = 'awaiting_review' "
        "RETURNING id, result",
        job_id,
    )
    if row is None:
        existing = await db.get_research_job(job_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="research job not found")
        raise HTTPException(status_code=409, detail=f"job is '{existing['status']}', not awaiting_review")

    succeeded = decision.decision == "confirm"
    new_status = "completed" if succeeded else "failed"

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
