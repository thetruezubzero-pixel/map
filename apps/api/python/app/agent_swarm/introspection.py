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

import asyncio
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
    #
    # A readiness review found the original version fetched the last 200
    # task_history rows across BOTH roles combined, then split by role --
    # if one role is more active than the other (a realistic steady state,
    # since amateur-vote failures/spawns aren't role-symmetric), the
    # less-active role's rate was silently computed from a much smaller,
    # non-200 sample despite the docstring's "a role's last 200" claim.
    # Querying each role's own last-200 window separately fixes it.
    disagreements: dict[str, list[bool]] = {}
    for role in ("query_analyzer", "result_synthesizer"):
        role_rows = await pool.fetch(
            "SELECT votes FROM task_history WHERE role = $1 ORDER BY created_at DESC LIMIT 200",
            role,
        )
        for r in role_rows:
            votes = json.loads(r["votes"]) if isinstance(r["votes"], str) else r["votes"]
            keys = {v["output_key"] for v in votes if v.get("weight", 0) > 0}
            disagreements.setdefault(role, []).append(len(keys) > 1)
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


# Phase 5d: full source-tree visibility -- see ROADMAP.md "Phase 5d:
# full source visibility" for the scope decision this implements. A
# denylist, not an allowlist, since "every file" is the point -- but
# anything secret-shaped is excluded outright, unconditionally, before
# any content is read, regardless of AGENT_FULL_SOURCE_VISIBILITY_ENABLED.
_EXCLUDED_DIR_NAMES = {
    ".git", "node_modules", "target", "dist", "build", "__pycache__",
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
_SOURCE_SUFFIXES = {".py", ".rs", ".ts", ".tsx", ".sql", ".md", ".toml", ".yml", ".yaml"}
_SECRET_SHAPED_TOKENS = ("secret", "credential", "password")
_SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx")


def _is_source_readable(path: Path) -> bool:
    """Confirmed by a security review: the original version only checked
    _SECRET_SHAPED_TOKENS against the leaf filename, so a directory like
    `secrets/` or `config/credentials/` with innocuously-named files
    inside (e.g. `secrets/db.yml`) would slip through -- no such
    directory exists in this repo today, but it's a real gap, not a
    hypothetical one, for any future secrets-holding directory. Now
    checks every path component, directories included, not just the
    file's own name."""
    parts_lower = [p.lower() for p in path.parts]
    if any(part in _EXCLUDED_DIR_NAMES for part in parts_lower):
        return False
    if any(token in part for part in parts_lower for token in _SECRET_SHAPED_TOKENS):
        return False
    name_lower = path.name.lower()
    if name_lower.startswith(".env") and name_lower != ".env.example":
        return False
    if name_lower.endswith(_SECRET_SUFFIXES):
        return False
    return path.suffix in _SOURCE_SUFFIXES


def _read_full_source_tree_sync(project_root: Path, *, max_total_chars: int) -> dict:
    """Reads real source file contents, line-by-line, not a summary --
    only when settings.agent_full_source_visibility_enabled (default
    off; see build_project_snapshot). Capped at max_total_chars TOTAL
    (not per file) so this can't silently blow past a model's context
    budget or balloon OpenRouter token cost -- confirmed this repo's
    own source (excluding node_modules/target/.git) is ~1MB/~17k lines
    as of this phase, so the default 2MB cap covers it with headroom,
    but the cap (and the `truncated` flag when it's hit) exists so
    growth doesn't silently start dropping files with no signal.

    Synchronous by design -- always called via asyncio.to_thread (see
    _read_full_source_tree below), since this walks and reads the
    project's *entire* tree and would otherwise block this single-worker
    service's event loop for the whole walk, the same bug class already
    fixed for _recent_git_log's subprocess call in this same file."""
    if not project_root.exists():
        return {"files": [], "total_files": 0, "total_chars": 0, "truncated": False}

    resolved_root = project_root.resolve()
    files: list[dict] = []
    total_chars = 0
    truncated = False
    for path in sorted(project_root.rglob("*")):
        if not path.is_file() or not _is_source_readable(path):
            continue
        # Confirmed by a security review: is_file()/read_text() both
        # follow symlinks, but _is_source_readable only inspects the
        # symlink's own name/suffix -- a symlinked path pointing outside
        # project_root would have its *target's* content read otherwise.
        # No such symlink exists in this repo today, but this check
        # doesn't depend on that staying true.
        #
        # A readiness review found this resolve() call sat OUTSIDE any
        # try/except -- is_file() above tolerates a permission error on an
        # intermediate directory (specific errnos only), but resolve()
        # doesn't, so one unreadable path anywhere under project_root
        # raised straight out of this function (and, unhandled, out of
        # build_project_snapshot -> POST /architect/run) instead of being
        # skipped-with-a-warning like every other read failure here.
        try:
            resolved_path = path.resolve()
        except OSError as exc:
            logger.warning("full-source-tree skipped a path that failed to resolve: %s: %s", path, exc)
            continue
        if resolved_path != resolved_root and resolved_root not in resolved_path.parents:
            logger.warning("full-source-tree skipped a path resolving outside project root: %s", path)
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("full-source-tree read skipped %s: %s", path, exc)
            continue
        if total_chars + len(text) > max_total_chars:
            truncated = True
            break
        files.append(
            {
                "path": str(path.relative_to(project_root)),
                "content": text,
                "line_count": text.count("\n") + 1,
            }
        )
        total_chars += len(text)

    return {"files": files, "total_files": len(files), "total_chars": total_chars, "truncated": truncated}


async def _read_full_source_tree(project_root: Path, *, max_total_chars: int) -> dict:
    """A readiness review found _read_full_source_tree_sync was called
    directly from build_project_snapshot with no asyncio.to_thread -- the
    exact bug class CLAUDE.md documents as already found and fixed for
    architect_committer.py/change_proposer.py's git calls and, in this
    same file, _recent_git_log, just missed for this one. Walking the
    whole tree and reading every matching file as plain synchronous I/O
    directly on the single uvicorn worker's event loop freezes every
    concurrent request (including /health) for the duration, whenever
    AGENT_FULL_SOURCE_VISIBILITY_ENABLED=true."""
    return await asyncio.to_thread(_read_full_source_tree_sync, project_root, max_total_chars=max_total_chars)


def _read_dag_inventory(project_root: Path) -> list[str]:
    dags_dir = project_root / "data" / "pipelines" / "dags"
    if not dags_dir.exists():
        return []
    return sorted(p.name for p in dags_dir.glob("*.py"))


async def _recent_git_log(project_root: Path, limit: int = 15) -> list[dict] | None:
    """Runs via asyncio.to_thread, not directly on the event loop -- a
    security review flagged this alongside architect_committer.py's git
    calls as blocking the single-worker service for its duration; `git
    log` is normally fast (no network round trip, unlike fetch/push),
    but there's no reason to leave this one call inconsistent with the
    same fix applied everywhere else this module family shells out."""
    if not (project_root / ".git").exists():
        return None

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(project_root), "log", f"-{limit}", "--pretty=format:%H%x1f%s%x1f%an%x1f%aI"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )

    try:
        result = await asyncio.to_thread(_run)
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

    # A readiness review found these two ran as plain synchronous
    # filesystem I/O directly inside this async def -- the same bug class
    # already fixed for _recent_git_log/_read_full_source_tree in this
    # same file (see their docstrings), just missed here. Each call is
    # small (one file read, one directory glob) but this service is a
    # single uvicorn worker, so any blocking call anywhere freezes every
    # concurrent request for its duration -- no "too small to matter"
    # exception to that.
    roadmap = await asyncio.to_thread(_read_roadmap, project_root)
    if roadmap is not None:
        snapshot["roadmap"] = roadmap

    dags = await asyncio.to_thread(_read_dag_inventory, project_root)
    if dags:
        snapshot["dags"] = dags

    git_log = await _recent_git_log(project_root)
    if git_log is not None:
        snapshot["recent_commits"] = git_log

    snapshot["gateway_routes"] = GATEWAY_ROUTES
    snapshot["python_api_routers"] = PYTHON_API_ROUTERS

    if settings.agent_full_source_visibility_enabled:
        snapshot["full_source_tree"] = await _read_full_source_tree(
            project_root, max_total_chars=settings.agent_full_source_visibility_max_chars
        )

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

    source_tree = snapshot.get("full_source_tree")
    source_note = ""
    if source_tree is not None:
        truncated_note = " (truncated -- hit the char cap)" if source_tree.get("truncated") else ""
        source_note = f"; full source visible: {source_tree.get('total_files', 0)} files{truncated_note}"

    return (
        f"{entity_total} entities across {len(db.get('entities_by_source_type', []))} "
        f"source/type pairs, {agent_total} registered agents, {n_dags} DAGs, "
        f"{n_commits} recent commits observed{swarm_note}{source_note}"
    )


def snapshot_to_json(snapshot: dict) -> str:
    return json.dumps(snapshot, default=str)
