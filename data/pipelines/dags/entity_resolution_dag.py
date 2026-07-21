"""DAG: entity resolution pass (dag_entity_resolution).

Runs apps/api/python/app/graph/resolve.py's dedup pipeline over
research_entities. Business entities only -- confidence >= 0.8 becomes a
`same_as` edge automatically; everything else queues in
entity_resolution_candidates for a human to confirm or reject via the
review queue (see apps/api/python/app/routers/graph.py).
"""

from __future__ import annotations

import os
import sys

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "apps", "api", "python"))

from airflow.sdk import dag, task


@dag(
    dag_id="entity_resolution",
    description="Scores candidate duplicate business entities and updates the resolution graph.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["resolution", "graph", "public-records"],
)
def entity_resolution_dag():
    @task
    def run_resolution() -> dict:
        import asyncio

        import asyncpg

        from app.graph.resolve import run_resolution_pass

        async def _run() -> dict:
            dsn = os.environ.get(
                "GATEWAY_DATABASE_URL", "postgres://aether:aether@localhost:5432/aether"
            )
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
            try:
                return await run_resolution_pass(pool)
            finally:
                await pool.close()

        return asyncio.run(_run())

    run_resolution()


entity_resolution_dag()
