"""DAG: FCC spectrum licensing sync (fcc_spectrum_licensing_sync).

Free, no API key. Phase 8's "FCC ULS (Universal Licensing System) +
Antenna Structure Registration" item -- see ROADMAP.md "Phase 8". Public
institutional records only: a business's radio-spectrum license and the
transmitter tower's coordinates, both already-public facts filed with a
federal agency. This DAG does not detect, scan for, or interact with any
actual radio signal or hardware -- it queries a published government
database, exactly like sec_edgar_ingestion_dag.py queries EDGAR filings.

Source: the FCC's Socrata open-data portal (opendata.fcc.gov), which
mirrors ULS license data as directly queryable datasets -- confirmed live
to need no API key/auth, unlike the FCC's own www.fcc.gov developer API
(License View API), which sits behind Akamai bot-protection that blocked
every request from this sandbox during development (HTTP/2 stream resets
regardless of User-Agent). Wired here: the "ULS 3650 Locations (Complete
Dataset)" dataset (resource id r3zi-75n9), covering the 3650-3700 MHz
band (a real, FCC-designated commercial/broadband radio service) --
confirmed live at 7,829 total rows, every row has non-null coordinates,
and `u_application_status` is one of Accepted/Deleted/Rejected (filtered
to Accepted here -- a Deleted/Rejected application isn't a current,
surfaceable fact). Extending to another ULS service/license-type dataset
means adding another (label, source_slug, resource_id) tuple to the seed
list below, following this same pattern -- opendata.fcc.gov hosts several
more (e.g. "Protected FSS Earth Station Registration").

Lands as entity_type='government_filing' (the row is fundamentally a
federal license grant), with the transmitter's real lat/lon in `geom` and
licensee name/call sign/frequency band in `metadata` -- same "one entity
type, everything else in metadata" shape newsapi/opencorporates already
use for a record that spans more than one facet.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (agency_label, source_slug, socrata_resource_id) -- extend via the
# `fcc_uls_datasets` Airflow Variable (JSON list of the same shape)
# rather than editing code.
DEFAULT_DATASETS = [
    ("FCC ULS 3650 MHz Band", "fcc_uls_3650", "r3zi-75n9"),
]

SOCRATA_BASE_URL = "https://opendata.fcc.gov/resource"
PAGE_SIZE = 1000


@dag(
    dag_id="fcc_spectrum_licensing_sync",
    description="Syncs real FCC spectrum-license + transmitter-location records into research_entities.",
    schedule="@weekly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "fcc", "public-records"],
)
def fcc_spectrum_licensing_dag():
    @task
    def fetch_licenses() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw = Variable.get("fcc_uls_datasets", deserialize_json=True)
            datasets = [tuple(d) for d in raw]
        except Exception:
            datasets = DEFAULT_DATASETS

        records: list[dict] = []
        with httpx.Client(timeout=30.0) as client:
            for agency_label, source_slug, resource_id in datasets:
                offset = 0
                while True:
                    resp = client.get(
                        f"{SOCRATA_BASE_URL}/{resource_id}.json",
                        params={
                            "$where": "u_application_status='Accepted'",
                            "$limit": PAGE_SIZE,
                            "$offset": offset,
                        },
                    )
                    resp.raise_for_status()
                    page = resp.json()
                    if not page:
                        break

                    for row in page:
                        call_sign = row.get("u_call_sign")
                        license_name = row.get("u_license_name")
                        try:
                            lat = float(row.get("u_latitude", ""))
                            lon = float(row.get("u_longitude", ""))
                        except (TypeError, ValueError):
                            continue
                        if not call_sign or not license_name:
                            continue

                        records.append(
                            scrub_record(
                                {
                                    "name": f"{license_name} ({call_sign})",
                                    "entity_type": "government_filing",
                                    "source": source_slug,
                                    "license": "FCC ULS (Universal Licensing System) -- public license record",
                                    "lat": lat,
                                    "lon": lon,
                                    "metadata": {
                                        "call_sign": call_sign,
                                        "agency": agency_label,
                                        "licensee": license_name,
                                        "location_city": row.get("u_location_city"),
                                        "location_state": row.get("u_location_state"),
                                        "location_county": row.get("u_location_county"),
                                        "lower_frequency": row.get("u_lower_frequency"),
                                        "upper_frequency": row.get("u_upper_frequency"),
                                        "application_status": row.get("u_application_status"),
                                        "retrieved_at": datetime.utcnow().isoformat(),
                                    },
                                }
                            )
                        )

                    if len(page) < PAGE_SIZE:
                        break
                    offset += PAGE_SIZE
        return records

    @task
    def load_records(records: list[dict]) -> int:
        from common.db import upsert_entities

        return upsert_entities(records)

    load_records(fetch_licenses())


fcc_spectrum_licensing_dag()
