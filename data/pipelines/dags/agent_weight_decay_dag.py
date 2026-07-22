"""DAG: agent weight decay pass (agent_weight_decay).

Runs apps/api/python/app/agent_swarm/services/credit_assigner.py's
apply_decay over the whole agent_registry -- a periodic maintenance pass
pulling every agent's weight back toward the neutral prior in proportion
to how long it's been since its last weight_history entry. Not tied to
any single task's reward, which is why nothing else in the request path
ever calls it.

apply_decay's own docstring says "Call this from a scheduled job
(Airflow or a simple cron), not from the request path" -- confirmed live
that nothing did: zero callers anywhere in the codebase before this DAG.
Without it, an agent that stops being selected (e.g. graduated out of
rotation, or simply unlucky) keeps whatever weight it last had forever,
rather than drifting back toward neutral the way the design intends.
"""

from __future__ import annotations

import os
import sys

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "..", "apps", "api", "python"))

from airflow.sdk import dag, task


@dag(
    dag_id="agent_weight_decay",
    description="Pulls stale agent weights back toward neutral -- see credit_assigner.py's apply_decay.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["agent-swarm", "maintenance"],
)
def agent_weight_decay_dag():
    @task
    def run_decay() -> int:
        import asyncio

        import asyncpg

        from app.agent_swarm.services.credit_assigner import apply_decay

        async def _run() -> int:
            dsn = os.environ.get(
                "GATEWAY_DATABASE_URL", "postgres://aether:aether@localhost:5432/aether"
            )
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
            try:
                return await apply_decay(pool)
            finally:
                await pool.close()

        return asyncio.run(_run())

    run_decay()


agent_weight_decay_dag()
