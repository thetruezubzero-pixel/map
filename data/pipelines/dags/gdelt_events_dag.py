"""DAG: GDELT global event sync (dag_gdelt_events).

Free, no API key. Uses the GDELT 2.0 Doc API (article search) rather than
the deprecated geo endpoint. Stored as `news_mention` records like
NewsAPI's, tagged source="gdelt" -- global news coverage, not
individual-level data.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

logger = logging.getLogger("aether.dags.gdelt")

DEFAULT_SEARCH_TERMS = ["business acquisition", "corporate merger"]
GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


@dag(
    dag_id="gdelt_events_sync",
    description="Syncs GDELT global news events into research_entities as news_mention records.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "gdelt", "public-records"],
)
def gdelt_events_dag():
    @task
    def fetch_events() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            search_terms = Variable.get("gdelt_search_terms", deserialize_json=True)
        except Exception:
            search_terms = DEFAULT_SEARCH_TERMS

        records: list[dict] = []
        with httpx.Client(timeout=20.0) as client:
            for term in search_terms:
                try:
                    resp = client.get(
                        GDELT_DOC_API,
                        params={"query": term, "mode": "artlist", "format": "json", "maxrecords": 20},
                    )
                    resp.raise_for_status()
                    if not resp.text.strip():
                        continue
                    articles = resp.json().get("articles", [])
                except (httpx.HTTPError, ValueError) as exc:
                    # GDELT rate-limits fairly aggressively on repeated calls;
                    # skip this term rather than fail the whole sync.
                    logger.warning("GDELT search failed for %r, skipping: %s", term, exc)
                    continue
                for article in articles:
                    records.append(
                        scrub_record(
                            {
                                "name": article.get("title", term),
                                "entity_type": "news_mention",
                                "source": "gdelt",
                                "license": "GDELT Project -- free for research/non-commercial use",
                                "metadata": {
                                    "url": article.get("url"),
                                    "domain": article.get("domain"),
                                    "seen_date": article.get("seendate"),
                                    "source_country": article.get("sourcecountry"),
                                    "language": article.get("language"),
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

    load_records(fetch_events())


gdelt_events_dag()
