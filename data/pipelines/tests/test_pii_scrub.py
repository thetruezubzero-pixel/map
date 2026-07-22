import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.pii_scrub import scrub_pii


def test_phone_scrub_still_catches_common_punctuated_formats():
    assert scrub_pii("call 555-123-4567") == "call [redacted-phone]"
    assert scrub_pii("call (555) 123-4567") == "call [redacted-phone]"
    assert scrub_pii("call 555.123.4567") == "call [redacted-phone]"
    assert scrub_pii("call +1 555-123-4567") == "call [redacted-phone]"


def test_phone_scrub_does_not_corrupt_a_sec_accession_number():
    """Regression test: a bare, unpunctuated 10-digit run (the CIK
    embedded in a SEC accession number) used to match the phone regex
    and get redacted, corrupting real business-identifying data pulled
    in verbatim by sec_edgar_ingestion_dag.py."""
    name = "Apple Inc. 10-Q (2026-05-01) 0000320193-26-000013"
    assert scrub_pii(name) == name


def test_ssn_and_email_scrubbing_unaffected():
    assert scrub_pii("ssn 123-45-6789") == "ssn [redacted-ssn]"
    assert scrub_pii("contact person@example.com") == "contact [redacted-email]"
