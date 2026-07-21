"""Alert dispatcher -- Task 28. Bridges Flink's raw detections to real
per-user alerts.

Consumes aether.detected_patterns (Flink CEP output, see
streaming/flink/cep_alerts.py), matches each detection against active
rows in Postgres `user_subscriptions` (apps/gateway/migrations/0007_alerts.sql),
and for each match:
  1. INSERTs into Postgres `user_alerts` -- this is what the Rust
     gateway's GET /ws/alerts actually listens to (via a NOTIFY trigger
     on that table), so this INSERT is the real delivery path.
  2. Publishes the same event to aether.user_alerts on Kafka, for parity
     with the rest of the streaming architecture and any future consumer
     that isn't the Rust gateway.

This is the "per-user subscription matching" step that both
streaming/README.md (ksqlDB section) and streaming/flink/cep_alerts.py's
docstring point to as deliberately deferred here, rather than attempted
in ksqlDB or Flink -- neither has a safe way to join live against
Postgres in this stack (see those files for why).

Subscription types (see 0007_alerts.sql):
  - entity: criteria={"cik": "..."} and/or {"entity_name": "..."}
  - keyword: criteria={"keywords": ["...", ...]}
  - geofence: criteria={"lat": ..., "lon": ..., "radius_km": ...}
  - composite: any combination of the above keys, all must match (AND)

Real limitation, not silently omitted: aether.detected_patterns (from
business_registrations + news_mentions) never carries lat/lon --
Flink's CEP job doesn't currently consume aether.property_changes (the
one topic that does have coordinates). So geofence criteria never
matches anything from this dispatcher today; entity and keyword do.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import asyncpg

from app.config import get_settings
from app.streaming.kafka_client import EventProducer, TOPICS, make_avro_consumer

logger = logging.getLogger("aether.streaming.alert_dispatcher")

_SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


def _meets_severity(pattern_severity: str, min_severity: str) -> bool:
    return _SEVERITY_RANK.get(pattern_severity, 0) >= _SEVERITY_RANK.get(min_severity, 0)


def _matches_entity(criteria: dict, pattern: dict) -> bool:
    cik = criteria.get("cik")
    if cik and pattern.get("cik") == cik:
        return True
    entity_name = criteria.get("entity_name")
    if entity_name and pattern.get("entity_name"):
        return entity_name.lower() in pattern["entity_name"].lower()
    return False


def _matches_keyword(criteria: dict, pattern: dict) -> bool:
    keywords = criteria.get("keywords") or []
    haystack = f"{pattern.get('title', '')} {pattern.get('description', '')}".lower()
    return any(kw.lower() in haystack for kw in keywords if kw)


def _matches_geofence(criteria: dict, pattern: dict) -> bool:
    # See module docstring -- detected_patterns never carries lat/lon
    # today, so this is always False, not a stub pretending to work.
    return False


def _matches(subscription: asyncpg.Record, pattern: dict) -> bool:
    criteria = json.loads(subscription["criteria"]) if isinstance(subscription["criteria"], str) else subscription["criteria"]
    sub_type = subscription["subscription_type"]

    if sub_type == "entity":
        return _matches_entity(criteria, pattern)
    if sub_type == "keyword":
        return _matches_keyword(criteria, pattern)
    if sub_type == "geofence":
        return _matches_geofence(criteria, pattern)
    if sub_type == "composite":
        checks = []
        if "cik" in criteria or "entity_name" in criteria:
            checks.append(_matches_entity(criteria, pattern))
        if "keywords" in criteria:
            checks.append(_matches_keyword(criteria, pattern))
        if "lat" in criteria:
            checks.append(_matches_geofence(criteria, pattern))
        return bool(checks) and all(checks)
    return False


async def dispatch_pattern(pool: asyncpg.Pool, producer: EventProducer, pattern: dict) -> int:
    subscriptions = await pool.fetch(
        "SELECT id, user_id, subscription_type, criteria, min_severity, channels "
        "FROM user_subscriptions WHERE is_active"
    )

    dispatched = 0
    for sub in subscriptions:
        if not _meets_severity(pattern["severity"], sub["min_severity"]):
            continue
        if not _matches(sub, pattern):
            continue

        alert_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)

        await pool.execute(
            """
            INSERT INTO user_alerts
                (id, subscription_id, user_id, severity, title, description,
                 source_topic, source_event_id, entity_id, lat, lon, channels, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            """,
            uuid.UUID(alert_id),
            sub["id"],
            sub["user_id"],
            pattern["severity"],
            pattern["title"],
            pattern["description"],
            pattern["source_topic"],
            pattern.get("pattern_id"),
            pattern.get("cik"),
            None,
            None,
            list(sub["channels"]),
            created_at,
        )

        producer.publish(
            TOPICS["user_alerts"],
            key=alert_id,
            value={
                "alert_id": alert_id,
                "subscription_id": str(sub["id"]),
                "user_id": sub["user_id"],
                "severity": pattern["severity"],
                "title": pattern["title"],
                "description": pattern["description"],
                "source_topic": pattern["source_topic"],
                "source_event_id": pattern.get("pattern_id"),
                "entity_id": pattern.get("cik"),
                "lat": None,
                "lon": None,
                "created_at": created_at.isoformat(),
                "channels": list(sub["channels"]),
            },
        )
        dispatched += 1

    if dispatched:
        producer.flush()
    return dispatched


async def run_forever() -> None:
    settings = get_settings()
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=5)
    producer = EventProducer()
    consumer, deserializer = make_avro_consumer(TOPICS["detected_patterns"], "alert-dispatcher")

    from confluent_kafka.serialization import MessageField, SerializationContext

    logger.info("alert_dispatcher: listening on %s", TOPICS["detected_patterns"])
    try:
        while True:
            msg = await asyncio.to_thread(consumer.poll, 1.0)
            if msg is None or msg.error():
                continue
            pattern = deserializer(msg.value(), SerializationContext(msg.topic(), MessageField.VALUE))
            n = await dispatch_pattern(pool, producer, pattern)
            if n:
                logger.info("dispatched %d alert(s) for pattern %s", n, pattern.get("pattern_id"))
    finally:
        consumer.close()
        await pool.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
