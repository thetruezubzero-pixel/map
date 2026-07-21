from app.graph.normalize import normalize_name
from app.graph.resolve import (
    SCORE_EXACT_ID,
    SCORE_NORMALIZED_NAME_EQUAL,
    SCORE_SAME_ADDRESS,
    SCORE_SAME_OFFICER,
    score_pair,
)


def test_normalize_strips_legal_suffixes():
    assert normalize_name("Acme Holdings, LLC") == "acme holdings"
    assert normalize_name("Acme Widgets Inc.") == "acme widgets"
    assert normalize_name("Acme Widgets Incorporated") == "acme widgets"


def test_normalize_preserves_meaningful_words():
    # "Holdings" and "Company" as part of a distinguishing name shouldn't
    # both vanish -- only a trailing legal-form token should.
    assert normalize_name("Acme Holdings Company") == "acme holdings"


def test_normalize_is_case_and_punctuation_insensitive():
    assert normalize_name("ACME, Widgets & Co.") == normalize_name("acme widgets & co.")


def test_score_pair_exact_cik_match_is_high_confidence():
    a = {"name": "Apple Inc.", "cik": "320193", "metadata": {}}
    b = {"name": "Apple Incorporated", "cik": "320193", "metadata": {}}
    result = score_pair(a, b)
    assert result.confidence >= SCORE_EXACT_ID - 0.001
    assert "cik_match" in result.match_basis


def test_score_pair_normalized_name_match_alone_is_below_review_threshold():
    a = {"name": "Acme Holdings LLC", "metadata": {}}
    b = {"name": "Acme Holdings, Inc.", "metadata": {}}
    result = score_pair(a, b)
    assert result.match_basis.get("normalized_name_equal") == SCORE_NORMALIZED_NAME_EQUAL
    assert result.confidence < 0.8  # must land in the human review queue


def test_score_pair_same_address_signal():
    a = {"name": "Acme East LLC", "lat": 40.7484, "lon": -73.9857, "metadata": {}}
    b = {"name": "Acme West Corp", "lat": 40.74841, "lon": -73.98571, "metadata": {}}
    result = score_pair(a, b)
    assert result.match_basis.get("same_address") == SCORE_SAME_ADDRESS


def test_score_pair_officer_overlap_never_creates_a_person_record():
    # The officer signal only ever compares two *company* dicts and
    # returns a float -- it must never surface the officer name itself
    # in the result, since that would be a step toward an individual
    # profile keyed on that name.
    a = {"name": "Acme East LLC", "metadata": {"officers": ["Jane Doe, Director"]}}
    b = {"name": "Acme West Corp", "metadata": {"officers": ["jane doe, director"]}}
    result = score_pair(a, b)
    assert result.match_basis.get("same_officer") == SCORE_SAME_OFFICER
    assert "Jane Doe" not in str(result.match_basis)
    assert "jane doe" not in str(result.match_basis).lower()


def test_score_pair_no_signals_means_zero_confidence():
    a = {"name": "Totally Different Co", "metadata": {}}
    b = {"name": "Unrelated Ventures", "metadata": {}}
    result = score_pair(a, b)
    assert result.confidence == 0.0
    assert result.match_basis == {}


def test_multiple_signals_boost_confidence_above_any_single_signal():
    a = {
        "name": "Acme Holdings LLC",
        "lat": 40.7484,
        "lon": -73.9857,
        "metadata": {"officers": ["Jane Doe"]},
    }
    b = {
        "name": "Acme Holdings, Inc.",
        "lat": 40.74841,
        "lon": -73.98571,
        "metadata": {"officers": ["jane doe"]},
    }
    result = score_pair(a, b)
    assert result.confidence > SCORE_NORMALIZED_NAME_EQUAL
    assert len(result.match_basis) >= 2
