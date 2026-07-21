# streaming/

Phase 4: real-time change detection. Kafka topics + Avro schemas here are
shared infrastructure used by the Python producers
(`apps/api/python/app/streaming/`), ksqlDB statements (`ksql/`), and the
Flink CEP job (`flink/`).

## Components and how they actually run here

| Component | Version | How it runs in this dev environment |
|---|---|---|
| Kafka | 4.3.1 | Standalone, KRaft mode (no ZooKeeper -- Kafka 4.x removed ZK support entirely; single broker/controller combined) |
| Schema Registry | 7.5.15 (Confluent Community) | Standalone, port 8082 (8081 is Flink's REST API, moved to avoid the clash) |
| ksqlDB | 7.5.15 (Confluent Community) | Standalone, port 8088. Needed `-Djava.security.manager=allow` to run on Java 21 (ksqlDB 7.5.x predates JDK's SecurityManager removal) |
| Flink | 2.3.0 | Standalone cluster (1 JobManager + 1 TaskManager, 1 slot), port 8081 |

`docker-compose.yml` describes the equivalent containerized services
(`kafka`, `schema-registry`, `ksqldb`, `flink-jobmanager`,
`flink-taskmanager`) for anyone running the full stack; this table is
about what was actually exercised in the sandbox that built this phase.
No Docker daemon was available there (see CLAUDE.md), so every component
above was run natively instead, and the compose service definitions --
while `docker compose config`-valid and version/port-matched to the
native setup verified here -- have not themselves been exercised via
`docker compose up`. Smoke-test them before relying on them in a real
deploy.

## Topics

| Topic | Schema | Producer |
|---|---|---|
| `aether.property_changes` | `schemas/property_change.avsc` | OSM changeset poller (Phase 4 free-source scope; county assessor feeds are Phase 5+, paid) |
| `aether.business_registrations` | `schemas/business_registration.avsc` | SEC EDGAR RSS poller, OpenCorporates delta checker |
| `aether.permit_issuances` | `schemas/permit_issuance.avsc` | Schema/topic ready, no producer built yet -- catalog.data.gov's CKAN API has been down since Phase 3 (see ROADMAP.md), so a live Data.gov poller was skipped rather than built against a dead upstream |
| `aether.news_mentions` | `schemas/news_mention.avsc` | NewsAPI + GDELT streamer, keyword-filtered with lightweight sentiment |
| `aether.entity_resolved` | `schemas/entity_resolved.avsc` | Schema/topic ready, no producer built yet -- `apps/api/python/app/graph/resolve.py`'s resolution pass is not yet wired to publish `EntityResolvedEvent`s |
| `aether.user_alerts` | `schemas/user_alert.avsc` | Flink CEP job output (Task 27, not yet built), consumed by the alert dispatch service |

All topics: 3 partitions, replication factor 1 (dev). Created idempotently
by `app.streaming.kafka_client.ensure_topics()` -- every producer calls it
on startup rather than assuming the topics already exist.

## Local dev

```
cd apps/api/python
source .venv/bin/activate
python -m app.streaming.producers.sec_edgar_rss     # one poll cycle
python -m app.streaming.producers.opencorporates_delta
python -m app.streaming.producers.newsapi_stream
python -m app.streaming.producers.osm_changesets
```

Required env: `KAFKA_BOOTSTRAP_SERVERS` (default `localhost:9092`),
`SCHEMA_REGISTRY_URL` (default `http://localhost:8082`), plus each
producer's own source API key/identity (`EDGAR_IDENTITY`,
`OPENCORPORATES_API_KEY`, `NEWSAPI_KEY`, `NOMINATIM_USER_AGENT`) -- see
`apps/api/python/.env.example`.

## ksqlDB (`ksql/`)

`ksql/01_streams.sql` declares a `STREAM` over each input topic;
`ksql/02_tables.sql` builds materialized "latest state per entity" views
on top of them (`CREATE TABLE ... AS SELECT ... GROUP BY ... EMIT
CHANGES`, i.e. CTAS). Apply in order against a running ksqlDB server:

```
for f in streaming/ksql/*.sql; do
  curl -s -X POST localhost:8088/ksql -H "Content-Type: application/vnd.ksql.v1+json" \
    -d "$(python3 -c "import json,sys; print(json.dumps({'ksql': open(sys.argv[1]).read(), 'streamsProperties': {}}))" "$f")"
done
```

**Gotcha (hit and fixed during Phase 4 build):** ksqlDB streams/tables
default to `auto.offset.reset=latest`. A `CREATE STREAM` issued after
events already exist in its topic will not see that backlog, so any
`CTAS` built on top of it materializes as empty even though the topic has
real data (confirmed: `latest_business_registration_by_cik` returned zero
rows against 89 already-published SEC EDGAR events until this was fixed).
Fix: set `ksql.streams.auto.offset.reset=earliest` in
`ksql-server.properties` before creating streams/tables that need to
backfill from history already in the topic, then restart ksqlDB (stream/
table DDL persists across restart via ksqlDB's internal command topic, so
nothing needs re-creating).

**Gotcha:** `CREATE STREAM ... WITH (VALUE_FORMAT='AVRO')` with no
explicit column list infers columns from the topic's registered Avro
schema -- which fails with error_code 40001 ("Schema ... does not exist
in the Schema Registry") if no producer has ever published to that topic
yet. Fix: call `app.streaming.kafka_client.ensure_schemas()` once to
proactively register all 6 topics' schemas before running
`01_streams.sql`, rather than waiting for a real producer run.

Per-user subscription filtering (geofence/entity/keyword) is deliberately
*not* done in ksqlDB -- it would need live join access to Postgres
subscription rows, which static declarative ksqlDB SQL can't reference
without a Kafka Connect JDBC/CDC connector (not installed in this dev
environment). That filtering is done in the Flink CEP job (`flink/`,
Task 27) instead, which can hold and refresh subscription state directly.
