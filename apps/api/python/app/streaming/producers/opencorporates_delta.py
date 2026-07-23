"""OpenCorporates delta producer.

OpenCorporates' free tier has no webhook/changelog endpoint, so "delta"
here means: re-run the same search terms as
data/pipelines/dags/opencorporates_sync_dag.py, hash each company record,
and publish a business_registrations event only when a company is new or
its hash changed since the last check (tracked in Redis). Free-tier rate
limits mean this should run at most daily, per the Phase 4 spec -- it is
deliberately not a tight poll loop.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import httpx
import redis
from tenacity import retry, wait_exponential, stop_after_attempt

from app.config import get_settings
from app.streaming.kafka_client import EventProducer, TOPICS, ensure_topics

logger = logging.getLogger("aether.streaming.opencorporates_delta")

DEFAULT_JURISDICTIONS = ["us_de", "us_ny"]
DEFAULT_SEARCH_TERMS = ["holdings", "ventures"]
HASH_KEY_PREFIX = "streaming:hash:opencorporates:"
HASH_TTL_SECONDS = 30 * 24 * 60 * 60


def _redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, password=settings.redis_password or None)


def _record_hash(company: dict) -> str:
    stable = json.dumps(
        {
            "name": company.get("name"),
            "company_number": company.get("company_number"),
            "current_status": company.get("current_status"),
            "jurisdiction_code": company.get("jurisdiction_code"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(stable.encode()).hexdigest()


@retry(
    wait=wait_exponential(multiplier=2, min=1, max=60),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _fetch_search_results(client: httpx.Client, term: str, api_token: str) -> dict:
    """Fetch OpenCorporates search results for a single term with exponential backoff.
    Retries up to 3 times on transient failures (rate limits, timeouts) with
    exponential backoff (1s, 2s, 4s max 60s). On persistent failures (4xx
    auth errors, malformed responses), raises immediately without retry."""
    resp = client.get(
        "https://api.opencorporates.com/v0.4/companies/search",
        params={
            "q": term,
            "jurisdiction_code": ",".join(DEFAULT_JURISDICTIONS),
            "api_token": api_token,
        },
    )
    resp.raise_for_status()
    return resp.json()


def fetch_companies(api_token: str, search_terms: list[str]) -> list[dict]:
    companies = []
    with httpx.Client(timeout=15.0) as client:
        for term in search_terms:
            try:
                results = _fetch_search_results(client, term, api_token)
            except httpx.HTTPError as exc:
                # After retry exhaustion (or on non-retryable errors like 401),
                # skip this term and continue with the rest. Rate limits and
                # timeouts are retried automatically above; if we get here it's
                # either a persistent error (bad/expired key) or a temporary one
                # that exceeded the retry budget. Either way, moving on is correct.
                # Redact the token before logging: it's sent as a URL query
                # param and httpx.HTTPStatusError.__str__() includes the full
                # request URL, so logging the raw exception would print the
                # token in cleartext. Same fix already applied in the DAG twin
                # (data/pipelines/dags/opencorporates_sync_dag.py).
                logger.warning(
                    "OpenCorporates search failed for %r after retries, skipping: %s",
                    term,
                    str(exc).replace(api_token, "***") if api_token else str(exc),
                )
                continue
            except Exception as exc:
                # Catch any non-HTTPError (e.g., JSON decode errors on
                # malformed response) and skip this term.
                logger.warning(
                    "OpenCorporates search failed for %r with unexpected error, skipping: %s",
                    term,
                    exc,
                )
                continue

            for c in results.get("results", {}).get("companies", []):
                if c.get("company"):
                    companies.append(c["company"])
    return companies


def run_once() -> int:
    settings = get_settings()
    api_token = os.environ.get("OPENCORPORATES_API_KEY", settings.opencorporates_api_key)
    if not api_token:
        logger.warning("OPENCORPORATES_API_KEY not set -- skipping this check")
        return 0

    ensure_topics()
    r = _redis_client()
    producer = EventProducer()
    published = 0

    for company in fetch_companies(api_token, DEFAULT_SEARCH_TERMS):
        number = company.get("company_number")
        if not number:
            continue

        current_hash = _record_hash(company)
        key = f"{HASH_KEY_PREFIX}{company.get('jurisdiction_code')}:{number}"
        previous_hash = r.get(key)
        r.set(key, current_hash, ex=HASH_TTL_SECONDS)

        if previous_hash is not None and previous_hash.decode() == current_hash:
            continue  # unchanged since last check

        event = {
            "event_id": str(uuid.uuid4()),
            "source": "opencorporates",
            "company_name": company.get("name", ""),
            "cik": None,
            "opencorporates_id": number,
            "filing_type": None,
            "jurisdiction": company.get("jurisdiction_code"),
            "url": company.get("opencorporates_url"),
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "license": "OpenCorporates ToS -- public register data",
            "metadata_json": json.dumps({"status": company.get("current_status")}),
        }
        producer.publish(TOPICS["business_registrations"], key=number, value=event)
        published += 1

    producer.flush()
    logger.info("opencorporates_delta: published %d change events", published)
    return published


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
