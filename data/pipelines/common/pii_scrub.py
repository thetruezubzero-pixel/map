"""PII-scrubbing middleware applied to every record before it lands in
research_entities. Sources are public business/location/news records, but
free-text fields (news snippets, business filing notes) can incidentally
contain a person's email, phone number, or SSN-shaped string -- this strips
those before storage. Defense-in-depth, not a substitute for choosing
in-scope sources (see ROADMAP.md).
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
# The separator between area code and exchange is mandatory (was fully
# optional, `[-.\s]?`) -- confirmed live via sec_edgar_ingestion_dag.py
# that a bare, unpunctuated 10-digit run (e.g. the CIK inside a SEC
# accession number like "0000320193-26-000013") matched as a phone
# number and got redacted, corrupting real business-identifying data.
# Free-text phone numbers this scrubber is meant to catch are
# realistically always punctuated ("555-123-4567", "(555) 123-4567",
# "555.123.4567"); an unformatted 10-digit blob is far more likely to be
# some other kind of structured ID.
_PHONE_RE = re.compile(r"(?<!\d)(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]?\d{4}(?!\d)")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")


def scrub_pii(text: str | None) -> str | None:
    if not text:
        return text

    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _SSN_RE.sub("[redacted-ssn]", text)
    text = _PHONE_RE.sub("[redacted-phone]", text)
    return text


def _scrub_value(value):
    if isinstance(value, str):
        return scrub_pii(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def scrub_record(record: dict) -> dict:
    """Applies scrub_pii to every string value in the record, recursing
    into nested dicts/lists -- a readiness review found the original
    version only scrubbed top-level string values, so any DAG that puts
    real free text into `metadata` (e.g. data_gov_search_dag.py's CKAN
    `notes` field is real free-text dataset description, a realistic place
    for a maintainer's contact email/phone to appear) bypassed this
    scrubber entirely. Confirmed live: scrub_record({"metadata": {"notes":
    "contact jane@x.gov"}}) used to return the email unredacted; now
    recurses and redacts it."""
    return {k: _scrub_value(v) for k, v in record.items()}
