"""DAG: Data.gov dataset search sync (dag_data_gov_search).

Free, no API key -- uses the CKAN `package_search` action API. Datasets
found (permits, zoning, infrastructure, environmental, ...) are stored as
`government_filing` records (the closest fit in the existing entity_type
allowlist -- see ROADMAP.md on adding new types) with the dataset's
metadata/resource links, not the dataset contents themselves.

NOTE: as of this writing catalog.data.gov's classic CKAN API endpoints
return 404 (the site appears to have been restructured); this DAG is
written against the documented CKAN contract and fails soft (empty
result, logged warning) if the endpoint is unreachable, rather than
raising. If data.gov's API has moved, update DATA_GOV_API_BASE.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

logger = logging.getLogger("aether.dags.data_gov")

DEFAULT_SEARCH_TERMS = ["zoning", "building permits"]
DATA_GOV_API_BASE = "https://catalog.data.gov/api/3/action"


@dag(
    dag_id="data_gov_search_sync",
    description="Searches Data.gov for new relevant datasets and records them in research_entities.",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "data-gov", "public-records"],
)
def data_gov_search_dag():
    @task
    def search_datasets() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            search_terms = Variable.get("data_gov_search_terms", deserialize_json=True)
        except Exception:
            search_terms = DEFAULT_SEARCH_TERMS

        records: list[dict] = []
        with httpx.Client(timeout=20.0) as client:
            for term in search_terms:
                try:
                    resp = client.get(
                        f"{DATA_GOV_API_BASE}/package_search", params={"q": term, "rows": 10}
                    )
                    resp.raise_for_status()
                    payload = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("data.gov search failed for %r, skipping: %s", term, exc)
                    continue

                for pkg in payload.get("result", {}).get("results", []):
                    records.append(
                        scrub_record(
                            {
                                "name": pkg.get("title", term),
                                "entity_type": "government_filing",
                                "source": "data_gov",
                                "license": pkg.get("license_title") or "Data.gov -- open government data",
                                "metadata": {
                                    "organization": (pkg.get("organization") or {}).get("title"),
                                    "notes": pkg.get("notes"),
                                    "tags": [t.get("name") for t in pkg.get("tags", [])],
                                    "url": f"https://catalog.data.gov/dataset/{pkg.get('name')}"
                                    if pkg.get("name")
                                    else None,
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

    load_records(search_datasets())


data_gov_search_dag()
