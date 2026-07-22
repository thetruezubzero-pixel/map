-- Audit finding: /search's default ORDER BY (no geo point, no text query)
-- sorts on retrieved_at, and date_from/date_to filters also hit this
-- column, but there was no index on it -- confirmed via EXPLAIN showing
-- a Seq Scan + Sort for the plain "browse latest records" query path.
CREATE INDEX IF NOT EXISTS research_entities_retrieved_at_idx ON research_entities (retrieved_at DESC);
