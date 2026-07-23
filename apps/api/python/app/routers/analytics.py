from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.search import elasticsearch_setup as es

logger = logging.getLogger("aether.analytics")

router = APIRouter(prefix="/analytics", tags=["analytics"])

# A readiness review found every handler below echoed str(exc) straight
# into the HTTP response detail -- python-api has no auth of its own (see
# CLAUDE.md's trust-boundary note) and web's /py-api/ proxy exposes this
# whole router with no auth check either, so any unauthenticated caller
# could trigger an ES failure (a malformed query, a down cluster) and read
# back whatever the underlying client's exception message happens to
# contain (query internals, index names, connection details). The real
# exception is still fully available server-side via logger.exception --
# only the caller-facing message is generic now.
_GENERIC_DETAIL = "elasticsearch unavailable"


@router.get("/nearby")
def nearby(lat: float, lon: float, radius_km: float = 5.0, entity_type: str | None = None) -> dict:
    """'Show all businesses within N km' -- ES geo_distance query."""
    try:
        results = es.geo_distance_search(lat, lon, radius_km, entity_type=entity_type)
    except Exception:  # noqa: BLE001 -- ES may not be reachable; surface as 503, not 500
        logger.exception("analytics.nearby: elasticsearch query failed")
        raise HTTPException(status_code=503, detail=_GENERIC_DETAIL) from None
    return {"results": results, "count": len(results)}


@router.get("/heatmap")
def heatmap(precision: int = 5, entity_type: str | None = None) -> dict:
    """Geohash grid clustering for a density heatmap layer."""
    precision = max(1, min(precision, 9))
    try:
        buckets = es.geohash_grid_heatmap(precision=precision, entity_type=entity_type)
    except Exception:  # noqa: BLE001
        logger.exception("analytics.heatmap: elasticsearch query failed")
        raise HTTPException(status_code=503, detail=_GENERIC_DETAIL) from None
    return {"buckets": buckets}


@router.get("/top-entity-types")
def top_entity_types(source: str, limit: int = 10) -> dict:
    """ES|QL: entity_type counts for one source, ranked -- e.g. 'top
    industries by business count in this dataset'."""
    try:
        result = es.top_entity_types_by_source(source, limit=max(1, min(limit, 50)))
    except Exception:  # noqa: BLE001
        logger.exception("analytics.top_entity_types: elasticsearch query failed")
        raise HTTPException(status_code=503, detail=_GENERIC_DETAIL) from None
    return result
