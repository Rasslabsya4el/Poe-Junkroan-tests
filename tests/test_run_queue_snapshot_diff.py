"""#407: what a queued job changes in its snapshot comes back as artifacts/runs/jobs/<id>/snapshot.diff.

Real git, real snapshot worktree and junctions in a temp repo; no PoB, no real process (the daemon's
FakeLauncher stands in for the child, and the test plays the job by writing into its cwd).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

import test_runs_daemon as td
from junkroan.runs import daemon as daemon_mod

TRACKED_NEW = b"rewritten\n\x00\xff binary-ish\n"
ADDED = b"brand new\n"


def git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True)
    return res.stdout.strip()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    (repo / "artifacts" / "runs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "src" / "tracked.txt").write_bytes(b"original\nline two\n")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.autocrlf", "false")  # byte for byte: no CRLF rewrite on this Windows box
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    pin = git(repo, "rev-parse", "HEAD")

    rq = daemon_mod.run_queue()
    monkeypatch.setattr(rq, "ROOT", repo)
    monkeypatch.setattr(rq, "RUNS", repo / "artifacts" / "runs")
    monkeypatch.setattr(rq, "SNAPSHOTS", tmp_path / "snapshots")

    launcher = td.FakeLauncher()
    daemon, store, queue = td.make_daemon(tmp_path, launcher=launcher)
    queue.make_snapshot = rq.make_snapshot
    queue.drop_snapshot = rq.drop_snapshot
    queue.save_snapshot_diff = rq.save_snapshot_diff
    job = store.submit(host="pc", priority="P1", tag="t", cmd="python scripts/benchmark.py --tag t", pin=pin)
    daemon.tick()
    snap = launcher.started[0]["cwd"]
    assert snap.is_dir() and snap != repo
    yield daemon, store, launcher, job, repo, pin, snap, tmp_path
    for d in rq.SHARED_DIRS:  # a kept snapshot still holds junctions: take them off as entries
        if (snap / d).exists():
            os.rmdir(snap / d)


def end_job(daemon, launcher) -> None:
    launcher.finish(launcher.started[0]["pid"], 0)
    daemon.tick()


def end_line(store, job_id: str) -> dict:
    lines = [json.loads(x) for x in store.path.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in lines if r["job"] == job_id and r["op"] == "end"][-1]


def test_changed_and_new_files_come_back_as_a_diff(world) -> None:
    daemon, store, launcher, job, repo, pin, snap, tmp_path = world
    (snap / "src" / "tracked.txt").write_bytes(TRACKED_NEW)
    (snap / "src" / "new.txt").write_bytes(ADDED)
    (snap / "artifacts" / "runs" / "output.txt").write_text("an output", encoding="utf-8")
    end_job(daemon, launcher)

    assert not snap.exists()
    diff = repo / "artifacts" / "runs" / "jobs" / job.id / "snapshot.diff"
    assert diff.is_file()
    assert end_line(store, job.id)["snapshot_diff"] == str(diff)
    assert b"output.txt" not in diff.read_bytes()

    clean = tmp_path / "clean"
    git(repo, "worktree", "add", "--detach", "-q", str(clean), pin)
    git(clean, "apply", str(diff))
    got_tracked = sha((clean / "src" / "tracked.txt").read_bytes())
    got_new = sha((clean / "src" / "new.txt").read_bytes())
    assert got_tracked == sha(TRACKED_NEW), f"tracked: applied {got_tracked} vs written {sha(TRACKED_NEW)}"
    assert got_new == sha(ADDED), f"new: applied {got_new} vs written {sha(ADDED)}"
    git(repo, "worktree", "remove", "--force", str(clean))  # no junctions in it


def test_a_job_writing_only_under_artifacts_leaves_no_diff(world) -> None:
    daemon, store, launcher, job, repo, pin, snap, tmp_path = world
    (snap / "artifacts" / "runs" / "output.txt").write_text("an output", encoding="utf-8")
    end_job(daemon, launcher)

    assert not snap.exists()
    assert not (repo / "artifacts" / "runs" / "jobs" / job.id / "snapshot.diff").exists()
    assert "snapshot_diff" not in end_line(store, job.id)


def test_a_failed_diff_keeps_the_snapshot_and_logs_one_line(world) -> None:
    daemon, store, launcher, job, repo, pin, snap, tmp_path = world
    (snap / "src" / "tracked.txt").write_text("changed", encoding="utf-8")
    messages: list[str] = []
    daemon.log = messages.append

    def boom(*a, **k):
        raise RuntimeError("forced")

    daemon.queue.save_snapshot_diff = boom
    end_job(daemon, launcher)

    assert snap.is_dir()
    assert "snapshot_diff" not in end_line(store, job.id)
    kept = [m for m in messages if "snapshot diff not saved" in m and "worktree kept" in m]
    assert len(kept) == 1 and job.id in kept[0], messages
