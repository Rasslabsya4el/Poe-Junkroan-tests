import os
import subprocess
import sys

import pytest

from junkroan.runs.pid_exit import open_exit_watch

win = pytest.mark.skipif(os.name != "nt", reason="Windows only")


def _child(code: int, sleep: float = 1.5) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time,sys; time.sleep({sleep}); sys.exit({code})"]
    )


@pytest.mark.skipif(os.name == "nt", reason="non-Windows only")
def test_non_windows_none():
    assert open_exit_watch(os.getpid()) is None


@win
def test_code_after_exit():
    p = _child(3)
    w = open_exit_watch(p.pid)
    assert w is not None
    assert w.poll() is None
    p.wait(timeout=30)
    assert w.poll() == 3
    assert w.poll() == 3
    w.close()


@win
def test_code_survives_reaped_popen():
    p = _child(3, 0.5)
    with open_exit_watch(p.pid) as w:
        assert p.wait(timeout=30) == 3
        del p
        assert w.poll() == 3


@win
def test_missing_pid():
    assert open_exit_watch(0x7FFFFFF0) is None


@win
def test_zero_code():
    p = _child(0, 0.3)
    w = open_exit_watch(p.pid)
    p.wait(timeout=30)
    assert w.poll() == 0
    w.close()


@win
def test_close_twice():
    p = _child(0, 0.1)
    w = open_exit_watch(p.pid)
    p.wait(timeout=30)
    w.close()
    w.close()
