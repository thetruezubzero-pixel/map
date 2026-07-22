import asyncio
import subprocess
from uuid import uuid4

import pytest

from app import config
from app.agent_swarm.services import architect_committer as ac
from app.models import PlanItemCategory, ProjectPlan, ProjectPlanItem


@pytest.mark.parametrize("branch", ["main", "Main", "MAIN", "master", " main ", "  Master  "])
def test_assert_never_main_rejects_protected_branches(branch):
    with pytest.raises(ac.ArchitectCommitError):
        ac._assert_never_main(branch)


def test_assert_never_main_allows_real_branch_names():
    ac._assert_never_main("agent/architect/20260101-update-plan")  # must not raise


def test_slugify_produces_safe_branch_fragment():
    assert ac._slugify("Wire apply_decay() to a scheduled job!") == "wire-apply-decay-to-a-scheduled-job"
    assert ac._slugify("") == "update"
    assert len(ac._slugify("x" * 200)) <= 40


def test_render_plan_doc_includes_every_item_and_flags_autoimplementable():
    plan = ProjectPlan(
        items=[
            ProjectPlanItem(
                title="Update plan doc",
                rationale="stale",
                category=PlanItemCategory.project_plan_doc,
                safe_to_autoimplement=True,
            ),
            ProjectPlanItem(
                title="Wire apply_decay",
                rationale="zero callers",
                category=PlanItemCategory.code_change,
                safe_to_autoimplement=False,
            ),
        ],
        reasoning_model="test-model",
        notes="some notes",
    )
    doc = ac._render_plan_doc(plan, "test snapshot summary")
    assert "Update plan doc" in doc
    assert "Wire apply_decay" in doc
    assert "(auto-implementable)" in doc  # only the first item should get this flag
    assert doc.count("(auto-implementable)") == 1
    assert "some notes" in doc
    assert "test snapshot summary" in doc
    # The architect never merges its own PRs -- the doc it writes about
    # itself must say so, not just the code that enforces it.
    assert "never merges" in doc.lower()


class _LoggingPool:
    async def execute(self, *a, **k):
        pass


def test_sync_project_plan_doc_returns_skipped_action_when_nothing_autoimplementable():
    """A readiness review found this function used to return None on every
    path (routers/architect.py never used the return value) -- now that
    architect.py wires a real credit_assigner reward to this outcome, every
    return path needs an actual {"action": ...} dict, not just a log row."""
    plan = ProjectPlan(
        items=[
            ProjectPlanItem(
                title="Some code change",
                rationale="not the doc flow",
                category=PlanItemCategory.code_change,
                safe_to_autoimplement=False,
            ),
        ],
        reasoning_model="test-model",
    )
    result = asyncio.run(ac.sync_project_plan_doc(_LoggingPool(), uuid4(), plan, "summary"))
    assert result == {"action": "skipped", "reason": "no safe_to_autoimplement project_plan_doc item this cycle"}


def test_sync_project_plan_doc_returns_skipped_action_when_auto_commit_disabled(monkeypatch):
    monkeypatch.setenv("ARCHITECT_AUTO_COMMIT_ENABLED", "false")
    config.get_settings.cache_clear()
    plan = ProjectPlan(
        items=[
            ProjectPlanItem(
                title="Update plan doc",
                rationale="stale",
                category=PlanItemCategory.project_plan_doc,
                safe_to_autoimplement=True,
            ),
        ],
        reasoning_model="test-model",
    )
    result = asyncio.run(ac.sync_project_plan_doc(_LoggingPool(), uuid4(), plan, "summary"))
    assert result == {"action": "skipped", "reason": "ARCHITECT_AUTO_COMMIT_ENABLED is false"}
    config.get_settings.cache_clear()


def test_run_git_converts_timeout_into_architect_commit_error(monkeypatch, tmp_path):
    """A readiness review found a hung `fetch`/`push` raised a raw
    subprocess.TimeoutExpired straight out of _run_git, uncaught by either
    this module's or change_proposer.py's except clauses (both scoped to
    ArchitectCommitError/ChangeProposalError/httpx.HTTPError) -- turning a
    slow network call into an unhandled 500 instead of a clean 'failed'
    outcome."""

    def _fake_run(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git fetch", timeout=30)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    with pytest.raises(ac.ArchitectCommitError, match="timed out"):
        asyncio.run(ac._run_git(tmp_path, "fetch", "origin", "main"))


def test_cleanup_working_tree_never_raises_on_a_failing_git_command(tmp_path):
    """A readiness review found the original inline cleanup neither checked
    subprocess.run's returncode (silently swallowing a real failure with no
    signal at all) nor caught a TimeoutExpired (which would propagate out
    of the finally block and replace whatever the try block had already
    successfully returned). Against a tmp_path that isn't a real git repo,
    every git command here genuinely fails -- this must still return
    cleanly, not raise."""
    ac._cleanup_working_tree(tmp_path, "some-branch-name")  # must not raise


def test_cleanup_working_tree_never_raises_when_git_itself_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd="git", timeout=15)),
    )
    ac._cleanup_working_tree(tmp_path, "some-branch-name")  # must not raise
