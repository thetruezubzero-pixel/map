# data/pipelines

Airflow 3.0 DAGs that keep `research_entities` in sync with public-record
sources. Each DAG follows the same shape: `fetch_*` (calls the source API,
tags every record with `source`/`license`, runs it through
`common.pii_scrub.scrub_record`) -> `load_records` (upserts into Postgres
via `common.db.upsert_entities`).

| DAG | Source | Schedule | entity_type written | API key |
|---|---|---|---|---|
| `osm_ingestion` | Nominatim (OSM) | `@daily` | `poi`, `location` | none (real User-Agent required) |
| `newsapi_ingestion` | NewsAPI | `@hourly` | `news_mention` | `NEWSAPI_KEY` |
| `opencorporates_sync` | OpenCorporates | `@weekly` | `business` | `OPENCORPORATES_API_KEY` |
| `sec_edgar_ingestion` | SEC EDGAR (via EdgarTools) | `@daily` | `business`, `government_filing` | none (real `EDGAR_IDENTITY` required) |
| `census_tiger_sync` | Census TIGERweb | `@monthly` | `location` | none |
| `usgs_elevation_sync` | USGS Elevation Point Query Service | `@monthly` | `location` | none |
| `gdelt_events_sync` | GDELT 2.0 Doc API | `@daily` | `news_mention` | none |
| `data_gov_search_sync` | Data.gov (CKAN `package_search`) | `@weekly` | `government_filing` | none |
| `fema_flood_hazard_sync` | FEMA NFHL (flood hazard zones) | `@monthly` | `location` | none |
| `noaa_alerts_sync` | NOAA/NWS active weather alerts | `@hourly` | `location` | none (real User-Agent required) |
| `entity_resolution` | (internal) `research_entities` dedup pass | `@daily` | n/a -- writes `entity_relationships`/`entity_resolution_candidates` | none |
| `elasticsearch_sync` | (internal) `research_entities` -> ES mirror | `@hourly` | n/a -- syncs `aether_entities` ES index | none |
| `project_architect_cycle` | (internal) triggers `POST /architect/run` | `@daily` | n/a -- writes `project_snapshots`/`project_plans`/`project_plan_actions` | `JWT_SECRET` (mints its own short-lived token) |

All new sources are free and require no paid tier. `sec_edgar_ingestion`
and `osm_ingestion` are the two that gate on request identity rather than
an API key -- see the policy note below. `entity_resolution` and
`elasticsearch_sync` don't call an external source at all; they operate on
data already in Postgres (see `apps/api/python/app/graph/resolve.py` and
`apps/api/python/app/search/elasticsearch_setup.py`).

## Local dev

```
pip install -r requirements.txt
export AIRFLOW_HOME=~/.airflow-aether
export AIRFLOW__CORE__DAGS_FOLDER=$(pwd)/dags
export AIRFLOW__CORE__LOAD_EXAMPLES=false
export GATEWAY_DATABASE_URL=postgres://aether:aether@localhost:5432/aether
export NOMINATIM_USER_AGENT="YourApp/0.1 (contact: you@yourdomain.org)"  # real contact required, see below
export EDGAR_IDENTITY="YourApp ops@yourdomain.org"                       # required by SEC's fair-access policy
export NOAA_NWS_USER_AGENT="YourApp/0.1 (contact: you@yourdomain.org)"   # same policy as Nominatim, see below
export NEWSAPI_KEY=...
export OPENCORPORATES_API_KEY=...

airflow db migrate
airflow standalone   # or: airflow tasks test osm_ingestion fetch_osm_records 2026-01-01
```

Seed queries/search terms are read from Airflow Variables (JSON list, one
per DAG: `osm_seed_queries`, `newsapi_search_terms`,
`opencorporates_search_terms`, `sec_edgar_tickers`, `census_county_queries`,
`usgs_seed_points`, `gdelt_search_terms`, `data_gov_search_terms`,
`fema_seed_points`, `noaa_seed_points`) with small hardcoded defaults as a
fallback so every DAG runs out of the box.

**Nominatim, SEC EDGAR, and NOAA/NWS all require a real, identifying
requester.** Nominatim's and NWS's usage policies reject generic
placeholder User-Agents (e.g. `*@example.com`, 403); SEC EDGAR requires
`EDGAR_IDENTITY` to be set at all or EdgarTools calls will fail. Use a
real, reachable contact in all three.

**GDELT rate-limits aggressively** on repeated calls from the same IP;
`gdelt_events_dag.py` fails soft per search term (logs a warning, keeps
going) rather than failing the whole run on a 429.

**`data_gov_search_sync` is written against the documented CKAN API
contract**, but as of this writing `catalog.data.gov`'s classic
`/api/3/action/*` routes return 404 (the site appears to have been
restructured). The DAG fails soft (empty result, logged warning) rather
than raising -- if data.gov's API has moved, update `DATA_GOV_API_BASE`
in `data_gov_search_dag.py`.

## Scope

Public records only -- see ../../ROADMAP.md.

- `opencorporates_sync` deliberately does not ingest officer/director
  names from OpenCorporates' company records; only the company entity
  itself is stored.
- `sec_edgar_ingestion` stores the company and the filing (form type,
  date, accession number, URL) only. Officer/insider names that appear in
  Form 4 filings are not extracted into their own records -- see
  ROADMAP.md: no individual profiling. If a later phase needs
  officer/director data for the entity graph, it must be stored as filing
  metadata attached to the company record, never as a standalone
  queryable entity (see `apps/api/python/app/graph/` for how this is
  enforced in the entity-resolution layer).
