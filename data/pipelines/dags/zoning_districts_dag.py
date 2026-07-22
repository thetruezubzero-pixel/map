"""DAG: NYC zoning district polygon sync (zoning_districts_sync).

Free, no API key. Part of Phase 6's "GTFS transit feeds, census-tract/
zoning polygon ingestion" -- stores real zoning district polygons in
research_entity_boundaries (0010_entity_boundaries.sql), same rationale
as census_tract_boundary_dag.py.

Source is NYC Department of City Planning's public "nyzd" (zoning
districts) ArcGIS FeatureServer -- the authoritative source published on
the city's BYTES of the BIG APPLE open-data portal. Confirmed live: a
bounding-box query over lower Manhattan returns real zoning polygons with
a ZONEDIST designation (e.g. "R8", "C6-2A").

Only one metro area's zoning is wired here (there is no single national
open-data API for zoning the way TIGERweb covers Census geography) --
extending to another city means adding another seed bbox/endpoint pair,
following this same pattern.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (label, min_lon, min_lat, max_lon, max_lat) -- extend via the
# `zoning_seed_bboxes` Airflow Variable (JSON list of the same shape)
# rather than editing code. Kept small deliberately: a wide bbox risks
# tripping the service's maxRecordCount (2000, confirmed live) silently
# truncating results.
DEFAULT_SEED_BBOXES = [
    ("Lower Manhattan, NY", -74.0100, 40.7050, -73.9950, 40.7150),
]

NYC_ZONING_LAYER = (
    "https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/arcgis/rest/services/nyzd/FeatureServer/0/query"
)


@dag(
    dag_id="zoning_districts_sync",
    description="Syncs real NYC zoning district polygons into research_entity_boundaries.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "zoning", "public-records", "boundaries"],
)
def zoning_districts_dag():
    @task
    def fetch_zoning_districts() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw = Variable.get("zoning_seed_bboxes", deserialize_json=True)
            bboxes = [tuple(b) for b in raw]
        except Exception:
            bboxes = DEFAULT_SEED_BBOXES

        records: list[dict] = []
        with httpx.Client(timeout=30.0) as client:
            for label, min_lon, min_lat, max_lon, max_lat in bboxes:
                resp = client.get(
                    NYC_ZONING_LAYER,
                    params={
                        "geometry": f"{min_lon},{min_lat},{max_lon},{max_lat}",
                        "geometryType": "esriGeometryEnvelope",
                        "spatialRel": "esriSpatialRelIntersects",
                        "inSR": 4326,
                        "outFields": "OBJECTID,ZONEDIST",
                        "returnGeometry": "true",
                        "f": "geojson",
                    },
                )
                resp.raise_for_status()
                for feature in resp.json().get("features", []):
                    geometry = feature.get("geometry")
                    attrs = feature.get("properties", {})
                    object_id = attrs.get("OBJECTID")
                    zone_dist = attrs.get("ZONEDIST")
                    if not geometry or object_id is None or not zone_dist:
                        continue

                    records.append(
                        scrub_record(
                            {
                                "name": f"Zoning District {zone_dist} ({object_id}), {label}",
                                "boundary_type": "zoning",
                                "source": "nyc_dcp_zoning",
                                "license": "NYC Department of City Planning -- public domain",
                                "geojson_geometry": geometry,
                                "metadata": {
                                    "zone_dist": zone_dist,
                                    "object_id": object_id,
                                    "retrieved_at": datetime.utcnow().isoformat(),
                                },
                            }
                        )
                    )
        return records

    @task
    def load_records(records: list[dict]) -> int:
        from common.db import upsert_boundaries

        return upsert_boundaries(records)

    load_records(fetch_zoning_districts())


zoning_districts_dag()
