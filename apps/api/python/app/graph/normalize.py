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
    Not for display -- only for comparison."""
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
