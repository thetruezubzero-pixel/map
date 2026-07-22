"""Phase 5c: widening safe_to_autoimplement beyond PROJECT_PLAN.md --
see ROADMAP.md "Phase 5c: widening safe_to_autoimplement" for the full,
written scope decision this implements (Phase 5b's own text already
anticipated this: "the architecture doesn't prevent widening that
allowlist ... but that widening is a future, separate decision").

Generalizes architect_committer.py's branch+commit+push+PR mechanism so
any agent (not just project_architect) can propose a file change, with
the same structural guarantees (never pushes to main, every step
logged to an append-only table) plus one new capability:
auto-merge, gated on a real, non-model-controlled check, not "the AI
decides it feels confident":

  1. `_assert_file_allowlisted` -- a hard-coded, code-enforced allowlist.
     Only markdown docs and `.env.example` templates are ever eligible,
     regardless of what any agent claims about safety. Source code, CI
     config, migrations, Dockerfiles, and CLAUDE.md/ROADMAP.md
     themselves (human-owned, same as project_architect's existing
     PROJECT_PLAN.md-only rule) are never reachable through this path,
     full stop -- this function raises before any git operation happens.
  2. `effective_score = confidence * agent_weight` -- confidence is the
     proposing agent's own self-reported confidence in this specific
     change; agent_weight is that agent's *learned, tracked* reliability
     from agent_registry.current_weight (the same credit_assigner-driven
     weight every swarm role already earns from real task outcomes, not
     a number the agent can just assert). Only when this product clears
     AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD, *and* the agent has completed
     at least AGENT_AUTO_MERGE_MIN_TRACK_RECORD prior cycles (see point
     4), and only when AGENT_AUTO_MERGE_ENABLED is explicitly on (default
     off), does the PR get merged automatically -- otherwise it stops at
     "PR opened," same as project_architect's existing PROJECT_PLAN.md
     flow.
  3. Auto-merge still means "the PR that was just opened gets merged via
     the GitHub API" -- it is never a direct push to main.
     `_assert_never_main` (reused from architect_committer.py) still
     structurally forbids that regardless of confidence.
  4. `agent_total_tasks >= AGENT_AUTO_MERGE_MIN_TRACK_RECORD` --
     confirmed live that a brand-new agent's current_weight starts at
     1.0 (agent_registry's neutral prior, not zero), so effective_score
     alone could clear the threshold on an agent's very first cycle with
     zero actual track record, undermining the "not a number the agent
     can just assert" framing in point 2. Requiring a minimum number of
     completed cycles first closes that gap.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.agent_swarm.services.architect_committer import (
    GIT_WORKING_TREE_LOCK,
    ArchitectCommitError,
    _assert_never_main,
    _cleanup_working_tree,
    _run_git,
    _slugify,
)
from app.config import get_settings

logger = logging.getLogger("aether.agent_swarm.change_proposer")

# Hard-coded, not model-controlled. Any doc file is eligible EXCEPT the
# two that stay human-owned per the existing Phase 5b norm.
_HUMAN_OWNED_FILES = {"CLAUDE.md", "ROADMAP.md"}


class ChangeProposalError(RuntimeError):
    pass


_HUMAN_OWNED_FILES_LOWER = {f.lower() for f in _HUMAN_OWNED_FILES}


def _assert_file_allowlisted(file_path: str) -> None:
    """The actual security boundary for this whole feature -- called
    before any git operation, so a bug or a manipulated agent output
    upstream cannot result in a write outside this allowlist. Never
    trusts safe_to_autoimplement/category flags from agent output alone
    (same "defense in depth, don't trust the caller got it right"
    principle project_architect.py's _parse already uses).

    Compares case-insensitively -- confirmed live that the original,
    case-sensitive version let a case variant like "claude.md" or
    "docs/Claude.MD" slip past the CLAUDE.md/ROADMAP.md block entirely
    (same bug class `_assert_never_main` in architect_committer.py
    already guards against for branch names via its own `.lower()`,
    which this was inconsistent with before this fix). On a
    case-insensitive filesystem (default macOS/Windows) that would even
    resolve to the *same file* as the real CLAUDE.md/ROADMAP.md."""
    normalized = file_path.strip().lstrip("/")

    if not normalized or ".." in normalized.split("/"):
        raise ChangeProposalError(f"invalid or path-traversal file_path rejected: {file_path!r}")

    basename = normalized.rsplit("/", 1)[-1]
    basename_lower = basename.lower()

    if basename_lower in _HUMAN_OWNED_FILES_LOWER:
        raise ChangeProposalError(f"{file_path!r} is human-owned (CLAUDE.md/ROADMAP.md), never agent-writable")

    if basename_lower.endswith(".md") or basename_lower.endswith(".env.example"):
        return

    raise ChangeProposalError(
        f"{file_path!r} is outside the allowlist -- only markdown docs and .env.example "
        "templates are eligible; never source code, CI config, migrations, or Dockerfiles"
    )


def _assert_resolves_within_project_root(project_root: Path, file_path: str) -> Path:
    """Defense in depth beyond the string-level ".." check above: resolve
    symlinks in any existing parent directories and confirm the final
    real path still lands inside project_root. Without this, a symlinked
    directory component (unlikely in this repo today, but not something
    the string check alone rules out) could make `write_text` land
    outside the checked-out tree despite file_path itself looking benign."""
    target = (project_root / file_path).resolve()
    root = project_root.resolve()
    if target != root and root not in target.parents:
        raise ChangeProposalError(f"resolved path {target} escapes project root {root}")
    return target


async def propose_change(
    pool,
    *,
    agent_name: str,
    role: str,
    file_path: str,
    new_content: str,
    title: str,
    rationale: str,
    confidence: float,
    agent_weight: float = 1.0,
    agent_total_tasks: int = 0,
) -> dict:
    """Propose a change to one allowlisted file. Returns a dict with at
    least an `action` key (skipped/failed/pr_opened/merged) -- never
    raises for expected conditions (not allowlisted, no token, disabled),
    matching sync_project_plan_doc's "clean skip, not a crash" pattern.

    `agent_total_tasks` (agent_registry.total_tasks for the proposing
    agent) gates auto-merge alongside effective_score -- confirmed live
    that a brand-new agent starts at current_weight=1.0 (the neutral
    prior, not zero), so score alone could clear the threshold on an
    agent's very first cycle with no real track record. Requiring
    agent_auto_merge_min_track_record completed cycles first closes that
    gap without needing a whole new reward-tracking mechanism."""
    settings = get_settings()
    effective_score = confidence * agent_weight
    has_track_record = agent_total_tasks >= settings.agent_auto_merge_min_track_record
    auto_merge_eligible = has_track_record and effective_score >= settings.agent_auto_merge_confidence_threshold

    async def log(action: str, **kw) -> None:
        await _log_proposal(
            pool,
            agent_name=agent_name,
            role=role,
            file_path=file_path,
            title=title,
            rationale=rationale,
            confidence=confidence,
            agent_weight=agent_weight,
            effective_score=effective_score,
            auto_merge_eligible=auto_merge_eligible,
            action=action,
            **kw,
        )

    try:
        _assert_file_allowlisted(file_path)
    except ChangeProposalError as exc:
        await log("skipped", detail={"reason": str(exc)})
        return {"action": "skipped", "reason": str(exc)}

    if not settings.architect_auto_commit_enabled:
        await log("skipped", detail={"reason": "ARCHITECT_AUTO_COMMIT_ENABLED is false"})
        return {"action": "skipped", "reason": "ARCHITECT_AUTO_COMMIT_ENABLED is false"}

    if not settings.github_token:
        await log("skipped", detail={"reason": "GITHUB_TOKEN not configured"})
        return {"action": "skipped", "reason": "GITHUB_TOKEN not configured"}

    project_root = Path(settings.project_root)
    if not (project_root / ".git").exists():
        await log("failed", detail={"reason": f"{project_root} is not a git working tree"})
        return {"action": "failed", "reason": f"{project_root} is not a git working tree"}

    slug = _slugify(title)
    branch_name = f"agent/{role}/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{slug}"
    _assert_never_main(branch_name)

    async with GIT_WORKING_TREE_LOCK:
        try:
            await _run_git(project_root, "fetch", "origin", "main")
            await _run_git(project_root, "checkout", "-B", branch_name, "origin/main")
            await log("branch_created", branch_name=branch_name)

            target_path = _assert_resolves_within_project_root(project_root, file_path)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(new_content, encoding="utf-8")
            await _run_git(project_root, "add", file_path)
            await _run_git(
                project_root,
                "-c", "user.name=Aether Agent",
                "-c", "user.email=agent@aether-sovereign.local",
                "commit",
                "-m",
                f"chore({role}): {title}\n\nProposed autonomously -- see ROADMAP.md "
                '"Phase 5c: widening safe_to_autoimplement".',
            )
            commit_sha = await _run_git(project_root, "rev-parse", "HEAD")
            await log("committed", branch_name=branch_name, commit_sha=commit_sha)

            _assert_never_main(branch_name)
            auth_header = base64.b64encode(f"x-access-token:{settings.github_token}".encode()).decode()
            await _run_git(
                project_root,
                "-c", f"http.extraHeader=Authorization: Basic {auth_header}",
                "push", f"https://github.com/{settings.github_repo}.git", f"{branch_name}:{branch_name}",
                redact=settings.github_token,
            )
            await log("pushed", branch_name=branch_name, commit_sha=commit_sha)

            body = (
                f"Autonomous proposal from the `{agent_name}` agent (`{role}` role).\n\n"
                f"{rationale}\n\n"
                f"Confidence {confidence:.2f} x agent weight {agent_weight:.2f} = effective score "
                f"{effective_score:.2f} (auto-merge threshold: {settings.agent_auto_merge_confidence_threshold:.2f}).\n\n"
                'See ROADMAP.md "Phase 5c: widening safe_to_autoimplement" for the allowlist and '
                "safeguards governing what this pipeline may touch."
            )
            pr_url, pr_number = await _open_pull_request(settings, branch_name, f"chore({role}): {title}"[:120], body)
            await log("pr_opened", branch_name=branch_name, commit_sha=commit_sha, pr_url=pr_url)

            if auto_merge_eligible and settings.agent_auto_merge_enabled:
                await _merge_pull_request(settings, pr_number)
                await log("merged", branch_name=branch_name, commit_sha=commit_sha, pr_url=pr_url)
                return {"action": "merged", "pr_url": pr_url}

            return {"action": "pr_opened", "pr_url": pr_url}
        except (ArchitectCommitError, ChangeProposalError, httpx.HTTPError) as exc:
            logger.error("change proposal failed: %s", exc)
            await log("failed", branch_name=branch_name, detail={"error": str(exc)})
            return {"action": "failed", "reason": str(exc)}
        finally:
            await asyncio.to_thread(_cleanup_working_tree, project_root, branch_name)


async def _open_pull_request(settings, branch_name: str, title: str, body: str) -> tuple[str, int]:
    _assert_never_main(branch_name)
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{settings.github_repo}/pulls",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"title": title, "head": branch_name, "base": "main", "body": body},
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            return data["html_url"], data["number"]
        except KeyError as exc:
            # A readiness review found this indexed straight into the
            # response with no guard -- a malformed/unexpected GitHub API
            # body raised a raw KeyError instead of the ChangeProposalError
            # propose_change's own except clause already catches and logs.
            raise ChangeProposalError(f"GitHub PR-open response missing html_url/number: {data!r}") from exc


async def _merge_pull_request(settings, pr_number: int) -> None:
    """The one operation this module can do that architect_committer.py
    never could: merge a PR without a human clicking the button. Still
    goes through GitHub's normal merge API against a real PR -- not a
    direct push to main, and only ever reached for a PR whose file
    already passed _assert_file_allowlisted and whose effective_score
    already cleared the confidence*weight threshold."""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(
            f"https://api.github.com/repos/{settings.github_repo}/pulls/{pr_number}/merge",
            headers={
                "Authorization": f"Bearer {settings.github_token}",
                "Accept": "application/vnd.github+json",
            },
            json={"merge_method": "squash"},
        )
        resp.raise_for_status()


async def _log_proposal(
    pool,
    *,
    agent_name: str,
    role: str,
    file_path: str,
    title: str,
    rationale: str,
    confidence: float,
    agent_weight: float,
    effective_score: float,
    auto_merge_eligible: bool,
    action: str,
    branch_name: str | None = None,
    commit_sha: str | None = None,
    pr_url: str | None = None,
    detail: dict | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO agent_change_proposals
            (agent_name, role, file_path, title, rationale, confidence, agent_weight,
             effective_score, auto_merge_eligible, action, branch_name, commit_sha, pr_url, detail)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        """,
        agent_name,
        role,
        file_path,
        title,
        rationale,
        confidence,
        agent_weight,
        effective_score,
        auto_merge_eligible,
        action,
        branch_name,
        commit_sha,
        pr_url,
        json.dumps(detail or {}),
    )
