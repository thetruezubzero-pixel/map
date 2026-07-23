"""DAG: NOAA/NWS active weather alerts sync (noaa_alerts_sync).

Free, no API key (a descriptive User-Agent is required by NWS's usage
policy, same requirement as Nominatim). Queries api.weather.gov for
active alerts (severe weather, flood, fire weather, etc.) intersecting
seed locations and stores each as a `location` record -- site/area hazard
conditions, not tied to any individual. Confirmed live: a point query
against 40.7829,-73.9654 returns real, currently-active alert data when
present (0 features is a normal/expected response when nothing is active
at that point right now).
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

# (name, lat, lon) -- extend via the `noaa_seed_points` Airflow Variable
# (JSON list of [name, lat, lon]) rather than editing code.
DEFAULT_SEED_POINTS = [
    ("Central Park, New York", 40.7829, -73.9654),
    ("Golden Gate Park, San Francisco", 37.7694, -122.4862),
]

ALERTS_URL = "https://api.weather.gov/alerts/active"

# NWS's usage policy requires a real, identifying contact, same as
# Nominatim's -- generic placeholder domains get blocked.
USER_AGENT = os.environ.get(
    "NOAA_NWS_USER_AGENT", "AetherSovereignOS/0.2 (contact: ops@yourdomain.org)"
)


@dag(
    dag_id="noaa_alerts_sync",
    description="Syncs NOAA/NWS active weather alerts for seed points into research_entities.",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["ingestion", "noaa", "public-records"],
)
def noaa_alerts_dag():
    @task
    def fetch_alerts() -> list[dict]:
        import httpx
        from airflow.sdk import Variable

        from common.pii_scrub import scrub_record

        try:
            raw_points = Variable.get("noaa_seed_points", deserialize_json=True)
            points = [tuple(p) for p in raw_points]
        except Exception:
            points = DEFAULT_SEED_POINTS

        records: list[dict] = []
        with httpx.Client(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
            for name, lat, lon in points:
                # A readiness review found this per-point call had no
                # try/except -- a single transient NWS failure (5xx, or a
                # malformed non-JSON body) crashed the whole task,
                # discarding every other point's alerts. Fail soft per
                # point instead.
                try:
                    resp = client.get(ALERTS_URL, params={"point": f"{lat},{lon}"})
                    resp.raise_for_status()
                    data = resp.json()
                except (httpx.HTTPError, ValueError) as exc:
                    import logging

                    logging.getLogger("airflow.task").warning(
                        "noaa_alerts: point %r failed, skipping: %s", name, exc
                    )
                    continue

                for feature in data.get("features", []):
                    props = feature.get("properties", {})
                    event = props.get("event")
                    alert_id = props.get("id")
                    if not event or not alert_id:
                        continue

                    # `alert_id` (an NWS-issued URN, stable across refetches
                    # of the *same* ongoing alert) is folded into `name`
                    # because the idempotency constraint is
                    # (source, entity_type, name) -- see
                    # apps/gateway/migrations/0004_entities_idempotency.sql.
                    # Without it, a brand-new alert issued after an old one
                    # at the same point expires would collide on
                    # "{event} -- {location}" and silently never insert,
                    # leaving the stale expired alert as the only record.
                    records.append(
                        scrub_record(
                            {
                                "name": f"{event} -- {name} [{alert_id}]",
                                "entity_type": "location",
                                "source": "noaa_nws_alerts",
                                "license": "NOAA/NWS -- public domain",
                                "lat": lat,
                                "lon": lon,
                                "metadata": {
                                    "alert_id": alert_id,
                                    "event": event,
                                    "severity": props.get("severity"),
                                    "certainty": props.get("certainty"),
                                    "urgency": props.get("urgency"),
                                    "area_desc": props.get("areaDesc"),
                                    "effective": props.get("effective"),
                                    "expires": props.get("expires"),
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

    load_records(fetch_alerts())


noaa_alerts_dag()
