"""Keeps scripts/repo_health_check.py (the dependency-free CI gate) in sync
with app/agent_swarm/introspection (the Architect's read-only scan), and
sanity-checks the standalone script's own logic. The two implementations
exist on purpose -- one is stdlib-only so CI runs it without installing the
python-api's deps -- but their security baselines must never drift."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SCRIPT = _REPO_ROOT / "scripts" / "repo_health_check.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("repo_health_check", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_script_file_exists():
    assert _SCRIPT.is_file(), "scripts/repo_health_check.py must exist for the CI gate"


def test_action_baseline_matches_introspection():
    from app.agent_swarm.introspection import _MIN_ACTION_MAJOR

    script = _load_script()
    assert script.MIN_ACTION_MAJOR == _MIN_ACTION_MAJOR, (
        "scripts/repo_health_check.py MIN_ACTION_MAJOR drifted from "
        "introspection._MIN_ACTION_MAJOR -- update both together"
    )


def test_secret_matcher_matches_introspection():
    from app.agent_swarm.introspection import _looks_like_committed_secret

    script = _load_script()
    for path in [".env", ".env.local", "certs/server.key", "id_rsa", "secrets.yml",
                 ".env.example", ".claude/hooks/secret-scrub.sh", "README.md", "app/main.py"]:
        assert script.looks_like_committed_secret(path) == _looks_like_committed_secret(path), path


def test_script_scan_flags_deprecated_action(tmp_path):
    script = _load_script()
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text("steps:\n  - uses: actions/upload-artifact@v3\n", encoding="utf-8")
    result = script.scan(tmp_path)
    assert any(d["action"] == "actions/upload-artifact@v3" for d in result["deprecated_actions"])


def test_script_scan_clean_repo(tmp_path):
    script = _load_script()
    result = script.scan(tmp_path)
    assert result == {"workflow_count": 0, "deprecated_actions": [], "committed_secret_files": []}


def test_real_repo_is_clean():
    """The gate must currently pass on this repo -- we already fixed the
    deprecated actions and commit no secrets. If this fails, the gate is
    doing its job and something regressed."""
    script = _load_script()
    result = script.scan(_REPO_ROOT)
    assert result["deprecated_actions"] == [], result["deprecated_actions"]
    assert result["committed_secret_files"] == [], result["committed_secret_files"]
