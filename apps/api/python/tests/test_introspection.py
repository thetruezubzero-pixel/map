import pytest

from app.agent_swarm.introspection import _is_source_readable, _read_full_source_tree, summarize_snapshot


def _base_snapshot(swarm_health):
    return {
        "db": {"entities_by_source_type": [], "agents_by_role_level": []},
        "swarm_health": swarm_health,
    }


def test_summarize_snapshot_notes_ungraduated_roles():
    snapshot = _base_snapshot(
        [
            {"role": "query_analyzer", "level": "amateur", "count": 2, "graduated_amateurs": 0},
            {"role": "result_synthesizer", "level": "amateur", "count": 2, "graduated_amateurs": 1},
        ]
    )
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations yet in: query_analyzer" in summary
    assert "result_synthesizer" not in summary.split("no amateur graduations yet in:")[1]


def test_summarize_snapshot_omits_note_when_no_amateurs_seeded():
    # count=0 means the role's amateurs were never seeded (e.g. all
    # promoted away) -- there's no shadow-training gap to flag, so the
    # note shouldn't fire on an empty roster the same way it would on a
    # populated-but-ungraduated one.
    snapshot = _base_snapshot([{"role": "query_analyzer", "level": "amateur", "count": 0, "graduated_amateurs": 0}])
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations" not in summary


def test_summarize_snapshot_omits_note_when_all_roles_graduated():
    snapshot = _base_snapshot(
        [
            {"role": "query_analyzer", "level": "amateur", "count": 2, "graduated_amateurs": 2},
            {"role": "result_synthesizer", "level": "amateur", "count": 2, "graduated_amateurs": 1},
        ]
    )
    summary = summarize_snapshot(snapshot)
    assert "no amateur graduations" not in summary


def test_summarize_snapshot_notes_full_source_visibility_and_truncation():
    snapshot = _base_snapshot([])
    snapshot["full_source_tree"] = {"total_files": 42, "truncated": False}
    summary = summarize_snapshot(snapshot)
    assert "full source visible: 42 files" in summary
    assert "truncated" not in summary

    snapshot["full_source_tree"] = {"total_files": 10, "truncated": True}
    summary = summarize_snapshot(snapshot)
    assert "truncated" in summary


def test_summarize_snapshot_omits_source_note_when_visibility_disabled():
    snapshot = _base_snapshot([])  # no full_source_tree key at all -- feature is off
    summary = summarize_snapshot(snapshot)
    assert "full source visible" not in summary


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "apps/api/python/some_secret.py",
        "config/credentials.yml",
        "config/password_reset.md",
        "certs/server.key",
        "certs/server.pem",
        "node_modules/pkg/index.py",
        ".git/config",
        "target/debug/build.rs",
        "docs/foo.txt",  # not a recognized source suffix at all
    ],
)
def test_is_source_readable_excludes_secret_shaped_and_denylisted_paths(path, tmp_path):
    from pathlib import Path

    assert _is_source_readable(Path(path)) is False


@pytest.mark.parametrize(
    "path",
    [
        ".ENV",
        "Secret.py",
        "config/CREDENTIALS.yml",
        "config/Password_Reset.MD",
        "certs/Server.KEY",
        "certs/Server.PEM",
        "NODE_MODULES/pkg/index.py",
        ".GIT/config",
    ],
)
def test_is_source_readable_case_insensitive_rejection(path):
    """Confirmed live (security review) that this repo's own
    change_proposer.py denylist had a case-sensitivity bypass fixed
    earlier this session -- this locks in that introspection.py's
    (separately implemented) denylist was already case-insensitive by
    construction (name_lower/parts_lower everywhere) and stays that
    way."""
    from pathlib import Path

    assert _is_source_readable(Path(path)) is False


@pytest.mark.parametrize(
    "path",
    [
        "secrets/db.yml",
        "config/credentials/settings.yml",
        "infra/password_vault/loader.py",
        "SECRETS/nested/deep/file.py",
    ],
)
def test_is_source_readable_rejects_secret_shaped_directory_names_not_just_filenames(path):
    """Confirmed by a security review: the original version only checked
    the leaf filename against secret/credential/password, so
    `secrets/db.yml` (an innocuous filename inside a secret-shaped
    directory) slipped through. Now checks every path component."""
    from pathlib import Path

    assert _is_source_readable(Path(path)) is False


@pytest.mark.parametrize("path", ["app/main.py", "src/lib.rs", "src/App.tsx", "README.md", "config.toml"])
def test_is_source_readable_accepts_real_source_files(path):
    from pathlib import Path

    assert _is_source_readable(Path(path)) is True


def test_read_full_source_tree_excludes_secrets_and_reads_real_content(tmp_path):
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("REAL_SECRET=abc123\n", encoding="utf-8")
    (tmp_path / "credentials.yml").write_text("api_key: abc123\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.py").write_text("noise\n", encoding="utf-8")

    result = _read_full_source_tree(tmp_path, max_total_chars=1_000_000)

    paths = {f["path"] for f in result["files"]}
    assert "app.py" in paths
    assert ".env" not in paths
    assert "credentials.yml" not in paths
    assert not any("node_modules" in p for p in paths)
    assert result["truncated"] is False

    app_entry = next(f for f in result["files"] if f["path"] == "app.py")
    assert app_entry["content"] == "print('hello')\n"
    assert app_entry["line_count"] == 2


def test_read_full_source_tree_sets_truncated_flag_when_cap_is_hit(tmp_path):
    (tmp_path / "big.py").write_text("x" * 2000, encoding="utf-8")
    result = _read_full_source_tree(tmp_path, max_total_chars=100)
    assert result["truncated"] is True
    assert result["files"] == []  # never includes a partial/truncated file


def test_read_full_source_tree_missing_project_root_degrades_cleanly(tmp_path):
    missing = tmp_path / "does-not-exist"
    result = _read_full_source_tree(missing, max_total_chars=1_000_000)
    assert result == {"files": [], "total_files": 0, "total_chars": 0, "truncated": False}


def test_read_full_source_tree_skips_a_symlink_that_escapes_project_root(tmp_path):
    """Confirmed by a security review: is_file()/read_text() both follow
    symlinks, so a symlinked path pointing outside project_root would
    have its target's content read and embedded in the snapshot despite
    looking like an ordinary in-repo file. This must be skipped, not
    silently included."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text("print('safe')\n", encoding="utf-8")

    outside = tmp_path / "outside_project_root"
    outside.mkdir()
    (outside / "leaked.py").write_text("print('should not be readable')\n", encoding="utf-8")
    (project_root / "escape.py").symlink_to(outside / "leaked.py")

    result = _read_full_source_tree(project_root, max_total_chars=1_000_000)

    paths = {f["path"] for f in result["files"]}
    assert "app.py" in paths
    assert "escape.py" not in paths
    assert not any("should not be readable" in f["content"] for f in result["files"])
