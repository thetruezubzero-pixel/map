-- Phase 4 / Task 26 -- ksqlDB stream declarations over the raw Kafka
-- topics. Run against a ksqlDB server that already has these topics'
-- Avro schemas registered in Schema Registry -- either because a
-- producer has already published at least one event, or because
-- `app.streaming.kafka_client.ensure_schemas()` was run up front. Without
-- a registered schema, `CREATE STREAM ... WITH (VALUE_FORMAT='AVRO')`
-- (no explicit column list) fails with "Schema for message values on
-- topic '...' does not exist in the Schema Registry" (error_code 40001).
--
-- aether.user_alerts is intentionally not declared as a stream here --
-- it's an output topic written by the alert dispatch service (Task 28),
-- not an input these transforms read from.
--
-- Run via: for f in streaming/ksql/*.sql; do
--   curl -s -X POST localhost:8088/ksql -H "Content-Type: application/vnd.ksql.v1+json" \
--     -d "$(python3 -c "import json,sys; print(json.dumps({'ksql': open(sys.argv[1]).read(), 'streamsProperties': {}}))" "$f")"
-- done

CREATE STREAM IF NOT EXISTS business_registrations_stream
  WITH (KAFKA_TOPIC='aether.business_registrations', VALUE_FORMAT='AVRO');

CREATE STREAM IF NOT EXISTS news_mentions_stream
  WITH (KAFKA_TOPIC='aether.news_mentions', VALUE_FORMAT='AVRO');

CREATE STREAM IF NOT EXISTS property_changes_stream
  WITH (KAFKA_TOPIC='aether.property_changes', VALUE_FORMAT='AVRO');

CREATE STREAM IF NOT EXISTS permit_issuances_stream
  WITH (KAFKA_TOPIC='aether.permit_issuances', VALUE_FORMAT='AVRO');

CREATE STREAM IF NOT EXISTS entity_resolved_stream
  WITH (KAFKA_TOPIC='aether.entity_resolved', VALUE_FORMAT='AVRO');
