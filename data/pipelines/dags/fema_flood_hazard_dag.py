"""DAG: FEMA National Flood Hazard Layer sync (fema_flood_hazard_sync).

Free, no API key. Queries FEMA's public NFHL ArcGIS REST endpoint (Flood
Hazard Zones layer) for seed locations and stores the flood zone
designation as a `location` record -- property/site flood risk, not tied
to any individual. Confirmed live: a point query against
40.7829,-73.9654 (Central Park) returns real zone polygon data
(FLD_ZONE="X", "AREA OF MINIMAL FLOOD HAZARD").
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (name, lat, lon) -- extend via the `fema_seed_points` Airflow Variable
# (JSON list of [name, lat, lon]) rather than editing code.
DEFAULT_SEED_POINTS = [
    ("Central Park, New York", 40.7829, -73.9654),
    ("Golden Gate Park, San Francisco", 37.7694, -122.4862),
]

# NFHL MapServer layer 28 = "Flood Hazard Zones".
NFHL_QUERY_URL = (
    "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
)


@dag(
    dag_id="fema_flood_hazard_sync",
    description="Syncs FEMA NFHL flood zone designations for seed points into research_entities.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "fema", "public-records"],
)
def fema_flood_hazard_dag():
    @task
    def fetch_flood_zones() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw_points = Variable.get("fema_seed_points", deserialize_json=True)
            points = [tuple(p) for p in raw_points]
        except Exception:
            points = DEFAULT_SEED_POINTS

        records: list[dict] = []
        with httpx.Client(timeout=20.0) as client:
            for name, lat, lon in points:
                # A readiness review found this per-point call had no
                # try/except -- a single transient NFHL failure (5xx, or a
                # malformed non-JSON body) crashed the whole task,
                # discarding every other point's records. Fail soft per
                # point instead.
                try:
                    resp = client.get(
                        NFHL_QUERY_URL,
                        params={
                            "geometry": f"{lon},{lat}",
                            "geometryType": "esriGeometryPoint",
                            "inSR": 4326,
                            "spatialRel": "esriSpatialRelIntersects",
                            "outFields": "FLD_ZONE,ZONE_SUBTY",
                            "f": "json",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    import logging

                    logging.getLogger("airflow.task").warning(
                        "fema_flood_hazard: point %r failed, skipping: %s", name, exc
                    )
                    continue
                features = data.get("features") or []
                if not features:
                    continue

                attrs = features[0].get("attributes", {})
                flood_zone = attrs.get("FLD_ZONE")
                if not flood_zone:
                    continue

                records.append(
                    scrub_record(
                        {
                            "name": name,
                            "entity_type": "location",
                            "source": "fema_nfhl",
                            "license": "FEMA -- public domain",
                            "lat": lat,
                            "lon": lon,
                            "metadata": {
                                "flood_zone": flood_zone,
                                "zone_subtype": attrs.get("ZONE_SUBTY"),
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

    load_records(fetch_flood_zones())


fema_flood_hazard_dag()
