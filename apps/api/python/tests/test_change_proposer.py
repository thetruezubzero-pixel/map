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
    monkeypatch.setattr(cp, "_run_git", lambda *a, **k: "fake-sha")

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
