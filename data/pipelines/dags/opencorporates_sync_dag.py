"""DAG 3: OpenCorporates business registration sync.

Company (not individual) records only. `officers`/director names are
intentionally not ingested here -- see ROADMAP.md: no individual profiling.
Every record is tagged source="opencorporates".
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

DEFAULT_JURISDICTIONS = ["us_de", "us_ny"]
DEFAULT_SEARCH_TERMS = ["holdings", "ventures"]


@dag(
    dag_id="opencorporates_sync",
    description="Syncs OpenCorporates business registrations into research_entities.",
    schedule="@weekly",  # free-tier daily quota is small; weekly keeps us well under it
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "opencorporates", "public-records"],
)
def opencorporates_sync_dag():
    @task
    def fetch_companies() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        api_token = os.environ.get("OPENCORPORATES_API_KEY", "")
        if not api_token:
            return []

        try:
            search_terms = Variable.get("opencorporates_search_terms", deserialize_json=True)
        except Exception:
            search_terms = DEFAULT_SEARCH_TERMS

        records: list[dict] = []
        with httpx.Client(timeout=15.0) as client:
            for term in search_terms:
                resp = client.get(
                    "https://api.opencorporates.com/v0.4/companies/search",
                    params={
                        "q": term,
                        "jurisdiction_code": ",".join(DEFAULT_JURISDICTIONS),
                        "api_token": api_token,
                    },
                )
                resp.raise_for_status()
                companies = resp.json().get("results", {}).get("companies", [])
                for c in companies:
                    company = c.get("company") or {}
                    records.append(
                        scrub_record(
                            {
                                "name": company.get("name", term),
                                "entity_type": "business",
                                "source": "opencorporates",
                                "license": "OpenCorporates ToS -- public register data",
                                "metadata": {
                                    "jurisdiction": company.get("jurisdiction_code"),
                                    "company_number": company.get("company_number"),
                                    "status": company.get("current_status"),
                                    "url": company.get("opencorporates_url"),
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

    load_records(fetch_companies())


opencorporates_sync_dag()
