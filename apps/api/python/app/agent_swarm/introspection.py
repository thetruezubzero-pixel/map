"""Builds the project's "digital twin" -- a structured, real snapshot of
the project's current state (never hallucinated). ProjectArchitectAgent
(app/agents/project_architect.py) only ever sees this JSON as input; it
does not have its own access to the filesystem or the DB.

Requires `settings.project_root` (the repo mounted read-only-in-spirit,
read-write-in-practice for architect_committer.py's git operations -- see
docker-compose.yml) to read ROADMAP.md/CLAUDE.md/the DAGs directory and
recent git log. If the mount isn't present (e.g. a bare `uvicorn` run
outside docker-compose), those sections degrade to empty/omitted rather
than raising -- DB introspection still works either way.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("aether.agent_swarm.introspection")

# Static, hand-maintained inventories rather than reflection over the
# Rust/TS source trees (this Python service can't import those) -- kept
# short and factual; extend when a new route/DAG genuinely ships, same as
# the Source/BASE_STYLES arrays kept in sync by hand elsewhere in this repo.
GATEWAY_ROUTES = [
    "GET /health", "GET /health/streaming", "GET /geocode", "GET /search",
    "GET /entities/:id", "POST /research", "GET /subscriptions",
    "POST /subscriptions", "PATCH /subscriptions/:id", "DELETE /subscriptions/:id",
    "GET /ws/alerts",
]

PYTHON_API_ROUTERS = [
    "research", "graph", "analytics", "agent_swarm (agents/swarm/training/heirlooms)",
    "architect",
]


async def _swarm_health(pool) -> list[dict]:
    """Per-role, per-level swarm health -- read-only input for the
    Architect's planning (see build_project_snapshot's docstring: this
    module never mutates agent_registry/task_history, only reads them,
    same trust level as everything else in the snapshot). Graduation
    reuses the exact accuracy/consecutive-successes formula
    agent_weight.meets_graduation_criteria applies in application code
    (kept in sync by hand -- there are only two thresholds, 0.90 and 50).
    """
    agent_rows = await pool.fetch(
        """
        SELECT role, level, count(*) AS n, avg(current_weight) AS avg_weight,
               count(*) FILTER (
                   WHERE level = 'amateur'
                     AND total_successes::float / NULLIF(total_tasks, 0) >= 0.90
                     AND consecutive_successes >= 50
               ) AS graduated_amateurs
        FROM agent_registry
        WHERE role IN ('query_analyzer', 'data_retriever', 'result_synthesizer')
        GROUP BY 1, 2 ORDER BY 1, 2
        """
    )

    # Recent-disagreement rate: fraction of a role's last 200 consensus
    # rounds where the (nonzero-weight) votes didn't converge on one
    # output_key. task_history doesn't persist ConsensusResult.agreement_ratio
    # directly, so this is reconstructed from the same votes JSON the
    # /swarm dashboard already renders, not a new stored metric.
    task_rows = await pool.fetch(
        """
        SELECT role, votes FROM task_history
        WHERE role IN ('query_analyzer', 'result_synthesizer')
        ORDER BY created_at DESC LIMIT 200
        """
    )
    disagreements: dict[str, list[bool]] = {}
    for r in task_rows:
        votes = json.loads(r["votes"]) if isinstance(r["votes"], str) else r["votes"]
        keys = {v["output_key"] for v in votes if v.get("weight", 0) > 0}
        disagreements.setdefault(r["role"], []).append(len(keys) > 1)
    disagreement_rate = {role: sum(flags) / len(flags) for role, flags in disagreements.items() if flags}

    return [
        {
            "role": r["role"],
            "level": r["level"],
            "count": r["n"],
            "avg_weight": float(r["avg_weight"]) if r["avg_weight"] is not None else None,
            "graduated_amateurs": r["graduated_amateurs"] if r["level"] == "amateur" else None,
            "recent_disagreement_rate": disagreement_rate.get(r["role"]),
        }
        for r in agent_rows
    ]


async def _db_counts(pool) -> dict:
    entity_rows = await pool.fetch(
        "SELECT source, entity_type, count(*) AS n FROM research_entities GROUP BY 1, 2 ORDER BY 1, 2"
    )
    agent_rows = await pool.fetch(
        "SELECT role, level, count(*) AS n, avg(current_weight) AS avg_weight "
        "FROM agent_registry GROUP BY 1, 2 ORDER BY 1, 2"
    )
    heirloom_count = await pool.fetchval("SELECT count(*) FROM heirloom_manifest")
    resolution_queue = await pool.fetchval(
        "SELECT count(*) FROM entity_resolution_candidates WHERE status = 'pending_review'"
    )
    return {
        "entities_by_source_type": [
            {"source": r["source"], "entity_type": r["entity_type"], "count": r["n"]} for r in entity_rows
        ],
        "agents_by_role_level": [
            {
                "role": r["role"],
                "level": r["level"],
                "count": r["n"],
                "avg_weight": float(r["avg_weight"]) if r["avg_weight"] is not None else None,
            }
            for r in agent_rows
        ],
        "heirloom_count": heirloom_count,
        "entity_resolution_pending": resolution_queue,
    }


def _read_roadmap(project_root: Path) -> dict | None:
    path = project_root / "ROADMAP.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")

    # Phase headers look like "## Phase N: <title>" or "### Phase N ..." --
    # tolerant of both; "done"/"complete"/"built" vs "future"/"pending" is
    # inferred from nearby text rather than a rigid schema, since ROADMAP.md
    # is a human-maintained prose doc, not structured data.
    phases = re.findall(r"^#{2,3}\s*(Phase\s+\d+[^\n]*)", text, re.MULTILINE)
    non_goals_match = re.search(
        r"##\s*Explicit non-goals.*?(?=\n##\s|\Z)", text, re.DOTALL | re.IGNORECASE
    )
    return {
        "phase_headers": phases,
        "non_goals_excerpt": non_goals_match.group(0).strip() if non_goals_match else None,
    }


def _read_dag_inventory(project_root: Path) -> list[str]:
    dags_dir = project_root / "data" / "pipelines" / "dags"
    if not dags_dir.exists():
        return []
    return sorted(p.name for p in dags_dir.glob("*.py"))


def _recent_git_log(project_root: Path, limit: int = 15) -> list[dict] | None:
    if not (project_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "-C", str(project_root), "log", f"-{limit}", "--pretty=format:%H%x1f%s%x1f%an%x1f%aI"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        logger.warning("git log introspection failed: %s", exc)
        return None

    commits = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        sha, subject, author, date = parts
        commits.append({"sha": sha[:12], "subject": subject, "author": author, "date": date})
    return commits


async def build_project_snapshot(pool) -> dict:
    """Real introspection only -- every field is either a live DB query
    result or a direct filesystem/git read. Returned dict is what gets
    stored verbatim in project_snapshots.snapshot and handed to
    ProjectArchitectAgent as its only view of "the project"."""
    settings = get_settings()
    project_root = Path(settings.project_root)

    snapshot: dict = {"db": await _db_counts(pool), "swarm_health": await _swarm_health(pool)}

    roadmap = _read_roadmap(project_root)
    if roadmap is not None:
        snapshot["roadmap"] = roadmap

    dags = _read_dag_inventory(project_root)
    if dags:
        snapshot["dags"] = dags

    git_log = _recent_git_log(project_root)
    if git_log is not None:
        snapshot["recent_commits"] = git_log

    snapshot["gateway_routes"] = GATEWAY_ROUTES
    snapshot["python_api_routers"] = PYTHON_API_ROUTERS

    return snapshot


def summarize_snapshot(snapshot: dict) -> str:
    """One-line human-facing summary stored alongside the full JSON in
    project_snapshots.summary, so a dashboard list doesn't need to
    deserialize the full payload just to show a row label."""
    db = snapshot.get("db", {})
    entity_total = sum(r["count"] for r in db.get("entities_by_source_type", []))
    agent_total = sum(r["count"] for r in db.get("agents_by_role_level", []))
    n_dags = len(snapshot.get("dags", []))
    n_commits = len(snapshot.get("recent_commits", []) or [])

    swarm_health = snapshot.get("swarm_health", [])
    ungraduated_roles = sorted(
        {
            h["role"]
            for h in swarm_health
            if h["level"] == "amateur" and h["count"] > 0 and not h["graduated_amateurs"]
        }
    )
    swarm_note = f"; no amateur graduations yet in: {', '.join(ungraduated_roles)}" if ungraduated_roles else ""

    return (
        f"{entity_total} entities across {len(db.get('entities_by_source_type', []))} "
        f"source/type pairs, {agent_total} registered agents, {n_dags} DAGs, "
        f"{n_commits} recent commits observed{swarm_note}"
    )


def snapshot_to_json(snapshot: dict) -> str:
    return json.dumps(snapshot, default=str)
