"""DAG: GTFS static transit stop sync (gtfs_transit_sync).

Free, no API key. Phase 6's "GTFS transit feeds" item -- transit stops are
point locations, so unlike the tract/zoning boundary DAGs this needs no
new schema: stops land in research_entities (entity_type='poi') via the
existing upsert_entities(), same as every other point source.

Source is Metrolink's (Southern California regional rail) published
static GTFS feed -- a standard, publicly documented, directly-downloadable
zip per GTFS's own best-practices spec. Confirmed live: the feed
downloads, unzips, and its stops.txt contains real station names/coords
(e.g. "Anaheim - ARTIC" at 33.802582,-117.877998). Also confirmed live:
the feed 403s a generic httpx default User-Agent, so (same requirement as
Nominatim/NOAA-NWS elsewhere in this repo) a real, identifying
`GTFS_USER_AGENT` is required.

Only one agency's feed is wired here -- extending to another agency means
adding another (label, url) pair to the seed list below, following this
same pattern.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import zipfile
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (agency_label, source_slug, gtfs_zip_url) -- extend via the
# `gtfs_feeds` Airflow Variable (JSON list of the same shape) rather than
# editing code.
DEFAULT_FEEDS = [
    ("Metrolink", "gtfs_metrolink", "https://metrolinktrains.com/globalassets/about/gtfs/gtfs.zip"),
]

# Confirmed live: this feed 403s httpx's generic default User-Agent
# (distinct from evasion -- it's an honest, identifying string, same
# requirement as Nominatim/NOAA elsewhere in this repo) but accepts one
# that identifies the requester.
USER_AGENT = os.environ.get(
    "GTFS_USER_AGENT", "AetherSovereignOS-Airflow/0.2 (public-records research tool; set GTFS_USER_AGENT)"
)


@dag(
    dag_id="gtfs_transit_sync",
    description="Syncs real GTFS static transit stops into research_entities.",
    schedule="@monthly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "gtfs", "public-records"],
)
def gtfs_transit_dag():
    @task
    def fetch_stops() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw = Variable.get("gtfs_feeds", deserialize_json=True)
            feeds = [tuple(f) for f in raw]
        except Exception:
            feeds = DEFAULT_FEEDS

        records: list[dict] = []
        with httpx.Client(
            timeout=60.0, follow_redirects=True, headers={"User-Agent": USER_AGENT}
        ) as client:
            for agency_label, source_slug, feed_url in feeds:
                resp = client.get(feed_url)
                resp.raise_for_status()

                with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
                    with archive.open("stops.txt") as stops_file:
                        reader = csv.DictReader(io.TextIOWrapper(stops_file, encoding="utf-8-sig"))
                        for row in reader:
                            stop_id = row.get("stop_id")
                            stop_name = row.get("stop_name")
                            try:
                                lat = float(row.get("stop_lat", ""))
                                lon = float(row.get("stop_lon", ""))
                            except (TypeError, ValueError):
                                continue
                            if not stop_id or not stop_name:
                                continue

                            records.append(
                                scrub_record(
                                    {
                                        "name": f"{stop_name} ({agency_label})",
                                        "entity_type": "poi",
                                        "source": source_slug,
                                        "license": "GTFS static feed -- published by agency for public use",
                                        "lat": lat,
                                        "lon": lon,
                                        "metadata": {
                                            "stop_id": stop_id,
                                            "agency": agency_label,
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

    load_records(fetch_stops())


gtfs_transit_dag()
