from __future__ import annotations

"""Elasticsearch connection, index mapping, and ES|QL geospatial
aggregations -- activated in Phase 3 (was prep-only in Phase 2).

Kept as the sync target for `research_entities`: `sync_entity`/
`bulk_sync_from_postgres` mirror Postgres rows into the `aether_entities`
index so ES|QL can run geo aggregations (geo-distance, geohash grid) that
PostGIS full-text/spatial queries in the Rust gateway don't cover as
conveniently.

NOT implemented: ENRICH spatial joins against census-tract/zoning-district
polygons. Phase 6 (see ROADMAP.md) added a real polygon boundary layer --
`research_entity_boundaries` (migrations/0010_entity_boundaries.sql),
populated by census_tract_boundary_sync/zoning_districts_sync, served via
the gateway's `GET /boundaries` -- so the schema/data half of this gap is
closed. Wiring an actual ES ENRICH policy against it (keyed on
ST_CONTAINS or the ES|QL equivalent) is still a separate, unbuilt task.
"""

from app.config import get_settings

INDEX_NAME = "aether_entities"

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "name": {"type": "text"},
            "entity_type": {"type": "keyword"},
            "source": {"type": "keyword"},
            "license": {"type": "keyword"},
            "retrieved_at": {"type": "date"},
            "location": {"type": "geo_point"},
            "metadata": {"type": "object", "enabled": True},
        }
    },
    "settings": {"number_of_shards": 1, "number_of_replicas": 0},
}

_client = None


def get_client():
    global _client
    if _client is None:
        from elasticsearch import Elasticsearch

        settings = get_settings()
        # api_key and basic_auth are mutually exclusive for the client --
        # prefer api_key when both happen to be configured.
        auth_kwargs: dict = {}
        if settings.elasticsearch_api_key:
            auth_kwargs["api_key"] = settings.elasticsearch_api_key
        elif settings.elasticsearch_username:
            auth_kwargs["basic_auth"] = (settings.elasticsearch_username, settings.elasticsearch_password)

        _client = Elasticsearch(settings.elasticsearch_url, **auth_kwargs)
    return _client


def ensure_index() -> None:
    client = get_client()
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)


def sync_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    source: str,
    license_: str | None,
    retrieved_at: str,
    lat: float | None,
    lon: float | None,
    metadata: dict | None = None,
) -> None:
    client = get_client()
    doc: dict = {
        "name": name,
        "entity_type": entity_type,
        "source": source,
        "license": license_,
        "retrieved_at": retrieved_at,
        "metadata": metadata or {},
    }
    if lat is not None and lon is not None:
        doc["location"] = {"lat": lat, "lon": lon}

    client.index(index=INDEX_NAME, id=entity_id, document=doc)


def geo_distance_search(
    lat: float, lon: float, radius_km: float, entity_type: str | None = None, size: int = 50
) -> list[dict]:
    """'Show all businesses within N km' -- a standard geo_distance query.
    (ES|QL as of 8.17 doesn't yet support geo_distance filtering directly,
    so this leg uses the Query DSL; geohash clustering below uses ES|QL.)"""
    client = get_client()
    filters: list[dict] = [
        {"geo_distance": {"distance": f"{radius_km}km", "location": {"lat": lat, "lon": lon}}}
    ]
    if entity_type:
        filters.append({"term": {"entity_type": entity_type}})

    resp = client.search(
        index=INDEX_NAME,
        query={"bool": {"filter": filters}},
        sort=[{"_geo_distance": {"location": {"lat": lat, "lon": lon}, "order": "asc", "unit": "km"}}],
        size=size,
    )
    return [
        {**hit["_source"], "id": hit["_id"], "distance_km": hit.get("sort", [None])[0]}
        for hit in resp["hits"]["hits"]
    ]


def geohash_grid_heatmap(precision: int = 5, entity_type: str | None = None) -> list[dict]:
    """Geohash grid clustering for heatmap visualization -- buckets
    entities into geohash cells and returns a count per cell."""
    client = get_client()
    query = {"term": {"entity_type": entity_type}} if entity_type else {"match_all": {}}

    resp = client.search(
        index=INDEX_NAME,
        query=query,
        size=0,
        aggs={
            "grid": {
                "geohash_grid": {"field": "location", "precision": precision},
                "aggs": {"centroid": {"geo_centroid": {"field": "location"}}},
            }
        },
    )
    buckets = resp["aggregations"]["grid"]["buckets"]
    return [
        {
            "geohash": b["key"],
            "count": b["doc_count"],
            "centroid": b["centroid"]["location"],
        }
        for b in buckets
    ]


async def bulk_sync_from_postgres(pool, batch_size: int = 500) -> int:
    """Mirrors research_entities into the ES index in bulk. Called
    periodically (see data/pipelines/dags/elasticsearch_sync_dag.py)
    rather than on every write -- ES here backs aggregation/analytics
    queries, not the primary read path (that's still PostGIS via the
    gateway's /search)."""
    from elasticsearch.helpers import bulk

    ensure_index()
    client = get_client()

    rows = await pool.fetch(
        """
        SELECT id, name, entity_type, source, license, retrieved_at,
               ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lon, metadata
        FROM research_entities
        """
    )

    import json

    def _actions():
        for row in rows:
            metadata = row["metadata"]
            if isinstance(metadata, str):
                metadata = json.loads(metadata) if metadata else {}
            doc: dict = {
                "name": row["name"],
                "entity_type": row["entity_type"],
                "source": row["source"],
                "license": row["license"],
                "retrieved_at": row["retrieved_at"].isoformat(),
                "metadata": metadata or {},
            }
            if row["lat"] is not None and row["lon"] is not None:
                doc["location"] = {"lat": row["lat"], "lon": row["lon"]}
            yield {"_index": INDEX_NAME, "_id": str(row["id"]), "_source": doc}

    if not rows:
        return 0

    success, _ = bulk(client, _actions(), chunk_size=batch_size)
    return success


def esql_query(query: str, params: list | None = None) -> dict:
    """Runs a raw ES|QL query (e.g. STATS/geo functions) and returns the
    column/value table as-is. Used for ad-hoc aggregations like 'top N
    industries by business count in this area' that are more naturally
    expressed in ES|QL than the Query DSL.

    `params`, when given, binds `?` placeholders in `query` via ES|QL's
    own parameterization (not string interpolation) -- required whenever
    any part of `query` is caller-controlled input; see
    top_entity_types_by_source for why."""
    client = get_client()
    resp = client.esql.query(query=query, params=params)
    return resp.body


def top_entity_types_by_source(source: str, limit: int = 10) -> dict:
    """Example ES|QL aggregation: entity_type counts for one source,
    ranked -- the ES|QL analogue of a SQL GROUP BY + ORDER BY + LIMIT.

    `source` is reachable from an unauthenticated route
    (GET /analytics/top-entity-types, see CLAUDE.md's python-api
    trust-boundary note) -- it used to be f-string-interpolated straight
    into the query string, so a value like
    `x" | LIMIT 1 | FROM some_other_index // ` could break out of the
    quoted literal and append arbitrary ES|QL stages. Bound via `?` +
    `params` instead, ES|QL's own parameterization, so `source` can never
    be anything but a literal value being compared against. `limit` is
    coerced to `int` explicitly rather than trusting the caller's type
    hint -- FastAPI's route already validates it, but this function
    shouldn't rely on every future caller doing the same."""
    query = (
        f'FROM {INDEX_NAME} '
        f'| WHERE source == ? '
        f"| STATS count = COUNT(*) BY entity_type "
        f"| SORT count DESC "
        f"| LIMIT {int(limit)}"
    )
    return esql_query(query, params=[source])
