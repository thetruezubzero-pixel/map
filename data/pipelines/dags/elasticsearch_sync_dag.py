"""DAG: Elasticsearch sync (dag_elasticsearch_sync).

Mirrors research_entities into the aether_entities ES index so ES|QL
geospatial aggregations (geo-distance, geohash grid clustering, STATS...BY)
have something to query. ES backs analytics/aggregation queries here, not
the primary read path -- PostGIS via the gateway's /search stays
authoritative.
"""

from __future__ import annotations

import os
import sys

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0,
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "apps", "api", "python"),
)

from airflow.sdk import dag, task


@dag(
    dag_id="elasticsearch_sync",
    description="Bulk-syncs research_entities into the Elasticsearch index for ES|QL aggregations.",
    schedule="@hourly",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["sync", "elasticsearch", "public-records"],
)
def elasticsearch_sync_dag():
    @task
    def sync() -> int:
        import asyncio

        import asyncpg

        from app.search.elasticsearch_setup import bulk_sync_from_postgres

        async def _run() -> int:
            dsn = os.environ.get(
                "GATEWAY_DATABASE_URL", "postgres://aether:aether@localhost:5432/aether"
            )
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
            try:
                return await bulk_sync_from_postgres(pool)
            finally:
                await pool.close()

        return asyncio.run(_run())

    sync()


elasticsearch_sync_dag()
