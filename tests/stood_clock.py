"""Test-local wall clocks that do not count the time the machine stood in play (D117, #779 rule 5)."""

from __future__ import annotations

import subprocess
import time

from tools.agentops.machine_mode import stood_between


def expired(started: float, timeout: float) -> bool:
    """True once `timeout` seconds have passed since `started` (time.time()), not counting play time."""
    now = time.time()
    return now - started - stood_between(started, now) >= timeout


def run(args, *, timeout: float, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run(..., capture_output=True, text=True)` whose timeout is `expired`'s clock."""
    started = time.time()
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **kwargs)
    while True:
        try:
            out, err = proc.communicate(timeout=1.0)
            return subprocess.CompletedProcess(args, proc.returncode, out, err)
        except subprocess.TimeoutExpired:
            if expired(started, timeout):
                proc.kill()
                proc.communicate()
                raise
