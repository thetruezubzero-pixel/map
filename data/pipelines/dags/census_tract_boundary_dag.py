"""DAG: Census tract polygon boundary sync (census_tract_boundary_sync).

Free, no API key. Phase 6 follow-up to census_tiger_dag.py: that DAG
stores county centroids only (research_entities.geom is Point-only,
noted in its own docstring as a limitation). This DAG stores the actual
tract polygon geometry in research_entity_boundaries
(0010_entity_boundaries.sql), unlocking real point-in-polygon spatial
joins and choropleth rendering per ROADMAP.md's Phase 6.

Confirmed live: a STATE=36/COUNTY=061 (New York County) query against
layer 0 ("Census Tracts") of TIGERweb's Tracts_Blocks service returns
real tract polygons with GEOID/NAME/TRACT attributes.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (state_fips, county_fips, label) -- extend via the `census_tract_counties`
# Airflow Variable (JSON list of [state_fips, county_fips, label]) rather
# than editing code.
DEFAULT_COUNTIES = [
    ("36", "061", "New York County, NY"),
    ("06", "075", "San Francisco County, CA"),
]

# Layer 0 = "Census Tracts" (maxRecordCount 100000, confirmed live -- a
# single county's tract count never approaches that, so no pagination
# is needed here unlike a statewide query would require).
TIGERWEB_TRACTS_LAYER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Tracts_Blocks/MapServer/0/query"
)


@dag(
    dag_id="census_tract_boundary_sync",
    description="Syncs real Census tract polygon boundaries into research_entity_boundaries.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "census", "public-records", "boundaries"],
)
def census_tract_boundary_dag():
    @task
    def fetch_tracts() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw = Variable.get("census_tract_counties", deserialize_json=True)
            counties = [tuple(c) for c in raw]
        except Exception:
            counties = DEFAULT_COUNTIES

        records: list[dict] = []
        with httpx.Client(timeout=30.0) as client:
            for state_fips, county_fips, label in counties:
                if not (str(state_fips).isdigit() and str(county_fips).isdigit()):
                    continue
                resp = client.get(
                    TIGERWEB_TRACTS_LAYER,
                    params={
                        "where": f"STATE='{state_fips}' AND COUNTY='{county_fips}'",
                        "outFields": "GEOID,NAME,STATE,COUNTY,TRACT",
                        "returnGeometry": "true",
                        "f": "geojson",
                    },
                )
                resp.raise_for_status()
                for feature in resp.json().get("features", []):
                    geometry = feature.get("geometry")
                    attrs = feature.get("properties", {})
                    geoid = attrs.get("GEOID")
                    if not geometry or not geoid:
                        continue

                    records.append(
                        scrub_record(
                            {
                                "name": f"Census Tract {attrs.get('TRACT')}, {label}",
                                "boundary_type": "census_tract",
                                "source": "census_tiger_tracts",
                                "license": "US Census Bureau -- public domain",
                                "geojson_geometry": geometry,
                                "metadata": {
                                    "geoid": geoid,
                                    "state_fips": attrs.get("STATE"),
                                    "county_fips": attrs.get("COUNTY"),
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

    load_records(fetch_tracts())


census_tract_boundary_dag()
