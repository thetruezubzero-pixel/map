"""DAG: USGS elevation sync (dag_usgs_national_map).

Free, no API key. Uses the USGS Elevation Point Query Service (part of
The National Map) to attach elevation metadata to seed locations. Stored
as `location` records tagged source="usgs_national_map"; this is
infrastructure/terrain data, not tied to any individual.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (name, lat, lon) -- extend via the `usgs_seed_points` Airflow Variable
# (JSON list of [name, lat, lon]) rather than editing code.
DEFAULT_SEED_POINTS = [
    ("Central Park, New York", 40.7829, -73.9654),
    ("Golden Gate Park, San Francisco", 37.7694, -122.4862),
]

EPQS_URL = "https://epqs.nationalmap.gov/v1/json"


@dag(
    dag_id="usgs_elevation_sync",
    description="Syncs USGS elevation data for seed points into research_entities.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "usgs", "public-records"],
)
def usgs_elevation_dag():
    @task
    def fetch_elevations() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw_points = Variable.get("usgs_seed_points", deserialize_json=True)
            points = [tuple(p) for p in raw_points]
        except Exception:
            points = DEFAULT_SEED_POINTS

        records: list[dict] = []
        with httpx.Client(timeout=15.0) as client:
            for name, lat, lon in points:
                # A readiness review found this per-point call had no
                # try/except -- a single transient EPQS failure (5xx, or a
                # malformed non-JSON body) crashed the whole task,
                # discarding every other point's records. Fail soft per
                # point instead.
                try:
                    resp = client.get(
                        EPQS_URL, params={"x": lon, "y": lat, "units": "Meters", "wkid": 4326}
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    import logging

                    logging.getLogger("airflow.task").warning(
                        "usgs_elevation: point %r failed, skipping: %s", name, exc
                    )
                    continue
                elevation = data.get("value")
                if elevation is None:
                    continue

                records.append(
                    scrub_record(
                        {
                            "name": name,
                            "entity_type": "location",
                            "source": "usgs_national_map",
                            "license": "USGS -- public domain",
                            "lat": lat,
                            "lon": lon,
                            "metadata": {
                                "elevation_m": float(elevation),
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

    load_records(fetch_elevations())


usgs_elevation_dag()
