"""#839 unit 2: PoB workers are BELOW_NORMAL by day (pc normal), Normal by night; play/laptop unchanged."""

from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import time

import pytest

from junkroan.pob import headless_runtime_adapter as adapter
from junkroan.runs import hosts as runs_hosts

BELOW_NORMAL = 0x4000
NORMAL = 0x20


@pytest.fixture()
def cfg():
    return runs_hosts.load_hosts_config()


def _prio(cfg, host, mode):
    return runs_hosts.mode_priority(runs_hosts._host_entry(cfg, host), host, mode)


def test_mode_priority_by_period(cfg, monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    assert _prio(cfg, "pc", "normal") == "BelowNormal"
    assert _prio(cfg, "pc", "play") == "Idle"
    laptop = [h for h in cfg if h != "pc"]
    assert laptop
    day = {(h, m): _prio(cfg, h, m) for h in laptop for m in cfg[h]["modes"]}
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
    assert _prio(cfg, "pc", "normal") == "Normal"
    assert _prio(cfg, "pc", "play") == "Idle"
    assert day == {(h, m): _prio(cfg, h, m) for h in laptop for m in cfg[h]["modes"]}
    assert all(v in ("Normal", "Idle") for v in day.values())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
def test_set_priority_class_on_live_process():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert runs_hosts.set_priority_class([child.pid], "BelowNormal") == [child.pid]
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        handle = k32.OpenProcess(0x1000, False, child.pid)
        assert k32.GetPriorityClass(ctypes.c_void_p(handle)) == BELOW_NORMAL
        k32.CloseHandle(ctypes.c_void_p(handle))
    finally:
        child.kill()


def test_restore_path_and_spawn_flag_by_day(tmp_path, monkeypatch):
    from tests.test_runs_daemon import BUDGET_NIGHT_10, FakeLauncher, make_daemon

    modes = tmp_path / "modes.json"
    modes.write_text(json.dumps({"pc": {"mode": "normal"}}), encoding="utf-8")
    cfg = runs_hosts.load_hosts_config()
    daemon, _, _ = make_daemon(tmp_path, launcher=FakeLauncher(), budget=BUDGET_NIGHT_10, hosts_config=cfg)
    daemon._modes_file = modes
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    assert daemon._mode_priority_now() == "BelowNormal"
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
    assert daemon._mode_priority_now() == "Normal"

    monkeypatch.setattr(runs_hosts, "read_modes", lambda path=None: {"pc": {"mode": "normal"}})
    monkeypatch.setattr("junkroan.pob.slot_budget.current_host", lambda root=None: "pc")
    if sys.platform == "win32":
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
        assert adapter._day_priority_flag() == BELOW_NORMAL
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
        assert adapter._day_priority_flag() == 0
