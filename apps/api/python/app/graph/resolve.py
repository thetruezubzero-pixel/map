from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from uuid import UUID

import asyncpg

from app.graph.normalize import normalize_name

AUTO_CONFIRM_THRESHOLD = 0.8
ADDRESS_MATCH_RADIUS_M = 50
FUZZY_NAME_RATIO_THRESHOLD = 0.85

# Per-signal confidence values -- see ROADMAP.md Phase 3 spec: exact ID
# match = 1.0, fuzzy name = 0.7, same address = 0.5, same officer = 0.6.
SCORE_EXACT_ID = 1.0
SCORE_NORMALIZED_NAME_EQUAL = 0.7
SCORE_FUZZY_NAME_SIMILAR = 0.6
SCORE_SAME_ADDRESS = 0.5
SCORE_SAME_OFFICER = 0.6

# When multiple independent signals agree, nudge confidence up rather than
# just taking the single strongest signal -- capped at 1.0.
MULTI_SIGNAL_BONUS = 0.05


@dataclass
class MatchResult:
    confidence: float
    match_basis: dict = field(default_factory=dict)


def _officer_names(metadata: dict) -> set[str]:
    officers = metadata.get("officers") if isinstance(metadata, dict) else None
    if not officers:
        return set()
    return {str(o).strip().lower() for o in officers if o}


def score_pair(entity_a: dict, entity_b: dict) -> MatchResult:
    """Pure scoring function -- no DB access, easy to unit test. Each
    entity dict: name, entity_type, cik, opencorporates_id, ein, lat, lon,
    metadata. Only ever compares business-to-business signals; never
    compares or stores anything about a named individual as its own
    entity (officer names are used only as a same-company signal)."""
    signals: dict[str, float] = {}

    for key in ("cik", "opencorporates_id", "ein"):
        val_a, val_b = entity_a.get(key), entity_b.get(key)
        if val_a and val_b and val_a == val_b:
            signals[f"{key}_match"] = SCORE_EXACT_ID

    norm_a = normalize_name(entity_a.get("name", ""))
    norm_b = normalize_name(entity_b.get("name", ""))
    if norm_a and norm_b:
        if norm_a == norm_b:
            signals["normalized_name_equal"] = SCORE_NORMALIZED_NAME_EQUAL
        else:
            ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
            if ratio >= FUZZY_NAME_RATIO_THRESHOLD:
                signals["fuzzy_name_similar"] = SCORE_FUZZY_NAME_SIMILAR

    lat_a, lon_a = entity_a.get("lat"), entity_a.get("lon")
    lat_b, lon_b = entity_b.get("lat"), entity_b.get("lon")
    if all(v is not None for v in (lat_a, lon_a, lat_b, lon_b)):
        # Cheap planar approximation is fine at this radius; the DB-side
        # candidate generation already used real geography ST_DWithin.
        if abs(lat_a - lat_b) < 0.001 and abs(lon_a - lon_b) < 0.001:
            signals["same_address"] = SCORE_SAME_ADDRESS

    officers_a = _officer_names(entity_a.get("metadata") or {})
    officers_b = _officer_names(entity_b.get("metadata") or {})
    if officers_a & officers_b:
        signals["same_officer"] = SCORE_SAME_OFFICER

    if not signals:
        return MatchResult(confidence=0.0, match_basis={})

    base = max(signals.values())
    extra_signals = len(signals) - 1
    confidence = min(1.0, base + extra_signals * MULTI_SIGNAL_BONUS)

    return MatchResult(confidence=round(confidence, 3), match_basis=signals)


async def backfill_normalized_names(pool: asyncpg.Pool) -> int:
    rows = await pool.fetch(
        "SELECT id, name FROM research_entities WHERE normalized_name IS NULL"
    )
    if not rows:
        return 0

    async with pool.acquire() as conn, conn.transaction():
        for row in rows:
            await conn.execute(
                "UPDATE research_entities SET normalized_name = $2 WHERE id = $1",
                row["id"],
                normalize_name(row["name"]),
            )
    return len(rows)


async def find_candidate_pairs(pool: asyncpg.Pool) -> list[tuple[UUID, UUID]]:
    """Generates candidate pairs via indexed lookups (normalized name,
    exact ID columns, geographic proximity) rather than an O(n^2) scan
    over every entity. Business entities only."""
    rows = await pool.fetch(
        """
        WITH biz AS (
            SELECT id, normalized_name, cik, opencorporates_id, ein, geom
            FROM research_entities
            WHERE entity_type = 'business'
        )
        SELECT DISTINCT LEAST(a.id, b.id) AS id_a, GREATEST(a.id, b.id) AS id_b
        FROM biz a
        JOIN biz b ON a.id < b.id
        WHERE
            (a.normalized_name IS NOT NULL AND a.normalized_name <> '' AND a.normalized_name = b.normalized_name)
            OR (a.cik IS NOT NULL AND a.cik = b.cik)
            OR (a.opencorporates_id IS NOT NULL AND a.opencorporates_id = b.opencorporates_id)
            OR (a.ein IS NOT NULL AND a.ein = b.ein)
            OR (
                a.geom IS NOT NULL AND b.geom IS NOT NULL
                AND ST_DWithin(a.geom::geography, b.geom::geography, $1)
            )
        """,
        ADDRESS_MATCH_RADIUS_M,
    )
    return [(row["id_a"], row["id_b"]) for row in rows]


async def _fetch_entity(pool: asyncpg.Pool, entity_id: UUID) -> dict:
    row = await pool.fetchrow(
        """
        SELECT name, entity_type, cik, opencorporates_id, ein,
               ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, metadata
        FROM research_entities WHERE id = $1
        """,
        entity_id,
    )
    return dict(row) if row else {}


async def run_resolution_pass(pool: asyncpg.Pool) -> dict:
    """Backfills normalized names, scores every candidate pair, and writes
    results: confidence >= AUTO_CONFIRM_THRESHOLD becomes a `same_as`
    entity_relationships edge; everything else queues in
    entity_resolution_candidates for human review. Idempotent -- re-running
    skips pairs already recorded."""
    backfilled = await backfill_normalized_names(pool)
    pairs = await find_candidate_pairs(pool)

    auto_confirmed = 0
    queued_for_review = 0

    for id_a, id_b in pairs:
        existing = await pool.fetchval(
            """
            SELECT 1 FROM entity_resolution_candidates
            WHERE (entity_a_id = $1 AND entity_b_id = $2) OR (entity_a_id = $2 AND entity_b_id = $1)
            """,
            id_a,
            id_b,
        )
        if existing:
            continue

        entity_a = await _fetch_entity(pool, id_a)
        entity_b = await _fetch_entity(pool, id_b)
        if not entity_a or not entity_b:
            continue

        result = score_pair(entity_a, entity_b)
        if result.confidence <= 0:
            continue

        if result.confidence >= AUTO_CONFIRM_THRESHOLD:
            await pool.execute(
                """
                INSERT INTO entity_relationships (parent_entity_id, child_entity_id, relation_type, source)
                VALUES ($1, $2, 'same_as', 'entity_resolution')
                ON CONFLICT DO NOTHING
                """,
                id_a,
                id_b,
            )
            auto_confirmed += 1
        else:
            import json

            await pool.execute(
                """
                INSERT INTO entity_resolution_candidates (entity_a_id, entity_b_id, confidence, match_basis)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                id_a,
                id_b,
                result.confidence,
                json.dumps(result.match_basis),
            )
            queued_for_review += 1

    return {
        "backfilled_names": backfilled,
        "candidate_pairs": len(pairs),
        "auto_confirmed": auto_confirmed,
        "queued_for_review": queued_for_review,
    }
