-- Phase 4: alert subscriptions + delivered alerts, backing
-- POST/GET/PATCH/DELETE /subscriptions and GET /ws/alerts.
--
-- Design note: the Flink CEP job (streaming/flink/cep_alerts.py) writes
-- raw pattern detections to Kafka topic aether.detected_patterns, not
-- directly to per-user alerts -- it has no way to join against this
-- table (Flink 2.3.0 has no compatible flink-connector-jdbc release, see
-- streaming/README.md). A separate consumer,
-- apps/api/python/app/streaming/producers/alert_dispatcher.py, reads
-- aether.detected_patterns, matches against user_subscriptions below,
-- and INSERTs the real per-user row into user_alerts here (which is what
-- fires the NOTIFY the Rust gateway's WebSocket listens for) -- and also
-- publishes the same event to aether.user_alerts on Kafka for parity
-- with the rest of the streaming architecture / any future non-HTTP
-- consumer.
--
-- Scope guardrail: subscription_type is entity | keyword | geofence |
-- composite over *business* entities, keywords, and locations -- not
-- individual people. See CLAUDE.md / ROADMAP.md.

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    subscription_type TEXT NOT NULL CHECK (subscription_type IN ('entity', 'keyword', 'geofence', 'composite')),
    -- entity: {"cik": "..."} and/or {"entity_name": "..."}
    -- keyword: {"keywords": ["...", ...]}
    -- geofence: {"lat": ..., "lon": ..., "radius_km": ...}
    -- composite: any combination of the above keys together (AND match)
    criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    min_severity TEXT NOT NULL DEFAULT 'INFO' CHECK (min_severity IN ('INFO', 'WARNING', 'CRITICAL')),
    channels TEXT[] NOT NULL DEFAULT ARRAY['in_app']::TEXT[],
    webhook_url TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_subscriptions_user_id_idx ON user_subscriptions (user_id);
CREATE INDEX IF NOT EXISTS user_subscriptions_active_idx ON user_subscriptions (is_active) WHERE is_active;

-- Durable, queryable record of every alert actually delivered to a user
-- -- mirrors the aether.user_alerts Avro schema
-- (streaming/schemas/user_alert.avsc) so the Rust gateway doesn't need
-- its own Kafka/Avro client just to serve /ws/alerts and alert history.
CREATE TABLE IF NOT EXISTS user_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES user_subscriptions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'CRITICAL')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    source_topic TEXT NOT NULL,
    source_event_id TEXT,
    entity_id TEXT,
    lat DOUBLE PRECISION,
    lon DOUBLE PRECISION,
    channels TEXT[] NOT NULL DEFAULT ARRAY['in_app']::TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS user_alerts_user_id_created_at_idx ON user_alerts (user_id, created_at DESC);

-- Real-time push for GET /ws/alerts: sqlx::postgres::PgListener on
-- channel 'user_alerts_channel'. Payload is just the new row's id +
-- user_id (NOTIFY payloads are capped at 8000 bytes and this keeps it
-- tiny) -- the WS handler fetches the full row by id after filtering to
-- its own connection's user_id, rather than trying to route the NOTIFY
-- itself per-user (Postgres NOTIFY has no per-listener filtering).
CREATE OR REPLACE FUNCTION notify_user_alert() RETURNS trigger AS $$
BEGIN
    PERFORM pg_notify('user_alerts_channel', json_build_object('id', NEW.id, 'user_id', NEW.user_id)::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS user_alerts_notify ON user_alerts;
CREATE TRIGGER user_alerts_notify
    AFTER INSERT ON user_alerts
    FOR EACH ROW EXECUTE FUNCTION notify_user_alert();
