"""tools/agentops/merge.py (issue #339): a no-op merge is refused, a stale local branch is synced
from its remote. Fake repos: a bare origin and clones in ``tmp_path``."""

from __future__ import annotations

from pathlib import Path

from tests.test_agentops_merge import (  # noqa: F401  (autouse fixture protects the real var/)
    _commit, _git, _local_main_head, _origin_main_head, _protect_real_agentops_var, _push_branch,
    _world, suite_cmd,
)
from tools.agentops.merge import run_merge


def _merge(tmp_path: Path, checkout: Path, branch: str):
    counter, flag = tmp_path / "counter339.txt", tmp_path / "flag339.txt"
    return run_merge(branch, suite_cmd(counter, flag), cwd=checkout,
                     lock_path=tmp_path / "merge.lock", lock_timeout=30)


def _rev(repo: Path, ref: str) -> str:
    return _git("rev-parse", ref, cwd=repo).stdout.strip()


def _behind_local(tmp_path: Path, bare: Path, checkout: Path, branch: str) -> tuple[Path, str, str]:
    """Remote ``branch`` has two commits, the local one only the first. Returns (worker, old, new)."""
    worker = _push_branch(bare, tmp_path, f"worker-{branch}", branch, "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    old = _rev(checkout, f"origin/{branch}")
    _git("branch", branch, old, cwd=checkout)
    _commit(worker, "b.py", "b = 2\n", "add b.py")
    _git("push", "-q", "origin", branch, cwd=worker)
    return worker, old, _rev(worker, "HEAD")


def test_stale_local_branch_already_in_main_is_refused(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _git("branch", "stale", cwd=checkout)  # tip == main: nothing to merge
    head_before, origin_before = _local_main_head(checkout), _origin_main_head(bare)

    result = _merge(tmp_path, checkout, "stale")

    assert not result.ok
    assert result.reason == "nothing-to-merge"
    assert "nothing to merge" in result.render()
    assert not result.pushed
    assert _local_main_head(checkout) == head_before
    assert _origin_main_head(bare) == origin_before


def test_local_behind_remote_fast_forwards_and_merges_the_remote_commits(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _, old, new = _behind_local(tmp_path, bare, checkout, "feature-a")

    result = _merge(tmp_path, checkout, "feature-a")

    assert result.ok, result.render()
    assert f"fast-forwarded feature-a {old[:12]} -> {new[:12]} from origin/feature-a" in result.message
    assert _rev(checkout, "feature-a") == new
    assert (checkout / "a.py").exists() and (checkout / "b.py").exists()
    assert _origin_main_head(bare) == _local_main_head(checkout)


def test_branch_checked_out_in_another_worktree_is_not_moved(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _, old, _ = _behind_local(tmp_path, bare, checkout, "feature-e")
    _git("worktree", "add", "-q", str(tmp_path / "other-wt"), "feature-e", cwd=checkout)

    result = _merge(tmp_path, checkout, "feature-e")

    assert result.ok, result.render()
    assert "left in place" in result.message
    assert _rev(checkout, "feature-e") == old
    assert (checkout / "b.py").exists()


def test_diverged_local_and_remote_is_refused_naming_both_tips(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-d", "feature-d", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    _git("checkout", "-q", "-b", "feature-d", "origin/main", cwd=checkout)
    _commit(checkout, "local.py", "x = 1\n", "local commit")
    local_tip, remote_tip = _rev(checkout, "HEAD"), _rev(checkout, "origin/feature-d")
    _git("checkout", "-q", "main", cwd=checkout)
    head_before, origin_before = _local_main_head(checkout), _origin_main_head(bare)

    result = _merge(tmp_path, checkout, "feature-d")

    assert not result.ok
    assert result.reason == "diverged"
    assert local_tip[:12] in result.message and remote_tip[:12] in result.message
    assert _local_main_head(checkout) == head_before
    assert _origin_main_head(bare) == origin_before


def test_only_a_remote_branch_is_merged(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-r", "feature-r", "r.py", "r = 1\n")

    result = _merge(tmp_path, checkout, "feature-r")

    assert result.ok, result.render()
    assert (checkout / "r.py").exists()
