"""Kill a running job's process tree (`runs.py stop`, the spike ladder's filler stop, #406)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable

from junkroan.runs.store import IllegalTransition, Job, Store


def taskkill_tree(pid: int, *, timeout: float = 30.0, gone_wait: float = 5.0) -> bool:
    """Kill `pid` and its whole tree (`taskkill /PID <pid> /T /F`). A pid already gone counts as
    done. Replaced by tests (`TREE_KILLER`). `timeout` bounds the taskkill call and `gone_wait` the
    pid check after a nonzero exit (#998: `bounded.run_bounded` passes shorter ones on its kill path)."""

    if sys.platform != "win32":
        import signal as _signal
        try:
            os.killpg(os.getpgid(pid), _signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return True
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        return True
    if "not found" in (result.stderr or result.stdout or "").lower():
        return True
    # taskkill can exit non-zero after the tree is dead (#412): the judge is the pid itself.
    return _pid_gone(pid, wait=gone_wait)


def taskkill_pid(pid: int) -> bool:
    """Kill only `pid`, never its children (`taskkill /PID <pid> /F`, no `/T`). Same result rules as
    `taskkill_tree`. The watchdog's takeover of a frozen daemon uses it: the jobs the daemon started
    are its children and must outlive it (#647)."""

    if sys.platform != "win32":
        import signal as _signal
        try:
            os.kill(pid, _signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        return True
    result = subprocess.run(
        ["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode == 0:
        return True
    if "not found" in (result.stderr or result.stdout or "").lower():
        return True
    return _pid_gone(pid)


def _pid_gone(pid: int, *, wait: float = 5.0) -> bool:
    """True when `pid` no longer exists, polled for up to `wait` seconds."""

    import time

    import psutil

    deadline = time.monotonic() + wait
    while True:
        if not psutil.pid_exists(pid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)


def kill_job(job: Job, killer: Callable[[int], bool]) -> str | None:
    """Kill the job's tree through `killer`. An error line, or None when killed (or no pid)."""

    pid = None
    if job.pid not in (None, ""):
        try:
            pid = int(job.pid)
        except (TypeError, ValueError):
            pid = None
    if pid is not None and not killer(pid):
        return f"stop: could not kill pid {pid} of job {job.id}; job left running"
    return None


def stop_job(store: Store, job: Job, who: str, killer: Callable[[int], bool], reason: str | None = None) -> str | None:
    """Kill the tree, then store the job `stopped` (#421), reason `stopped by <who>`. An error line, or None.
    The job is ended only after the kill did not fail."""

    err = kill_job(job, killer)
    if err:
        return err
    try:
        store.stop(job.id, reason=reason or f"stopped by {who}")
    except IllegalTransition as exc:
        return f"stop: {exc}"
    return None
