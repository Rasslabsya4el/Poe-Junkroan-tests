"""Burners (#842): processes whose only job is to use the processor, started at BELOW_NORMAL for a bounded time.

The one entry for every rig or test that needs a busy machine. ``start_burners`` returns a handle; ``close``
(or leaving the ``with`` block) kills what is left. Each burner also exits by itself at its deadline or when
the starting process is gone, so a terminated caller leaves no orphan.
On the PC by day more than one burner is refused (``BurnerRefused``): the owner's desktop is in use.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import psutil

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
BELOW_NORMAL = 0x00004000 if os.name == "nt" else 0

# argv: parent pid, seconds to live (counted from the burner's own start, so a slow spawn cannot eat them)
_BURNER_CODE = (
    "import sys, time, psutil\n"
    "parent, deadline = int(sys.argv[1]), time.time() + float(sys.argv[2])\n"
    "last = 0.0\n"
    "while True:\n"
    "    sum(range(10000))\n"
    "    now = time.time()\n"
    "    if now > deadline:\n"
    "        break\n"
    "    if now - last > 0.25:\n"
    "        last = now\n"
    "        if not psutil.pid_exists(parent):\n"
    "            break\n"
)


class BurnerRefused(RuntimeError):
    """More than one burner on the PC by day."""


def refusal(host: str, period: str, count: int) -> str | None:
    """A reason not to start, or None. The PC by day with more than one burner is refused."""
    if host == "pc" and period == "day" and count > 1:
        return (f"refused: {count} burners on the PC by day (08:00-01:00); more than 1 is allowed on the PC "
                f"only 01:00-08:00; run the row on the laptop (through the queue) or between 01:00 and 08:00")
    return None


def _tree(proc: psutil.Process) -> list[psutil.Process]:
    try:
        return proc.children(recursive=True) + [proc]
    except psutil.Error:
        return [proc]


class Burners:
    def __init__(self, procs: list[subprocess.Popen]):
        self.procs = procs

    def pids(self) -> list[int]:
        return [p.pid for p in self.procs]

    def wait(self, timeout: float | None = None) -> None:
        end = None if timeout is None else time.time() + timeout
        for p in self.procs:
            left = None if end is None else max(0.0, end - time.time())
            try:
                p.wait(left)
            except subprocess.TimeoutExpired:
                return

    def close(self) -> None:
        victims = []
        for p in self.procs:
            try:
                victims += _tree(psutil.Process(p.pid))
            except psutil.Error:
                pass
        for v in victims:
            try:
                v.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(victims, timeout=5)
        for p in self.procs:
            try:
                p.kill()
                p.wait(5)
            except (OSError, subprocess.SubprocessError):
                pass

    def __enter__(self) -> "Burners":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def start_burners(count: int, seconds: float, host: str | None = None, period: str | None = None,
                  priority: str = "below_normal") -> Burners:
    """Start ``count`` burners for at most ``seconds``; raises BurnerRefused (nothing started) on the PC by day.

    ``host`` / ``period`` default to ``slot_budget.current_host()`` / ``hosts.current_period()``
    (``JUNKROAN_HOST`` and ``JUNKROAN_FORCE_PERIOD`` force them). ``priority``: below_normal or normal.
    """
    if host is None:
        from junkroan.pob.slot_budget import current_host
        host = current_host()
    if period is None:
        from junkroan.runs.hosts import current_period
        period = current_period()
    reason = refusal(host, period, count)
    if reason:
        raise BurnerRefused(reason)
    flags = NO_WINDOW | (BELOW_NORMAL if priority == "below_normal" else 0)
    procs: list[subprocess.Popen] = []
    try:
        for _ in range(count):
            procs.append(subprocess.Popen(
                [sys.executable, "-c", _BURNER_CODE, str(os.getpid()), repr(float(seconds))], creationflags=flags,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL))
    except BaseException:
        Burners(procs).close()
        raise
    return Burners(procs)
