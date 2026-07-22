from __future__ import annotations

import json
import logging
from uuid import UUID

from app.config import get_settings
from app.models import EntityType, ResearchPlan
from app.openrouter_client import openrouter_client
from app.agents.base import Agent

logger = logging.getLogger("aether.agents.query_analyzer")

SYSTEM_PROMPT = """You are the query analyzer for a public-records research \
platform. You turn a natural-language research request into a structured \
plan. Scope: business registrations, government filings, locations/POIs, \
and public news mentions ONLY. Never plan to look up information about a \
private individual -- if the request asks for that, set entity_types to an \
empty list and explain why in `notes`.

Respond with ONLY a JSON object matching this shape:
{
  "normalized_query": string,
  "entity_types": array of any of ["business","government_filing","location","poi","news_mention"],
  "candidate_sources": array of any of ["openstreetmap","newsapi","opencorporates"],
  "notes": string or null
}

Always write `notes` in English, regardless of what language the request itself is in.
"""


class QueryAnalyzerAgent(Agent):
    name = "query_analyzer"

    async def run(self, query: str, job_id: UUID | None = None, model: str | None = None) -> ResearchPlan:
        """`model` lets a caller pin this run to a specific model instead
        of the default fast-model routing -- used by
        app/agent_swarm/services/swarm_coordinator.py to run several
        differently-modeled agent instances of this same role. Omit it
        (the default) for the original single-agent behavior."""
        settings = get_settings()
        model_used, response = await openrouter_client.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            model=model or settings.openrouter_fast_model,
            fallback_models=[settings.openrouter_default_model, settings.openrouter_fallback_model],
            temperature=0.1,
            max_tokens=500,
        )

        text = openrouter_client.extract_text(response)
        plan = self._parse(text, query, model_used)

        await self.audit(
            job_id,
            "analyze_query",
            {"query": query, "model": model_used, "plan": plan.model_dump(mode="json")},
        )
        return plan

    def _parse(self, text: str, original_query: str, model_used: str) -> ResearchPlan:
        try:
            start, end = text.index("{"), text.rindex("}") + 1
            data = json.loads(text[start:end])
            entity_types = [EntityType(t) for t in data.get("entity_types", []) if t in EntityType._value2member_map_]
            return ResearchPlan(
                normalized_query=data.get("normalized_query", original_query),
                entity_types=entity_types,
                candidate_sources=data.get("candidate_sources", []),
                reasoning_model=model_used,
                notes=data.get("notes"),
            )
        except (ValueError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("failed to parse query analyzer output, using safe default: %s", exc)
            return ResearchPlan(
                normalized_query=original_query,
                entity_types=[EntityType.business],
                candidate_sources=["opencorporates"],
                reasoning_model=model_used,
                notes="fallback plan: model output could not be parsed",
            )
