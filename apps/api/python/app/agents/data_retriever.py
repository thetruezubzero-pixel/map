from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx

from app.config import get_settings
from app.models import EntityType, ResearchPlan, SourcedRecord
from app.agents.base import Agent

logger = logging.getLogger("aether.agents.data_retriever")


class DataRetrieverAgent(Agent):
    """Fetches from public APIs only: OSM (Nominatim), NewsAPI headlines,
    OpenCorporates business registrations. Every record is tagged with
    source, retrieved_at, and license. No PII, no individual profiling --
    OpenCorporates/NewsAPI lookups are scoped to company names, not people.
    """

    name = "data_retriever"

    async def run(self, plan: ResearchPlan, job_id: UUID | None = None) -> list[SourcedRecord]:
        settings = get_settings()
        tasks = []

        if "openstreetmap" in plan.candidate_sources:
            tasks.append(self._fetch_osm(plan.normalized_query, settings))
        if "newsapi" in plan.candidate_sources and settings.newsapi_key:
            tasks.append(self._fetch_newsapi(plan.normalized_query, settings))
        if "opencorporates" in plan.candidate_sources and settings.opencorporates_api_key:
            tasks.append(self._fetch_opencorporates(plan.normalized_query, settings))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        records: list[SourcedRecord] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("data source fetch failed: %s", result)
                continue
            records.extend(result)

        await self.audit(job_id, "retrieve_data", {"sources": plan.candidate_sources, "record_count": len(records)})
        return records

    async def _fetch_osm(self, query: str, settings) -> list[SourcedRecord]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.nominatim_base_url}/search",
                params={"q": query, "format": "jsonv2", "limit": 10, "addressdetails": 1},
                headers={"User-Agent": "AetherSovereignOS/0.2 (public research)"},
            )
            resp.raise_for_status()
            hits = resp.json()

        return [
            SourcedRecord(
                name=hit.get("display_name", query),
                entity_type=EntityType.location,
                source="openstreetmap",
                license="ODbL",
                retrieved_at=datetime.now(timezone.utc),
                lat=float(hit["lat"]) if hit.get("lat") else None,
                lon=float(hit["lon"]) if hit.get("lon") else None,
                metadata={"osm_type": hit.get("type"), "osm_class": hit.get("class")},
            )
            for hit in hits
        ]

    async def _fetch_newsapi(self, query: str, settings) -> list[SourcedRecord]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://newsapi.org/v2/everything",
                params={"q": query, "pageSize": 10, "sortBy": "publishedAt", "language": "en"},
                headers={"X-Api-Key": settings.newsapi_key},
            )
            resp.raise_for_status()
            articles = resp.json().get("articles", [])

        return [
            SourcedRecord(
                name=article.get("title", query),
                entity_type=EntityType.news_mention,
                source="newsapi",
                license="headline/snippet only, per NewsAPI ToS",
                retrieved_at=datetime.now(timezone.utc),
                url=article.get("url"),
                metadata={"published_at": article.get("publishedAt"), "outlet": (article.get("source") or {}).get("name")},
            )
            for article in articles
        ]

    async def _fetch_opencorporates(self, query: str, settings) -> list[SourcedRecord]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params={"q": query, "api_token": settings.opencorporates_api_key},
            )
            resp.raise_for_status()
            companies = resp.json().get("results", {}).get("companies", [])

        return [
            SourcedRecord(
                name=(c.get("company") or {}).get("name", query),
                entity_type=EntityType.business,
                source="opencorporates",
                license="OpenCorporates ToS -- public register data",
                retrieved_at=datetime.now(timezone.utc),
                url=(c.get("company") or {}).get("opencorporates_url"),
                metadata={
                    "jurisdiction": (c.get("company") or {}).get("jurisdiction_code"),
                    "company_number": (c.get("company") or {}).get("company_number"),
                    "status": (c.get("company") or {}).get("current_status"),
                },
            )
            for c in companies
        ]
