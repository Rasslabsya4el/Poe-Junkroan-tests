"""#663: a branch already waiting in the merge line cannot be queued twice."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from timing_bound import bound

import pytest

from tools.agentops import detach, merge
from tools.agentops.merge import MergeAlreadyQueued, MergeLock
from tests.test_agentops_merge import _push_branch, _git, _world, suite_cmd

ROOT = Path(__file__).resolve().parents[1]


def _info(kind="merge", branch="b", cwd="/c"):
    return {"kind": kind, "branch": branch, "suite": "s", "remote": "origin", "main": "main", "cwd": cwd}


def _queue(tmp_path: Path) -> Path:
    return tmp_path / "merge.lock.queue"


def _put(tmp_path: Path, pid: int, info: dict, name_seq: int = 0) -> None:
    q = _queue(tmp_path)
    q.mkdir(parents=True, exist_ok=True)
    (q / f"{time.time_ns():020d}-{pid}-{name_seq}").write_text(json.dumps(info), encoding="utf-8")


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def test_row1_live_same_branch_not_queued(tmp_path: Path):
    _put(tmp_path, os.getpid(), _info())
    lock = MergeLock(tmp_path / "merge.lock")
    with pytest.raises(MergeAlreadyQueued) as ei:
        lock.acquire(5, ticket_info=_info())
    assert re.match(rf"already queued: b since \d\d:\d\d \(.+\) by pid {os.getpid()}, result see merge.log", str(ei.value))
    assert len(list(_queue(tmp_path).iterdir())) == 1


def test_row1b_ticket_result_is_named(tmp_path: Path):
    _put(tmp_path, os.getpid(), {**_info(), "result": "R.json"})
    with pytest.raises(MergeAlreadyQueued, match="result R.json"):
        MergeLock(tmp_path / "merge.lock").acquire(5, ticket_info=_info())


def test_row2_dead_pid_ignored(tmp_path: Path):
    _put(tmp_path, _dead_pid(), _info())
    lock = MergeLock(tmp_path / "merge.lock")
    assert lock.acquire(5, ticket_info=_info()) is None  # queued, took the lock
    lock.release()


def _queues_behind(tmp_path: Path, info: dict) -> int:
    """Runs acquire in a thread behind the seeded live ticket; returns the ticket count seen while it
    waits, then frees the line so the thread ends."""
    import threading
    seeded = next(_queue(tmp_path).iterdir())
    lock = MergeLock(tmp_path / "merge.lock")
    err: list = []

    def run():
        try:
            lock.acquire(5, ticket_info=info)
            lock.release()
        except Exception as exc:  # noqa: BLE001
            err.append(exc)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    deadline = time.time() + 10
    while time.time() < deadline and len(list(_queue(tmp_path).iterdir())) < 2 and not err:
        time.sleep(0.05)
    n = len(list(_queue(tmp_path).iterdir()))
    seeded.unlink()
    t.join(15)
    assert not err and not t.is_alive()
    return n


def test_row3_other_branch_queues(tmp_path: Path):
    _put(tmp_path, os.getpid(), _info())
    assert _queues_behind(tmp_path, _info(branch="c")) == 2


def test_row4_commit_tickets_coexist(tmp_path: Path):
    _put(tmp_path, os.getpid(), {"kind": "commit", "branch": "b"})
    assert _queues_behind(tmp_path, {"kind": "commit", "branch": "b"}) == 2


def test_row5_real_subprocess_twice(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-x", "feature-x", "x.py", "x = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    counter, flag = tmp_path / "counter", tmp_path / "flag"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "AGENTOPS_MERGE_LOG": str(tmp_path / "m.log"),
           "AGENTOPS_MERGE_SUITE_OUTPUT_DIR": str(tmp_path / "suite_out")}
    argv = [sys.executable, "-m", "tools.agentops", "merge", "origin/feature-x", "--cwd", str(checkout),
            "--lock", str(tmp_path / "merge.lock"), "--suite", suite_cmd(counter, flag, 25.0)]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    first = subprocess.Popen(argv, cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, creationflags=flags)
    try:
        q = _queue(tmp_path)
        holding = tmp_path / "merge.lock.holding"
        deadline = time.time() + 20
        while time.time() < deadline and not holding.exists():
            time.sleep(0.1)
        assert holding.exists(), f"first merge never queued: rc {first.poll()} {first.stdout.read() if first.poll() is not None else ''}"
        t0 = time.time()
        second = subprocess.run(argv, cwd=str(ROOT), env=env, capture_output=True, text=True,
                                timeout=5, creationflags=flags)
        # bound = max(floor, factor x a CPU spin timed here): load that slows the spin slows the call (#826)
        bound_s = bound(5.0, 33.0)
        assert time.time() - t0 < bound_s, f"second merge took {time.time() - t0:.1f}s, bound {bound_s:.1f}s"
        out = second.stdout + second.stderr
        assert second.returncode == merge.EXIT_ALREADY_QUEUED == 5
        assert f"already queued: origin/feature-x since" in out and f"by pid {first.pid}" in out
        assert detach.classify(second.returncode, out) == ("already-queued", None)
        assert not list(q.iterdir())  # the holder holds; the duplicate wrote no ticket
    finally:
        first.kill()
        first.wait(timeout=10)
