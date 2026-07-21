# data/pipelines

Airflow 3.0 DAGs that keep `research_entities` in sync with public-record
sources. Each DAG follows the same shape: `fetch_*` (calls the source API,
tags every record with `source`/`license`, runs it through
`common.pii_scrub.scrub_record`) -> `load_records` (upserts into Postgres
via `common.db.upsert_entities`).

| DAG | Source | Schedule | entity_type written |
|---|---|---|---|
| `osm_ingestion` | Nominatim (OSM) | `@daily` | `poi`, `location` |
| `newsapi_ingestion` | NewsAPI | `@hourly` | `news_mention` |
| `opencorporates_sync` | OpenCorporates | `@daily` | `business` |

## Local dev

```
pip install -r requirements.txt
export AIRFLOW_HOME=~/.airflow-aether
export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/dags
export AIRFLOW__CORE__LOAD_EXAMPLES=false
export GATEWAY_DATABASE_URL=postgres://aether:aether@localhost:5432/aether
export NOMINATIM_USER_AGENT="YourApp/0.1 (contact: you@yourdomain.org)"  # real contact required, see below
export NEWSAPI_KEY=...
export OPENCORPORATES_API_KEY=...

airflow db migrate
airflow standalone   # or: airflow tasks test osm_ingestion fetch_osm_records 2026-01-01
```

Seed queries/search terms are read from Airflow Variables
(`osm_seed_queries`, `newsapi_search_terms`, `opencorporates_search_terms`,
each a JSON list) with small hardcoded defaults as a fallback so the DAGs
run out of the box.

**Nominatim's usage policy blocks generic placeholder contacts** (e.g. any
`*@example.com` User-Agent) -- use a real, reachable contact in
`NOMINATIM_USER_AGENT` or ingestion will get 403s.

## Scope

Public records only -- see ../../ROADMAP.md. `opencorporates_sync`
deliberately does not ingest officer/director names from OpenCorporates'
company records; only the company entity itself is stored.
