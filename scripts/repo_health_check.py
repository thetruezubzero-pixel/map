#!/usr/bin/env python3
"""Always-on repository health & security gate (Phase 11).

Runs the same deprecated-GitHub-Action and committed-secret checks the
Architect surfaces in its snapshot (app/agent_swarm/introspection.py's
_scan_repo_health) -- but as a dependency-free CI gate that fails the build
the moment either appears, WITHOUT needing OpenRouter or the Python API's
deps. This is the automatic "defensive rake": the exact rot that silently
broke this repo's CI (actions/upload-artifact@v3) would fail a PR here
instead of merging.

Stdlib only on purpose, so CI can run it with a bare `python` and no
`pip install`. The action-baseline table below is kept in sync with
introspection._MIN_ACTION_MAJOR by tests/test_repo_health_script.py (a
parity test), so the two can't silently drift.

Usage:
  python scripts/repo_health_check.py          # exit 1 if any finding
  python scripts/repo_health_check.py --json   # machine-readable

Always scans THIS repository (the one containing the script), derived from
the script's own location -- it deliberately does NOT take a target path
from the command line, so there's no untrusted-path source flowing into
the file reads / git subprocess below.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# Minimum non-deprecated major version for common GitHub Actions. GitHub
# HARD-fails workflows using upload-/download-artifact v3 or below; the
# rest are soft-deprecated but flagged before they become a hard failure.
# KEEP IN SYNC with app/agent_swarm/introspection._MIN_ACTION_MAJOR
# (enforced by tests/test_repo_health_script.py).
MIN_ACTION_MAJOR = {
    "actions/upload-artifact": 4,
    "actions/download-artifact": 4,
    "actions/checkout": 4,
    "actions/setup-node": 4,
    "actions/setup-python": 5,
    "actions/setup-java": 4,
    "actions/cache": 4,
}
_ACTION_USES_RE = re.compile(r"uses:\s*([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)@v(\d+)")

_COMMITTED_SECRET_SUFFIXES = (".key", ".pem", ".p12", ".pfx")
_COMMITTED_SECRET_NAMES = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".pgpass",
    "credentials.json", "secrets.yaml", "secrets.yml",
}


def looks_like_committed_secret(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    if name.startswith(".env") and not name.endswith(".example"):
        return True
    if name.endswith(_COMMITTED_SECRET_SUFFIXES):
        return True
    return name in _COMMITTED_SECRET_NAMES


def scan(project_root: Path) -> dict:
    deprecated_actions: list[dict] = []
    workflow_count = 0
    wf_dir = project_root / ".github" / "workflows"
    if wf_dir.exists():
        for wf in sorted(list(wf_dir.glob("*.yml")) + list(wf_dir.glob("*.yaml"))):
            workflow_count += 1
            try:
                text = wf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _ACTION_USES_RE.finditer(text):
                action, major = m.group(1), int(m.group(2))
                min_major = MIN_ACTION_MAJOR.get(action)
                if min_major is not None and major < min_major:
                    deprecated_actions.append(
                        {
                            "workflow": wf.name,
                            "action": f"{action}@v{major}",
                            "recommended": f"{action}@v{min_major}",
                        }
                    )

    committed_secret_files: list[str] = []
    if (project_root / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(project_root), "ls-files"],
                capture_output=True, text=True, timeout=15, check=True,
            )
            committed_secret_files = [
                rel for rel in result.stdout.splitlines() if looks_like_committed_secret(rel)
            ]
        except (subprocess.SubprocessError, OSError):
            pass

    return {
        "workflow_count": workflow_count,
        "deprecated_actions": deprecated_actions,
        "committed_secret_files": committed_secret_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Repository health & security gate")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    # Scan THIS repo, derived from the script's own location -- not a path
    # taken from argv. A CI gate should check its own tree, and accepting an
    # arbitrary root from the command line is an unnecessary untrusted-path
    # source (CodeQL py/path-injection) for zero real benefit here.
    root = Path(__file__).resolve().parents[1]
    findings = scan(root)

    if args.json:
        print(json.dumps(findings, indent=2))

    deprecated = findings["deprecated_actions"]
    secrets = findings["committed_secret_files"]

    if not args.json:
        print(f"Scanned {findings['workflow_count']} workflow file(s).")
        if deprecated:
            print(f"\n❌ {len(deprecated)} deprecated GitHub Action(s):")
            for d in deprecated:
                print(f"   {d['workflow']}: {d['action']} -> use {d['recommended']}")
        if secrets:
            print(f"\n❌ {len(secrets)} committed secret-shaped file(s):")
            for s in secrets:
                print(f"   {s}")
        if not deprecated and not secrets:
            print("✅ No deprecated actions or committed secrets found.")

    return 1 if (deprecated or secrets) else 0


if __name__ == "__main__":
    sys.exit(main())
