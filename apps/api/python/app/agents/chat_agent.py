from __future__ import annotations

import json
import logging

from app.agents.base import Agent
from app.config import get_settings
from app.openrouter_client import openrouter_client

logger = logging.getLogger("aether.agents.chat_agent")

SYSTEM_PROMPT = """You are the research assistant for Aether Sovereign OS, \
a public-records research platform (business/property/location records \
from OpenStreetMap, NewsAPI/GDELT, OpenCorporates/SEC EDGAR, Census/USGS). \
Answer only about businesses, locations, and public filings -- never about \
a named individual's personal life, relationships, habits, or whereabouts; \
this platform has no person-record type and never will. If the user asks \
something a people-search tool would answer, say plainly that's out of \
scope rather than guessing.

You may be given a "Grounding records" list below, pulled live from this \
platform's own database -- each has a source, entity_type, and \
retrieved_at. Base any factual claim about a specific named entity only on \
those records; if grounding is empty or doesn't cover the question, say so \
instead of inventing details.

You are wired directly into the map: the same request the user just made \
is also parsed into map actions and executed automatically (the entities \
you're grounded on get plotted, the map moves/filters as asked, and \
"research/investigate X" launches the full multi-source swarm). So speak \
as if the map is already responding -- "I've put these on the map", "I'm \
running a full research job on X (it's multi-source and human-reviewed)" \
-- rather than telling the user to go find a separate panel or button. \
That deeper research job is still the human-reviewed pipeline; this chat \
reply is the quick, best-effort answer alongside it.

Always reply in English, regardless of what language the user writes in \
or what internal representation any other part of this platform uses \
between agents -- the user-facing answer is English, always.
"""


class ChatAgent(Agent):
    """Direct, plain-English conversation with the platform -- distinct
    from the query_analyzer/data_retriever/result_synthesizer research
    pipeline, which stays report-oriented and human-reviewed. Grounds
    answers about specific entities in a live, read-only lookup against
    research_entities.search_vector (the same full-text index
    apps/gateway/src/routes/search.rs's /search route already uses), so
    replies about real entities aren't hallucinated from the model's own
    training data. Stateless: the caller resends the full message history
    each turn -- no new persistence surface, no new scope-guardrail
    question to answer for a chat-history table that doesn't exist."""

    name = "chat_agent"

    async def run(self, pool, messages: list[dict], model: str | None = None) -> tuple[str, list[dict]]:
        settings = get_settings()
        latest_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        grounding = await self._search_grounding(pool, latest_user) if latest_user.strip() else []

        system_content = SYSTEM_PROMPT
        if grounding:
            system_content += "\n\nGrounding records (from this platform's live database):\n" + json.dumps(grounding)

        try:
            _model_used, response = await openrouter_client.complete(
                messages=[{"role": "system", "content": system_content}, *messages],
                model=model or settings.openrouter_fast_model,
                fallback_models=[settings.openrouter_fallback_model],
                temperature=0.3,
                max_tokens=500,
            )
            reply = openrouter_client.extract_text(response)
        except Exception as exc:  # noqa: BLE001 -- chat must never crash the request
            logger.warning("chat completion failed, using fallback: %s", exc)
            if grounding:
                names = ", ".join(g["name"] for g in grounding)
                reply = f"I couldn't reach the language model just now, but I found matching records: {names}."
            else:
                reply = (
                    "I couldn't reach the language model just now. Try rephrasing, or start a "
                    "research job from the Research panel for a deeper, multi-source lookup."
                )

        await self.audit(None, "chat_reply", {"grounding_count": len(grounding)})
        return (
            reply
            or "I don't have a good answer for that -- try rephrasing, or start a research job for a deeper look.",
            grounding,
        )

    async def _search_grounding(self, pool, query: str, limit: int = 5) -> list[dict]:
        # plainto_tsquery ANDs every content word together -- fine for the
        # gateway's /search route (short keyword queries), but confirmed
        # live to break chat's full-sentence input: "What do you know
        # about Acme Test Widgets?" produces 'know' & 'acm' & 'test' &
        # 'widget', which only matches a document containing ALL FOUR
        # lexemes, so a real seeded "Acme Test Widgets LLC" row matched
        # zero rows. Converting plainto_tsquery's AND-joined output to an
        # OR-joined to_tsquery (any shared content word is a candidate,
        # ranked by ts_rank so multi-word matches still score highest)
        # fixed it -- confirmed live against the same seeded row.
        # lon/lat are selected (via PostGIS ST_X/ST_Y on the geom column) so
        # the grounded entities the agent cites can be plotted on the map --
        # the conversational agent and the map draw from the same
        # research_entities rows, and dropping the coordinates here was the
        # only reason a grounded entity couldn't appear as a marker. A row
        # with no geometry simply returns NULL lon/lat and stays chat-only.
        rows = await pool.fetch(
            """
            SELECT id, name, entity_type, source, license, retrieved_at,
                   ST_X(geom::geometry) AS lon, ST_Y(geom::geometry) AS lat
            FROM research_entities
            WHERE search_vector @@ to_tsquery('english', replace(plainto_tsquery('english', $1)::text, ' & ', ' | '))
            ORDER BY ts_rank(
                search_vector,
                to_tsquery('english', replace(plainto_tsquery('english', $1)::text, ' & ', ' | '))
            ) DESC
            LIMIT $2
            """,
            query,
            limit,
        )
        return [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "entity_type": r["entity_type"],
                "source": r["source"],
                "license": r["license"],
                "retrieved_at": r["retrieved_at"].isoformat(),
                "lon": r["lon"],
                "lat": r["lat"],
            }
            for r in rows
        ]
