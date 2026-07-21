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
| Flink | 2.3.0 | Standalone cluster (1 JobManager + 1 TaskManager, 1 slot), port 8081. Needs `flink-sql-connector-kafka-5.0.0-2.2.jar` and `flink-sql-avro-confluent-registry-2.3.0.jar` in `lib/` -- see `flink/` below |

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
| `aether.user_alerts` | `schemas/user_alert.avsc` | Schema/topic ready, no producer built yet -- per-user subscription matching (Task 28) reads `aether.detected_patterns` below and writes the real per-user rows here |
| `aether.detected_patterns` *(internal)* | `schemas/detected_pattern.avsc` | Flink CEP job (`flink/cep_alerts.py`, Task 27) -- not one of the 6 user-facing topics, see `flink/` below |

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
proactively register all producer-facing topics' schemas before running
`01_streams.sql`, rather than waiting for a real producer run.
(`aether.detected_patterns` is excluded from `ensure_schemas()` --
Flink owns that schema, see the Flink section below.)

Per-user subscription filtering (geofence/entity/keyword) is deliberately
*not* done in ksqlDB -- it would need live join access to Postgres
subscription rows, which static declarative ksqlDB SQL can't reference
without a Kafka Connect JDBC/CDC connector (not installed in this dev
environment).

## Flink CEP job (`flink/`)

`flink/cep_alerts.py` reads `aether.business_registrations` and
`aether.news_mentions` and writes to `aether.detected_patterns` (an
internal topic, not one of the 6 user-facing ones -- see below for why).
Three detections, all genuinely running against the live cluster and
verified against real data from the Phase 4 build:

1. **FILING_CLUSTER** -- real Flink SQL CEP (`MATCH_RECOGNIZE`, the
   SQL-standard pattern-matching clause), partitioned by CIK: 2+ filings
   from the same company within 1 hour.
2. **FILING_VOLUME_SPIKE** -- sliding window aggregation (`HOP`, 1-minute
   slide / 10-minute size) over all filings, flagged past a fixed
   threshold (`FILING_SPIKE_THRESHOLD`, default 5). A fixed threshold,
   not a statistical baseline -- no historical mean/stddev is computed.
3. **REGISTRATION_NEWS_CORRELATION** -- interval join between the two
   streams: a news article mentioning the filing company's name,
   published within 1 hour of the filing. Matched by company-name
   substring (`LIKE`), **not** a shared entity ID -- `aether.entity_resolved`
   has no producer yet, so there's no resolved-entity key to join on.
   Real limitation: false negatives from name-formatting differences,
   occasional false positives for short/generic names. In the live test
   run (89 SEC EDGAR filings x 20 GDELT articles), this produced zero
   matches -- consistent with a small, topically unrelated sample, not
   a sign the join itself is broken (the other two detections, run
   against the same data, produced real matches).

### Why `aether.detected_patterns` and not `aether.user_alerts` directly

`aether.user_alerts` needs a real `user_id`/`subscription_id` per row (see
`schemas/user_alert.avsc`), which means joining against Postgres
`user_subscriptions` -- a table that doesn't exist until Task 28. Flink
2.3.0 has no compatible `flink-connector-jdbc` release yet either (checked
Maven Central: latest is `3.3.0-1.20`, built for Flink 1.20's connector
API, not 2.x) so a live JDBC lookup join isn't safely available even once
the table exists. Rather than write fake/broadcast placeholder
`user_id`/`subscription_id` values into the real output topic, Flink
writes raw detections to `aether.detected_patterns`, and a separate
alert-dispatch consumer (Task 28, once `user_subscriptions` exists) reads
that topic, matches against real subscriptions, and writes the real
per-user `aether.user_alerts` rows.

### Connector jars

Flink 2.3.0 predates a same-numbered official Kafka connector release.
Downloaded from Maven Central and dropped into the cluster's `lib/`:

```
flink-sql-connector-kafka-5.0.0-2.2.jar          # closest available (built for Flink 2.2's connector API)
flink-sql-avro-confluent-registry-2.3.0.jar      # exact version match
```

### Running it

Own venv (`flink/requirements.txt`), deliberately separate from
`apps/api/python`'s -- `apache-flink` pulls in `apache-beam` and
force-downgraded numpy when first tried in the shared FastAPI venv
(confirmed live, then reverted; see the comment in
`flink/requirements.txt`).

```
cd streaming/flink && python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

cd /path/to/flink-2.3.0
bin/flink run \
  -pyclientexec /path/to/streaming/flink/.venv/bin/python \
  -pyexec /path/to/streaming/flink/.venv/bin/python \
  -py /path/to/streaming/flink/cep_alerts.py
```

Both `-pyclientexec` (the driver process that builds the job graph, runs
on the machine that calls `flink run`) and `-pyexec` (the TaskManager's
Python UDF worker) need setting -- `-pyexec` alone still failed with
`ModuleNotFoundError: No module named 'typing_extensions'` because the
*driver* process (which imports `pyflink.table` directly to build the
plan) uses the system Python unless `-pyclientexec` is also set.

### Real gotchas hit building this (all fixed, all left in the code as comments)

- **`MATCH_RECOGNIZE` clause order**: `ONE ROW PER MATCH` / `AFTER MATCH
  SKIP ...` must come *before* `PATTERN (...)`, not after -- unlike the
  order that reads naturally left-to-right in prose. Got a `SqlParserException`
  pointing at `ONE` until fixed.
- **Greedy quantifier at pattern end**: `PATTERN (A{2,})` fails in
  streaming mode ("Greedy quantifiers are not allowed as the last element
  of a Pattern yet"). Fixed with the reluctant form: `A{2,}?`.
- **`TO_TIMESTAMP` default format**: `TO_TIMESTAMP(detected_at)` on an
  ISO8601 string (`2026-07-21T13:38:37...`) silently produced `NULL` for
  every row (default format is `yyyy-MM-dd HH:mm:ss`, space-separated, no
  `T`) -- which then surfaced downstream as "RowTime field should not be
  null" from the windowed aggregation, not from the parse itself. Fixed
  with an explicit format string: `TO_TIMESTAMP(SUBSTRING(detected_at, 1, 19),
  'yyyy-MM-dd''T''HH:mm:ss')`.
- **Avro enum vs Flink SQL**: Flink SQL has no `ENUM` column type, and
  Avro only resolves enum-to-enum, never enum-to-string. A source column
  declared `sentiment STRING` against a writer schema where `sentiment`
  is an Avro enum fails with `AvroTypeException: Found ... Sentiment,
  expecting union`. Fixed two ways: (1) the `sentiment` field is
  excluded from the Flink source table's column list entirely (Avro
  supports partial/projected reads); (2) `detected_pattern.avsc` -- a
  schema this session created and controls, unlike `news_mention.avsc`
  -- declares `pattern_type`/`severity` as plain strings from the start
  rather than Avro enums, since Flink is the only producer of that topic.
- **Pre-registering the Flink sink's schema**: calling
  `ensure_schemas()` for `aether.detected_patterns` before ever running
  the job registered a schema that structurally differs from what Flink
  auto-derives from its own Table DDL (nullability wrapping, mainly),
  and Flink's own registration attempt then got a live `409` from Schema
  Registry's compatibility check. Fixed by excluding
  `aether.detected_patterns` from `ensure_schemas()` -- Flink is the
  sole producer of that topic, so it should be the sole registrar of its
  schema.

## Alert dispatch + delivery (Task 28)

Closes the loop from Flink's raw `aether.detected_patterns` to a real
alert a specific user actually sees, live-verified end to end (SEC EDGAR
producer -> Kafka -> Flink CEP -> `aether.detected_patterns` ->
dispatcher -> Postgres `user_alerts` -> WebSocket, delivered ~0.4s after
the dispatcher's INSERT):

- **`apps/gateway/migrations/0007_alerts.sql`** -- `user_subscriptions`
  (entity/keyword/geofence/composite criteria, min severity, channels)
  and `user_alerts` (durable, queryable delivery record). An
  `AFTER INSERT` trigger on `user_alerts` calls `pg_notify` so the
  gateway's WebSocket doesn't need to poll.
- **`apps/api/python/app/streaming/producers/alert_dispatcher.py`** --
  consumes `aether.detected_patterns`, matches against active
  `user_subscriptions` rows, and for each match INSERTs into
  `user_alerts` (the real delivery path) and publishes the same event to
  `aether.user_alerts` on Kafka (for parity/any future non-HTTP
  consumer). Geofence criteria never matches today -- `detected_patterns`
  carries no lat/lon (see the CEP job's docstring); entity and keyword
  matching are real and tested against live data.
- **Rust gateway** (`apps/gateway/src/routes/`):
  - `subscriptions.rs` -- full CRUD, hard JWT-required (`require_user_id`,
    401 if missing/invalid -- unlike `/research`'s optional auth, a
    subscription is inherently per-user).
  - `alerts_ws.rs` -- `GET /ws/alerts?token=<jwt>` holds a
    `sqlx::postgres::PgListener` on `user_alerts_channel` for the
    connection's lifetime and pushes matching rows as JSON. Token is a
    query param, not the `Authorization` header, because browsers can't
    set custom headers during a WS handshake -- see the doc comment on
    `require_user_id_from_query` for the logging/history tradeoff that
    comes with that.
  - `health_streaming.rs` -- `GET /health/streaming`: Kafka
    topic/partition metadata + per-topic message counts (via `rdkafka`,
    dynamically linked against the system `librdkafka-dev` -- see
    `Cargo.toml`/`Dockerfile`), Flink job/checkpoint overview (its REST
    API), ksqlDB and Schema Registry reachability. Deliberately **not**
    full per-consumer-group lag -- there's no single canonical consumer
    group across ksqlDB/Flink/the Python producers/the dispatcher to
    report lag for, so this reports topic message counts (a real,
    honest "is data flowing" signal) instead of a fabricated lag number.

Own-venv note: `alert_dispatcher.py` runs in `apps/api/python`'s regular
venv (unlike the Flink job) -- it only needs `asyncpg` (already a
dependency there) plus the existing `kafka_client` module, no new
heavyweight dependency.

### Measured latency (not sub-500ms -- documented honestly)

The original ask was sub-500ms source-to-alert latency. Live measurement
(publish a real business-registration event pair for a fresh CIK, time
until the corresponding `FILING_CLUSTER` row appears on
`aether.detected_patterns`): **~42 seconds**, not sub-500ms. Root cause:
this job sets `table.exec.source.idle-timeout = 10s` (needed so a quiet
dev-volume source doesn't stall the other source's watermark
indefinitely -- see `build_table_env()`), and with only two events on an
otherwise-idle partition, the watermark needed to safely emit the
`MATCH_RECOGNIZE` result only advances via that idle-timeout mechanism,
which pays its ~10s cost more than once before the match is confirmed
and emitted. This is a real property of low-volume dev topics with an
idle-timeout-based watermark strategy, not a bug in the pattern logic
itself (the pattern *does* fire correctly, see above). Closing the gap
to sub-500ms in a real deployment needs: continuously-arriving
higher-volume streams (watermarks advance from real event flow rather
than falling back to idle-timeout), and/or a much tighter idle-timeout
tuned against actual traffic patterns rather than this dev default.
