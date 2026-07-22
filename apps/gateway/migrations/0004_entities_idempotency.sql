-- Fixes a critical idempotency bug found in audit: research_entities had
-- no unique constraint, so `ON CONFLICT DO NOTHING` in
-- data/pipelines/common/db.py's upsert_entities() had nothing to conflict
-- against (every row gets a fresh random `id`), meaning every DAG re-run
-- silently duplicated every record it had already ingested.
--
-- (source, entity_type, name) is an approximation of "same real-world
-- record" -- each source's `name` is built deterministically from that
-- source's own data (e.g. SEC: "<company> <form> (<date>)", Census:
-- "<county>, <state>"), so a re-run of the same DAG against the same
-- upstream data produces the same name and hits this constraint. It is
-- not a perfect identity key (e.g. two GDELT articles could coincidentally
-- share a title), but it is a large, concrete improvement over "no
-- idempotency at all", and cheap to relax later per-source if needed.
ALTER TABLE research_entities
    ADD CONSTRAINT research_entities_source_type_name_key
    UNIQUE (source, entity_type, name);
