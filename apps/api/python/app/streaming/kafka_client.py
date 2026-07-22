from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from confluent_kafka import Consumer, KafkaException, Producer
from confluent_kafka.admin import AdminClient, NewTopic
from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext, StringSerializer

from app.config import get_settings

logger = logging.getLogger("aether.streaming.kafka")

# apps/api/python/app/streaming/kafka_client.py -> repo root is 5 parents up.
SCHEMAS_DIR = Path(__file__).resolve().parents[5] / "streaming" / "schemas"

TOPICS = {
    "property_changes": "aether.property_changes",
    "business_registrations": "aether.business_registrations",
    "permit_issuances": "aether.permit_issuances",
    "news_mentions": "aether.news_mentions",
    "entity_resolved": "aether.entity_resolved",
    "user_alerts": "aether.user_alerts",
    # Internal -- not one of the 6 user-facing topics. Raw Flink CEP
    # output before per-user subscription matching, see
    # streaming/schemas/detected_pattern.avsc.
    "detected_patterns": "aether.detected_patterns",
}

SCHEMA_FILES = {
    TOPICS["property_changes"]: "property_change.avsc",
    TOPICS["business_registrations"]: "business_registration.avsc",
    TOPICS["permit_issuances"]: "permit_issuance.avsc",
    TOPICS["news_mentions"]: "news_mention.avsc",
    TOPICS["entity_resolved"]: "entity_resolved.avsc",
    TOPICS["user_alerts"]: "user_alert.avsc",
    TOPICS["detected_patterns"]: "detected_pattern.avsc",
}


def ensure_topics(num_partitions: int = 3, replication_factor: int = 1) -> list[str]:
    """Idempotent topic creation -- safe to call on every producer/consumer
    startup. Returns the names of topics actually created."""
    settings = get_settings()
    admin = AdminClient({"bootstrap.servers": settings.kafka_bootstrap_servers})
    existing = set(admin.list_topics(timeout=10).topics.keys())

    to_create = [
        NewTopic(name, num_partitions=num_partitions, replication_factor=replication_factor)
        for name in TOPICS.values()
        if name not in existing
    ]
    if not to_create:
        return []

    futures = admin.create_topics(to_create)
    created = []
    for topic, future in futures.items():
        try:
            future.result()
            created.append(topic)
        except KafkaException as exc:
            # TOPIC_ALREADY_EXISTS is a benign race with another producer
            # doing the same idempotent check concurrently.
            if "already exists" not in str(exc):
                raise
    return created


def ensure_schemas() -> list[str]:
    """Registers every producer-facing topic's Avro schema with Schema
    Registry up front. Without this, a topic that hasn't had a message
    produced to it yet has no registered schema, and tools that infer
    schema from the registry (ksqlDB's `CREATE STREAM ... WITH
    (VALUE_FORMAT='AVRO')` with no column list) fail with 'Schema ...
    does not exist'. Idempotent -- registering an identical schema again
    just returns the existing id.

    aether.detected_patterns is deliberately excluded: it's written
    solely by the Flink job in streaming/flink/cep_alerts.py, which
    auto-derives its own Avro schema from its Table SQL column types on
    first write. Pre-registering streaming/schemas/detected_pattern.avsc
    here caused a live 409 (schema-registry rejects it as incompatible
    with Flink's structurally-different auto-derived schema, even though
    both use the same field names/types) -- Flink needs to be the sole
    registrar for topics it's the only producer of.
    """
    from confluent_kafka.schema_registry import Schema

    client = _schema_registry_client()
    registered = []
    for topic in TOPICS.values():
        if topic == TOPICS["detected_patterns"]:
            continue
        schema = Schema(load_schema(topic), schema_type="AVRO")
        client.register_schema(f"{topic}-value", schema)
        registered.append(topic)
    return registered


def load_schema(topic: str) -> str:
    return (SCHEMAS_DIR / SCHEMA_FILES[topic]).read_text()


@lru_cache
def _schema_registry_client() -> SchemaRegistryClient:
    settings = get_settings()
    return SchemaRegistryClient({"url": settings.schema_registry_url})


class EventProducer:
    """Thin wrapper over confluent_kafka.Producer with Avro value
    serialization against the schemas in streaming/schemas/. One instance
    per producer process (RSS poller, delta checker, etc.) -- reuses the
    underlying librdkafka producer and serializer across calls instead of
    reconnecting per event.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
        self._key_serializer = StringSerializer("utf_8")
        self._value_serializers: dict[str, AvroSerializer] = {}

    def _value_serializer(self, topic: str) -> AvroSerializer:
        if topic not in self._value_serializers:
            self._value_serializers[topic] = AvroSerializer(
                _schema_registry_client(), load_schema(topic)
            )
        return self._value_serializers[topic]

    def publish(self, topic: str, key: str, value: dict) -> None:
        def _on_delivery(err, msg) -> None:
            if err is not None:
                logger.warning("delivery failed for %s: %s", topic, err)

        self._producer.produce(
            topic=topic,
            key=self._key_serializer(key),
            value=self._value_serializer(topic)(value, SerializationContext(topic, MessageField.VALUE)),
            on_delivery=_on_delivery,
        )
        self._producer.poll(0)

    def flush(self, timeout: float = 10.0) -> int:
        """Returns the number of messages still undelivered after timeout."""
        return self._producer.flush(timeout)


def make_avro_consumer(topic: str, group_id: str) -> tuple[Consumer, AvroDeserializer]:
    settings = get_settings()
    deserializer = AvroDeserializer(_schema_registry_client(), load_schema(topic))
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([topic])
    return consumer, deserializer
