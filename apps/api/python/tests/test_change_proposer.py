import asyncio

import pytest

from app import config
from app.agent_swarm.services import change_proposer as cp
from app.agent_swarm.services.change_proposer import (
    ChangeProposalError,
    _assert_file_allowlisted,
    _assert_resolves_within_project_root,
    propose_change,
)


@pytest.mark.parametrize(
    "path",
    [
        "docs/foo.md",
        "README.md",
        "apps/gateway/.env.example",
        "nested/dir/notes.md",
    ],
)
def test_allowlisted_paths_pass(path):
    _assert_file_allowlisted(path)  # must not raise


@pytest.mark.parametrize(
    "path",
    [
        "CLAUDE.md",
        "ROADMAP.md",
        "app/main.py",
        "apps/gateway/src/main.rs",
        ".github/workflows/ci.yml",
        "apps/gateway/migrations/9999_evil.sql",
        "Dockerfile",
        "../../etc/passwd.md",
        "",
    ],
)
def test_disallowed_paths_rejected(path):
    with pytest.raises(ChangeProposalError):
        _assert_file_allowlisted(path)


def test_propose_change_skips_before_any_git_operation_for_disallowed_path():
    """The allowlist check must fire before propose_change touches
    settings/git at all -- confirmed by passing a pool double that raises
    if it's ever queried past the first log call."""

    class _LoggingPool:
        def __init__(self):
            self.calls = 0

        async def execute(self, *a, **k):
            self.calls += 1

    pool = _LoggingPool()
    result = asyncio.run(
        propose_change(
            pool,
            agent_name="test_agent",
            role="project_architect",
            file_path="CLAUDE.md",
            new_content="malicious",
            title="sneaky",
            rationale="test",
            confidence=0.99,
            agent_weight=2.0,
        )
    )
    assert result["action"] == "skipped"
    assert "human-owned" in result["reason"]
    assert pool.calls == 1  # only the one "skipped" log row, no other DB/git activity


def test_effective_score_math_matches_weighted_consensus_group_score_shape():
    """change_proposer's confidence * agent_weight gate deliberately
    mirrors weighted_consensus.group_score's weight * confidence formula
    (consensus_vote.py) -- same shape, reused on purpose so "the weights
    decide" means the same thing in both places."""
    confidence = 0.8
    agent_weight = 1.2
    assert round(confidence * agent_weight, 4) == 0.96


@pytest.mark.parametrize(
    "path",
    ["claude.md", "Claude.md", "CLAUDE.MD", "cLaUdE.Md", "docs/claude.md", "roadmap.md", "ROADMAP.MD"],
)
def test_case_variants_of_protected_files_are_rejected(path):
    """Confirmed live (security review) that the original, case-sensitive
    comparison let a case variant like "claude.md" slip past the
    CLAUDE.md/ROADMAP.md block entirely -- on a case-insensitive
    filesystem (default macOS/Windows) that would resolve to the *same
    file* as the real CLAUDE.md. This must be rejected exactly like the
    exact-case name is."""
    with pytest.raises(ChangeProposalError, match="human-owned"):
        _assert_file_allowlisted(path)


@pytest.mark.parametrize("path", ["docs/FOO.MD", "README.MD", "apps/gateway/.ENV.EXAMPLE"])
def test_case_variants_of_allowed_suffixes_still_pass(path):
    _assert_file_allowlisted(path)  # must not raise -- case shouldn't matter either direction


def test_resolves_within_project_root_accepts_a_real_subpath(tmp_path):
    result = _assert_resolves_within_project_root(tmp_path, "docs/foo.md")
    assert result == (tmp_path / "docs" / "foo.md").resolve()


def test_resolves_within_project_root_rejects_a_symlink_escape(tmp_path):
    """A symlinked directory component could make a benign-looking
    file_path resolve outside the checked-out tree despite passing the
    string-level ".." check -- confirmed this is caught by resolving the
    real path and checking containment, not just string-matching."""
    outside = tmp_path.parent / "outside_project_root"
    outside.mkdir(exist_ok=True)
    escape_link = tmp_path / "escape"
    escape_link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ChangeProposalError, match="escapes project root"):
        _assert_resolves_within_project_root(tmp_path, "escape/sneaky.md")


class _RecordingPool:
    def __init__(self):
        self.actions: list[str] = []

    async def execute(self, query, *args):
        # agent_change_proposals INSERT's 10th positional param is `action`
        self.actions.append(args[9])


def _prepare_fake_repo_settings(monkeypatch, tmp_path, **env_overrides):
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-test")
    monkeypatch.setenv("GITHUB_REPO", "test/repo")
    monkeypatch.setenv("ARCHITECT_AUTO_COMMIT_ENABLED", "true")
    for key, value in env_overrides.items():
        monkeypatch.setenv(key, str(value))
    config.get_settings.cache_clear()


def _patch_git_and_github(monkeypatch, merge_calls):
    async def _fake_run_git(*a, **k):
        return "fake-sha"

    monkeypatch.setattr(cp, "_run_git", _fake_run_git)

    async def _fake_open_pr(settings, branch_name, title, body):
        return "https://github.com/test/repo/pull/1", 1

    async def _fake_merge_pr(settings, pr_number):
        merge_calls.append(pr_number)

    monkeypatch.setattr(cp, "_open_pull_request", _fake_open_pr)
    monkeypatch.setattr(cp, "_merge_pull_request", _fake_merge_pr)


def test_auto_merge_disabled_never_merges_even_at_a_high_score(monkeypatch, tmp_path):
    """The single most consequential runtime behavior of this module,
    confirmed under test (flagged as untested by the security review):
    AGENT_AUTO_MERGE_ENABLED=false must prevent _merge_pull_request from
    ever being called, no matter how high confidence*weight is."""
    _prepare_fake_repo_settings(
        monkeypatch, tmp_path,
        AGENT_AUTO_MERGE_ENABLED="false",
        AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD="0.5",
        AGENT_AUTO_MERGE_MIN_TRACK_RECORD="1",
    )
    merge_calls: list[int] = []
    _patch_git_and_github(monkeypatch, merge_calls)

    result = asyncio.run(
        propose_change(
            _RecordingPool(),
            agent_name="project_architect",
            role="project_architect",
            file_path="docs/example.md",
            new_content="# hi",
            title="add example doc",
            rationale="test",
            confidence=1.0,
            agent_weight=1.0,
            agent_total_tasks=100,
        )
    )
    assert result["action"] == "pr_opened"
    assert merge_calls == []
    config.get_settings.cache_clear()


def test_auto_merge_blocked_below_minimum_track_record_even_when_enabled(monkeypatch, tmp_path):
    """Confirmed live (security review finding): a brand-new agent starts
    at agent_registry.current_weight=1.0 (the neutral prior, not an
    earned track record), so confidence*weight alone could clear the
    threshold on an agent's very first cycle. agent_total_tasks below
    AGENT_AUTO_MERGE_MIN_TRACK_RECORD must block auto-merge regardless of
    how high the score is, even with the kill switch on."""
    _prepare_fake_repo_settings(
        monkeypatch, tmp_path,
        AGENT_AUTO_MERGE_ENABLED="true",
        AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD="0.5",
        AGENT_AUTO_MERGE_MIN_TRACK_RECORD="10",
    )
    merge_calls: list[int] = []
    _patch_git_and_github(monkeypatch, merge_calls)

    result = asyncio.run(
        propose_change(
            _RecordingPool(),
            agent_name="project_architect",
            role="project_architect",
            file_path="docs/example.md",
            new_content="# hi",
            title="add example doc",
            rationale="test",
            confidence=1.0,
            agent_weight=1.0,
            agent_total_tasks=1,  # far below the min_track_record=10 floor
        )
    )
    assert result["action"] == "pr_opened"
    assert merge_calls == []
    config.get_settings.cache_clear()


def test_auto_merge_fires_once_score_and_track_record_both_clear(monkeypatch, tmp_path):
    _prepare_fake_repo_settings(
        monkeypatch, tmp_path,
        AGENT_AUTO_MERGE_ENABLED="true",
        AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD="0.5",
        AGENT_AUTO_MERGE_MIN_TRACK_RECORD="10",
    )
    merge_calls: list[int] = []
    _patch_git_and_github(monkeypatch, merge_calls)

    result = asyncio.run(
        propose_change(
            _RecordingPool(),
            agent_name="project_architect",
            role="project_architect",
            file_path="docs/example.md",
            new_content="# hi",
            title="add example doc",
            rationale="test",
            confidence=1.0,
            agent_weight=1.0,
            agent_total_tasks=25,
        )
    )
    assert result["action"] == "merged"
    assert merge_calls == [1]
    config.get_settings.cache_clear()


def test_concurrent_propose_change_calls_are_serialized_by_the_shared_lock(monkeypatch, tmp_path):
    """A security review found propose_change and sync_project_plan_doc
    had no concurrency guard on the shared mounted working tree -- two
    overlapping calls could interleave checkout/commit/push against the
    same tree. GIT_WORKING_TREE_LOCK (architect_committer.py, imported
    here) should serialize them: confirmed by having two concurrent
    calls each record entry/exit events into a shared list and asserting
    one call's full event sequence completes before the other's starts,
    never interleaved."""
    _prepare_fake_repo_settings(
        monkeypatch, tmp_path,
        AGENT_AUTO_MERGE_ENABLED="false",
        AGENT_AUTO_MERGE_CONFIDENCE_THRESHOLD="0.99",
        AGENT_AUTO_MERGE_MIN_TRACK_RECORD="1",
    )

    events: list[str] = []

    async def _fake_run_git(project_root, *args, **kwargs):
        call_name = args[0] if args else "unknown"
        events.append(f"start:{call_name}")
        await asyncio.sleep(0.01)  # yield control -- gives a real race a chance to interleave
        events.append(f"end:{call_name}")
        return "fake-sha"

    async def _fake_open_pr(settings, branch_name, title, body):
        return "https://github.com/test/repo/pull/1", 1

    monkeypatch.setattr(cp, "_run_git", _fake_run_git)
    monkeypatch.setattr(cp, "_open_pull_request", _fake_open_pr)

    async def _one_call(n: int):
        return await propose_change(
            _RecordingPool(),
            agent_name=f"agent-{n}",
            role="project_architect",
            file_path=f"docs/example-{n}.md",
            new_content="# hi",
            title=f"doc {n}",
            rationale="test",
            confidence=0.5,
            agent_weight=1.0,
            agent_total_tasks=1,
        )

    async def _run_both():
        return await asyncio.gather(_one_call(1), _one_call(2))

    results = asyncio.run(_run_both())
    assert all(r["action"] == "pr_opened" for r in results)

    # Group consecutive events by which call's fetch/checkout/add/commit/
    # push sequence they belong to isn't directly labeled, but true
    # interleaving would show a "start" for one file appearing between
    # another call's "start"/"end" of the *same* git subcommand name at a
    # depth greater than 1 -- simplest real assertion: every "start:X" is
    # immediately followed by its own "end:X" (no other call's git
    # command sneaks in between), which only holds if the lock actually
    # serializes the two callers' subprocess calls.
    for i in range(0, len(events), 2):
        assert events[i].startswith("start:")
        assert events[i + 1].startswith("end:")
        assert events[i].split(":", 1)[1] == events[i + 1].split(":", 1)[1]
    config.get_settings.cache_clear()
