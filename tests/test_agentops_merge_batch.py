"""#615 unit 2: the merge holder batches the waiting merges into one suite run.

Real ``run_merge`` calls in threads behind a lock the test holds first, then releases. No PoB."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from tests.test_agentops_merge import (  # fixtures + helpers of the sibling file
    NO_LOAD_REACHES, _clone, _git, _ThreadCapture, _green_default_commit_suite, _origin_main_head,
    _protect_real_agentops_var,
    _push_branch, _world, suite_cmd,
)
from tools.agentops.merge import MergeLock, run_commit, run_merge

_ = (_protect_real_agentops_var, _green_default_commit_suite)  # autouse fixture, imported so it applies here

_FILE_SUITE = """
import pathlib, sys
c = pathlib.Path(sys.argv[1])
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
sys.exit(1 if pathlib.Path(sys.argv[2]).exists() else 0)
"""


def _queued(lock_path: Path) -> int:
    q = lock_path.with_name(lock_path.name + ".queue")
    return len(list(q.iterdir())) if q.exists() else 0


def _wait_queued(lock_path: Path, n: int) -> None:
    deadline = time.time() + 120
    while time.time() < deadline:
        if _queued(lock_path) >= n:
            return
        time.sleep(0.02)
    raise AssertionError(f"fewer than {n} tickets queued")


class _Queue:
    """Starts jobs one by one behind a lock held by the test; each is queued before the next starts."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.lock = MergeLock(lock_path)
        assert self.lock.acquire(NO_LOAD_REACHES) is None
        self.threads: list[tuple[threading.Thread, _ThreadCapture]] = []

    def add(self, fn) -> None:
        cap = _ThreadCapture(fn)
        t = threading.Thread(target=cap)
        t.start()
        self.threads.append((t, cap))
        _wait_queued(self.lock_path, len(self.threads))

    def release_and_join(self) -> None:
        self.lock.release()
        for t, _cap in self.threads:
            t.join(timeout=NO_LOAD_REACHES)
            assert not t.is_alive(), "a queued job hung past its bound"
        for _t, cap in self.threads:
            cap.reraise()


def _merge_jobs(tmp_path, checkout, lock_path, branches, suite, results, log):
    jobs = []
    for b in branches:
        def job(b=b):
            results[b] = run_merge(f"origin/{b}", suite, cwd=checkout, lock_path=lock_path,
                                   lock_timeout=NO_LOAD_REACHES, merge_log_path=log,
                                   suite_output_dir=tmp_path / "suite_out")
        jobs.append(job)
    return jobs


def _log_lines(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _counter(path: Path) -> int:
    return int(path.read_text()) if path.exists() else 0


def _setup(tmp_path, names_files):
    bare, checkout = _world(tmp_path)
    for i, (b, f) in enumerate(names_files):
        _push_branch(bare, tmp_path, f"w{i}", b, f, f"{b} = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    return bare, checkout


def test_a_three_waiting_merges_share_one_suite_run(tmp_path: Path):
    bare, checkout = _setup(tmp_path, [("f1", "a.py"), ("f2", "b.py"), ("f3", "c.py")])
    counter, flag, log = tmp_path / "counter.txt", tmp_path / "flag.txt", tmp_path / "merge.log"
    lock_path = tmp_path / "merge.lock"
    results: dict = {}
    q = _Queue(lock_path)
    for job in _merge_jobs(tmp_path, checkout, lock_path, ["f1", "f2", "f3"],
                           suite_cmd(counter, flag), results, log):
        q.add(job)
    q.release_and_join()

    assert _counter(counter) == 1
    assert all(r.ok and r.pushed for r in results.values()), {k: r.message for k, r in results.items()}
    heads = {r.head_after for r in results.values()}
    assert heads == {_origin_main_head(bare)}
    assert sorted(r.batched for r in results.values()) == [False, True, True]
    fresh = _clone(bare, tmp_path / "verify")
    for f in ("a.py", "b.py", "c.py"):
        assert (fresh / f).exists()
    subjects = _git("log", "--format=%s", "--first-parent", "main", cwd=fresh).stdout.split("\n")
    assert len([s for s in subjects if s.startswith("Merge branch")]) == 3
    lines = _log_lines(log)
    assert len(lines) == 1 and "batch of 3: origin/f1, origin/f2, origin/f3" in lines[0], lines


def test_b_a_conflicting_waiter_is_left_in_line_and_meets_its_own_refusal(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "w0", "f1", "x.py", "one\n")
    _push_branch(bare, tmp_path, "w1", "f2", "x.py", "two\n")
    _push_branch(bare, tmp_path, "w2", "f3", "c.py", "c = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    counter, flag, log = tmp_path / "counter.txt", tmp_path / "flag.txt", tmp_path / "merge.log"
    lock_path = tmp_path / "merge.lock"
    results: dict = {}
    q = _Queue(lock_path)
    for job in _merge_jobs(tmp_path, checkout, lock_path, ["f1", "f2", "f3"],
                           suite_cmd(counter, flag), results, log):
        q.add(job)
    q.release_and_join()

    assert _counter(counter) == 1  # the conflicting one ran no suite of its own
    assert results["f1"].ok and results["f3"].ok
    assert results["f1"].head_after == results["f3"].head_after == _origin_main_head(bare)
    assert not results["f2"].ok and results["f2"].reason == "conflict"
    assert results["f2"].suite_runs == 0
    lines = _log_lines(log)
    assert any("origin/f2 | left in line: conflict" in ln for ln in lines), lines
    assert any("batch of 2: origin/f1, origin/f3" in ln for ln in lines), lines
    assert any("origin/f2 | conflict" in ln for ln in lines), lines


def test_c_a_red_batch_merges_the_holder_alone(tmp_path: Path):
    bare, checkout = _setup(tmp_path, [("f1", "a.py"), ("f2", "b.py"), ("f3", "c.py")])
    script = tmp_path / "file_suite.py"
    script.write_text(_FILE_SUITE, encoding="utf-8")
    counter, log = tmp_path / "counter.txt", tmp_path / "merge.log"
    suite = f'"{sys.executable}" "{script}" "{counter}" "b.py"'
    lock_path = tmp_path / "merge.lock"
    results: dict = {}
    q = _Queue(lock_path)
    for job in _merge_jobs(tmp_path, checkout, lock_path, ["f1", "f2", "f3"], suite, results, log):
        q.add(job)
    q.release_and_join()

    assert results["f1"].ok and results["f1"].suite_runs == 2 and not results["f1"].batched
    assert not results["f2"].ok and results["f2"].reason == "red-suite" and not results["f2"].batched
    assert results["f3"].ok and not results["f3"].batched
    assert results["f3"].head_after == _origin_main_head(bare)
    fresh = _clone(bare, tmp_path / "verify")
    assert (fresh / "a.py").exists() and (fresh / "c.py").exists() and not (fresh / "b.py").exists()
    lines = _log_lines(log)
    # the red batch leg is logged (it has no FAILED ids to triage with, so the old per-branch path runs)
    assert not any("batch of" in ln and "pushed" in ln for ln in lines), lines
    assert any("batch of 3" in ln and "| red-suite |" in ln for ln in lines), lines
    assert any("origin/f2 | red-suite" in ln for ln in lines), lines
    # f1 two runs (red batch, green alone); f2 two runs (batch with f3 red, alone red); f3 one run
    assert _counter(counter) == 5


def test_d_a_queued_commit_is_a_barrier(tmp_path: Path):
    bare, checkout = _setup(tmp_path, [("f0", "z.py"), ("f1", "a.py"), ("f2", "b.py")])
    counter, flag, log = tmp_path / "counter.txt", tmp_path / "flag.txt", tmp_path / "merge.log"
    lock_path = tmp_path / "merge.lock"
    results: dict = {}
    jobs = _merge_jobs(tmp_path, checkout, lock_path, ["f0", "f1", "f2"],
                       suite_cmd(counter, flag), results, log)
    commit_res: dict = {}

    def commit_job():
        (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")
        commit_res["r"] = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                                     lock_timeout=NO_LOAD_REACHES, merge_log_path=log)

    q = _Queue(lock_path)
    q.add(jobs[0])
    q.add(jobs[1])
    q.add(commit_job)
    q.add(jobs[2])
    q.release_and_join()

    assert commit_res["r"].ok, commit_res["r"].message
    assert results["f0"].ok and results["f1"].ok and results["f2"].ok
    assert results["f0"].head_after == results["f1"].head_after  # holder + f1 batched
    assert results["f1"].batched and not results["f0"].batched and not results["f2"].batched
    assert results["f2"].head_after != results["f0"].head_after
    fresh = _clone(bare, tmp_path / "verify")
    subjects = [s for s in _git("log", "--format=%s", "--first-parent", "main", cwd=fresh).stdout.split("\n") if s]
    assert subjects.index("Merge branch 'origin/f2'") < subjects.index("state: update") < \
        subjects.index("Merge branch 'origin/f1'")  # newest first
    assert any("batch of 2: origin/f0, origin/f1" in ln for ln in _log_lines(log))
