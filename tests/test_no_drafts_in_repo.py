"""Agents' drafts and scratch files never sit in the repo (#1033).

Two checks: the five draft/scratch families are listed in .gitignore and git ignores
names of each family, and no TRACKED file matches one of the families.
"""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The five families of agents' drafts and scratch files. Each is anchored to the repo root:
# a pattern starting with "/" matches from the root, and a pattern with a "/" inside is
# relative to the .gitignore folder, which is the root as well.
FAMILIES = ("/tmp_*", ".claude/scratch_*", ".claude/tmp*", "/var_*", "/.scratch*")


def _in_family(path: str, pattern: str) -> bool:
    """True when `path`, or one of its leading folders, matches `pattern` anchored at the root."""
    anchored = pattern.lstrip("/")
    parts = path.split("/")
    return any(
        fnmatch.fnmatchcase("/".join(parts[:k]), anchored) for k in range(1, len(parts) + 1)
    )


def test_no_tracked_file_is_a_draft_or_scratch_file():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    tracked = [line for line in out.splitlines() if line]
    offenders = [
        f"{path} ({pattern})"
        for path in tracked
        for pattern in FAMILIES
        if _in_family(path, pattern)
    ]
    assert not offenders, "tracked drafts or scratch files: " + ", ".join(offenders)


def test_the_five_families_are_in_gitignore_and_git_ignores_them():
    lines = {line.strip() for line in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    missing = [pattern for pattern in FAMILIES if pattern not in lines]
    assert not missing, f".gitignore lacks the families: {missing}"
    # git check-ignore -q exits 0 when the name is ignored; the files need not exist.
    for name in ("tmp_x_cp1.md", ".claude/scratch_ab_1.md"):
        result = subprocess.run(["git", "check-ignore", "-q", name], cwd=REPO)
        assert result.returncode == 0, f"git does not ignore {name}"
