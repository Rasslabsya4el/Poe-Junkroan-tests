"""#839 unit 6: the daemon's tick re-classes live workers when the day/night period changes."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys

import pytest

from junkroan.runs import hosts as runs_hosts

BELOW_NORMAL = 0x4000
NORMAL = 0x20

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")


def _class_of(pid: int) -> int:
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)
    try:
        return k32.GetPriorityClass(ctypes.c_void_p(handle))
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    from tests.test_runs_daemon import BUDGET_NIGHT_10, FakeLauncher, make_daemon

    modes = tmp_path / "modes.json"
    modes.write_text(json.dumps({"pc": {"mode": "normal"}}), encoding="utf-8")
    daemon, _, _ = make_daemon(tmp_path, launcher=FakeLauncher(), budget=BUDGET_NIGHT_10,
                               hosts_config=runs_hosts.load_hosts_config())
    daemon._modes_file = modes
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    calls: list[tuple[list[int], str]] = []
    real = runs_hosts.set_priority_class

    def setter(pids, priority):
        calls.append((list(pids), priority))
        return real(pids, priority)

    daemon._pid_finder = lambda: [child.pid]
    daemon._priority_setter = setter
    try:
        yield daemon, child, calls, monkeypatch
    finally:
        child.kill()


def test_class_follows_period_within_one_tick_both_directions(rig):
    daemon, child, calls, monkeypatch = rig
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    daemon.tick()  # baseline tick: records the period, no call
    assert calls == []
    runs_hosts.set_priority_class([child.pid], "BelowNormal")
    assert _class_of(child.pid) == BELOW_NORMAL

    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
    daemon.tick()
    assert calls == [([child.pid], "Normal")]
    assert _class_of(child.pid) == NORMAL

    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    daemon.tick()
    assert calls[-1] == ([child.pid], "BelowNormal")
    assert len(calls) == 2
    assert _class_of(child.pid) == BELOW_NORMAL


def test_no_period_change_no_setter_call(rig):
    daemon, _, calls, monkeypatch = rig
    for period in ("day", "day", "day", "night", "night"):
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
        daemon.tick()
    assert len(calls) == 1  # only the day -> night change
