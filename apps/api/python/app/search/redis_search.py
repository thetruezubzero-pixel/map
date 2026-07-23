from __future__ import annotations

from typing import Any

import redis

from app.config import get_settings
from app.search.embeddings import EMBEDDING_DIM, embed

INDEX_NAME = "idx:entities"
KEY_PREFIX = "entity:"

_client: redis.Redis | None = None

# RediSearch's documented special characters (query-syntax metacharacters
# for tag/text fields) -- must be backslash-escaped before a caller-supplied
# value is interpolated into a `@field:{value}` tag filter, same bug class
# already fixed in elasticsearch_setup.py's top_entity_types_by_source (an
# unescaped value there let `x" | LIMIT 1 | FROM ...` break out of the
# filter and append arbitrary query stages). hybrid_search below has no
# callers yet, but fixing this proactively avoids relying on "not reachable
# yet" as the only protection once it is wired to a route.
_TAG_SPECIAL_CHARS = ",.<>{}[]\"':;!@#$%^&*()-+=~ \t\n"


def _escape_tag_value(value: str) -> str:
    return "".join(f"\\{c}" if c in _TAG_SPECIAL_CHARS else c for c in value)


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
        filters.append(f"@entity_type:{{{_escape_tag_value(entity_type)}}}")
    if source:
        filters.append(f"@source:{{{_escape_tag_value(source)}}}")
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
