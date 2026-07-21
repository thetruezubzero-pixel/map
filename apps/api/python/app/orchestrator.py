from __future__ import annotations

import logging
from uuid import UUID

from app import db
from app.agents import DataRetrieverAgent, QueryAnalyzerAgent, ResultSynthesizerAgent
from app.cache import semantic_cache
from app.models import ResearchReport

logger = logging.getLogger("aether.orchestrator")

query_analyzer = QueryAnalyzerAgent()
data_retriever = DataRetrieverAgent()
result_synthesizer = ResultSynthesizerAgent()


async def run_research_job(job_id: UUID, query: str) -> None:
    """Runs the QUERY_ANALYZER -> DATA_RETRIEVER -> RESULT_SYNTHESIZER
    pipeline for one job. Every job lands in `awaiting_review` -- nothing
    is auto-finalized (see ROADMAP.md: human-in-the-loop is a hard
    requirement, not a nice-to-have).
    """
    try:
        await db.update_research_job(job_id, "running")

        cached = await semantic_cache.get(query)
        if cached is not None:
            report = ResearchReport.model_validate(cached)
            await db.write_audit_log(job_id, "orchestrator", "cache_hit", {"query": query})
        else:
            plan = await query_analyzer.run(query, job_id=job_id)

            if not plan.entity_types:
                report = ResearchReport(
                    summary=plan.notes or "Query out of scope for this platform (see ROADMAP.md).",
                    records=[],
                    requires_human_review=True,
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
