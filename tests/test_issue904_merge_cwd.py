"""#904: a merge started with a worktree as cwd is refused, never answered "nothing-to-merge"."""

from __future__ import annotations

from pathlib import Path

from tests.test_agentops_merge import (  # noqa: F401
    _git, _protect_real_agentops_var, _push_branch, _world,
)
from tests.test_agentops_merge_sync import _merge


def test_merge_from_worktree_is_refused(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-wt", "feature-wt", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    wt = tmp_path / "wt-feature"
    _git("worktree", "add", "-q", "-b", "feature-wt", str(wt), "origin/feature-wt", cwd=checkout)

    result = _merge(tmp_path, wt, "feature-wt")

    assert not result.ok
    assert result.reason != "nothing-to-merge"
    assert result.reason == "worktree"
    assert str(checkout) in result.message


def test_merge_in_main_checkout_still_nothing_to_merge(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _git("branch", "stale", cwd=checkout)

    result = _merge(tmp_path, checkout, "stale")

    assert result.reason == "nothing-to-merge"
