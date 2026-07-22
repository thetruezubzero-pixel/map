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


def scrub_record(record: dict) -> dict:
    """Applies scrub_pii to every string value in a flat record dict."""
    return {k: (scrub_pii(v) if isinstance(v, str) else v) for k, v in record.items()}
