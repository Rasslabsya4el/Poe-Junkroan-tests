"""#839 job launch: the runs daemon starts a job BELOW_NORMAL by day (pc normal), unchanged by night."""

from __future__ import annotations

import subprocess
import sys

import pytest

from junkroan.runs import daemon as daemon_mod
from junkroan.runs import hosts as runs_hosts

BELOW_NORMAL = 0x4000
NORMAL = 0x20

_PROBE = (
    "import ctypes, subprocess, sys\n"
    "k = ctypes.windll.kernel32\n"
    "k.GetCurrentProcess.restype = ctypes.c_void_p\n"
    "k.GetPriorityClass.argtypes = [ctypes.c_void_p]\n"
    "def own(): return k.GetPriorityClass(k.GetCurrentProcess())\n"
    "if len(sys.argv) > 1:\n"
    "    print('child', hex(own()))\n"
    "else:\n"
    "    print('parent', hex(own()), flush=True)\n"
    "    print(subprocess.run([sys.executable, '-c', open(__file__).read(), 'g'], capture_output=True,\n"
    "                         text=True).stdout.replace('child', 'grandchild'), end='')\n"
)


@pytest.fixture(autouse=True)
def _pc_normal(monkeypatch):
    monkeypatch.setattr("junkroan.pob.slot_budget.current_host", lambda: "pc")
    monkeypatch.setattr(runs_hosts, "read_modes", lambda *a, **k: {"pc": {"mode": "normal"}})


def _flags_passed(monkeypatch, tmp_path):
    seen = {}

    class _P:
        pid = 1

    def fake_popen(cmd, **kw):
        seen.update(kw)
        return _P()

    monkeypatch.setattr(daemon_mod.subprocess, "Popen", fake_popen)
    daemon_mod.ProcessLauncher().start(["x"], cwd=tmp_path, out=tmp_path / "o.txt", env={})
    return seen["creationflags"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
def test_creationflags_day_has_below_normal(monkeypatch, tmp_path):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    flags = _flags_passed(monkeypatch, tmp_path)
    assert flags & BELOW_NORMAL
    assert flags & daemon_mod._JOB_CREATIONFLAGS == daemon_mod._JOB_CREATIONFLAGS


def test_creationflags_night_unchanged(monkeypatch, tmp_path):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")
    assert _flags_passed(monkeypatch, tmp_path) == daemon_mod._JOB_CREATIONFLAGS


@pytest.fixture()
def _normal_self():
    """The test process may itself run BELOW_NORMAL (merge suite, daemon): children would inherit it."""
    import psutil

    me = psutil.Process()
    before = me.nice()
    me.nice(psutil.NORMAL_PRIORITY_CLASS)
    yield
    me.nice(before)


def _run_job(tmp_path):
    script = tmp_path / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    out = tmp_path / "out.txt"
    launched = daemon_mod.ProcessLauncher().start([sys.executable, str(script)], cwd=tmp_path, out=out,
                                                  env=None)
    launched._process.wait(timeout=60)
    launched.close()
    return dict(line.split() for line in out.read_text(encoding="utf-8").splitlines())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows priority classes")
@pytest.mark.parametrize("period,expected", [("day", BELOW_NORMAL), ("night", NORMAL)])
def test_job_and_grandchild_priority_class(_normal_self, monkeypatch, tmp_path, period, expected):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
    got = _run_job(tmp_path)
    assert int(got["parent"], 16) == expected
    assert int(got["grandchild"], 16) == expected
