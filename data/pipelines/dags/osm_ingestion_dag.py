"""DAG 1: OSM boundary and POI ingestion (Nominatim -> PostGIS).

Public OpenStreetMap data only. Every record is tagged with source="openstreetmap"
and license="ODbL" per OSM's license terms.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# Seed queries define what this DAG keeps in sync -- extend via an Airflow
# Variable (`osm_seed_queries`, JSON list) in production rather than editing
# code for every new area of interest.
DEFAULT_SEED_QUERIES = [
    "Central Park, New York",
    "Golden Gate Park, San Francisco",
]


@dag(
    dag_id="osm_ingestion",
    description="Ingests OSM boundaries/POIs for seed queries into research_entities.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "osm", "public-records"],
)
def osm_ingestion_dag():
    @task
    def fetch_osm_records() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            seed_queries = Variable.get("osm_seed_queries", deserialize_json=True)
        except Exception:
            seed_queries = DEFAULT_SEED_QUERIES

        user_agent = os.environ.get(
            "NOMINATIM_USER_AGENT", "AetherSovereignOS-Airflow/0.2 (set NOMINATIM_USER_AGENT)"
        )
        base_url = os.environ.get("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")

        records: list[dict] = []
        with httpx.Client(timeout=15.0, headers={"User-Agent": user_agent}) as client:
            for query in seed_queries:
                resp = client.get(
                    f"{base_url}/search",
                    params={"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1},
                )
                resp.raise_for_status()
                for hit in resp.json():
                    records.append(
                        scrub_record(
                            {
                                "name": hit.get("display_name", query),
                                "entity_type": "poi" if hit.get("type") != "administrative" else "location",
                                "source": "openstreetmap",
                                "license": "ODbL",
                                "lat": float(hit["lat"]) if hit.get("lat") else None,
                                "lon": float(hit["lon"]) if hit.get("lon") else None,
                                "metadata": {
                                    "osm_type": hit.get("type"),
                                    "osm_class": hit.get("class"),
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

    load_records(fetch_osm_records())


osm_ingestion_dag()
