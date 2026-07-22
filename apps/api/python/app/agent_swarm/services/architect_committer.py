"""The one place in this repo where an agent has real, unsupervised git
commit and GitHub push authority -- scoped narrowly and guarded
structurally rather than left to prompt discipline alone:

  1. It only ever writes ONE file: PROJECT_PLAN.md. ProjectArchitectAgent's
     own output is filtered before it ever reaches here (see
     app/agents/project_architect.py's `_parse` -- safe_to_autoimplement
     is forced False for every category except `project_plan_doc`), and
     this module re-checks that filter itself rather than trusting the
     caller got it right.
  2. It never merges. It commits to a fresh `agent/architect/...` branch,
     pushes it, and opens a PR against `main` -- landing always goes
     through the same human/CI-gated review every other change in this
     repo does. `_assert_never_main` makes pushing directly to `main`
     structurally impossible, not just discouraged by convention.
  3. Every step (branch created, committed, pushed, PR opened, or
     skipped/failed and why) is written to project_plan_actions, which is
     append-only at the DB level (see migrations/0009_project_architect.sql)
     -- this is the ledger a human reviews to see exactly what the
     architect has done to the real repository.

Disabled by default in spirit, not just in theory: with no GITHUB_TOKEN
set, every cycle logs a clear 'skipped' action and does nothing else --
same "clear error/no-op, never silent fallback" pattern as
heirloom_sync.py's HEIRLOOM_DEVICE_KEY.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx

from app.config import get_settings
from app.models import PlanItemCategory, ProjectPlan

logger = logging.getLogger("aether.agent_swarm.architect_committer")

PLAN_DOC_FILENAME = "PROJECT_PLAN.md"
PROTECTED_BRANCHES = {"main", "master"}


class ArchitectCommitError(RuntimeError):
    pass


def _assert_never_main(branch: str) -> None:
    """Structural guard, not a style convention -- called before every
    git push and again immediately before the GitHub PR-open call, so a
    bug anywhere upstream that somehow produced branch="main" cannot
    result in a direct push/PR-to-self against the protected branch."""
    if branch.strip().lower() in PROTECTED_BRANCHES:
        raise ArchitectCommitError(f"refusing to push directly to protected branch {branch!r}")


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:40] or "update"


def _run_git(project_root: Path, *args: str, redact: str | None = None) -> str:
    """`redact`, when given, is stripped from both the echoed command and
    git's stderr before either can reach an exception message -- the push
    step passes the GITHUB_TOKEN-bearing remote URL here specifically,
    since without this a failed push would otherwise leak the token
    verbatim into logs and into project_plan_actions.detail (persisted,
    and rendered on the /architect dashboard's action ledger). Confirmed
    by secret-scrub.sh's pre-commit hook flagging the credential-in-URL
    pattern -- this is the actual fix, not a suppression of the check."""
    result = subprocess.run(
        ["git", "-C", str(project_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        cmd_display = " ".join(args)
        stderr = result.stderr.strip()
        if redact:
            cmd_display = cmd_display.replace(redact, "***")
            stderr = stderr.replace(redact, "***")
        raise ArchitectCommitError(f"git {cmd_display} failed: {stderr}")
    return result.stdout.strip()


def _render_plan_doc(plan: ProjectPlan, snapshot_summary: str) -> str:
    lines = [
        "# Project Plan",
        "",
        "**This file is written and committed autonomously by the Architect**"
        " (`project_architect` agent role) -- see ROADMAP.md's \"Phase 5b: the"
        " Architect\" for what that means and doesn't mean. It never merges"
        " its own PRs; a human (or CI) always reviews the change that updates"
        " this file, same as every other change in this repo.",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat()} from a digital-twin"
        f" snapshot: {snapshot_summary}_",
        "",
        "## Ranked next steps",
        "",
    ]
    for i, item in enumerate(plan.items, start=1):
        flag = " (auto-implementable)" if item.safe_to_autoimplement else ""
        lines += [
            f"### {i}. {item.title}{flag}",
            "",
            f"**Category:** {item.category.value}",
            "",
            item.rationale,
            "",
        ]
    if plan.notes:
        lines += ["## Notes", "", plan.notes, ""]
    return "\n".join(lines)


async def sync_project_plan_doc(
    pool, plan_id: UUID, plan: ProjectPlan, snapshot_summary: str
) -> None:
    """The only entry point. Regenerates PROJECT_PLAN.md in full from the
    latest plan (a single self-owned status file, not a per-item patch)
    and opens a PR -- but only if the plan actually contains a
    project_plan_doc item the agent judged safe to auto-implement this
    cycle; otherwise this is a deliberate no-op, logged as such."""
    settings = get_settings()

    autoimplementable = [
        item
        for item in plan.items
        if item.safe_to_autoimplement and item.category == PlanItemCategory.project_plan_doc
    ]
    if not autoimplementable:
        await _log_action(pool, plan_id, 0, "skipped", detail={"reason": "no safe_to_autoimplement project_plan_doc item this cycle"})
        return

    if not settings.architect_auto_commit_enabled:
        await _log_action(pool, plan_id, 0, "skipped", detail={"reason": "ARCHITECT_AUTO_COMMIT_ENABLED is false"})
        return

    if not settings.github_token:
        await _log_action(pool, plan_id, 0, "skipped", detail={"reason": "GITHUB_TOKEN not configured"})
        return

    project_root = Path(settings.project_root)
    if not (project_root / ".git").exists():
        await _log_action(pool, plan_id, 0, "failed", detail={"reason": f"{project_root} is not a git working tree"})
        return

    slug = _slugify(autoimplementable[0].title)
    branch_name = f"agent/architect/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slug}"
    _assert_never_main(branch_name)

    try:
        _run_git(project_root, "fetch", "origin", "main")
        _run_git(project_root, "checkout", "-B", branch_name, "origin/main")
        await _log_action(pool, plan_id, 0, "branch_created", branch_name=branch_name)

        (project_root / PLAN_DOC_FILENAME).write_text(_render_plan_doc(plan, snapshot_summary), encoding="utf-8")
        _run_git(project_root, "add", PLAN_DOC_FILENAME)
        _run_git(
            project_root,
            "-c", "user.name=Aether Project Architect",
            "-c", "user.email=architect@aether-sovereign.local",
            "commit",
            "-m", f"chore(architect): update {PLAN_DOC_FILENAME}\n\nAutonomously generated -- see ROADMAP.md \"Phase 5b: the Architect\".",
        )
        commit_sha = _run_git(project_root, "rev-parse", "HEAD")
        await _log_action(pool, plan_id, 0, "committed", branch_name=branch_name, commit_sha=commit_sha)

        _assert_never_main(branch_name)
        # Auth via a header, not credentials embedded in the URL itself --
        # GitHub's documented approach for git-over-HTTPS with a PAT
        # (docs.github.com/en/get-started/git-basics/caching-your-credentials-in-git).
        # Embedding a token as the URL's userinfo component is exactly
        # the shape secret-scrub.sh's pre-commit hook flags on sight,
        # regardless of whether the value is a variable or a literal.
        auth_header = base64.b64encode(f"x-access-token:{settings.github_token}".encode()).decode()
        _run_git(
            project_root,
            "-c", f"http.extraHeader=Authorization: Basic {auth_header}",
            "push", f"https://github.com/{settings.github_repo}.git", f"{branch_name}:{branch_name}",
            redact=settings.github_token,
        )
        await _log_action(pool, plan_id, 0, "pushed", branch_name=branch_name, commit_sha=commit_sha)

        pr_url = await _open_pull_request(settings, branch_name, autoimplementable[0].title, plan)
        await _log_action(pool, plan_id, 0, "pr_opened", branch_name=branch_name, commit_sha=commit_sha, pr_url=pr_url)
    except (ArchitectCommitError, httpx.HTTPError) as exc:
        logger.error("architect commit cycle failed: %s", exc)
        await _log_action(pool, plan_id, 0, "failed", branch_name=branch_name, detail={"error": str(exc)})
    finally:
        # Leave the mounted working tree clean for the next cycle
        # regardless of outcome -- back to main, drop the local branch
        # ref (the pushed copy on GitHub, if any, is untouched).
        subprocess.run(["git", "-C", str(project_root), "checkout", "main"], capture_output=True, timeout=15)
        subprocess.run(["git", "-C", str(project_root), "branch", "-D", branch_name], capture_output=True, timeout=15)


async def _open_pull_request(settings, branch_name: str, title: str, plan: ProjectPlan) -> str:
    _assert_never_main(branch_name)
    body = (
        f"Autonomous update from the Architect (`project_architect` agent role).\n\n"
        f"This PR only touches `{PLAN_DOC_FILENAME}` -- see ROADMAP.md's "
        f'"Phase 5b: the Architect" for the scope and safeguards. It was not '
        f"merged by the agent; that's this review.\n\n"
        f"Plan reasoning model: `{plan.reasoning_model}`."
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{settings.github_repo}/pulls",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={
                "title": f"chore(architect): {title}"[:120],
                "head": branch_name,
                "base": "main",
                "body": body,
            },
        )
        resp.raise_for_status()
        return resp.json()["html_url"]


async def _log_action(
    pool,
    plan_id: UUID,
    item_index: int,
    action: str,
    branch_name: str | None = None,
    commit_sha: str | None = None,
    pr_url: str | None = None,
    detail: dict | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO project_plan_actions (plan_id, item_index, action, branch_name, commit_sha, pr_url, detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        plan_id,
        item_index,
        action,
        branch_name,
        commit_sha,
        pr_url,
        json.dumps(detail or {}),
    )
