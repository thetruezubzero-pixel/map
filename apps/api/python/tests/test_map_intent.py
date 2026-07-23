"""Unit tests for the deterministic map-intent parser (no DB, no API key).

These pin the agent-drives-the-map contract: plain English in, typed
MapActions out, and -- critically -- that it never emits an out-of-scope
entity type or a device/tracking action.
"""

from __future__ import annotations

from app.agents.map_intent import parse_map_intent


def _types(actions):
    return [a.type for a in actions]


def test_empty_input_yields_nothing():
    actions, summary = parse_map_intent("")
    assert actions == []
    assert summary is None


def test_whitespace_only_yields_nothing():
    actions, summary = parse_map_intent("    \n  ")
    assert actions == []
    assert summary is None


def test_search_near_place():
    actions, summary = parse_map_intent("show businesses near Austin")
    search = next(a for a in actions if a.type == "search")
    assert search.entity_type == "business"
    assert search.near_place == "austin"
    assert summary and "austin" in summary.lower()


def test_search_extracts_free_text_keywords():
    actions, _ = parse_map_intent("find coffee shops near Portland")
    search = next(a for a in actions if a.type == "search")
    assert search.entity_type is None  # "coffee shops" isn't an entity type
    assert search.near_place == "portland"
    assert "coffee" in (search.q or "")


def test_entity_type_synonyms_map_to_allowlist():
    for phrase, expected in [
        ("show companies near Reno", "business"),
        ("find SEC filings near Dallas", "government_filing"),
        ("map news near Miami", "news_mention"),
        ("show points of interest near Denver", "poi"),
        ("list places near Boise", "location"),
    ]:
        actions, _ = parse_map_intent(phrase)
        search = next(a for a in actions if a.type == "search")
        assert search.entity_type == expected, phrase


def test_layer_toggle_on_and_off():
    on, _ = parse_map_intent("show the news heatmap")
    toggle_on = next(a for a in on if a.type == "toggle_layer")
    assert toggle_on.layer == "newsHeatmap"
    assert toggle_on.enabled is True

    off, _ = parse_map_intent("hide the zoning districts")
    toggle_off = next(a for a in off if a.type == "toggle_layer")
    assert toggle_off.layer == "zoningDistricts"
    assert toggle_off.enabled is False


def test_news_heatmap_matches_before_bare_news():
    # "news heatmap" must map to the layer, not be mistaken for a news search.
    actions, _ = parse_map_intent("turn on the news heatmap")
    assert "toggle_layer" in _types(actions)
    assert all(a.layer == "newsHeatmap" for a in actions if a.type == "toggle_layer")


def test_base_style_switch():
    actions, summary = parse_map_intent("switch to satellite view")
    style = next(a for a in actions if a.type == "set_base_style")
    assert style.base_style == "satellite"

    dark, _ = parse_map_intent("give me the dark map")
    assert next(a for a in dark if a.type == "set_base_style").base_style == "navigationNight"


def test_only_restricts_entity_types():
    actions, _ = parse_map_intent("show only businesses")
    show = next(a for a in actions if a.type == "show_entity_types")
    assert show.entity_types == ["business"]


def test_reset_clears():
    actions, summary = parse_map_intent("reset the map")
    assert _types(actions) == ["reset"]
    assert summary and "cleared" in summary.lower()


def test_multiple_actions_in_one_message():
    actions, _ = parse_map_intent("switch to satellite and show businesses near Austin")
    types = _types(actions)
    assert "set_base_style" in types
    assert "search" in types


def test_never_emits_person_entity_type():
    # No phrasing should ever produce a person entity type -- there is none.
    for phrase in [
        "find people near Austin",
        "show persons near Dallas",
        "map individuals near Miami",
        "who lives near here",
    ]:
        actions, _ = parse_map_intent(phrase)
        for a in actions:
            assert a.entity_type != "person"
            if a.entity_types:
                assert "person" not in a.entity_types


def test_no_device_tracking_action_type_exists():
    # Device/connectivity requests produce no map action here -- the parser
    # only knows public-records actions. (The refusal is handled upstream.)
    for phrase in [
        "track this phone's bluetooth",
        "map every wifi device nearby",
        "show airplay devices around me",
    ]:
        actions, _ = parse_map_intent(phrase)
        # It may emit an innocuous "near me" search at most, but never a
        # tracking/device action (there is no such type in the union).
        assert all(a.type in {
            "search", "set_viewport", "set_base_style", "set_filter",
            "show_entity_types", "toggle_layer", "reset",
        } for a in actions)


def test_pure_conversational_message_yields_no_actions():
    actions, summary = parse_map_intent("what can you help me with?")
    assert actions == []
    assert summary is None


def test_arbitrary_input_never_raises():
    for junk in ["...", "🙂🙂", "SELECT * FROM x; --", "a" * 5000, "near near near"]:
        actions, summary = parse_map_intent(junk)
        assert isinstance(actions, list)
