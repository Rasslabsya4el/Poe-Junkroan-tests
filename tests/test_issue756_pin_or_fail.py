"""#756 rule 1: a job with a pin runs at the pin or does not run (PoB-free)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import run_queue  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from test_runs_daemon import FakeLauncher, make_daemon  # noqa: E402

PIN = "3ba7abf"


def _real_branch(monkeypatch, tmp_path: Path, branch: str) -> None:
    """Make the real `run_queue.make_snapshot` fail in one of its four None-branches."""

    monkeypatch.setattr(run_queue, "ROOT", tmp_path)
    monkeypatch.setattr(run_queue, "SNAPSHOTS", tmp_path / "snapshots")
    monkeypatch.setattr(run_queue, "SHARED_DIRS", ("var",))
    (tmp_path / "var").mkdir(exist_ok=True)
    monkeypatch.setattr(run_queue, "drop_snapshot", lambda snap: None)

    def fake_git(*args):
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout="" if branch == "unresolved" else "3ba7abf\n", stderr="")
        if branch == "worktree":
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="boom")
        (tmp_path / "snapshots" / args[-2].split("\\")[-1].split("/")[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(run_queue, "_git", fake_git)
    monkeypatch.setattr(run_queue, "junction_target_refusal", lambda *a: "refused" if branch == "refused" else "")
    monkeypatch.setattr(run_queue.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=b"", stderr=b"nope"))


class RealBranchQueue:
    """The FakeQueueBackend's seam, but `make_snapshot` is the real one (so is the failure reason)."""

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def make_snapshot(self, name, pin):
        return run_queue.make_snapshot(name, pin)

    def snapshot_failure(self):
        return run_queue.LAST_SNAPSHOT_FAILURE


@pytest.mark.parametrize("branch", ["unresolved", "worktree", "refused", "mklink"])
def test_row1_pin_set_snapshot_fails_starts_nothing_and_fails_the_job(tmp_path, monkeypatch, branch):
    (tmp_path / "root").mkdir(exist_ok=True)
    _real_branch(monkeypatch, tmp_path / "root", branch)
    launcher = FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher)
    daemon.queue = RealBranchQueue(queue)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python scripts/benchmark.py --tag t", pin=PIN)
    daemon.tick()
    assert launcher.started == []
    got = store.get(job.id)
    assert got.state == "failed"
    assert PIN in (got.reason or "")
    assert {"unresolved": "not on this host", "worktree": "worktree add", "refused": "refused",
            "mklink": "mklink"}[branch] in got.reason


def test_row1_follower_after_a_pin_failed_job_does_not_start(tmp_path):
    launcher = FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher)
    queue.make_snapshot = lambda name, pin: None
    first = store.submit(host="pc", priority="P1", tag="a", cmd="python scripts/benchmark.py --tag a", pin=PIN)
    store.submit(host="pc", priority="P1", tag="b", cmd="python scripts/benchmark.py --tag b", after=[first.id])
    daemon.tick()
    daemon.tick()
    assert launcher.started == []


def test_row2_no_pin_and_snapshot_none_starts_as_today(tmp_path):
    launcher = FakeLauncher()
    daemon, store, queue = make_daemon(tmp_path, launcher=launcher)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python scripts/benchmark.py --tag t")
    daemon.tick()
    assert len(launcher.started) == 1
    assert launcher.started[0]["cwd"] == daemon_mod.PROJECT_ROOT
    assert store.get(job.id).state == "running"
