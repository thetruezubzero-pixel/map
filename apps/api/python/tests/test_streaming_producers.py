from app.streaming.producers.newsapi_stream import _classify_sentiment
from app.streaming.producers.opencorporates_delta import _record_hash
from app.streaming.producers.osm_changesets import _classify
from app.streaming.producers.sec_edgar_rss import _ACCNO_RE, _TITLE_RE


def test_sec_edgar_title_regex_extracts_form_company_cik():
    title = "8-K - MainStreet Bancshares, Inc. (0001693577) (Filer)"
    match = _TITLE_RE.match(title)
    assert match is not None
    assert match.group("form") == "8-K"
    assert match.group("company") == "MainStreet Bancshares, Inc."
    assert match.group("cik") == "0001693577"


def test_sec_edgar_accno_regex_extracts_accession_number():
    summary = " <b>Filed:</b> 2026-07-21 <b>AccNo:</b> 0001437749-26-023920 <b>Size:</b> 189 KB"
    match = _ACCNO_RE.search(summary)
    assert match is not None
    assert match.group("accno") == "0001437749-26-023920"


def test_opencorporates_hash_stable_for_identical_records():
    company = {"name": "Acme Co", "company_number": "123", "current_status": "Active", "jurisdiction_code": "us_de"}
    assert _record_hash(company) == _record_hash(dict(company))


def test_opencorporates_hash_changes_when_status_changes():
    base = {"name": "Acme Co", "company_number": "123", "current_status": "Active", "jurisdiction_code": "us_de"}
    changed = {**base, "current_status": "Dissolved"}
    assert _record_hash(base) != _record_hash(changed)


def test_sentiment_classifies_positive_negative_neutral():
    assert _classify_sentiment("Company reports record profits and historic growth")[0] == "POSITIVE"
    assert _classify_sentiment("Company faces fraud investigation and mass layoffs")[0] == "NEGATIVE"
    assert _classify_sentiment("Company files routine quarterly report")[0] == "NEUTRAL"


def test_osm_classify_matches_building_keyword():
    assert _classify("school added", created=10, deleted=1) == "NEW_BUILDING"


def test_osm_classify_matches_road_keyword():
    assert _classify("fixed highway alignment", created=2, deleted=0) == "ROAD_CHANGE"


def test_osm_classify_falls_back_to_removed_when_only_deletions():
    assert _classify("cleanup", created=0, deleted=3) == "POI_REMOVED"


def test_osm_classify_falls_back_to_added_by_default():
    assert _classify("misc edits", created=1, deleted=0) == "POI_ADDED"
