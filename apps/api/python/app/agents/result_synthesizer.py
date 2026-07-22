from __future__ import annotations

import json
import logging
from uuid import UUID

from app.config import get_settings
from app.models import (
    EntityRelationship,
    EntityType,
    ResearchPlan,
    ResearchReport,
    ResearchTimelineEvent,
    SourcedRecord,
)
from app.openrouter_client import openrouter_client
from app.agents.base import Agent

logger = logging.getLogger("aether.agents.result_synthesizer")

SYSTEM_PROMPT = """You summarize public-record research results into a \
short, neutral report. Business/property records only. Do NOT infer or \
state anything about a named individual's personal life, relationships, \
habits, or whereabouts -- if the input data drifts into that territory, \
omit it and note the omission. Write 3-6 sentences, factual tone, cite \
source names inline (e.g. "per OpenCorporates"). Always write the summary \
in English, regardless of what language the underlying records are in.
"""


class ResultSynthesizerAgent(Agent):
    """Aggregates multi-source results into a structured report: summary,
    chronological timeline, and a corporate parent/subsidiary graph where
    the data supports it. NO personal relationship mapping, NO individual
    dossiers. Every report queues for human review before finalization.

    Not done, flagged rather than silently omitted: "where the data
    supports it" currently means never -- see _build_relationships.
    """

    name = "result_synthesizer"

    async def run(
        self,
        plan: ResearchPlan,
        records: list[SourcedRecord],
        job_id: UUID | None = None,
        model: str | None = None,
    ) -> ResearchReport:
        """`model` lets a caller pin this run to a specific model --
        used by app/agent_swarm/services/swarm_coordinator.py to run
        several differently-modeled instances of this role. Omit it
        (the default) for the original single-agent behavior."""
        settings = get_settings()
        summary = await self._summarize(plan, records, settings, model)
        timeline = self._build_timeline(records)
        relationships = self._build_relationships(records)

        report = ResearchReport(
            summary=summary,
            records=records,
            timeline=timeline,
            relationships=relationships,
            requires_human_review=True,
        )

        await self.audit(
            job_id,
            "synthesize_report",
            {"record_count": len(records), "timeline_events": len(timeline), "relationships": len(relationships)},
        )
        return report

    async def _summarize(
        self, plan: ResearchPlan, records: list[SourcedRecord], settings, model: str | None = None
    ) -> str:
        if not records:
            return "No public records matched this query."

        digest = json.dumps(
            [{"name": r.name, "type": r.entity_type.value, "source": r.source} for r in records[:25]]
        )

        try:
            model_used, response = await openrouter_client.complete(
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Query: {plan.normalized_query}\nRecords: {digest}"},
                ],
                model=model or settings.openrouter_default_model,
                fallback_models=[settings.openrouter_fallback_model],
                temperature=0.2,
                max_tokens=400,
            )
            return openrouter_client.extract_text(response) or f"Found {len(records)} public records."
        except Exception as exc:  # noqa: BLE001 -- synthesis must never crash the job
            logger.warning("summary generation failed, using fallback: %s", exc)
            return f"Found {len(records)} public records across {len({r.source for r in records})} sources."

    def _build_timeline(self, records: list[SourcedRecord]) -> list[ResearchTimelineEvent]:
        events = sorted(records, key=lambda r: r.retrieved_at)
        return [
            ResearchTimelineEvent(
                date=r.retrieved_at.date().isoformat(),
                description=f"{r.name} ({r.entity_type.value})",
                source=r.source,
            )
            for r in events
        ]

    def _build_relationships(self, records: list[SourcedRecord]) -> list[EntityRelationship]:
        """Corporate parent/subsidiary graph only, derived from
        OpenCorporates metadata when present. Never applied to
        news_mention or location records, which have no ownership
        semantics.

        Currently always returns [] in practice: data_retriever.py's
        _fetch_opencorporates only calls OpenCorporates' company *search*
        endpoint, whose response never includes parent/controlling-entity
        data (that's only on their per-company *detail* endpoint, which
        nothing here calls) -- confirmed live, `metadata["parent_company"]`
        is set nowhere in this codebase. Wiring a real signal would mean
        an extra live HTTP call per business record (a real rate-limit/
        cost tradeoff, and OpenCorporates' free tier has separately been
        confirmed to no longer work at all as of this repo's current
        state -- see opencorporates_sync_dag.py), so this is left as a
        real, flagged gap rather than a guessed-at fix."""
        relationships: list[EntityRelationship] = []
        businesses = [r for r in records if r.entity_type == EntityType.business]

        for r in businesses:
            parent_name = r.metadata.get("parent_company")
            if parent_name:
                relationships.append(
                    EntityRelationship(parent=parent_name, child=r.name, source=r.source)
                )

        return relationships
