"""OSM changeset producer -- monitors OpenStreetMap edits for configured
areas of interest, publishes to aether.property_changes.

Classification is heuristic (comment/tag keyword matching on each
changeset's metadata), not a full OsmChange diff parse -- that would need
downloading and parsing each changeset's full element-level diff to see
which tags (building=*, highway=*, amenity=*, ...) were actually added.
Metadata heuristics are what's implemented here; a real diff parser is
future work (noted in streaming/README.md).

Dedup: by changeset id in Redis, same pattern as the other producers.
"""

from __future__ import annotations

import logging
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx
import redis

from app.config import get_settings
from app.streaming.kafka_client import EventProducer, TOPICS, ensure_topics

logger = logging.getLogger("aether.streaming.osm_changesets")

# (name, bbox) -- min_lon,min_lat,max_lon,max_lat. Extend via
# OSM_WATCH_AREAS env var (JSON list of [name, bbox_str]) rather than
# editing code for every new area of interest.
DEFAULT_AREAS = [
    ("New York City", "-74.05,40.68,-73.90,40.80"),
    ("San Francisco", "-122.52,37.70,-122.35,37.83"),
]

SEEN_KEY_PREFIX = "streaming:seen:osm:"
SEEN_TTL_SECONDS = 7 * 24 * 60 * 60

_CLASSIFY_KEYWORDS = [
    ("NEW_BUILDING", ["building", "school", "hospital", "store", "house"]),
    ("ROAD_CHANGE", ["road", "highway", "street", "path", "sidewalk"]),
    ("BOUNDARY_CHANGE", ["boundary", "border", "admin"]),
]


def _redis_client() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, password=settings.redis_password or None)


def _already_seen(r: redis.Redis, changeset_id: str) -> bool:
    key = f"{SEEN_KEY_PREFIX}{changeset_id}"
    return not r.set(key, "1", nx=True, ex=SEEN_TTL_SECONDS)


def _classify(comment: str, created: int, deleted: int) -> str:
    lower = comment.lower()
    for change_type, keywords in _CLASSIFY_KEYWORDS:
        if any(k in lower for k in keywords):
            return change_type
    if deleted > 0 and created == 0:
        return "POI_REMOVED"
    return "POI_ADDED"


def fetch_changesets(identity: str, areas: list[tuple[str, str]]) -> list[dict]:
    changesets = []
    with httpx.Client(timeout=15.0, headers={"User-Agent": identity}) as client:
        for area_name, bbox in areas:
            resp = client.get(
                "https://api.openstreetmap.org/api/0.6/changesets",
                params={"bbox": bbox, "closed": "true", "limit": 20},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            for cs in root.findall("changeset"):
                tags = {t.get("k"): t.get("v") for t in cs.findall("tag")}
                changesets.append(
                    {
                        "id": cs.get("id"),
                        "area_name": area_name,
                        "comment": tags.get("comment", ""),
                        "created_count": int(cs.get("created_count", 0)),
                        "deleted_count": int(cs.get("deleted_count", 0)),
                        "lat": (float(cs.get("min_lat")) + float(cs.get("max_lat"))) / 2
                        if cs.get("min_lat")
                        else None,
                        "lon": (float(cs.get("min_lon")) + float(cs.get("max_lon"))) / 2
                        if cs.get("min_lon")
                        else None,
                        "closed_at": cs.get("closed_at"),
                    }
                )
    return changesets


def run_once() -> int:
    identity = os.environ.get("NOMINATIM_USER_AGENT", "")
    if not identity:
        logger.warning("NOMINATIM_USER_AGENT not set -- skipping this poll cycle")
        return 0

    ensure_topics()
    r = _redis_client()
    producer = EventProducer()
    published = 0

    for cs in fetch_changesets(identity, DEFAULT_AREAS):
        if _already_seen(r, cs["id"]):
            continue

        change_type = _classify(cs["comment"], cs["created_count"], cs["deleted_count"])
        event = {
            "event_id": str(uuid.uuid4()),
            "source": "openstreetmap",
            "change_type": change_type,
            "name": cs["comment"] or f"Changeset {cs['id']} in {cs['area_name']}",
            "lat": cs["lat"],
            "lon": cs["lon"],
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "license": "ODbL",
            "metadata_json": f'{{"changeset_id": "{cs["id"]}", "area": "{cs["area_name"]}"}}',
        }
        producer.publish(TOPICS["property_changes"], key=cs["id"], value=event)
        published += 1

    producer.flush()
    logger.info("osm_changesets: published %d new change events", published)
    return published


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
