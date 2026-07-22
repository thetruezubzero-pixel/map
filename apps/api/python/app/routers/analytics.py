from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.search import elasticsearch_setup as es

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/nearby")
def nearby(lat: float, lon: float, radius_km: float = 5.0, entity_type: str | None = None) -> dict:
    """'Show all businesses within N km' -- ES geo_distance query."""
    try:
        results = es.geo_distance_search(lat, lon, radius_km, entity_type=entity_type)
    except Exception as exc:  # noqa: BLE001 -- ES may not be reachable; surface as 503, not 500
        raise HTTPException(status_code=503, detail=f"elasticsearch unavailable: {exc}") from None
    return {"results": results, "count": len(results)}


@router.get("/heatmap")
def heatmap(precision: int = 5, entity_type: str | None = None) -> dict:
    """Geohash grid clustering for a density heatmap layer."""
    precision = max(1, min(precision, 9))
    try:
        buckets = es.geohash_grid_heatmap(precision=precision, entity_type=entity_type)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"elasticsearch unavailable: {exc}") from None
    return {"buckets": buckets}


@router.get("/top-entity-types")
def top_entity_types(source: str, limit: int = 10) -> dict:
    """ES|QL: entity_type counts for one source, ranked -- e.g. 'top
    industries by business count in this dataset'."""
    try:
        result = es.top_entity_types_by_source(source, limit=min(limit, 50))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"elasticsearch unavailable: {exc}") from None
    return result
