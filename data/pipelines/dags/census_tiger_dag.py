"""DAG: Census TIGERweb boundary sync (dag_census_tiger).

Free, no API key. Queries the TIGERweb ArcGIS REST service for county
boundaries by name and stores the county centroid as a `location` record.
research_entities.geom is a Point column, so full polygon boundaries
aren't stored here -- GEOID is kept in metadata for a future PostGIS
polygon table if that becomes worth the schema change.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

DEFAULT_COUNTY_QUERIES = ["New York", "San Francisco"]
TIGERWEB_COUNTY_LAYER = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1/query"
)


@dag(
    dag_id="census_tiger_sync",
    description="Syncs Census TIGERweb county boundaries (as centroids) into research_entities.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "census", "public-records"],
)
def census_tiger_dag():
    @task
    def fetch_counties() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            queries = Variable.get("census_county_queries", deserialize_json=True)
        except Exception:
            queries = DEFAULT_COUNTY_QUERIES

        records: list[dict] = []
        with httpx.Client(timeout=20.0) as client:
            for query in queries:
                resp = client.get(
                    TIGERWEB_COUNTY_LAYER,
                    params={
                        "where": f"NAME LIKE '{query}%'",
                        "outFields": "NAME,STATE,COUNTY,GEOID,CENTLAT,CENTLON",
                        "returnGeometry": "false",
                        "f": "json",
                    },
                )
                resp.raise_for_status()
                for feature in resp.json().get("features", []):
                    attrs = feature["attributes"]
                    try:
                        lat = float(attrs["CENTLAT"])
                        lon = float(attrs["CENTLON"])
                    except (TypeError, ValueError):
                        continue

                    records.append(
                        scrub_record(
                            {
                                "name": f"{attrs['NAME']}, {attrs['STATE']}",
                                "entity_type": "location",
                                "source": "census_tiger",
                                "license": "US Census Bureau -- public domain",
                                "lat": lat,
                                "lon": lon,
                                "metadata": {
                                    "geoid": attrs.get("GEOID"),
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
        from common.db import upsert_entities

        return upsert_entities(records)

    load_records(fetch_counties())


census_tiger_dag()
