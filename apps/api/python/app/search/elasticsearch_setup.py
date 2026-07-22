from __future__ import annotations

"""Elasticsearch connection, index mapping, and ES|QL geospatial
aggregations -- activated in Phase 3 (was prep-only in Phase 2).

Kept as the sync target for `research_entities`: `sync_entity`/
`bulk_sync_from_postgres` mirror Postgres rows into the `aether_entities`
index so ES|QL can run geo aggregations (geo-distance, geohash grid) that
PostGIS full-text/spatial queries in the Rust gateway don't cover as
conveniently.

NOT implemented: ENRICH spatial joins against census-tract/zoning-district
polygons. `research_entities` only stores point geometry (see
migrations/0001_init.sql), and the Census/USGS DAGs in this phase only
ingest point data (county centroids, elevation samples) -- there's no
polygon boundary layer yet for ENRICH to join against. Adding one is a
real schema change (a polygon table + an ENRICH policy keyed on
ST_CONTAINS), not a config flag, so it's left for whenever that boundary
data is actually ingested rather than faked here.
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


def esql_query(query: str) -> dict:
    """Runs a raw ES|QL query (e.g. STATS/geo functions) and returns the
    column/value table as-is. Used for ad-hoc aggregations like 'top N
    industries by business count in this area' that are more naturally
    expressed in ES|QL than the Query DSL."""
    client = get_client()
    resp = client.esql.query(query=query)
    return resp.body


def top_entity_types_by_source(source: str, limit: int = 10) -> dict:
    """Example ES|QL aggregation: entity_type counts for one source,
    ranked -- the ES|QL analogue of a SQL GROUP BY + ORDER BY + LIMIT."""
    query = (
        f'FROM {INDEX_NAME} '
        f'| WHERE source == "{source}" '
        f"| STATS count = COUNT(*) BY entity_type "
        f"| SORT count DESC "
        f"| LIMIT {limit}"
    )
    return esql_query(query)
