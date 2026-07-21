from __future__ import annotations

import uuid
from typing import Any

from app.config import get_settings
from app.search.embeddings import EMBEDDING_DIM, embed

_client = None


def get_client():
    """Lazily imports qdrant_client so importing this module doesn't
    require the dependency unless hybrid search is actually used."""
    global _client
    if _client is None:
        from qdrant_client import QdrantClient

        settings = get_settings()
        _client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    return _client


def ensure_collection() -> None:
    """Creates the entities collection (cosine distance) with a geo payload
    index on `location`, enabling radius/polygon/bounding-box filtering
    alongside vector search."""
    from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

    settings = get_settings()
    client = get_client()

    if not client.collection_exists(settings.qdrant_collection):
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
        )

    client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="location",
        field_schema=PayloadSchemaType.GEO,
    )
    client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="entity_type",
        field_schema=PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=settings.qdrant_collection,
        field_name="source",
        field_schema=PayloadSchemaType.KEYWORD,
    )


def upsert_entity(
    entity_id: str,
    name: str,
    entity_type: str,
    source: str,
    description: str,
    lat: float | None = None,
    lon: float | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> None:
    from qdrant_client.models import PointStruct

    settings = get_settings()
    client = get_client()
    vector = embed(description or name)

    payload: dict[str, Any] = {"name": name, "entity_type": entity_type, "source": source}
    if lat is not None and lon is not None:
        payload["location"] = {"lat": lat, "lon": lon}
    if extra_payload:
        payload.update(extra_payload)

    client.upsert(
        collection_name=settings.qdrant_collection,
        points=[PointStruct(id=str(uuid.UUID(entity_id)), vector=vector.tolist(), payload=payload)],
    )


def search(
    query: str,
    *,
    entity_type: str | None = None,
    source: str | None = None,
    geo_radius_m: float | None = None,
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 20,
) -> list[dict]:
    """Semantic search with optional geo-radius filtering. This is the
    Qdrant leg of hybrid search; Redis Search (FT.SEARCH KNN + filters)
    provides the real-time tag/geo leg for lower-latency lookups."""
    from qdrant_client.models import FieldCondition, Filter, GeoRadius, MatchValue

    settings = get_settings()
    client = get_client()
    vector = embed(query)

    conditions = []
    if entity_type:
        conditions.append(FieldCondition(key="entity_type", match=MatchValue(value=entity_type)))
    if source:
        conditions.append(FieldCondition(key="source", match=MatchValue(value=source)))
    if geo_radius_m and lat is not None and lon is not None:
        conditions.append(
            FieldCondition(
                key="location",
                geo_radius=GeoRadius(center={"lat": lat, "lon": lon}, radius=geo_radius_m),
            )
        )

    results = client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector.tolist(),
        query_filter=Filter(must=conditions) if conditions else None,
        limit=limit,
    )

    return [{"id": p.id, "score": p.score, **p.payload} for p in results.points]
