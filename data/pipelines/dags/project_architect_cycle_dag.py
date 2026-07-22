"""DAG: the Architect's daily planning cycle (dag_project_architect_cycle).

Reuses Airflow as the scheduler rather than building a second one inside
python-api (which has none -- see ROADMAP.md "Phase 5b: the Architect").
Calls POST /architect/run, which does the real work: builds a fresh
project snapshot (the "digital twin"), runs ProjectArchitectAgent to
produce a ranked plan, and -- only for a project_plan_doc item the agent
itself judged safe_to_autoimplement -- opens a real PR updating
PROJECT_PLAN.md. It never merges; see architect_committer.py.

/architect/run is the one route in this feature gated behind JWT (it's
reachable unauthenticated via web's nginx /py-api/ proxy otherwise, same
as every python-api route -- see CLAUDE.md), so this DAG mints its own
short-lived token from the same JWT_SECRET the gateway and python-api
both verify against, rather than needing a human to log in on a cron.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pendulum

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from airflow.sdk import dag, task

PYTHON_API_BASE_URL = os.environ.get("PYTHON_API_BASE_URL", "http://python-api:8000")


@dag(
    dag_id="project_architect_cycle",
    description="Runs the Architect's snapshot -> plan -> (bounded) autonomous PR cycle.",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["architect", "agent-swarm", "self-improvement"],
)
def project_architect_cycle_dag():
    @task
    def run_cycle() -> dict:
        import httpx
        import jwt

        jwt_secret = os.environ.get("JWT_SECRET", "")
        if not jwt_secret:
            # Fail soft, matching gdelt/data_gov's "log and skip" pattern
            # for a misconfigured-but-non-critical DAG, rather than
            # raising and going red on every scheduled run.
            return {"skipped": "JWT_SECRET not set"}

        token = jwt.encode(
            {"sub": "architect-cron", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            jwt_secret,
            algorithm="HS256",
        )

        resp = httpx.post(
            f"{PYTHON_API_BASE_URL}/architect/run",
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()

    run_cycle()


project_architect_cycle_dag()
