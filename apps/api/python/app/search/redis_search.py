from __future__ import annotations

from typing import Any

import redis

from app.config import get_settings
from app.search.embeddings import EMBEDDING_DIM, embed

INDEX_NAME = "idx:entities"
KEY_PREFIX = "entity:"

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        settings = get_settings()
        _client = redis.from_url(settings.redis_url, password=settings.redis_password or None)
    return _client


def ensure_index() -> None:
    """Creates the RediSearch index backing hybrid queries: vector KNN
    (HNSW/cosine) combined with tag and geo filters in a single FT.SEARCH
    call, for lower-latency lookups than a separate Qdrant round trip."""
    from redis.commands.search.field import GeoField, TagField, TextField, VectorField
    from redis.commands.search.indexDefinition import IndexDefinition, IndexType

    client = get_client()
    try:
        client.ft(INDEX_NAME).info()
        return  # already exists
    except redis.ResponseError:
        pass

    schema = (
        TextField("name"),
        TagField("entity_type"),
        TagField("source"),
        GeoField("location"),
        VectorField(
            "embedding",
            "HNSW",
            {"TYPE": "FLOAT32", "DIM": EMBEDDING_DIM, "DISTANCE_METRIC": "COSINE"},
        ),
    )
    client.ft(INDEX_NAME).create_index(
        schema, definition=IndexDefinition(prefix=[KEY_PREFIX], index_type=IndexType.HASH)
    )


def index_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    source: str,
    description: str,
    lat: float | None = None,
    lon: float | None = None,
) -> None:
    client = get_client()
    vector = embed(description or name)

    mapping: dict[str, Any] = {
        "name": name,
        "entity_type": entity_type,
        "source": source,
        "embedding": vector.tobytes(),
    }
    if lat is not None and lon is not None:
        mapping["location"] = f"{lon},{lat}"

    client.hset(f"{KEY_PREFIX}{entity_id}", mapping=mapping)


def hybrid_search(
    query: str,
    *,
    entity_type: str | None = None,
    source: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: float | None = None,
    limit: int = 20,
) -> list[dict]:
    """Combines a tag/geo filter with a vector KNN clause in one FT.SEARCH
    call -- Redis's hybrid (filtered vector) search pattern."""
    from redis.commands.search.query import Query

    client = get_client()
    vector = embed(query)

    filters = []
    if entity_type:
        filters.append(f"@entity_type:{{{entity_type}}}")
    if source:
        filters.append(f"@source:{{{source}}}")
    if radius_m and lat is not None and lon is not None:
        radius_km = radius_m / 1000
        filters.append(f"@location:[{lon} {lat} {radius_km} km]")

    filter_expr = "".join(filters) if filters else "*"
    redis_query = (
        Query(f"({filter_expr})=>[KNN {limit} @embedding $vec AS score]")
        .sort_by("score")
        .paging(0, limit)
        .dialect(2)
    )

    result = client.ft(INDEX_NAME).search(redis_query, query_params={"vec": vector.tobytes()})
    return [
        {
            "id": doc.id.removeprefix(KEY_PREFIX),
            "name": doc.name,
            "entity_type": doc.entity_type,
            "source": doc.source,
            "score": float(doc.score),
        }
        for doc in result.docs
    ]
