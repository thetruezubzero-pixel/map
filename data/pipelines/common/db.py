"""Shared Postgres/PostGIS writer for ingestion DAGs. Writes into the same
research_entities table the gateway and Python API read from (see
apps/gateway/migrations/0002_phase2.sql for the schema, including the
entity_type allowlist that keeps `person` out of scope).
"""

from __future__ import annotations

import json
import os
from typing import Any


def get_connection():
    import psycopg2

    dsn = os.environ.get("GATEWAY_DATABASE_URL", "postgres://aether:aether@localhost:5432/aether")
    return psycopg2.connect(dsn)


def upsert_entities(records: list[dict[str, Any]]) -> int:
    """Each record: name, entity_type, source, license, lat, lon, metadata.
    Idempotent on (source, entity_type, name) -- see
    apps/gateway/migrations/0004_entities_idempotency.sql for the unique
    constraint this relies on (without it, `ON CONFLICT DO NOTHING` has
    nothing to conflict against, since `id` is always a fresh random UUID,
    and every re-run silently duplicates every row).

    Returns the number of rows actually inserted (not the input count --
    rows skipped as duplicates are not counted).
    """
    if not records:
        return 0

    conn = get_connection()
    try:
        inserted = 0
        with conn, conn.cursor() as cur:
            for record in records:
                lat = record.get("lat")
                lon = record.get("lon")
                geom_expr = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)" if lat is not None and lon is not None else "NULL"
                params: list[Any] = []
                if lat is not None and lon is not None:
                    params.extend([lon, lat])

                cur.execute(
                    f"""
                    INSERT INTO research_entities (name, entity_type, source, license, geom, metadata)
                    VALUES (%s, %s, %s, %s, {geom_expr}, %s)
                    ON CONFLICT (source, entity_type, name) DO NOTHING
                    """,
                    [
                        record["name"],
                        record["entity_type"],
                        record["source"],
                        record.get("license"),
                        *params,
                        json.dumps(record.get("metadata", {})),
                    ],
                )
                inserted += cur.rowcount
        return inserted
    finally:
        conn.close()
