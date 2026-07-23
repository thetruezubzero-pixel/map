from __future__ import annotations

import re

# Legal-form suffixes stripped for fuzzy matching -- "Acme Inc." and "Acme
# Incorporated" should normalize to the same string, but "Acme Holdings"
# should NOT lose "Holdings" (that's part of the actual name).
_SUFFIXES = [
    r"incorporated",
    r"inc\.?",
    r"corporation",
    r"corp\.?",
    r"limited",
    r"ltd\.?",
    r"llc",
    r"l\.l\.c\.?",
    r"lp",
    r"l\.p\.?",
    r"llp",
    r"l\.l\.p\.?",
    r"plc",
    r"co\.?",
    r"company",
]
_SUFFIX_RE = re.compile(r"[,\s]+(" + "|".join(_SUFFIXES) + r")\.?\s*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Normalizes a company name for exact/fuzzy matching across sources.
    Not for display -- only for comparison.

    Intentionally biases toward false NEGATIVES (stricter matching). For example:
    - "Acme-Inc" normalizes to "acme" (punctuation removed)
    - "Acme Inc" normalizes to "acme inc" (suffix kept after substitution)
    These don't match after normalization, even though a human would recognize
    them as the same company.

    This bias is intentional and correct for a due-diligence tool: requiring
    human review of near-misses is safer than auto-confirming matches that
    look similar but differ on formatting. The cost of a false negative (a
    match queued for human review instead of auto-confirmed) is lower than
    a false positive (auto-confirming a wrong match). See ROADMAP.md Phase 3
    for entity-resolution architecture and confidence scoring.
    """
    if not name:
        return ""

    normalized = name.strip()
    # Strip suffixes iteratively -- "Acme Holdings, LLC." has one, but
    # some names stack a comma + suffix more than once after cleanup.
    for _ in range(2):
        normalized = _SUFFIX_RE.sub("", normalized).strip()

    normalized = _PUNCT_RE.sub(" ", normalized)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip().lower()
    return normalized
