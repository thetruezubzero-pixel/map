"""DAG 2: NewsAPI headline aggregation (public news only).

Stores headline + URL + outlet, never full article body, per NewsAPI's
terms of service. Every record is tagged source="newsapi".
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

DEFAULT_SEARCH_TERMS = ["business acquisition", "corporate merger"]


@dag(
    dag_id="newsapi_ingestion",
    description="Aggregates public NewsAPI headlines into research_entities as news_mention records.",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "newsapi", "public-records"],
)
def newsapi_ingestion_dag():
    @task
    def fetch_headlines() -> list[dict]:
        import logging

        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        logger = logging.getLogger(__name__)

        api_key = os.environ.get("NEWSAPI_KEY", "")
        if not api_key:
            return []

        try:
            search_terms = Variable.get("newsapi_search_terms", deserialize_json=True)
        except Exception:
            search_terms = DEFAULT_SEARCH_TERMS

        records: list[dict] = []
        with httpx.Client(timeout=15.0) as client:
            for term in search_terms:
                try:
                    resp = client.get(
                        "https://newsapi.org/v2/everything",
                        params={"q": term, "pageSize": 20, "sortBy": "publishedAt", "language": "en"},
                        headers={"X-Api-Key": api_key},
                    )
                    resp.raise_for_status()
                except httpx.HTTPError as exc:
                    # A bad/expired key or a rate limit must not crash the
                    # whole task -- confirmed live, a set-but-invalid
                    # NEWSAPI_KEY gets a real 401 from newsapi.org, and this
                    # used to have no try/except at all around the request.
                    # Matches the fail-soft behavior this source's streaming
                    # producer (app/streaming/producers/newsapi_stream.py)
                    # already has.
                    logger.warning("NewsAPI search failed for %r, skipping: %s", term, exc)
                    continue
                for article in resp.json().get("articles", []):
                    records.append(
                        scrub_record(
                            {
                                "name": article.get("title", term),
                                "entity_type": "news_mention",
                                "source": "newsapi",
                                "license": "headline/snippet only, per NewsAPI ToS",
                                "metadata": {
                                    "url": article.get("url"),
                                    "outlet": (article.get("source") or {}).get("name"),
                                    "published_at": article.get("publishedAt"),
                                    "retrieved_at": datetime.utcnow().isoformat(),
                                },
                            }
                        )
                    )
        return records

    @task
    def load_records(records: list[dict]) -> int:
        from common.db import upsert_entities

        return upsert_entities(records)

    load_records(fetch_headlines())


newsapi_ingestion_dag()
