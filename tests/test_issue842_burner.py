"""#842 unit 1: the shared burner helper. Period and host are always forced; at most 12 burners for 2 s."""
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from junkroan import burner  # noqa: E402

sys.path.insert(0, str(ROOT / "tests"))
from timing_bound import bound  # noqa: E402

SCRIPT = ROOT / "scripts" / "burner.py"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _env(period, host=None):
    e = dict(os.environ, JUNKROAN_FORCE_PERIOD=period)
    if host:
        e["JUNKROAN_HOST"] = host
    return e


def many_real_ok():
    """May this machine start many REAL spinners now? Read from the real host and real clock (#869): not the PC by day."""
    from junkroan.pob.slot_budget import current_host
    from junkroan.runs.hosts import current_period
    return burner.refusal(current_host(), current_period(), 2) is None


NOT_HERE = "12 real spinners only on the laptop or at night (01:00-08:00); on the PC by day the launch is recorded instead"
_CHILD_SPINNERS: list[int] = []  # spinners started inside child processes by the cases (for the #869 count)


class _FakeProc:
    pid = 0

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


def _record_popen(monkeypatch):
    """Replace the Popen of burner.py by a recorder; nothing reaches a real process."""
    calls = []

    def fake(args, **kw):
        calls.append((args, kw))
        return _FakeProc()

    monkeypatch.setattr(burner.subprocess, "Popen", fake)
    monkeypatch.setattr(burner.Burners, "close", lambda self: None)
    return calls


def _check_recorded(calls, count, life):
    assert len(calls) == count
    for args, kw in calls:
        assert kw["creationflags"] & burner.BELOW_NORMAL == burner.BELOW_NORMAL
        assert args[3] == str(os.getpid())  # the parent pid
        assert float(args[4]) == pytest.approx(life)  # the deadline


def _alive(pids):
    out = []
    for p in pids:
        try:
            if psutil.Process(p).status() != psutil.STATUS_ZOMBIE:
                out.append(p)
        except (psutil.Error, OSError):
            pass
    return out


def test_pc_day_12_refused(monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    before = len(psutil.Process().children(recursive=True))
    r = subprocess.run([sys.executable, str(SCRIPT), "--count", "12", "--seconds", "2"], capture_output=True,
                       text=True, timeout=bound(30.0, 400), env=_env("day", "pc"), creationflags=NO_WINDOW)
    assert r.returncode != 0
    assert "laptop" in r.stderr and "01:00-08:00" in r.stderr
    with pytest.raises(burner.BurnerRefused):
        burner.start_burners(12, 2)
    assert len(psutil.Process().children(recursive=True)) == before  # 0 started


def test_pc_day_one_burner_allowed(monkeypatch):
    with burner.start_burners(1, 2, host="pc", period="day") as b:
        assert len(b.pids()) == 1


def _burners_below_normal_then_gone(host, period, monkeypatch):
    if not many_real_ok():
        calls = _record_popen(monkeypatch)
        burner.start_burners(12, 2.0, host=host, period=period)
        _check_recorded(calls, 12, 2.0)
        pytest.skip(NOT_HERE)
    # under load 12 spawns take seconds and a burner's life counts from its own start: the life and the bounds
    # follow the machine (tests/timing_bound.py), a quiet machine keeps the floors (4 s life, 15 s total).
    # #855: the 15 s total counts from the moment the spawn returned (a loaded spawn took ~3 min once in a full
    # run, the burners themselves ended in time), and the load is read before the spawn too (the load may be gone
    # by the time the bound is read after it)
    life = bound(4.0, 12)
    total = bound(15.0, 400)
    b = burner.start_burners(12, life, host=host, period=period)
    t0 = time.time()
    pids = b.pids()
    assert len(pids) == 12
    # #855: the first burner of 12 slow spawns may have ended by its own deadline before it is looked at (a
    # NoSuchProcess in the full run's neighbour runs); one that ended by itself (exit 0) is not a failure,
    # but every burner still alive must be below normal, and at least one must be seen
    seen = 0
    for p, pid in zip(b.procs, pids):
        try:
            assert psutil.Process(pid).nice() == psutil.BELOW_NORMAL_PRIORITY_CLASS
            seen += 1
        except psutil.NoSuchProcess:
            assert p.poll() == 0, "a burner vanished without ending by its own deadline"
    assert seen >= 1
    b.wait(life + 8)
    b.close()
    assert time.time() - t0 < max(total, bound(15.0, 400))
    end = time.time() + bound(5.0, 30)
    while time.time() < end and _alive(pids):
        time.sleep(0.2)
    assert _alive(pids) == []


@pytest.mark.parametrize("host,period", [("pc", "night"), ("laptop", "day")])
def test_12_burners_below_normal_then_gone(host, period, monkeypatch):
    _burners_below_normal_then_gone(host, period, monkeypatch)


def test_slow_spawn_does_not_count_against_the_burners_total(monkeypatch):
    # the red of 9909ca4d: the time before the burners existed (the spawn) was counted into the 15 s total.
    # Here the spawn is simulated slow (16 s) against the 15 s floor of the total: the burners end at once, the test is green
    if not many_real_ok():  # PC by day: recorded launch only (no 16 s sleep, no real spinner)
        _burners_below_normal_then_gone("laptop", "day", monkeypatch)
    real = burner.start_burners

    def slow(*a, **k):
        time.sleep(16.0)
        return real(*a, **k)

    monkeypatch.setattr(burner, "start_burners", slow)
    _burners_below_normal_then_gone("laptop", "day", monkeypatch)


def test_script_laptop_day_runs_and_ends(monkeypatch):
    if not many_real_ok():
        import importlib.util
        spec = importlib.util.spec_from_file_location("burner_script", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        calls = _record_popen(monkeypatch)
        monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")
        assert mod.main(["--count", "12", "--seconds", "2", "--host", "laptop"]) == 0
        _check_recorded(calls, 12, 2.0)
        pytest.skip(NOT_HERE)
    r = subprocess.run([sys.executable, str(SCRIPT), "--count", "12", "--seconds", "2", "--host", "laptop"],
                       capture_output=True, text=True, timeout=bound(30.0, 400), env=_env("day"), creationflags=NO_WINDOW)
    assert r.returncode == 0, r.stderr


PARENT = (
    "import sys, time\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "from junkroan.burner import start_burners\n"
    "b = start_burners(int(sys.argv[2]), 60,host='laptop', period='day')\n"
    "print(' '.join(map(str, b.pids())), flush=True)\n"
    "time.sleep(60)\n"
)


def test_caller_killed_leaves_no_burner():
    n = 4 if many_real_ok() else 1  # by day on the PC: one real spinner; the parent's kill is what is proven
    _CHILD_SPINNERS.append(n)
    parent = subprocess.Popen([sys.executable, "-c", PARENT, str(ROOT / "src"), str(n)], stdout=subprocess.PIPE,
                              text=True, creationflags=NO_WINDOW)
    try:
        pids = [int(x) for x in parent.stdout.readline().split()]
        assert len(pids) == n and len(_alive(pids)) == n
        parent.kill()  # terminate: no finally, no atexit runs
        parent.wait(10)
        end = time.time() + 5
        while time.time() < end and _alive(pids):
            time.sleep(0.2)
        assert _alive(pids) == []
    finally:
        parent.kill()
