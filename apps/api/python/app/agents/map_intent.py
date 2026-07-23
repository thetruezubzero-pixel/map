"""Deterministic natural-language -> map-action intent parsing.

This is the connective spine that lets the agent *operate the map itself*
from plain English -- the user says what they want ("show businesses near
Austin", "hide the news heatmap", "switch to satellite"), and the agent
emits typed `MapAction`s the frontend executes against `useMapStore`. The
user talks; the agent drives the map.

Two deliberate design choices:

  1. **No API key required.** This parser is pure Python -- regex/keyword
     matching over a small, declarative synonym table -- so the map
     responds to plain-English commands even with `OPENROUTER_API_KEY`
     unset. When a key *is* present, `chat_agent` still writes the
     conversational reply on top; the actions are additive, not dependent
     on the model. (Matches the platform's standing "works without API
     keys, don't nerf the system" constraint.)

  2. **Scope-safe by construction.** The only entity types it will ever
     emit are the DB-constrained allowlist (business / government_filing /
     location / poi / news_mention). There is no person type and no
     device/tracking action type -- a request like "track this phone"
     simply produces no action here (the model reply, or the fallback,
     handles the refusal). See CLAUDE.md / ROADMAP.md non-goals.

EXTENDING (this is meant to grow -- every "other idea" becomes a new
action the agent can take):
  - New action verb?  add a `MapActionType` value + a matcher in
    `parse_map_intent`.
  - New layer/base-style/entity synonym? add a row to the tables below.
The frontend's `applyMapActions` dispatch mirrors these one-for-one.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

# The DB-constrained entity allowlist -- mirrors models.EntityType and the
# `research_entities.entity_type` CHECK constraint. Never add `person`.
_ENTITY_SYNONYMS: dict[str, str] = {
    "business": "business",
    "businesses": "business",
    "company": "business",
    "companies": "business",
    "firm": "business",
    "firms": "business",
    "filing": "government_filing",
    "filings": "government_filing",
    "sec": "government_filing",
    "edgar": "government_filing",
    "government": "government_filing",
    "regulatory": "government_filing",
    "location": "location",
    "locations": "location",
    "place": "location",
    "places": "location",
    "poi": "poi",
    "pois": "poi",
    "point of interest": "poi",
    "points of interest": "poi",
    "landmark": "poi",
    "landmarks": "poi",
    "news": "news_mention",
    "article": "news_mention",
    "articles": "news_mention",
    "mention": "news_mention",
    "mentions": "news_mention",
}

# Frontend `BASE_STYLES` keys (useMapStore.ts). Keep in sync if that grows.
_BASE_STYLE_SYNONYMS: dict[str, str] = {
    "satellite": "satellite",
    "aerial": "satellite",
    "imagery": "satellite",
    "street": "streets",
    "streets": "streets",
    "default": "streets",
    "topo": "outdoors",
    "topographic": "outdoors",
    "terrain map": "outdoors",
    "outdoors": "outdoors",
    "light": "light",
    "dark": "navigationNight",
    "night": "navigationNight",
    "voyager": "navigationDay",
    "navigation": "navigationDay",
}

# Frontend `Layers` keys (useMapStore.ts). Order matters: multi-word keys
# are matched before single words so "news heatmap" wins over "news".
_LAYER_SYNONYMS: list[tuple[str, str]] = [
    ("news heatmap", "newsHeatmap"),
    ("news density", "newsHeatmap"),
    ("heatmap", "newsHeatmap"),
    ("census tract", "censusTracts"),
    ("census tracts", "censusTracts"),
    ("census", "censusTracts"),
    ("zoning district", "zoningDistricts"),
    ("zoning districts", "zoningDistricts"),
    ("zoning", "zoningDistricts"),
    ("land cover", "landCover"),
    ("landcover", "landCover"),
    ("terrain", "terrain"),
    ("alert", "alerts"),
    ("alerts", "alerts"),
    ("marker", "entities"),
    ("markers", "entities"),
    ("entities", "entities"),
]

MapActionType = Literal[
    "search",
    "set_viewport",
    "set_base_style",
    "set_filter",
    "show_entity_types",
    "toggle_layer",
    "reset",
    # Hand off to the full multi-agent research swarm (POST /research:
    # query_analyzer -> data_retriever -> result_synthesizer). This is the
    # conversational surface reaching the "last trial" research pipeline --
    # the deep, multi-source, human-reviewed path, vs. `search`'s instant
    # index lookup. Carries the subject in `q`.
    "research",
]


class MapAction(BaseModel):
    """One typed instruction for the frontend to execute against the map.

    A flat optional-field shape (rather than a strict per-type union) keeps
    the TypeScript mirror trivial and forward-compatible: a field the
    frontend doesn't recognize for a given `type` is simply ignored, so
    adding a field here never breaks an older client."""

    type: MapActionType
    # search / set_viewport
    q: str | None = None
    near_place: str | None = None
    radius_m: int | None = None
    lat: float | None = None
    lon: float | None = None
    zoom: float | None = None
    # filters / search refinement
    entity_type: str | None = None
    source: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    # show_entity_types
    entity_types: list[str] | None = None
    # set_base_style
    base_style: str | None = None
    # toggle_layer
    layer: str | None = None
    enabled: bool | None = None


# Phrases that turn a layer/style/filter on vs. off.
_OFF_WORDS = ("hide", "remove", "turn off", "disable", "clear", "drop", "no ")
_ON_WORDS = ("show", "add", "turn on", "enable", "display", "overlay", "reveal")

# Deep-research trigger: "research/investigate/dig into/deep dive on/full
# report on <subject>" -- captures the subject as the rest of the message.
_RESEARCH_RE = re.compile(
    r"\b(?:research|investigate|dig into|deep[- ]dive(?:\s+(?:on|into))?|"
    r"full report on|run research on|look deeply into)\s+(.+)",
    re.IGNORECASE,
)

# "near/in/around/at <place>" -- captures the place phrase up to a
# clause-ending word or punctuation.
_NEAR_RE = re.compile(
    r"\b(?:near|in|around|at|by|close to|nearby)\s+"
    r"([A-Za-z0-9][A-Za-z0-9 .,'\-]*?)"
    r"(?:\s+(?:with|and|then|please|show|for)\b|[.?!]|$)",
    re.IGNORECASE,
)


def _find_entity_type(text: str) -> str | None:
    """Return the first allowlisted entity type named in the text, matching
    multi-word synonyms before single words."""
    for phrase in sorted(_ENTITY_SYNONYMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            return _ENTITY_SYNONYMS[phrase]
    return None


def _find_all_entity_types(text: str) -> list[str]:
    found: list[str] = []
    for phrase in sorted(_ENTITY_SYNONYMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            canonical = _ENTITY_SYNONYMS[phrase]
            if canonical not in found:
                found.append(canonical)
    return found


def _polarity(text: str) -> bool:
    """True = enable/show, False = disable/hide. Defaults to enable."""
    for w in _OFF_WORDS:
        if w in text:
            return False
    return True


def parse_map_intent(message: str) -> tuple[list[MapAction], str | None]:
    """Parse one user message into an ordered list of map actions plus a
    short deterministic summary of what was done (usable as a fallback
    reply when the language model is unreachable).

    Returns ([], None) when nothing maps to a map action -- the caller
    should then rely on the conversational agent's reply alone. This
    function never raises on arbitrary input."""
    if not message or not message.strip():
        return [], None

    text = message.lower().strip()
    actions: list[MapAction] = []
    summary_parts: list[str] = []

    # 1. Reset / clear-everything.
    if re.search(r"\b(reset|clear|start over|clear the map|clear everything)\b", text) and not _find_entity_type(text):
        actions.append(MapAction(type="reset"))
        return actions, "Cleared the map filters and results."

    # 2. Deep-research hand-off to the full swarm. Takes precedence over the
    #    instant `search` below: "investigate Acme" should run the real
    #    multi-agent pipeline, not just a one-shot index lookup. The subject
    #    is passed through verbatim; the swarm's query_analyzer is what
    #    enforces scope (it returns an empty plan for out-of-scope/person
    #    requests), so this router doesn't second-guess it here.
    research_match = _RESEARCH_RE.search(text)
    if research_match:
        subject = research_match.group(1).strip(" .?!,")
        # Strip a leading connective the trigger left behind ("dig into X"
        # already consumed "into"; "deep dive on X" leaves "on"/"into").
        subject = re.sub(r"^(?:on|into|about|the)\s+", "", subject).strip()
        if subject:
            actions.append(MapAction(type="research", q=subject))
            return actions, f"Starting a full research job on {subject}. This runs the multi-source swarm and is human-reviewed."

    # 3. Base-style switch ("switch to satellite", "dark map").
    for phrase in sorted(_BASE_STYLE_SYNONYMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text) and re.search(r"\b(map|view|style|satellite|dark|light|topo|terrain|imagery|aerial)\b", text):
            style = _BASE_STYLE_SYNONYMS[phrase]
            actions.append(MapAction(type="set_base_style", base_style=style))
            summary_parts.append(f"switched the base map to {phrase}")
            break

    # 4. Layer toggles ("show the news heatmap", "hide zoning").
    #    Only fire when a layer word is actually present.
    matched_layers: set[str] = set()
    for phrase, layer_key in _LAYER_SYNONYMS:
        if layer_key in matched_layers:
            continue
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            enabled = _polarity(text)
            actions.append(MapAction(type="toggle_layer", layer=layer_key, enabled=enabled))
            matched_layers.add(layer_key)
            summary_parts.append(f"{'showed' if enabled else 'hid'} the {phrase} layer")

    # 5. "only <type>" / "just <type>" -> restrict visible entity types.
    if re.search(r"\b(only|just)\b", text):
        types = _find_all_entity_types(text)
        if types:
            actions.append(MapAction(type="show_entity_types", entity_types=types))
            summary_parts.append(f"showing only {', '.join(types)}")

    # 6. Search intent: an explicit find/show verb, a place, or an entity
    #    type all imply "populate the map with matching records".
    place_match = _NEAR_RE.search(text)
    near_place = place_match.group(1).strip() if place_match else None
    entity_type = _find_entity_type(text)
    wants_search = bool(
        near_place
        or re.search(r"\b(find|show|search|look up|lookup|map|list|where|locate|pull up)\b", text)
    )
    # Don't fire a redundant search when the message was purely a layer/
    # style/reset command with no place or entity intent.
    already_handled_only = any(a.type == "show_entity_types" for a in actions)
    if wants_search and (near_place or entity_type) and not (already_handled_only and not near_place):
        search = MapAction(type="search", entity_type=entity_type, near_place=near_place)
        # A free-text keyword: strip the place clause + known verbs so a
        # query like "coffee shops near Austin" still carries "coffee shops".
        q = _extract_keywords(text, near_place, entity_type)
        if q:
            search.q = q
        actions.append(search)
        where = f" near {near_place}" if near_place else ""
        what = entity_type or (q or "records")
        summary_parts.append(f"searching for {what}{where}")

    summary = ("Done: " + "; ".join(summary_parts) + ".") if summary_parts else None
    return actions, summary


_STOPWORDS = {
    "find", "show", "search", "look", "up", "lookup", "map", "list", "where",
    "locate", "pull", "me", "the", "a", "an", "all", "please", "for", "of",
    "near", "in", "around", "at", "by", "close", "to", "nearby", "with",
    "and", "then", "only", "just", "some", "any", "that", "this", "are",
    "is", "on", "off",
}


def _extract_keywords(text: str, near_place: str | None, entity_type: str | None) -> str | None:
    """Best-effort free-text query: drop the place clause, entity-type
    words, and command stopwords, keeping the substantive nouns."""
    working = text
    if near_place:
        # Remove "near <place>" (and its lead-in preposition) from the text.
        working = _NEAR_RE.sub(" ", working)
    # Drop entity-type synonym words -- they're carried on entity_type.
    for phrase in _ENTITY_SYNONYMS:
        working = re.sub(rf"\b{re.escape(phrase)}\b", " ", working)
    tokens = [t for t in re.findall(r"[a-z0-9']+", working) if t not in _STOPWORDS]
    q = " ".join(tokens).strip()
    return q or None
