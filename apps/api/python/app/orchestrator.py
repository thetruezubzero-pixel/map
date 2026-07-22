from __future__ import annotations

import logging
from uuid import UUID

from app import db
from app.agent_swarm.services import swarm_coordinator
from app.agents import DataRetrieverAgent, QueryAnalyzerAgent, ResultSynthesizerAgent
from app.cache import semantic_cache
from app.config import get_settings
from app.models import ResearchReport

logger = logging.getLogger("aether.orchestrator")

query_analyzer = QueryAnalyzerAgent()
data_retriever = DataRetrieverAgent()
result_synthesizer = ResultSynthesizerAgent()


async def run_research_job(job_id: UUID, query: str, requested_by: str | None = None) -> None:
    """Runs the QUERY_ANALYZER -> DATA_RETRIEVER -> RESULT_SYNTHESIZER
    pipeline for one job. Every job lands in `awaiting_review` -- nothing
    is auto-finalized (see ROADMAP.md: human-in-the-loop is a hard
    requirement, not a nice-to-have).

    When `agent_swarm_enabled` (default on), query_analyzer and
    result_synthesizer each run as a weighted multi-agent vote via
    app.agent_swarm.services.swarm_coordinator instead of a single call
    -- see that module for what "vote" means for each role and why
    data_retriever (deterministic tool execution) doesn't get one. If
    every agent instance in a role's swarm fails (e.g. OpenRouter
    unreachable), swarm_coordinator itself degrades to the single-agent
    call below, so this function doesn't need its own fallback branch.
    """
    settings = get_settings()
    use_swarm = settings.agent_swarm_enabled

    try:
        await db.update_research_job(job_id, "running")

        cached = await semantic_cache.get(query)
        if cached is not None:
            report = ResearchReport.model_validate(cached)
            await db.write_audit_log(job_id, "orchestrator", "cache_hit", {"query": query})
        else:
            if use_swarm:
                pool = await db.get_pool()
                plan, _ = await swarm_coordinator.run_query_analyzer_swarm(
                    pool, query, job_id=job_id, user_id=requested_by
                )
            else:
                plan = await query_analyzer.run(query, job_id=job_id)

            if not plan.entity_types:
                report = ResearchReport(
                    summary=plan.notes or "Query out of scope for this platform (see ROADMAP.md).",
                    records=[],
                    requires_human_review=True,
                )
            else:
                if use_swarm:
                    records = await swarm_coordinator.run_data_retriever_single(
                        pool, plan, job_id, user_id=requested_by
                    )
                    report, _ = await swarm_coordinator.run_result_synthesizer_swarm(
                        pool, plan, records, job_id=job_id, user_id=requested_by
                    )
                else:
                    records = await data_retriever.run(plan, job_id=job_id)
                    report = await result_synthesizer.run(plan, records, job_id=job_id)
                await semantic_cache.set(query, report.model_dump(mode="json"))

        await db.update_research_job(job_id, "awaiting_review", report.model_dump(mode="json"))
    except Exception as exc:  # noqa: BLE001 -- job failures must be recorded, not raised into the worker
        logger.exception("research job %s failed", job_id)
        await db.write_audit_log(job_id, "orchestrator", "job_failed", {"error": str(exc)})
        await db.update_research_job(job_id, "failed", {"error": str(exc)})
