-- Phase 4 / Task 26 -- materialized "latest state per entity" views,
-- built on top of the streams in 01_streams.sql. Run after those.
--
-- IMPORTANT: ksqlDB streams/tables default to `auto.offset.reset=latest`,
-- meaning a table created here only aggregates events produced *after*
-- its underlying stream was declared -- it will not backfill from
-- history already sitting in the topic. This deployment sets
-- `ksql.streams.auto.offset.reset=earliest` in ksql-server.properties
-- so these CTAS queries backfill from the beginning of each topic
-- (confirmed: latest_business_registration_by_cik picked up all 89
-- pre-existing SEC EDGAR events after this was set and the server
-- restarted). If you deploy without that setting, these tables will
-- appear empty until new events arrive.

CREATE TABLE IF NOT EXISTS latest_business_registration_by_cik AS
  SELECT
    cik,
    LATEST_BY_OFFSET(company_name) AS company_name,
    LATEST_BY_OFFSET(filing_type) AS latest_filing_type,
    LATEST_BY_OFFSET(url) AS latest_url,
    LATEST_BY_OFFSET(detected_at) AS last_seen_at,
    COUNT(*) AS filing_count
  FROM business_registrations_stream
  WHERE cik IS NOT NULL
  GROUP BY cik
  EMIT CHANGES;

-- Running sentiment/volume rollup per news source (newsapi vs gdelt),
-- refreshed on every new mention -- used by the dashboard's "what's
-- happening now" feed (Task 29) to show source-level sentiment trend
-- without the frontend re-aggregating raw events itself.
CREATE TABLE IF NOT EXISTS news_sentiment_by_source AS
  SELECT
    source,
    LATEST_BY_OFFSET(title) AS latest_headline,
    LATEST_BY_OFFSET(sentiment) AS latest_sentiment,
    AVG(sentiment_score) AS avg_sentiment_score,
    COUNT(*) AS mention_count
  FROM news_mentions_stream
  GROUP BY source
  EMIT CHANGES;
