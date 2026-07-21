from __future__ import annotations

"""Elasticsearch connection + index mapping prep for Phase 3 aggregation.

Not wired into the active search path in Phase 2 -- ROADMAP.md scopes
Elasticsearch activation to Phase 3, once county assessor / SEC EDGAR /
PACER ingestion (which need the aggregation layer this backs) are
credentialed and legally reviewed. This module only prepares the index
mapping so Phase 3 doesn't start from zero.
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
        _client = Elasticsearch(
            settings.elasticsearch_url,
            basic_auth=(settings.elasticsearch_username, settings.elasticsearch_password)
            if settings.elasticsearch_username
            else None,
            api_key=settings.elasticsearch_api_key or None,
        )
    return _client


def ensure_index() -> None:
    client = get_client()
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
