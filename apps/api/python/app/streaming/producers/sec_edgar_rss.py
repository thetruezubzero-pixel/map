"""SEC EDGAR RSS producer -- real-time filing alerts.

Polls SEC's "latest filings" Atom feed (no API key, but SEC's fair-access
policy requires a real identifying User-Agent -- same requirement as
EdgarTools in data/pipelines/dags/sec_edgar_ingestion_dag.py). Publishes
to aether.business_registrations.

Dedup: SEC's feed always returns the most recent N filings, so polling on
an interval re-fetches filings you've already seen. A Redis SET with a
24h TTL per accession number keeps this producer from republishing the
same filing every poll cycle -- this is the streaming producer's own
idempotency concern, separate from (and in addition to) any consumer-side
dedup.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timezone

import feedparser
import httpx
import redis

from app.config import get_settings
from app.streaming.kafka_client import EventProducer, TOPICS, ensure_topics

logger = logging.getLogger("aether.streaming.sec_edgar_rss")

MONITORED_FORMS = ["10-K", "10-Q", "8-K", "4"]
FEED_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
SEEN_KEY_PREFIX = "streaming:seen:sec_edgar:"
SEEN_TTL_SECONDS = 24 * 60 * 60

_TITLE_RE = re.compile(r"^(?P<form>\S+)\s*-\s*(?P<company>.+?)\s*\((?P<cik>\d+)\)")
_ACCNO_RE = re.compile(r"AccNo:</b>\s*(?P<accno>[\d-]+)")


def _redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, password=settings.redis_password or None)


def _already_seen(r: redis.Redis, accession_no: str) -> bool:
    key = f"{SEEN_KEY_PREFIX}{accession_no}"
    # SET ... NX returns True only if the key didn't already exist --
    # atomically checks-and-marks in one round trip.
    return not r.set(key, "1", nx=True, ex=SEEN_TTL_SECONDS)


def fetch_filings(identity: str, forms: list[str] = MONITORED_FORMS) -> list[dict]:
    records = []
    with httpx.Client(timeout=15.0, headers={"User-Agent": identity}) as client:
        for form in forms:
            resp = client.get(
                FEED_URL,
                params={
                    "action": "getcurrent",
                    "type": form,
                    "company": "",
                    "owner": "include",
                    "count": 40,
                    "output": "atom",
                },
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.text)

            for entry in feed.entries:
                match = _TITLE_RE.match(entry.title)
                accno_match = _ACCNO_RE.search(entry.get("summary", ""))
                if not match or not accno_match:
                    continue

                records.append(
                    {
                        "form": match.group("form"),
                        "company": match.group("company"),
                        "cik": match.group("cik"),
                        "accession_no": accno_match.group("accno"),
                        "url": entry.link,
                        "filed_at": entry.get("updated", ""),
                    }
                )
    return records


def run_once() -> int:
    """Runs one poll cycle. Returns the number of new events published."""
    settings = get_settings()
    identity = os.environ.get("EDGAR_IDENTITY", "")
    if not identity:
        logger.warning("EDGAR_IDENTITY not set -- skipping this poll cycle")
        return 0

    ensure_topics()
    r = _redis_client()
    producer = EventProducer()
    published = 0

    for filing in fetch_filings(identity):
        if _already_seen(r, filing["accession_no"]):
            continue

        event = {
            "event_id": str(uuid.uuid4()),
            "source": "sec_edgar_rss",
            "company_name": filing["company"],
            "cik": filing["cik"],
            "opencorporates_id": None,
            "filing_type": filing["form"],
            "jurisdiction": None,
            "url": filing["url"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "license": "SEC EDGAR -- public domain, no copyright restriction",
            "metadata_json": f'{{"accession_no": "{filing["accession_no"]}"}}',
        }
        producer.publish(TOPICS["business_registrations"], key=filing["cik"], value=event)
        published += 1

    producer.flush()
    logger.info("sec_edgar_rss: published %d new filing events", published)
    return published


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
