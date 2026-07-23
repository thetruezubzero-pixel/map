"""Flink CEP / anomaly / correlation job -- Task 27.

Reads aether.business_registrations and aether.news_mentions, detects
three kinds of patterns, and writes raw detections to
aether.detected_patterns (internal topic, see
streaming/schemas/detected_pattern.avsc):

1. FILING_CLUSTER -- MATCH_RECOGNIZE (real Flink SQL CEP, the SQL-standard
   pattern-matching clause) over business_registrations, partitioned by
   CIK: 2+ filings from the same company within 1 hour. A real signal --
   clusters of 8-Ks/10-Qs in a short window often precede or follow a
   material event.

2. FILING_VOLUME_SPIKE -- sliding window aggregation (HOP) over all
   filings, 1-minute slide / 10-minute size, flagged when the windowed
   count exceeds FILING_SPIKE_THRESHOLD (default 5). A fixed threshold,
   not a statistical baseline (no historical mean/stddev is computed) --
   documented as a real limitation, not silently a "real" anomaly model.

3. REGISTRATION_NEWS_CORRELATION -- interval join between
   business_registrations and news_mentions: a news article mentioning
   the filing company's name, published within 1 hour of the filing.
   Matched by company-name substring (LIKE), NOT a shared entity ID --
   aether.entity_resolved has no producer yet (see streaming/README.md),
   so there is no resolved-entity key to join on. This means false
   negatives (name formatting differs between SEC EDGAR and news outlets,
   e.g. "Inc." vs "Incorporated") and occasional false positives for
   short/generic company names. Documented limitation, not hidden.

Per-user subscription matching (which of these should become a real
aether.user_alerts row, for which user, over which channel) is
deliberately NOT done here. Flink 2.3.0 has no flink-connector-jdbc
release built against the Flink 2.x connector API yet (checked Maven
Central: latest is 3.3.0-1.20, i.e. built for Flink 1.20), so a live join
against Postgres user_subscriptions isn't safely available. That fan-out
step is a separate consumer of aether.detected_patterns, to be built in
Task 28 alongside the user_subscriptions table and the Rust
/subscriptions CRUD.

Run against the standalone cluster (not a local MiniCluster) so it's a
real, monitorable Flink job:

    cd /path/to/flink-2.3.0
    bin/flink run -pyexec /path/to/streaming/flink/.venv/bin/python \
        -py /path/to/streaming/flink/cep_alerts.py

Requires flink-sql-connector-kafka and flink-sql-avro-confluent-registry
on the cluster's lib/ (see streaming/README.md for exact versions/URLs --
Flink 2.3.0 predates a same-numbered official Kafka connector release, so
the closest compatible version was used and verified against this job).
"""

from __future__ import annotations

import os

from pyflink.table import EnvironmentSettings, TableEnvironment

KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
SCHEMA_REGISTRY_URL = os.environ.get("SCHEMA_REGISTRY_URL", "http://localhost:8082")
FILING_SPIKE_THRESHOLD = int(os.environ.get("FILING_SPIKE_THRESHOLD", "5"))

# ISO8601 with a numeric offset (e.g. "2026-07-21T13:38:37.352824+00:00")
# -- TO_TIMESTAMP's default format is 'yyyy-MM-dd HH:mm:ss' (space
# separator, no offset, no fraction), so both an explicit format string
# and truncating to the first 19 chars are required, or every row's
# rowtime silently parses to NULL (confirmed live: this is exactly what
# happened before the explicit format was added -- windowed operators
# failed hard with "RowTime field should not be null"). Second
# precision is fine for 1-10 minute windows; not fine for sub-second CEP,
# which this job doesn't attempt.
_EVENT_TIME_COL = (
    "event_time AS TO_TIMESTAMP(SUBSTRING(detected_at, 1, 19), 'yyyy-MM-dd''T''HH:mm:ss'), "
    "WATERMARK FOR event_time AS event_time - INTERVAL '10' SECOND"
)


def _kafka_source_with(topic: str, group_id: str) -> str:
    return (
        f"'connector' = 'kafka', "
        f"'topic' = '{topic}', "
        f"'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP_SERVERS}', "
        f"'properties.group.id' = '{group_id}', "
        f"'scan.startup.mode' = 'earliest-offset', "
        f"'value.format' = 'avro-confluent', "
        f"'value.avro-confluent.url' = '{SCHEMA_REGISTRY_URL}'"
    )


def build_table_env() -> TableEnvironment:
    settings = EnvironmentSettings.in_streaming_mode()
    t_env = TableEnvironment.create(settings)
    t_env.get_config().set("parallelism.default", "1")
    # Dev topics are low-volume -- without this, a quiet source can stall
    # the other source's watermark from advancing, which stalls the
    # interval join and window aggregations indefinitely.
    t_env.get_config().set("table.exec.source.idle-timeout", "10 s")
    return t_env


def register_sources(t_env: TableEnvironment) -> None:
    t_env.execute_sql(
        f"""
        CREATE TABLE business_registrations (
            event_id STRING,
            source STRING,
            company_name STRING,
            cik STRING,
            opencorporates_id STRING,
            filing_type STRING,
            jurisdiction STRING,
            url STRING,
            detected_at STRING,
            license STRING,
            metadata_json STRING,
            {_EVENT_TIME_COL}
        ) WITH (
            {_kafka_source_with('aether.business_registrations', 'flink-cep-business-registrations')}
        )
        """
    )

    # `sentiment` is deliberately omitted here even though
    # news_mention.avsc has it -- it's an Avro enum in the writer schema,
    # and Flink SQL has no ENUM column type, so a reader schema derived
    # from a STRING column can't resolve against it (Avro only resolves
    # enum-to-enum, never enum-to-string; confirmed live via
    # AvroTypeException: "Found os.aether.streaming.Sentiment, expecting
    # union" before this field was dropped from the projection).
    # sentiment_score (a plain double, no enum) is unaffected and kept.
    t_env.execute_sql(
        f"""
        CREATE TABLE news_mentions (
            event_id STRING,
            source STRING,
            title STRING,
            url STRING,
            outlet STRING,
            published_at STRING,
            matched_keywords ARRAY<STRING>,
            sentiment_score DOUBLE,
            lat DOUBLE,
            lon DOUBLE,
            detected_at STRING,
            license STRING,
            {_EVENT_TIME_COL}
        ) WITH (
            {_kafka_source_with('aether.news_mentions', 'flink-cep-news-mentions')}
        )
        """
    )


def register_sink(t_env: TableEnvironment) -> None:
    t_env.execute_sql(
        f"""
        CREATE TABLE detected_patterns (
            pattern_id STRING,
            pattern_type STRING,
            severity STRING,
            title STRING,
            description STRING,
            source_topic STRING,
            entity_name STRING,
            cik STRING,
            evidence_json STRING,
            detected_at STRING,
            window_start STRING,
            window_end STRING
        ) WITH (
            'connector' = 'kafka',
            'topic' = 'aether.detected_patterns',
            'properties.bootstrap.servers' = '{KAFKA_BOOTSTRAP_SERVERS}',
            'value.format' = 'avro-confluent',
            'value.avro-confluent.url' = '{SCHEMA_REGISTRY_URL}',
            'value.avro-confluent.subject' = 'aether.detected_patterns-value'
        )
        """
    )


FILING_CLUSTER_SQL = """
INSERT INTO detected_patterns
SELECT
    UUID() AS pattern_id,
    'FILING_CLUSTER' AS pattern_type,
    'WARNING' AS severity,
    CONCAT('Rapid filing activity: ', company_name) AS title,
    CONCAT(CAST(filing_count AS STRING), ' filings for CIK ', cik,
           ' within 1 hour (', CAST(first_filing_at AS STRING), ' - ',
           CAST(last_filing_at AS STRING), ')') AS description,
    'aether.business_registrations' AS source_topic,
    company_name AS entity_name,
    cik,
    CONCAT('{"filing_count":', CAST(filing_count AS STRING), '}') AS evidence_json,
    CAST(CURRENT_TIMESTAMP AS STRING) AS detected_at,
    CAST(first_filing_at AS STRING) AS window_start,
    CAST(last_filing_at AS STRING) AS window_end
FROM (
    SELECT * FROM business_registrations WHERE cik IS NOT NULL
)
MATCH_RECOGNIZE (
    PARTITION BY cik
    ORDER BY event_time
    MEASURES
        LAST(A.company_name) AS company_name,
        FIRST(A.event_time) AS first_filing_at,
        LAST(A.event_time) AS last_filing_at,
        COUNT(A.event_id) AS filing_count
    ONE ROW PER MATCH
    AFTER MATCH SKIP PAST LAST ROW
    PATTERN (A{2,}?) WITHIN INTERVAL '1' HOUR
    DEFINE
        A AS TRUE
) AS T
"""

FILING_VOLUME_SPIKE_SQL = f"""
INSERT INTO detected_patterns
SELECT
    UUID() AS pattern_id,
    'FILING_VOLUME_SPIKE' AS pattern_type,
    'WARNING' AS severity,
    'Unusual filing volume' AS title,
    CONCAT(CAST(filing_count AS STRING), ' filings between ',
           CAST(window_start AS STRING), ' and ', CAST(window_end AS STRING),
           ' (threshold: {FILING_SPIKE_THRESHOLD})') AS description,
    'aether.business_registrations' AS source_topic,
    CAST(NULL AS STRING) AS entity_name,
    CAST(NULL AS STRING) AS cik,
    CONCAT('{{"filing_count":', CAST(filing_count AS STRING), '}}') AS evidence_json,
    CAST(CURRENT_TIMESTAMP AS STRING) AS detected_at,
    CAST(window_start AS STRING) AS window_start,
    CAST(window_end AS STRING) AS window_end
FROM (
    SELECT window_start, window_end, COUNT(*) AS filing_count
    FROM TABLE(
        HOP(TABLE business_registrations, DESCRIPTOR(event_time), INTERVAL '1' MINUTE, INTERVAL '10' MINUTE)
    )
    GROUP BY window_start, window_end
)
WHERE filing_count > {FILING_SPIKE_THRESHOLD}
"""

REGISTRATION_NEWS_CORRELATION_SQL = """
INSERT INTO detected_patterns
SELECT
    UUID() AS pattern_id,
    'REGISTRATION_NEWS_CORRELATION' AS pattern_type,
    'INFO' AS severity,
    CONCAT('News mention following filing: ', b.company_name) AS title,
    CONCAT(b.company_name, ' filed ', COALESCE(b.filing_type, 'a registration'),
           ' and was mentioned in news within 1 hour: "', n.title,
           '" (sentiment score: ', CAST(n.sentiment_score AS STRING), ')') AS description,
    'aether.business_registrations' AS source_topic,
    b.company_name AS entity_name,
    b.cik,
    CONCAT('{"news_url":"',
           REPLACE(REPLACE(COALESCE(n.url, ''), '\\', '\\\\'), '"', '\\"'),
           '","sentiment_score":',
           CAST(n.sentiment_score AS STRING), '}') AS evidence_json,
    CAST(CURRENT_TIMESTAMP AS STRING) AS detected_at,
    CAST(b.event_time AS STRING) AS window_start,
    CAST(n.event_time AS STRING) AS window_end
FROM business_registrations b, news_mentions n
WHERE n.title LIKE CONCAT('%', b.company_name, '%')
  AND n.event_time BETWEEN b.event_time AND b.event_time + INTERVAL '1' HOUR
"""


def main() -> None:
    t_env = build_table_env()
    register_sources(t_env)
    register_sink(t_env)

    statement_set = t_env.create_statement_set()
    statement_set.add_insert_sql(FILING_CLUSTER_SQL)
    statement_set.add_insert_sql(FILING_VOLUME_SPIKE_SQL)
    statement_set.add_insert_sql(REGISTRATION_NEWS_CORRELATION_SQL)
    statement_set.execute()


if __name__ == "__main__":
    main()
