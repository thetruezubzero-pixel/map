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

Cross-source blending (Phase 8's "link a business's FCC license... to its
existing research_entities row" item): a second task,
link_to_business_entities, connects each FCC filing to an existing
entity_type='business' row by exact normalized-name match, reusing
app.graph.normalize.normalize_name -- the identical function
entity_resolution_dag.py uses for business-to-business dedup, so "the
same normalized name" means the same thing in both places. This is
deliberately NOT written as a 'same_as' edge (that means "these two rows
are the same real-world entity," which an FCC filing and a business
record are not) and does not extend resolve.py's business-only
find_candidate_pairs/score_pair machinery (which scores identity-equivalence
signals -- exact ID columns, same officer -- that don't apply to a filing
row). Instead it's a new, distinct entity_relationships.relation_type,
'holds_fcc_license' -- the same free-text column already models
'subsidiary' and 'same_as', just a third, narrower kind of institutional
relationship (a business holds a license), not personal relationship
mapping and not identity-equivalence."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "apps", "api", "python"))

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
                    try:
                        resp = client.get(
                            f"{SOCRATA_BASE_URL}/{resource_id}.json",
                            params={
                                "$where": "u_application_status='Accepted'",
                                # Socrata's offset+limit paging isn't
                                # guaranteed stable across calls without an
                                # explicit deterministic order -- a
                                # readiness review flagged this could
                                # silently skip/duplicate rows across
                                # pages. `:id` is Socrata's own internal
                                # row identifier, documented for exactly
                                # this stable-pagination use case.
                                "$order": ":id",
                                "$limit": PAGE_SIZE,
                                "$offset": offset,
                            },
                        )
                        resp.raise_for_status()
                    except httpx.HTTPError as exc:
                        # A readiness review found a single transient
                        # 5xx/429 mid-pagination discarded every
                        # already-accumulated record, not just this
                        # dataset's -- fail soft per dataset instead,
                        # matching opencorporates_sync_dag.py/
                        # data_gov_search_dag.py's established pattern for
                        # this exact class of flaky-external-API failure.
                        import logging

                        logging.getLogger("airflow.task").warning(
                            "fcc_spectrum_licensing_sync: %s fetch failed at offset %d: %s",
                            source_slug, offset, exc,
                        )
                        break
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

    @task
    def link_to_business_entities(loaded_count: int) -> int:
        """Runs after load_records so it always sees this run's rows
        (Airflow's TaskFlow dependency via `loaded_count`, unused
        otherwise). Re-scans every fcc_uls_* filing on each run, not just
        this run's new ones -- idempotent (ON CONFLICT DO NOTHING) and
        self-healing: a business entity added after its FCC filing was
        first ingested still gets linked on the next weekly run."""
        import asyncio

        import asyncpg

        async def _run() -> int:
            from app.graph.normalize import normalize_name

            dsn = os.environ.get(
                "GATEWAY_DATABASE_URL", "postgres://aether:aether@localhost:5432/aether"
            )
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
            try:
                business_rows = await pool.fetch(
                    "SELECT id, name FROM research_entities WHERE entity_type = 'business' ORDER BY id"
                )
                # A readiness review found that two genuinely distinct
                # businesses whose names both normalize to the same
                # string (normalize_name strips legal-form suffixes like
                # Inc/LLC/Corp -- two unrelated "Example Wireless" filers
                # under different suffixes would collide) picked a
                # non-deterministic winner via setdefault, silently
                # writing a wrong holds_fcc_license fact with no
                # confidence score and no review path -- unlike
                # resolve.py's own handling of the identical
                # normalized-name-alone signal, which scores it at 0.7,
                # below the 0.8 auto-confirm bar, and requires a second
                # corroborating signal before auto-linking. FCC filings
                # have none of resolve.py's other signals available
                # (no cik/opencorporates_id/ein), so rather than
                # inventing a second signal, an ambiguous collision here
                # is marked with `None` and skipped outright below --
                # conservative by design, matching a public-records tool
                # that shouldn't record a fact it isn't sure of.
                business_by_norm_name: dict[str, str | None] = {}
                for row in business_rows:
                    norm = normalize_name(row["name"])
                    if not norm:
                        continue
                    if norm in business_by_norm_name:
                        business_by_norm_name[norm] = None
                    else:
                        business_by_norm_name[norm] = row["id"]

                filing_rows = await pool.fetch(
                    "SELECT id, metadata FROM research_entities "
                    "WHERE entity_type = 'government_filing' AND source LIKE 'fcc_uls_%'"
                )

                linked = 0
                for row in filing_rows:
                    metadata = row["metadata"]
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    licensee = (metadata or {}).get("licensee")
                    if not licensee:
                        continue

                    business_id = business_by_norm_name.get(normalize_name(licensee))
                    if not business_id:
                        continue

                    result = await pool.execute(
                        """
                        INSERT INTO entity_relationships
                            (parent_entity_id, child_entity_id, relation_type, source)
                        VALUES ($1, $2, 'holds_fcc_license', 'fcc_spectrum_licensing_sync')
                        ON CONFLICT DO NOTHING
                        """,
                        business_id,
                        row["id"],
                    )
                    if result.endswith(" 1"):
                        linked += 1
                return linked
            finally:
                await pool.close()

        return asyncio.run(_run())

    link_to_business_entities(load_records(fetch_licenses()))


fcc_spectrum_licensing_dag()
