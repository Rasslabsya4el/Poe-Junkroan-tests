"""tools/agentops/merge.py: one merge at a time across every live session (issue #190).

A bare repo stands in for GitHub; every checkout is a clone in ``tmp_path``. No network,
no real opencode, no real ORCH. A tiny suite command (a python one-liner) lets a test
count how many times the suite ran and on which head."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from timing_bound import bound
from pathlib import Path

import pytest

from tools.agentops import core_settings, merge as merge_module, util
from tools.agentops.core_check import run_check
from tools.agentops.merge import (
    MergeError,
    MergeLock,
    MergeLockTimeout,
    resolve_suite_env,
    commit_needs_suite,
    run_commit,
    run_commit_command,
    run_merge,
)
from tools.agentops.util import pid_alive

SUITE_SCRIPT = Path(__file__).with_name("_merge_suite_helper.py")

# A ceiling for a test that measures the ORDER a lock imposes between two contending holders,
# not the speed either one runs at (issue #223 -- a ceiling of 30 s turned a merge on an
# unrelated branch red under full-suite load, chained `FileExistsError` -> `MergeLockTimeout`).
# No load on this machine reaches it; every ORDER site in this file uses the one constant.
NO_LOAD_REACHES = 600.0  # 10 min


@pytest.fixture(autouse=True)
def _protect_real_agentops_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One protection for the whole file (#234): every ``run_merge``/``_append_merge_log``/
    ``_prune_suite_outputs`` call that omits its path argument -- as the 12 pre-#212 calls in
    this file do -- must still land under ``tmp_path``, never under the real
    ``var/agentops/merge.log`` / ``var/agentops/merge_suite/``. A test added later that
    forgets to pass its own paths is still covered."""
    monkeypatch.setattr(merge_module, "SUITE_OUTPUT_DIR", tmp_path / "_autoprotect_merge_suite")
    monkeypatch.setattr(merge_module, "MERGE_LOG_PATH", tmp_path / "_autoprotect_merge.log")


@pytest.fixture(autouse=True)
def _green_default_commit_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """A commit of a non-docs path runs the merge suite (#375); a test that does not name its own
    suite gets a green stand-in here, never the real settings' pytest suite."""
    green = f'"{sys.executable}" -c "pass"'
    monkeypatch.setattr(merge_module, "resolve_suite_cmd", lambda explicit=None: explicit or green)


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, f"git {args} failed in {cwd}: {result.stderr}"
    return result


def _git_allow_fail(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def suite_cmd(counter: Path, flag: Path, sleep_seconds: float = 0.0,
             env_probe_name: str | None = None) -> str:
    tail = f" {sleep_seconds}"
    if env_probe_name:
        tail += f" {env_probe_name}"
    return f'"{sys.executable}" "{SUITE_SCRIPT}" "{counter}" "{flag}"{tail}'


def _init_bare(tmp_path: Path, name: str = "origin.git") -> Path:
    bare = tmp_path / name
    bare.mkdir()
    _git("init", "-q", "--bare", "-b", "main", cwd=bare)
    return bare


def _clone(bare: Path, dest: Path) -> Path:
    _git("clone", "-q", str(bare), str(dest), cwd=dest.parent)
    _git("config", "user.email", "agentops-test@example.invalid", cwd=dest)
    _git("config", "user.name", "agentops test", cwd=dest)
    return dest


def _commit(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    _git("add", name, cwd=repo)
    _git("commit", "-q", "-m", message, cwd=repo)


def _world(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin with one commit on main, and one clone (``checkout``) of it."""
    bare = _init_bare(tmp_path)
    seed = _clone(bare, tmp_path / "seed")
    _commit(seed, "README.md", "hello\n", "initial")
    _git("push", "-q", "origin", "main", cwd=seed)
    checkout = _clone(bare, tmp_path / "checkout")
    return bare, checkout


def _push_branch(bare: Path, tmp_path: Path, name: str, branch: str, file_name: str,
                 content: str) -> Path:
    """A fresh clone makes ``branch`` off current origin/main, commits one file, pushes it."""
    worker = _clone(bare, tmp_path / name)
    _git("checkout", "-q", "-b", branch, cwd=worker)
    _commit(worker, file_name, content, f"add {file_name}")
    _git("push", "-q", "origin", branch, cwd=worker)
    return worker


def _origin_main_head(bare: Path) -> str:
    return _git("rev-parse", "main", cwd=bare).stdout.strip()


def _local_main_head(checkout: Path) -> str:
    return _git("rev-parse", "main", cwd=checkout).stdout.strip()


class _ThreadCapture:
    """Wraps a thread's target so its exception becomes the joining test's own (issue #223):
    ``threading`` prints and swallows an exception raised inside a thread, so a bare
    ``results[name]`` lookup after ``join()`` fails with a misleading ``KeyError`` instead of
    the real error. Call ``reraise()`` after ``join()``; it is a no-op when the thread raised
    nothing."""

    def __init__(self, fn):
        self._fn = fn
        self.exc: BaseException | None = None

    def __call__(self, *args, **kwargs) -> None:
        try:
            self._fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - re-raised by reraise() below
            self.exc = exc

    def reraise(self) -> None:
        if self.exc is not None:
            raise self.exc


def test_thread_capture_reraises_the_threads_own_exception():
    def boom():
        raise ValueError("boom")

    capture = _ThreadCapture(boom)
    thread = threading.Thread(target=capture)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    with pytest.raises(ValueError, match="boom"):
        capture.reraise()


# -- 1. two concurrent merges: 2 suite runs, 0 forced pushes -----------------------------------

def test_two_concurrent_merges_serialize_through_the_lock(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _push_branch(bare, tmp_path, "worker-b", "feature-b", "b.py", "b = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    counter_a, flag_a = tmp_path / "counter-a.txt", tmp_path / "flag-a.txt"
    counter_b, flag_b = tmp_path / "counter-b.txt", tmp_path / "flag-b.txt"
    lock_path = tmp_path / "merge.lock"

    results: dict[str, object] = {}

    # This test measures the order the lock imposes, not the speed either merge runs at: what
    # is asserted stays the same: both merged, one after the other, both on the remote. See
    # `NO_LOAD_REACHES` above.

    def run(name, branch, counter, flag):
        results[name] = run_merge(
            f"origin/{branch}", suite_cmd(counter, flag), cwd=checkout, lock_path=lock_path,
            lock_timeout=NO_LOAD_REACHES,
        )

    capture_a = _ThreadCapture(lambda: run("a", "feature-a", counter_a, flag_a))
    capture_b = _ThreadCapture(lambda: run("b", "feature-b", counter_b, flag_b))
    t1 = threading.Thread(target=capture_a)
    t2 = threading.Thread(target=capture_b)
    t1.start()
    t2.start()
    t1.join(timeout=NO_LOAD_REACHES)
    t2.join(timeout=NO_LOAD_REACHES)
    assert not t1.is_alive() and not t2.is_alive(), "a merge hung past its bound"
    capture_a.reraise()
    capture_b.reraise()

    result_a, result_b = results["a"], results["b"]
    assert result_a.ok and result_b.ok, (result_a.message, result_b.message)
    assert result_a.pushed and result_b.pushed
    assert result_a.suite_runs == 1
    assert result_b.suite_runs == 1
    assert result_a.rebases == 0 and result_b.rebases == 0

    fresh = _clone(bare, tmp_path / "verify")
    log = _git("log", "--oneline", "main", cwd=fresh).stdout
    assert "add a.py" in log and "add b.py" in log


# -- 1b. the case that went red: a holder past the old 30 s ceiling, the waiter lands -----------

@pytest.mark.slow  # a real 40 s hold: excluded from the default "-m not slow" run (pytest.ini)
def test_waiter_lands_after_a_holder_past_the_old_30s_ceiling(tmp_path: Path):
    """Issue #223: under full-suite load a holder's own critical section outlived the test's
    30 s ceiling, so the waiter raised `MergeLockTimeout` instead of landing after it. With the
    ceiling raised to one no load on this machine reaches, a holder that takes 40 s -- longer
    than that old ceiling -- is still just waited for."""
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-j", "feature-j", "j.py", "j = 1\n")
    _push_branch(bare, tmp_path, "worker-k", "feature-k", "k.py", "k = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    checkout_b = _clone(bare, tmp_path / "checkout-j-b")

    lock_path = tmp_path / "merge.lock"
    counter_a, flag_a = tmp_path / "counter-j.txt", tmp_path / "flag-j.txt"
    counter_b, flag_b = tmp_path / "counter-k.txt", tmp_path / "flag-k.txt"
    results: dict[str, object] = {}

    def run(name, checkout_dir, branch, counter, flag, sleep_seconds):
        results[name] = run_merge(f"origin/{branch}", suite_cmd(counter, flag, sleep_seconds),
                                  cwd=checkout_dir, lock_path=lock_path, lock_timeout=NO_LOAD_REACHES)

    capture_a = _ThreadCapture(lambda: run("a", checkout, "feature-j", counter_a, flag_a, 40.0))
    t1 = threading.Thread(target=capture_a)
    t1.start()
    import time
    time.sleep(0.3)  # let a hold the lock first
    run("b", checkout_b, "feature-k", counter_b, flag_b, 0.0)
    t1.join(timeout=NO_LOAD_REACHES)  # the order is measured, not the speed: no load reaches 10 min
    assert not t1.is_alive()
    capture_a.reraise()

    result_a, result_b = results["a"], results["b"]
    assert result_a.ok, result_a.message
    assert result_b.ok, result_b.message
    assert result_a.pushed and result_b.pushed

    fresh = _clone(bare, tmp_path / "verify-j")
    log = _git("log", "--oneline", "main", cwd=fresh).stdout
    assert "add j.py" in log and "add k.py" in log


# -- 2. a dead holder never blocks: 0 min wait --------------------------------------------------

def test_dead_holder_is_taken_over_at_once(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-c", "feature-c", "c.py", "c = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead_pid = dead.pid
    assert dead.wait(timeout=10) == 0
    # `dead` (and its process handle) is deliberately kept alive/held for the rest of this
    # test: `pid_alive` must read the process' own exit state, not whether a handle to it
    # is still open (issue #195, acceptance 5 -- the old bug this used to route around).

    lock_path = tmp_path / "merge.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(f'{{"pid": {dead_pid}, "started": "irrelevant"}}', encoding="utf-8")

    # The bound is on the wait for the lock, not on the whole merge (issue #205): the time is
    # read around `MergeLock.acquire` itself, so a loaded PC slowing git or the suite cannot
    # turn this red. The suite sleeps 3 s to prove the two are measured apart.
    import time
    waits: list[float] = []
    real_acquire = MergeLock.acquire

    def timed_acquire(self, max_age_seconds=None, **kwargs):
        t0 = time.monotonic()
        try:
            return real_acquire(self, max_age_seconds, **kwargs)
        finally:
            waits.append(time.monotonic() - t0)

    monkeypatch.setattr(MergeLock, "acquire", timed_acquire)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    started = time.monotonic()
    result = run_merge("origin/feature-c", suite_cmd(counter, flag, 3.0), cwd=checkout,
                       lock_path=lock_path, lock_timeout=10)
    whole = time.monotonic() - started

    assert result.ok, result.message
    assert len(waits) == 1
    bound_s = bound(1.0, 6.0)  # max(floor, factor x CPU spin) (#826)
    assert waits[0] < bound_s, f"waited {waits[0]:.1f}s for a dead holder, bound {bound_s:.1f}s"
    assert whole > 3.0, f"the merge took {whole:.1f}s, the 3 s suite did not run inside it"
    dead.wait(timeout=10)  # drop our own reference cleanly


# -- a PermissionError on create is a held lock, not a crash (issue #223) ------------------------

def test_permission_error_on_create_is_taken_over_like_file_exists(tmp_path: Path, monkeypatch):
    """Windows: a lock file just unlinked and still open elsewhere answers the next create with
    `PermissionError`, not `FileExistsError` -- `acquire` must not let that escape as a crash."""
    lock_path = tmp_path / "merge.lock"
    real_open = os.open
    calls = {"n": 0}

    def flaky_open(path, flags, *args, **kwargs):
        if str(path) == str(lock_path) and calls["n"] == 0:
            calls["n"] += 1
            raise PermissionError(13, "Permission denied")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(merge_module.os, "open", flaky_open)

    lock = MergeLock(lock_path)
    lock.acquire(max_age_seconds=10)  # raises nothing: the injected error costs one more turn
    assert calls["n"] == 1
    assert lock_path.exists()


# -- pid_alive itself (issue #195) ----------------------------------------------------------------

def test_pid_alive_false_for_an_exited_process_whose_handle_is_still_held():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    assert proc.wait(timeout=10) == 0
    # the Popen object (and its handle) stays alive/held here: acceptance 1.
    assert pid_alive(proc.pid) is False
    proc.wait(timeout=10)


def test_pid_alive_true_for_a_live_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        assert pid_alive(proc.pid) is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.skipif(os.name != "nt", reason="Windows-only OpenProcess stub")
def test_pid_alive_true_when_open_process_is_access_denied(monkeypatch):
    monkeypatch.setattr(util, "_open_process", lambda pid: (0, 5))
    assert pid_alive(12345) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows-only OpenProcess stub")
def test_pid_alive_false_when_open_process_says_no_such_process(monkeypatch):
    monkeypatch.setattr(util, "_open_process", lambda pid: (0, 87))
    assert pid_alive(12345) is False


# -- the waiter behind a slow holder never times out on wall-clock alone -------------------------

def test_waiter_lands_after_a_slow_holder_instead_of_timing_out(tmp_path: Path):
    bare, checkout_a = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-h", "feature-h", "h.py", "h = 1\n")
    _push_branch(bare, tmp_path, "worker-i", "feature-i", "i.py", "i = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout_a)
    checkout_b = _clone(bare, tmp_path / "checkout-b")

    lock_path = tmp_path / "merge.lock"
    counter_a, flag_a = tmp_path / "counter-h.txt", tmp_path / "flag-h.txt"
    counter_b, flag_b = tmp_path / "counter-i.txt", tmp_path / "flag-i.txt"

    # the holder's own critical section (fetch+merge+suite+push) takes ~3 s: longer than the
    # old, now-removed, 2 s wait bound.
    results: dict[str, object] = {}

    def run(name, checkout, branch, counter, flag, sleep_seconds):
        results[name] = run_merge(f"origin/{branch}", suite_cmd(counter, flag, sleep_seconds),
                                  cwd=checkout, lock_path=lock_path, lock_timeout=NO_LOAD_REACHES)  # the order is measured, not the speed: no load reaches 10 min

    capture_a = _ThreadCapture(lambda: run("a", checkout_a, "feature-h", counter_a, flag_a, 3.0))
    t1 = threading.Thread(target=capture_a)
    t1.start()
    import time
    time.sleep(0.3)  # let a hold the lock first
    run("b", checkout_b, "feature-i", counter_b, flag_b, 0.0)
    t1.join(timeout=NO_LOAD_REACHES)
    assert not t1.is_alive()
    capture_a.reraise()

    result_a, result_b = results["a"], results["b"]
    assert result_a.ok, result_a.message
    assert result_b.ok, result_b.message
    assert result_a.pushed and result_b.pushed
    assert result_a.suite_runs == 1
    assert result_b.suite_runs == 1


# -- a holder past the age ceiling is named, not waited for forever ------------------------------

def test_waiter_exits_3_past_the_age_ceiling_leaving_the_lock_untouched(tmp_path: Path):
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        lock_path = tmp_path / "merge.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        # issue #235: `started` must stay close to `live`'s own, real creation time -- a lie
        # ancient enough to blow any ceiling (the old "2000-01-01" fixture) now also reads as a
        # holder on a *reused* pid and is taken over at once, never reaching the ceiling check
        # this test means to exercise. `max_age_seconds=0.0` forces the ceiling past on its own
        # without lying about `started`.
        real_started = util.now()
        lock_path.write_text(f'{{"pid": {live.pid}, "started": "{real_started}"}}', encoding="utf-8")
        before = lock_path.read_bytes()

        lock = MergeLock(lock_path)
        import time as time_mod
        started = time_mod.monotonic()
        with pytest.raises(MergeLockTimeout) as excinfo:
            lock.acquire(max_age_seconds=0.0)
        elapsed = time_mod.monotonic() - started

        # issue #212: this path takes one loop iteration (no `time.sleep`) -- normally under a
        # millisecond -- so the bound only needs to be well short of a real poll wait (which
        # moves in multiples of the lock's own 0.1 s poll interval); a machine at 100% CPU
        # (#212's own load recipe: one busy python process per core) can still delay this
        # process' own scheduling by more than the old 1.0 s bound without a real wait ever
        # happening, so the bound is widened rather than narrowed further -- there is nothing
        # left inside this span to separate out the way #205 split the lock-wait off the suite.
        bound_s = bound(5.0, 33.0)
        assert elapsed < bound_s, f"took {elapsed:.2f}s to notice the ceiling, bound {bound_s:.1f}s"
        message = str(excinfo.value)
        assert str(live.pid) in message and "traceback" not in message.lower()
        assert message.count("\n") == 0
        assert lock_path.read_bytes() == before
    finally:
        live.terminate()
        live.wait(timeout=10)


# -- a reused pid is not a live holder either, for the merge lock (issue #235) -------------------

@pytest.mark.skipif(sys.platform != "win32", reason="creation-time check is Windows-only")
def test_row7_merge_lock_takes_over_a_reused_pid_holder_in_under_1s(tmp_path: Path):
    """Row 7 (the merge lock with row 1's lock): a live process of this test, but `started`
    claims it began 1 hour before that process was created -- reused-pid shape. Taken over at
    once, the way a dead holder already is (`test_dead_holder_is_taken_over_at_once` above)."""
    import json as json_mod
    import time as time_mod
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        old_started = time_mod.strftime("%Y-%m-%d %H:%M:%S", time_mod.localtime(time_mod.time() - 3600))
        lock_path = tmp_path / "merge.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(json_mod.dumps({"pid": live.pid, "started": old_started}),
                             encoding="utf-8")

        lock = MergeLock(lock_path)
        started = time_mod.monotonic()
        lock.acquire(max_age_seconds=10)
        elapsed = time_mod.monotonic() - started
        try:
            bound_s = bound(1.0, 6.0)
            assert elapsed < bound_s, f"waited {elapsed:.1f}s for a reused-pid holder, bound {bound_s:.1f}s"
            assert json_mod.loads(lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()
        finally:
            lock.release()
        assert not lock_path.exists()
    finally:
        live.terminate()
        live.wait(timeout=10)


def test_row7_merge_lock_waits_for_the_true_holder_as_today(tmp_path: Path):
    """Row 7 (the merge lock with row 2's lock): this process' own pid, `started` matching when
    it actually began -- the ordinary "somebody else genuinely holds it" case. Still waits, and
    still reports the age ceiling by naming the holder, exactly as before this issue."""
    import json as json_mod
    lock_path = tmp_path / "merge.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json_mod.dumps({"pid": os.getpid(), "started": util.now()}),
                         encoding="utf-8")

    lock = MergeLock(lock_path)
    with pytest.raises(MergeLockTimeout) as excinfo:
        lock.acquire(max_age_seconds=0.0)
    assert str(os.getpid()) in str(excinfo.value)
    assert json_mod.loads(lock_path.read_text(encoding="utf-8"))["pid"] == os.getpid()


# -- 3. a red suite leaves both heads unchanged, 0 pushes ---------------------------------------

def test_red_suite_rolls_back_and_pushes_nothing(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-d", "feature-d", "d.py", "d = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    head_before = _local_main_head(checkout)
    origin_before = _origin_main_head(bare)

    # an unrelated file, dirty in the checkout, that the merge never touches
    unrelated = checkout / "unrelated-note.txt"
    unrelated.write_text("another session's uncommitted note\n", encoding="utf-8")
    unrelated_before = unrelated.read_bytes()

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    flag.write_text("fail", encoding="utf-8")  # the suite always fails

    result = run_merge("origin/feature-d", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert not result.ok
    assert result.reason == "red-suite"
    assert not result.pushed
    assert _local_main_head(checkout) == head_before
    assert _origin_main_head(bare) == origin_before
    assert unrelated.read_bytes() == unrelated_before


# -- 4. a conflict names the files ---------------------------------------------------------------

def test_conflict_names_the_files(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    # both the branch and local main touch conflict.py after diverging
    _push_branch(bare, tmp_path, "worker-e", "feature-e", "conflict.py", "branch = 1\n")
    _commit(checkout, "conflict.py", "main = 1\n", "edit conflict.py on main")
    _git("push", "-q", "origin", "main", cwd=checkout)
    _git("fetch", "-q", "origin", cwd=checkout)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-e", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert not result.ok
    assert result.reason == "conflict"
    assert result.conflicting_files == ["conflict.py"]
    status = _git("status", "--porcelain", cwd=checkout).stdout
    assert status == ""  # the abort left the tree clean


# -- 5. origin moved between sync and push: 1 fetch+re-merge+suite, 0 forced pushes --------------

def test_origin_moved_lands_after_one_rebase(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-f", "feature-f", "f.py", "f = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    mover = _clone(bare, tmp_path / "mover")

    # an unrelated file, dirty in the checkout, present through the whole re-merge
    unrelated = checkout / "unrelated-note.txt"
    unrelated.write_text("another session's uncommitted note\n", encoding="utf-8")
    unrelated_before = unrelated.read_bytes()

    import tools.agentops.merge as merge_mod
    real_run_suite = merge_mod._run_suite
    moved = {"done": False}

    def moving_run_suite(cmd, cwd, env=None, output_path=None, head_line="", **kw):
        ok, output = real_run_suite(cmd, cwd, env, output_path, head_line, **kw)
        if not moved["done"]:
            moved["done"] = True
            _commit(mover, "mover.py", "mover = 1\n", "a race: pushed while our suite ran")
            _git("push", "-q", "origin", "main", cwd=mover)
        return ok, output

    monkeypatch.setattr(merge_mod, "_run_suite", moving_run_suite)

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-f", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok, result.message
    assert result.pushed
    assert result.rebases == 1
    assert result.suite_runs == 2
    assert unrelated.read_bytes() == unrelated_before

    fresh = _clone(bare, tmp_path / "verify")
    log = _git("log", "--oneline", "main", cwd=fresh).stdout
    assert "add f.py" in log
    assert "a race: pushed while our suite ran" in log


# -- 6. a dirty touched file refuses the merge, byte-identical after -----------------------------

def test_dirty_touched_file_refuses_and_stays_identical(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-g", "feature-g", "g.py", "g = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    (checkout / "g.py").write_text("dirty, uncommitted\n", encoding="utf-8")
    before_bytes = (checkout / "g.py").read_bytes()

    counter, flag = tmp_path / "counter.txt", tmp_path / "flag.txt"
    result = run_merge("origin/feature-g", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert not result.ok
    assert result.reason == "dirty"
    assert "g.py" in result.conflicting_files
    assert (checkout / "g.py").read_bytes() == before_bytes


# -- merge_suite_env (issue #198): applied to every suite run, including an explicit --suite ------

def _minimal_settings_json(**extra) -> str:
    """A settings file with every `core_settings.REQUIRED_KEYS` filled in (arbitrary values),
    plus whatever `extra` keys a test wants to add on top."""
    base = {key: "x" for key in core_settings.REQUIRED_KEYS}
    base["local_modules"] = []
    base.update(extra)
    import json as _json
    return _json.dumps(base)


def test_resolve_suite_env_reads_the_settings_key(monkeypatch, tmp_path: Path):
    settings_path = tmp_path / "orchestration.json"
    settings_path.write_text(
        _minimal_settings_json(merge_suite_env={"JUNKROAN_NO_POB": "1", "OTHER": "x"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(core_settings, "SETTINGS_PATH", settings_path)
    assert resolve_suite_env() == {"JUNKROAN_NO_POB": "1", "OTHER": "x"}


def test_resolve_suite_env_is_empty_without_the_key(monkeypatch, tmp_path: Path):
    settings_path = tmp_path / "orchestration.json"
    settings_path.write_text(_minimal_settings_json(), encoding="utf-8")
    monkeypatch.setattr(core_settings, "SETTINGS_PATH", settings_path)
    assert resolve_suite_env() == {}


def test_run_merge_applies_suite_env_to_the_suite_process(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-env", "feature-env", "env.py", "env = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    counter, flag = tmp_path / "counter-env.txt", tmp_path / "flag-env.txt"
    result = run_merge(
        "origin/feature-env", suite_cmd(counter, flag, env_probe_name="JUNKROAN_NO_POB"),
        cwd=checkout, lock_path=tmp_path / "merge.lock", lock_timeout=30,
        suite_env={"JUNKROAN_NO_POB": "1"},
    )

    assert result.ok, result.message
    probe = counter.with_name(counter.name + ".env-JUNKROAN_NO_POB")
    assert probe.read_text(encoding="utf-8") == "1"


def test_run_merge_with_an_explicit_suite_still_gets_suite_env(tmp_path: Path):
    """`--suite` overrides the command; `merge_suite_env` applies regardless (the spec's own
    wording: "whatever words its selection holds")."""
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-env2", "feature-env2", "env2.py", "env2 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    counter, flag = tmp_path / "counter-env2.txt", tmp_path / "flag-env2.txt"
    explicit_suite = suite_cmd(counter, flag, env_probe_name="JUNKROAN_NO_POB")
    result = run_merge(
        "origin/feature-env2", explicit_suite, cwd=checkout, lock_path=tmp_path / "merge.lock",
        lock_timeout=30, suite_env={"JUNKROAN_NO_POB": "1"},
    )

    assert result.ok, result.message
    probe = counter.with_name(counter.name + ".env-JUNKROAN_NO_POB")
    assert probe.read_text(encoding="utf-8") == "1"


# -- commit (issue #207): the same lock, only the named paths, pushed, lock always released ------

# -- acceptance 1: a holder's successful merge -> the commit lands on the head it left -----------

def test_commit_waits_behind_a_live_holder_and_lands_on_the_head_it_left(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-j", "feature-j", "j.py", "j = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    lock_path = tmp_path / "merge.lock"
    counter, flag = tmp_path / "counter-j.txt", tmp_path / "flag-j.txt"

    merge_result: dict[str, object] = {}

    def hold():
        merge_result["r"] = run_merge("origin/feature-j", suite_cmd(counter, flag, 2.0),
                                      cwd=checkout, lock_path=lock_path, lock_timeout=30)

    import time
    t = threading.Thread(target=hold)
    t.start()
    time.sleep(0.5)

    # the bound is on the wait for the lock, not on the whole commit (#205's own rule).
    waits: list[float] = []
    real_acquire = MergeLock.acquire

    def timed_acquire(self, max_age_seconds=None, **kwargs):
        t0 = time.monotonic()
        try:
            return real_acquire(self, max_age_seconds, **kwargs)
        finally:
            waits.append(time.monotonic() - t0)

    monkeypatch.setattr(MergeLock, "acquire", timed_acquire)

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")
    # this test measures the order the lock imposes between the holder's merge and the waiting
    # commit, not the speed either runs at (issue #243). See `NO_LOAD_REACHES` above.
    commit_result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                               lock_timeout=NO_LOAD_REACHES)

    t.join(timeout=NO_LOAD_REACHES)
    assert not t.is_alive(), "the holder's merge hung past its bound"

    assert merge_result["r"].ok, merge_result["r"].message
    assert commit_result.ok, commit_result.message
    assert len(waits) == 1
    assert waits[0] > 1.0, f"the commit did not wait behind the live holder: {waits}"

    parent = _git("rev-parse", "HEAD^", cwd=checkout).stdout.strip()
    assert parent == merge_result["r"].head_after, "the commit's parent is not the head the holder left"


# -- acceptance 2: the holder's merge ends red-suite during the wait -> 0 commits of it pushed ----

def test_commit_after_a_refused_merge_lands_on_the_original_head(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-k", "feature-k", "k.py", "k = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    head_before = _local_main_head(checkout)

    lock_path = tmp_path / "merge.lock"
    counter, flag = tmp_path / "counter-k.txt", tmp_path / "flag-k.txt"
    flag.write_text("fail", encoding="utf-8")  # the suite always fails

    merge_result: dict[str, object] = {}

    def hold():
        merge_result["r"] = run_merge("origin/feature-k", suite_cmd(counter, flag, 1.0),
                                      cwd=checkout, lock_path=lock_path, lock_timeout=30)

    import time
    t = threading.Thread(target=hold)
    t.start()
    time.sleep(0.3)

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")
    # this test measures the order the lock imposes between the holder's merge and the waiting
    # commit, not the speed either runs at (issue #243). See `NO_LOAD_REACHES` above.
    commit_result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                               lock_timeout=NO_LOAD_REACHES)

    t.join(timeout=NO_LOAD_REACHES)
    assert not t.is_alive(), "the holder's merge hung past its bound"

    assert not merge_result["r"].ok
    assert merge_result["r"].reason == "red-suite"
    assert not merge_result["r"].pushed
    assert commit_result.ok, commit_result.message

    parent = _git("rev-parse", "HEAD^", cwd=checkout).stdout.strip()
    assert parent == head_before, "the commit's parent is a commit the holder made and rolled back"

    fresh = _clone(bare, tmp_path / "verify-k")
    log = _git("log", "--oneline", "main", cwd=fresh).stdout
    assert "add k.py" not in log
    assert "state: update" in log


# -- acceptance 3: no holder -> 1 commit, 1 push, exit 0, the lock file gone afterwards -----------

def test_commit_with_no_holder_pushes_once_and_clears_the_lock(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"
    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert result.ok, result.message
    assert result.pushed
    assert result.reason == "pushed"
    assert not lock_path.exists()

    fresh = _clone(bare, tmp_path / "verify-3")
    count = _git("rev-list", "--count", "main", cwd=fresh).stdout.strip()
    assert count == "2"  # the seed commit, plus this one
    log = _git("log", "-1", "--format=%s", "main", cwd=fresh).stdout.strip()
    assert log == "state: update"


# -- acceptance 4: an untracked folder and a modified file not named stay untouched ---------------

def test_commit_only_touches_the_named_paths(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")
    (checkout / "README.md").write_text("hello, modified\n", encoding="utf-8")
    readme_before = (checkout / "README.md").read_bytes()
    untracked_dir = checkout / "scratch"
    untracked_dir.mkdir()
    (untracked_dir / "note.txt").write_text("scratch note\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert result.ok, result.message
    status = _git("status", "--porcelain", cwd=checkout).stdout
    assert "README.md" in status  # still modified, uncommitted
    assert "scratch/" in status  # still untracked
    assert (checkout / "README.md").read_bytes() == readme_before
    committed = _git("show", "--name-only", "--format=", "HEAD", cwd=checkout).stdout.split()
    assert committed == ["state.txt"]


# -- issue #211: commit brings the checkout up to the remote first ------------------------------

# -- row 1: 2 behind, the named path untouched -> synced first, then commits and pushes on top ---

def test_commit_behind_the_remote_syncs_first_and_pushes_on_top(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    mover = _clone(bare, tmp_path / "mover-row1")
    _commit(mover, "one.txt", "one = 1\n", "add one.py")
    _git("push", "-q", "origin", "main", cwd=mover)
    _commit(mover, "two.txt", "two = 1\n", "add two.py")
    _git("push", "-q", "origin", "main", cwd=mover)

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert result.ok, result.message
    assert not lock_path.exists()

    fresh = _clone(bare, tmp_path / "verify-row1")
    log = _git("log", "--format=%s", "main", cwd=fresh).stdout.strip().splitlines()
    assert log[:3] == ["state: update", "add two.py", "add one.py"]
    remote_head = _git("rev-parse", "main", cwd=fresh).stdout.strip()
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == remote_head


# -- row 2: 1 ahead (its own unpushed commit) and 1 behind -> refused, 0 commits made ------------

def test_commit_diverged_is_refused_before_anything_is_committed(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    _commit(checkout, "local.txt", "local = 1\n", "checkout: local unpushed commit")
    head_before = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

    mover = _clone(bare, tmp_path / "mover-row2")
    _commit(mover, "remote.txt", "remote = 1\n", "origin: moved on")
    _git("push", "-q", "origin", "main", cwd=mover)

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert not result.ok
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == head_before
    assert "1 ahead, 1 behind" in result.message
    status = _git("status", "--porcelain", cwd=checkout).stdout
    assert "state.txt" in status
    assert not lock_path.exists()


# -- row 3: 1 behind, and the incoming commit changes a file that is changed locally too --------

def test_commit_ff_would_overwrite_a_changed_file_names_it(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    mover = _clone(bare, tmp_path / "mover-row3")
    (mover / "README.md").write_text("hello, from origin\n", encoding="utf-8")
    _git("add", "README.md", cwd=mover)
    _git("commit", "-q", "-m", "origin: README.md changed", cwd=mover)
    _git("push", "-q", "origin", "main", cwd=mover)

    (checkout / "README.md").write_text("hello, from checkout\n", encoding="utf-8")
    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert not result.ok
    assert "README.md" in result.message
    log = _git("log", "--format=%s", cwd=checkout).stdout
    assert "state: update" not in log
    assert not lock_path.exists()


# -- row 4: the remote moves once between the fetch and the push -> retried, ok after 2 pushes ---

def test_commit_pushes_again_when_the_remote_moves_once(tmp_path: Path, monkeypatch):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"
    mover = _clone(bare, tmp_path / "mover-row4")

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    from tools.agentops import merge as merge_module
    real_git = merge_module._git
    pushes = {"n": 0}
    moved_once = {"done": False}

    def spy(cwd, *args, **kw):
        if cwd == checkout and args[:1] == ("push",):
            pushes["n"] += 1
            if not moved_once["done"]:
                moved_once["done"] = True
                _commit(mover, "mover.txt", "mover = 1\n", "a race: origin moved")
                _git("push", "-q", "origin", "main", cwd=mover)
        return real_git(cwd, *args, **kw)

    monkeypatch.setattr(merge_module, "_git", spy)

    result = run_commit(["state.txt"], "state: update", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10)

    assert result.ok, result.message
    assert pushes["n"] == 2

    fresh = _clone(bare, tmp_path / "verify-row4")
    log = _git("log", "--format=%s", "main", cwd=fresh).stdout.strip().splitlines()
    assert log[0] == "state: update"
    assert log[1] == "a race: origin moved"


# -- row 5: the remote moves before every push -> gives up after 3, the local commit kept --------

def test_commit_gives_up_after_three_pushes_when_the_remote_always_moves(tmp_path: Path, capsys,
                                                                          monkeypatch):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"
    mover = _clone(bare, tmp_path / "mover-row5")

    (checkout / "state.txt").write_text("state v1\n", encoding="utf-8")

    from tools.agentops import merge as merge_module
    real_git = merge_module._git
    pushes = {"n": 0}

    def spy(cwd, *args, **kw):
        if cwd == checkout and args[:1] == ("push",):
            pushes["n"] += 1
            _commit(mover, f"mover{pushes['n']}.txt", "x = 1\n", f"a race #{pushes['n']}")
            _git("push", "-q", "origin", "main", cwd=mover)
        return real_git(cwd, *args, **kw)

    monkeypatch.setattr(merge_module, "_git", spy)

    args = argparse.Namespace(message="state: update", paths=["state.txt"], cwd=checkout,
                              lock=lock_path, timeout=10.0)
    exit_code = run_commit_command(args)
    captured = capsys.readouterr()

    assert exit_code != 0
    assert pushes["n"] == 3
    assert captured.out.count("\n") == 1
    assert "3" in captured.out
    assert _git("log", "-1", "--format=%s", cwd=checkout).stdout.strip() == "state: update"
    assert not lock_path.exists()


# -- #375: a commit of a non-docs path runs the merge suite ------------------------------------

def _red_suite_cmd(tmp_path: Path) -> str:
    # the directory is named `pytest` on purpose: merge._is_pytest_command wants the whole word
    # `pytest` in the command, and where tmp_path sits must not decide that
    (tmp_path / "pytest").mkdir(exist_ok=True)
    red = tmp_path / "pytest" / "red_suite.py"
    red.write_text("import sys\n"
                   "print('FAILED tests/test_x.py::test_boom - assert 0')\n"
                   "print('1 failed, 3 passed in 0.1s')\n"
                   "sys.exit(1)\n", encoding="utf-8")
    return f'"{sys.executable}" "{red}"'


def test_commit_red_suite_refuses_keeps_changes_and_pushes_nothing(tmp_path: Path, capsys):
    # a root-level file: the core's `suite_free_paths` (config/*.json) would make a config JSON suite-free
    bare, checkout = _world(tmp_path)
    (checkout / "state.txt").write_text("v1\n", encoding="utf-8")
    origin_before = _git("rev-parse", "main", cwd=bare).stdout.strip()
    local_before = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()

    result = run_commit(["state.txt"], "state: x", cwd=checkout, lock_path=tmp_path / "merge.lock",
                        lock_timeout=10, suite_cmd=_red_suite_cmd(tmp_path))

    assert not result.ok and result.reason == "red-suite"
    assert "1 failed: tests/test_x.py::test_boom" in result.message
    assert _git("rev-parse", "main", cwd=bare).stdout.strip() == origin_before
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == local_before
    assert (checkout / "state.txt").read_text(encoding="utf-8") == "v1\n"
    assert "state.txt" in _git("status", "--porcelain", "-uall", cwd=checkout).stdout
    assert not (tmp_path / "merge.lock").exists()
    assert "test_boom" in capsys.readouterr().out


def test_commit_red_suite_after_origin_moved_resets_to_the_synced_head(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    mover = _clone(bare, tmp_path / "mover")
    _commit(mover, "other.txt", "upstream\n", "upstream change")
    _git("push", "-q", "origin", "main", cwd=mover)
    new_origin = _origin_main_head(bare)
    (checkout / "state.txt").write_text("v1\n", encoding="utf-8")

    result = run_commit(["state.txt"], "state: x", cwd=checkout, lock_path=tmp_path / "merge.lock",
                        lock_timeout=10, suite_cmd=_red_suite_cmd(tmp_path))

    assert not result.ok and result.reason == "red-suite"
    assert _origin_main_head(bare) == new_origin
    assert _git("rev-parse", "HEAD", cwd=checkout).stdout.strip() == new_origin
    status = _git("status", "--porcelain", "-uall", cwd=checkout).stdout.split("\n")
    # the standing suite worktree lives under .claude/ (ignored in the real repo, not in this tmp one)
    assert [line[3:] for line in status if line and not line[3:].startswith(".claude/")] == ["state.txt"]


def test_commit_red_suite_command_exits_nonzero_and_names_the_failing_test(tmp_path: Path, capsys,
                                                                            monkeypatch):
    bare, checkout = _world(tmp_path)
    (checkout / "state.txt").write_text("v1\n", encoding="utf-8")
    red = _red_suite_cmd(tmp_path)
    monkeypatch.setattr(merge_module, "resolve_suite_cmd", lambda explicit=None: red)
    args = argparse.Namespace(message="state", paths=["state.txt"], cwd=checkout,
                              lock=tmp_path / "merge.lock", timeout=10.0)

    exit_code = run_commit_command(args)
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "1 failed: tests/test_x.py::test_boom" in out
    assert _git("rev-list", "--count", "HEAD", cwd=checkout).stdout.strip() == "1"


def test_commit_green_suite_with_a_non_docs_path_commits_and_pushes(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    (checkout / "state.txt").write_text("v1\n", encoding="utf-8")
    counter, flag = tmp_path / "counter", tmp_path / "flag"

    result = run_commit(["state.txt"], "state: x", cwd=checkout, lock_path=tmp_path / "merge.lock",
                        lock_timeout=10, suite_cmd=suite_cmd(counter, flag))

    assert result.ok and result.pushed, result.message
    assert counter.read_text() == "1"
    head = _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()
    assert _git("rev-parse", "main", cwd=bare).stdout.strip() == head
    assert _git("show", "--name-only", "--format=", "HEAD", cwd=checkout).stdout.split() == ["state.txt"]


def test_commit_of_docs_markdown_only_never_runs_the_suite(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    (checkout / "docs" / "agents").mkdir(parents=True)
    (checkout / "docs" / "STATE.md").write_text("state\n", encoding="utf-8")
    (checkout / "docs" / "agents" / "x.md").write_text("x\n", encoding="utf-8")
    counter, flag = tmp_path / "counter", tmp_path / "flag"

    result = run_commit(["docs/STATE.md", "docs/agents/x.md"], "docs", cwd=checkout,
                        lock_path=tmp_path / "merge.lock", lock_timeout=10,
                        suite_cmd=suite_cmd(counter, flag))

    assert result.ok and result.pushed, result.message
    assert not counter.exists()
    assert _git("rev-parse", "main", cwd=bare).stdout.strip() == \
        _git("rev-parse", "HEAD", cwd=checkout).stdout.strip()


def test_commit_needs_suite_only_outside_docs_markdown():
    assert not commit_needs_suite(["docs/STATE.md", "docs/agents/x.md", "./docs/a.md"])
    assert not commit_needs_suite(["config/x.json"])  # #40: the core's suite_free_paths include config/*.json
    assert commit_needs_suite(["docs/STATE.md", "state.txt"])
    assert commit_needs_suite(["docs/data.json"])
    assert commit_needs_suite(["README.md"])


# -- row 6: `merge` reports a diverged checkout the same way `commit` does -----------------------

def test_merge_diverged_reports_the_state_like_commit_does(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"
    _push_branch(bare, tmp_path, "worker-m", "feature-m", "m.py", "m = 1\n")

    _commit(checkout, "local.txt", "local = 1\n", "checkout: local unpushed commit")

    mover = _clone(bare, tmp_path / "mover-row6")
    _commit(mover, "remote.txt", "remote = 1\n", "origin: moved on")
    _git("push", "-q", "origin", "main", cwd=mover)

    counter, flag = tmp_path / "counter-m.txt", tmp_path / "flag-m.txt"
    result = run_merge("origin/feature-m", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=lock_path, lock_timeout=10)

    assert not result.ok
    assert result.reason == "sync-failed"
    assert result.render().startswith("not merged (sync-failed): diverged: 1 ahead, 1 behind")


# -- 7. the core check: every core file 0/0/0/0, the new module in the manifest ------------------

def test_core_check_stays_clean_with_the_new_module():
    rows, ok = run_check()
    assert ok
    by_path = {row.path: row for row in rows}
    assert "tools/agentops/merge.py" in by_path
    row = by_path["tools/agentops/merge.py"]
    # L1-L3 are the failing counts for a .py file; H (issue and decision references) is informational there
    assert (row.counts.get("L1", 0), row.counts.get("L2", 0), row.counts.get("L3", 0)) == (0, 0, 0)


# -- issue #212: a red merge names its tests, keeps the suite's output, and logs every attempt ----

def _make_pytest_suite(dir_path: Path, total: int, failing: int) -> None:
    """A small real pytest directory: the first ``failing`` of ``total`` tests fail."""
    dir_path.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(total):
        lines.append(f"def test_case_{i}():")
        lines.append("    assert False" if i < failing else "    assert True")
        lines.append("")
    (dir_path / "test_generated.py").write_text("\n".join(lines), encoding="utf-8")


def _pytest_suite_cmd(suite_dir: Path) -> str:
    return f'"{sys.executable}" -m pytest "{suite_dir}" -q'


def test_red_suite_names_the_failed_tests_and_keeps_the_output(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-x1", "feature-x1", "x1.py", "x1 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    head_before = _local_main_head(checkout)

    suite_dir = tmp_path / "suite-2-of-5"
    _make_pytest_suite(suite_dir, total=5, failing=2)
    suite_output_dir = tmp_path / "suite-out-1"

    result = run_merge("origin/feature-x1", _pytest_suite_cmd(suite_dir), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=suite_output_dir, merge_log_path=tmp_path / "merge-1.log")

    assert not result.ok
    assert result.reason == "red-suite"
    assert result.failed_count == 2
    assert len(result.failed_tests) == 2
    for test_id in result.failed_tests:
        assert test_id in result.message
    assert _local_main_head(checkout) == head_before

    output_path = Path(result.suite_output_path)
    assert output_path.exists()
    output_text = output_path.read_text(encoding="utf-8")
    assert "2 failed" in output_text and "3 passed" in output_text


def test_red_suite_with_7_failures_caps_ids_at_5_and_more(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-x2", "feature-x2", "x2.py", "x2 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    suite_dir = tmp_path / "suite-7-of-7"
    _make_pytest_suite(suite_dir, total=7, failing=7)
    suite_output_dir = tmp_path / "suite-out-2"

    result = run_merge("origin/feature-x2", _pytest_suite_cmd(suite_dir), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=suite_output_dir, merge_log_path=tmp_path / "merge-2.log")

    assert not result.ok
    assert result.reason == "red-suite"
    assert result.failed_count == 7
    assert "and 2 more" in result.message
    for test_id in result.failed_tests[:5]:
        assert test_id in result.message


def test_green_suite_logs_merged_and_0_failed(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-x3", "feature-x3", "x3.py", "x3 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    suite_dir = tmp_path / "suite-green"
    _make_pytest_suite(suite_dir, total=3, failing=0)
    suite_output_dir = tmp_path / "suite-out-3"
    merge_log_path = tmp_path / "merge-3.log"

    result = run_merge("origin/feature-x3", _pytest_suite_cmd(suite_dir), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=suite_output_dir, merge_log_path=merge_log_path)

    assert result.ok, result.message
    assert result.failed_count == 0
    output_path = Path(result.suite_output_path)
    assert output_path.exists()

    log_lines = merge_log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert "merged" in log_lines[0] and "0 failed" in log_lines[0]


def test_non_pytest_red_suite_names_only_the_path(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-x4", "feature-x4", "x4.py", "x4 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)

    not_pytest_cmd = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    suite_output_dir = tmp_path / "suite-out-4"

    result = run_merge("origin/feature-x4", not_pytest_cmd, cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30,
                       suite_output_dir=suite_output_dir, merge_log_path=tmp_path / "merge-4.log")

    assert not result.ok
    assert result.reason == "red-suite"
    assert result.failed_count is None
    assert "failed:" not in result.message
    assert str(Path(result.suite_output_path)) in result.render()


def test_22_merges_in_a_row_leave_20_output_files(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    suite_dir = tmp_path / "suite-22"
    _make_pytest_suite(suite_dir, total=1, failing=0)
    suite_output_dir = tmp_path / "suite-out-22"
    merge_log_path = tmp_path / "merge-22.log"
    lock_path = tmp_path / "merge.lock"

    for i in range(22):
        worker_name, branch, file_name = f"worker-y{i}", f"feature-y{i}", f"y{i}.py"
        _push_branch(bare, tmp_path, worker_name, branch, file_name, f"y{i} = 1\n")
        _git("fetch", "-q", "origin", cwd=checkout)
        result = run_merge(f"origin/{branch}", _pytest_suite_cmd(suite_dir), cwd=checkout,
                           lock_path=lock_path, lock_timeout=30,
                           suite_output_dir=suite_output_dir, merge_log_path=merge_log_path)
        assert result.ok, result.message

    files = list(suite_output_dir.glob("*.out"))
    assert len(files) == 20


def test_merge_log_holds_2_lines_with_human_durations(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    merge_log_path = tmp_path / "merge-two-lines.log"
    suite_output_dir = tmp_path / "suite-out-two-lines"
    lock_path = tmp_path / "merge.lock"

    # row 1: a red suite
    _push_branch(bare, tmp_path, "worker-z1", "feature-z1", "z1.py", "z1 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    red_suite_dir = tmp_path / "suite-two-lines-red"
    _make_pytest_suite(red_suite_dir, total=5, failing=2)
    red = run_merge("origin/feature-z1", _pytest_suite_cmd(red_suite_dir), cwd=checkout,
                    lock_path=lock_path, lock_timeout=30,
                    suite_output_dir=suite_output_dir, merge_log_path=merge_log_path)
    assert not red.ok

    # row 3: a green suite
    _push_branch(bare, tmp_path, "worker-z2", "feature-z2", "z2.py", "z2 = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    green_suite_dir = tmp_path / "suite-two-lines-green"
    _make_pytest_suite(green_suite_dir, total=3, failing=0)
    green = run_merge("origin/feature-z2", _pytest_suite_cmd(green_suite_dir), cwd=checkout,
                      lock_path=lock_path, lock_timeout=30,
                      suite_output_dir=suite_output_dir, merge_log_path=merge_log_path)
    assert green.ok, green.message

    log_lines = merge_log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 2
    for line in log_lines:
        # a bare count of seconds over 90 is forbidden (principle 7); these suites take well
        # under a second, so a plain "N s" with N < 90 (or a "min"/"h" unit) is the only shape.
        match = re.search(r"suite (-?\d+(?:\.\d+)?) (s|min|h)\b", line)
        assert match, line
        if match.group(2) == "s":
            assert float(match.group(1)) < 90


# -- issue #234: a call with no path args must never touch the real var/agentops/ files ----------

def test_run_merge_with_no_path_args_never_touches_the_real_var(tmp_path: Path):
    """The 12 pre-#212 calls in this file (and any future one) pass neither ``suite_output_dir``
    nor ``merge_log_path``. ``merge.SUITE_OUTPUT_DIR``/``merge.MERGE_LOG_PATH`` are looked up at
    call time (not bound as def-time defaults), so the autouse fixture's monkeypatch of those two
    module constants is enough to keep such a call off the real installation's files -- proven
    here against the real paths (``merge.ROOT`` itself is never monkeypatched)."""
    real_merge_log = merge_module.ROOT / "var" / "agentops" / "merge.log"
    real_suite_dir = merge_module.ROOT / "var" / "agentops" / "merge_suite"

    # What counts is what THIS test's own merge writes, not a raw before/after compare: a real
    # merge or a detached result of another session may append to the live files meanwhile (#417).
    def _live_log_lines() -> set[str]:
        return set(real_merge_log.read_text(encoding="utf-8", errors="replace").splitlines())             if real_merge_log.exists() else set()

    def _live_suite_files() -> set[Path]:
        return set(real_suite_dir.glob("*")) if real_suite_dir.exists() else set()

    log_before, suite_before = _live_log_lines(), _live_suite_files()

    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-guard", "feature-guard", "guard.py", "guard = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    counter, flag = tmp_path / "counter-guard.txt", tmp_path / "flag-guard.txt"

    result = run_merge("origin/feature-guard", suite_cmd(counter, flag), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)
    assert result.ok, result.message

    own_marks = ("feature-guard", str(tmp_path))
    new_lines = _live_log_lines() - log_before
    assert not [ln for ln in new_lines if any(m in ln for m in own_marks)], new_lines
    own_files = []
    for f in _live_suite_files() - suite_before:
        try:
            text = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""
        except OSError:
            continue
        if any(m in text for m in own_marks):
            own_files.append(f)
    assert not own_files, own_files


# -- issue #240: `commit --state-entry` -- one Updated line per writer, written under the lock ----

def _state_seed(checkout: Path, bare: Path, tmp_path: Path, body: str = "Updated: original\n") -> None:
    """Seed the bare origin (and fast-forward ``checkout``) with a State-style file holding
    ``body``'s one ``Updated`` line, the file's own shape today (row 7)."""
    seeder = _clone(bare, tmp_path / "state-seeder")
    (seeder / "state.txt").write_text(body, encoding="utf-8")
    _git("add", "state.txt", cwd=seeder)
    _git("commit", "-q", "-m", "seed state.txt", cwd=seeder)
    _git("push", "-q", "origin", "main", cwd=seeder)
    _git("fetch", "-q", "origin", cwd=checkout)
    _git("merge", "-q", "--ff-only", "origin/main", cwd=checkout)


# -- row 1: red on main first -- two writers race the same line, one entry is lost ---------------

def test_row1_two_writers_race_the_shared_line_on_main_loses_one(tmp_path: Path):
    """This reproduces #240's own incident with plain `commit` (no `--state-entry`) against a
    shared `Updated:` line: writer A edits it and stages it (`git add`); before A's `commit`
    runs, writer B overwrites the same line in the one shared checkout and commits first (this
    is exactly what happens across the merge lock's wait: whoever gets the lock next commits
    whatever the file holds then). A's own `git add` staged content is silently replaced by B's
    working-tree overwrite (the same file, one working tree), so A's `commit` finds nothing of
    its own staged and answers `commit-failed` with an empty reason -- main's own behavior,
    reproduced here directly with plain git rather than through the lock's timing. The fix
    (the rows below) has writers hand their entry's text to `commit --state-entry` instead of
    editing this shared line by hand."""
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path)

    (checkout / "state.txt").write_text("Updated: writer A's entry\n", encoding="utf-8")
    _git("add", "state.txt", cwd=checkout)

    # B's edit lands in the one shared working tree before A's commit runs, and B commits first
    (checkout / "state.txt").write_text("Updated: writer B's entry\n", encoding="utf-8")
    _git("add", "state.txt", cwd=checkout)
    b_commit = _git("commit", "-q", "-m", "State: B", "--", "state.txt", cwd=checkout)
    assert b_commit.returncode == 0

    a_commit = _git_allow_fail("commit", "-m", "State: A", "--", "state.txt", cwd=checkout)

    assert (checkout / "state.txt").read_text() == "Updated: writer B's entry\n"
    assert _git("log", "-1", "--format=%s", cwd=checkout).stdout.strip() == "State: B"
    assert a_commit.returncode != 0
    assert a_commit.stderr.strip() == "", "main's own empty reason for the loser"
    assert "writer A's entry" not in _git("log", "--format=%B", cwd=checkout).stdout, \
        "writer A's entry is lost"


# -- row 2: two writers, `--state-entry`, a third party holds the lock first, then releases -------

def test_row2_two_writers_state_entry_both_land_neither_lost(tmp_path: Path):
    """This test measures the ORDER the lock imposes between the two waiting writers and the
    third party that holds it first, not the speed either writer runs at. See `NO_LOAD_REACHES`
    above."""
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path)
    lock_path = tmp_path / "merge.lock"

    lock = MergeLock(lock_path)
    lock.acquire(NO_LOAD_REACHES)

    results: dict[str, object] = {}

    def writer(name: str, entry: str):
        results[name] = run_commit(["state.txt"], f"State: {name}", cwd=checkout,
                                   lock_path=lock_path, lock_timeout=NO_LOAD_REACHES,
                                   state_entry=entry, state_as=name)

    ta = threading.Thread(target=writer, args=("writer-a", "writer A's entry 2026-10-09 10:00"))
    tb = threading.Thread(target=writer, args=("writer-b", "writer B's entry 2026-10-09 10:00"))
    ta.start()
    tb.start()
    import time
    time.sleep(0.5)
    lock.release()
    ta.join(NO_LOAD_REACHES)
    tb.join(NO_LOAD_REACHES)
    assert not ta.is_alive() and not tb.is_alive()

    a, b = results["writer-a"], results["writer-b"]
    assert a.ok, a.message
    assert b.ok, b.message

    text = (checkout / "state.txt").read_text()
    assert "Updated (writer-a): writer A's entry" in text
    assert "Updated (writer-b): writer B's entry" in text

    fresh = _clone(bare, tmp_path / "verify-row2")
    log = _git("log", "--format=%s", "main", cwd=fresh).stdout.strip().splitlines()
    assert "State: writer-a" in log
    assert "State: writer-b" in log
    remote_text = (fresh / "state.txt").read_text()
    assert "Updated (writer-a): writer A's entry" in remote_text
    assert "Updated (writer-b): writer B's entry" in remote_text


# -- row 3: the same writer twice -- one line of that writer, the newer text ----------------------

def test_row3_same_writer_twice_keeps_one_line_the_newer_text(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path)  # the file's own shape today: one unnamed line
    lock_path = tmp_path / "merge.lock"

    r1 = run_commit(["state.txt"], "State: 1", cwd=checkout, lock_path=lock_path, lock_timeout=10,
                    state_entry="first entry 2026-10-09 10:00", state_as="writer-a")
    assert r1.ok, r1.message
    r2 = run_commit(["state.txt"], "State: 2", cwd=checkout, lock_path=lock_path, lock_timeout=10,
                    state_entry="second entry 2026-10-09 10:00", state_as="writer-a")
    assert r2.ok, r2.message

    text = (checkout / "state.txt").read_text()
    lines = [line for line in text.splitlines() if line.startswith("Updated")]
    writer_a_lines = [line for line in lines if line.startswith("Updated (writer-a)")]
    assert len(writer_a_lines) == 1, "one line of that writer"
    assert writer_a_lines[0] == "Updated (writer-a): second entry 2026-10-09 10:00", "the newer text"


# -- row 4: 7 writers one after another -- 6 lines, the oldest gone -------------------------------

def test_row4_seven_writers_keeps_six_lines_oldest_gone(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path)
    lock_path = tmp_path / "merge.lock"

    for i in range(1, 8):
        result = run_commit(["state.txt"], f"State: {i}", cwd=checkout, lock_path=lock_path,
                            lock_timeout=10, state_entry=f"entry {i} 2026-10-09 10:00", state_as=f"writer-{i}")
        assert result.ok, result.message

    text = (checkout / "state.txt").read_text()
    lines = [line for line in text.splitlines() if line.startswith("Updated")]
    assert len(lines) == 6
    assert "writer-1" not in text  # the oldest, dropped
    assert all(f"writer-{i}" in text for i in range(2, 8))


# -- row 5: another writer's uncommitted change elsewhere in the file stays byte for byte ---------

def test_row5_another_writers_uncommitted_change_survives_untouched(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    body = "# State\n\nsome intro text.\n\nUpdated: original\n\nLast review: none.\n"
    _state_seed(checkout, bare, tmp_path, body=body)
    lock_path = tmp_path / "merge.lock"

    other_change = body.replace("Last review: none.", "Last review: SOMETHING ELSE, uncommitted.")
    (checkout / "state.txt").write_text(other_change, encoding="utf-8")
    assert (checkout / "state.txt").read_text() == other_change

    result = run_commit(["state.txt"], "State: entry", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10, state_entry="a fresh entry 2026-10-09 10:00", state_as="writer-a")
    assert result.ok, result.message

    diff = _git("show", "--format=", "HEAD", cwd=checkout).stdout
    changed_lines = [line for line in diff.splitlines()
                     if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    assert all("Last review" not in line for line in changed_lines), \
        "the commit's diff is the entry's line alone"
    assert any("a fresh entry" in line for line in changed_lines)

    working_text = (checkout / "state.txt").read_text()
    assert "SOMETHING ELSE, uncommitted" in working_text, "the other change stays in the working tree"
    assert "Updated (writer-a): a fresh entry" in working_text

    status = _git("status", "--porcelain", cwd=checkout).stdout
    assert "state.txt" in status, "still uncommitted: the Last review change was never staged"


# -- row 6: `commit` with paths that hold no change --------------------------------------------

def test_row6_nothing_to_commit_names_the_paths_not_an_empty_reason(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    result = run_commit(["README.md"], "no-op", cwd=checkout, lock_path=lock_path, lock_timeout=10)

    assert not result.ok
    assert result.reason == "nothing-to-commit"
    assert result.message == "README.md"
    assert result.render() == "not committed (nothing-to-commit): README.md"


def test_row6_state_entry_identical_to_head_is_also_nothing_to_commit(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path, body="Updated (writer-a): same text 2026-10-09 10:00\n")
    lock_path = tmp_path / "merge.lock"

    result = run_commit(["state.txt"], "no-op", cwd=checkout, lock_path=lock_path, lock_timeout=10,
                        state_entry="same text 2026-10-09 10:00", state_as="writer-a")

    assert not result.ok
    assert result.reason == "nothing-to-commit"
    assert result.message == "state.txt"


def test_row6_exit_code_is_distinct_from_a_generic_failure(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    lock_path = tmp_path / "merge.lock"

    args = argparse.Namespace(message="no-op", paths=["README.md"], cwd=checkout, lock=lock_path,
                              timeout=10.0, state_entry=None, state_as="")
    exit_code = run_commit_command(args)

    assert exit_code == 4
    assert exit_code not in (0, 1, 2, 3)


# -- row 7: the file as it is today (one unnamed `Updated:` line) at the first call ---------------

def test_row7_the_unnamed_line_is_kept_until_it_is_the_seventh(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path, body="Updated: the file's own shape today\n")
    lock_path = tmp_path / "merge.lock"

    result = run_commit(["state.txt"], "State: a", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10, state_entry="writer-a's entry 2026-10-09 10:00", state_as="writer-a")
    assert result.ok, result.message

    text = (checkout / "state.txt").read_text()
    lines = [line for line in text.splitlines() if line.startswith("Updated")]
    assert len(lines) == 2
    assert "Updated: the file's own shape today" in lines
    assert "Updated (writer-a): writer-a's entry 2026-10-09 10:00" in lines

    # so far: unnamed (oldest) + writer-a = 2 distinct writers. Four more new writers make 6,
    # still under the cap -- the unnamed line stays.
    for i in range(1, 5):
        result = run_commit(["state.txt"], f"State: {i}", cwd=checkout, lock_path=lock_path,
                            lock_timeout=10, state_entry=f"entry {i} 2026-10-09 10:00", state_as=f"writer-{i}")
        assert result.ok, result.message
    text = (checkout / "state.txt").read_text()
    lines = [line for line in text.splitlines() if line.startswith("Updated")]
    assert len(lines) == 6
    assert "Updated: the file's own shape today" in lines

    # the 7th distinct writer overall pushes the unnamed line (the oldest) out
    result = run_commit(["state.txt"], "State: 5", cwd=checkout, lock_path=lock_path,
                        lock_timeout=10, state_entry="entry 5 2026-10-09 10:00", state_as="writer-5")
    assert result.ok, result.message
    text = (checkout / "state.txt").read_text()
    lines = [line for line in text.splitlines() if line.startswith("Updated")]
    assert len(lines) == 6
    assert "Updated: the file's own shape today" not in lines


# -- the suite runs in the standing suite worktree, on the merge commit (issue #301) --------------

def _stand_in(tmp_path: Path) -> tuple[Path, Path]:
    """A world whose main holds a tiny pytest suite: ``tests/test_config.py`` reads the committed
    ``config.txt`` next to it, ``tests/test_where.py`` imports the tracked ``mod.py``."""
    bare, checkout = _world(tmp_path)
    (checkout / "tests").mkdir()
    (checkout / "tests" / "test_config.py").write_text(
        "from pathlib import Path\n\n\ndef test_config():\n"
        "    assert (Path(__file__).parent.parent / 'config.txt').read_text() == 'ok\\n'\n", encoding="utf-8")
    (checkout / "tests" / "test_where.py").write_text(
        "import mod\n\n\ndef test_where():\n"
        "    assert '.claude' in mod.__file__ and 'merge-suite' in mod.__file__, mod.__file__\n",
        encoding="utf-8")
    (checkout / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (checkout / "config.txt").write_text("ok\n", encoding="utf-8")
    _git("add", ".", cwd=checkout)
    _git("commit", "-q", "-m", "stand-in suite", cwd=checkout)
    _git("push", "-q", "origin", "main", cwd=checkout)
    return bare, checkout


def _pytest_suite() -> str:
    return f'"{sys.executable}" -m pytest tests -q -p no:cacheprovider'


def _worktree_lines(repo: Path) -> int:
    return len(_git("worktree", "list", cwd=repo).stdout.splitlines())


def _read_log_and_output(tmp_path: Path, result) -> str:
    return Path(result.suite_output_path).read_text(encoding="utf-8")


def test_suite_ignores_an_uncommitted_edit_of_the_main_checkout(tmp_path: Path):
    bare, checkout = _stand_in(tmp_path)
    _push_branch(bare, tmp_path, "worker-s1", "feature-s1", "s1.py", "s = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    (checkout / "config.txt").write_text("edited, uncommitted\n", encoding="utf-8")
    before = (checkout / "config.txt").read_bytes()

    result = run_merge("origin/feature-s1", _pytest_suite(), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok, result.render()
    assert result.reason == "pushed" and result.failed_count == 0
    assert (checkout / "config.txt").read_bytes() == before
    assert "1 failed" not in _read_log_and_output(tmp_path, result)


def test_suite_does_not_collect_an_untracked_file_of_the_main_checkout(tmp_path: Path):
    bare, checkout = _stand_in(tmp_path)
    _push_branch(bare, tmp_path, "worker-s2", "feature-s2", "s2.py", "s = 2\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    (checkout / "tests" / "test_untracked.py").write_text("def test_no():\n    assert False\n",
                                                          encoding="utf-8")

    result = run_merge("origin/feature-s2", _pytest_suite(), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert result.ok, result.render()
    output = _read_log_and_output(tmp_path, result)
    assert "2 passed" in output  # the two committed tests, not the untracked third
    assert "test_untracked" not in output
    assert (checkout / "tests" / "test_untracked.py").exists()


def test_suite_reds_on_a_branch_that_breaks_a_test(tmp_path: Path):
    bare, checkout = _stand_in(tmp_path)
    base = _local_main_head(checkout)
    worker = _clone(bare, tmp_path / "worker-s3")
    _git("checkout", "-q", "-b", "feature-s3", cwd=worker)
    _commit(worker, "config.txt", "broken\n", "break the config")
    _git("push", "-q", "origin", "feature-s3", cwd=worker)
    _git("fetch", "-q", "origin", cwd=checkout)
    origin_before = _origin_main_head(bare)

    result = run_merge("origin/feature-s3", _pytest_suite(), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert not result.ok and result.reason == "red-suite"
    assert result.failed_count == 1
    assert _origin_main_head(bare) == origin_before
    assert _local_main_head(checkout) == base
    assert (checkout / "config.txt").read_text(encoding="utf-8") == "ok\n"


def test_merge_log_names_the_suite_dir_and_two_merges_add_one_worktree(tmp_path: Path):
    bare, checkout = _stand_in(tmp_path)
    log = tmp_path / "own_merge.log"
    n0 = _worktree_lines(checkout)
    for i in (1, 2):
        _push_branch(bare, tmp_path, f"worker-s4{i}", f"feature-s4{i}", f"s4{i}.py", f"s = {i}\n")
        _git("fetch", "-q", "origin", cwd=checkout)
        result = run_merge(f"origin/feature-s4{i}", _pytest_suite(), cwd=checkout,
                           lock_path=tmp_path / "merge.lock", lock_timeout=30, merge_log_path=log)
        assert result.ok, result.render()
        assert _worktree_lines(checkout) == n0 + 1  # +1 at the first merge, +0 at the second
    suite_dir = checkout / ".claude" / "worktrees" / "merge-suite"
    assert result.suite_dir == str(suite_dir)
    assert all(f"suite dir {suite_dir}" in line for line in log.read_text(encoding="utf-8").splitlines())


def test_a_suite_worktree_error_is_a_failed_merge_rolled_back(tmp_path: Path, monkeypatch):
    bare, checkout = _stand_in(tmp_path)
    _push_branch(bare, tmp_path, "worker-s5", "feature-s5", "s5.py", "s = 5\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    base = _local_main_head(checkout)
    origin_before = _origin_main_head(bare)

    def boom(*args, **kwargs):
        raise merge_module.SuiteWorktreeError("no worktree today")
    monkeypatch.setattr(merge_module, "ensure_suite_worktree", boom)

    result = run_merge("origin/feature-s5", _pytest_suite(), cwd=checkout,
                       lock_path=tmp_path / "merge.lock", lock_timeout=30)

    assert not result.ok and result.reason == "suite-worktree"
    assert "no worktree today" in result.message
    assert _local_main_head(checkout) == base and _origin_main_head(bare) == origin_before


@pytest.mark.parametrize("cmd, want", [
    ("pytest -q -rs", "pytest -q -rsf"),
    ("pytest -q", "pytest -q -rf"),
    ("pytest -rf", "pytest -rf"),
    ("pytest -rsf", "pytest -rsf"),
    ("pytest -r s", "pytest -r sf"),
    ("pytest -q -ra", "pytest -q -ra"),
    ("python -m pytest tests -q -m \"not slow\"", "python -m pytest tests -q -m \"not slow\" -rf"),
    ("echo -rs", "echo -rs"),
])
def test_augmented_suite_cmd_merges_r_letters(cmd, want):
    """#348: pytest keeps only the last -r, so -f joins the letters of an existing -r."""
    assert merge_module._augmented_suite_cmd(cmd) == want


def test_state_entry_and_review_entry_in_one_call(tmp_path: Path):
    bare, checkout = _world(tmp_path)
    _state_seed(checkout, bare, tmp_path,
                body="Updated: original\n\nLast review: r1. Before it: r2. Before it: r3.\n")
    r = run_commit(["state.txt"], "State: both", cwd=checkout, lock_path=tmp_path / "merge.lock",
                   lock_timeout=10, state_entry="new state 2026-10-09 10:00", state_as="writer-a",
                   review_entry="r0")
    assert r.ok, r.message
    expect = ("Updated (writer-a): new state 2026-10-09 10:00\nUpdated: original\n\n"
              "Last review: r0. Before it: r1. Before it: r2.\n")
    assert (checkout / "state.txt").read_text() == expect
    fresh = _clone(bare, tmp_path / "verify-both")
    assert (fresh / "state.txt").read_text() == expect
    with pytest.raises(MergeError):
        run_commit(["state.txt", "other.txt"], "m", cwd=checkout, lock_path=tmp_path / "merge.lock",
                   review_entry="x")
