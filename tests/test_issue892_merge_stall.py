"""#892: the merge's suite run gets a StallWatch: a run in which no test finishes ends `stuck`; a plan that does not
cover the selected count is no bound (no false stall). Waits scale by one measured child start."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

from tools.agentops import merge
from tools.agentops.merge import StallWatch
from tools.agentops.suite_plan import plan_path
from tests.test_issue829_stall import FAR, Clock, _unit


def _suite(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake_suite.py"
    p.write_text(body, encoding="utf-8")
    return f'"{sys.executable}" "{p}"'


def _write_plan(out: Path, n: int, longest: float) -> None:
    plan_path(out).write_text(json.dumps({"seconds": [longest] + [0.1] * (n - 1)}), encoding="utf-8")


def test_a_plan_shorter_than_the_selected_count_is_no_bound(tmp_path):
    out = tmp_path / "s.out"
    _write_plan(out, 9, 0.2)                    # 9 numbers for 5303 selected tests (the 2026-10-11 file)
    clock = Clock()
    w = StallWatch(out, interval=1, factor=3, min_share=0.05, clock=clock, expected=5303, total_limit=FAR)
    clock.t = 10 ** 6
    assert w.tick("", cpu_now=0.0) == ""
    full = StallWatch(out, interval=1, factor=3, min_share=0.05, clock=clock, expected=9, total_limit=FAR)
    clock.t = 2 * 10 ** 6
    assert full.tick(".", cpu_now=0.0) == ""    # #1020: the first dot opens the window
    clock.t = 2 * 10 ** 6 + 100
    assert full.tick(".", cpu_now=0.0) != ""    # a covering plan does bound


def test_a_silent_merge_suite_ends_stuck_and_leaves_no_process(tmp_path, monkeypatch):
    unit = _unit()
    longest = 10 * unit
    out = tmp_path / "s.out"
    _write_plan(out, 4, longest)
    monkeypatch.setattr(merge, "STALL_POLL_SECONDS", unit / 2)
    monkeypatch.setattr(merge, "STALL_FACTOR", 1)
    monkeypatch.setattr(merge, "STALL_MIN_SHARE", 1.0)
    pidfile = tmp_path / "pid"
    cmd = _suite(tmp_path, f"import subprocess, sys, time\n"
                           f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({60 * longest})'])\n"
                           f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
                           f"sys.stdout.write('..'); sys.stdout.flush()\ntime.sleep({60 * longest})\n")  # #1020: two dots, then none
    run = merge._run_merge_suite(cmd, cmd, 1, "selected 4 of 9 (map abcdef12)", tmp_path, None, out)
    assert not run.ok
    assert run.stuck.startswith("stalled: no test finished for ") and "last suite line: '..'" in run.stuck
    assert "pids held: " in run.stuck and run.stuck.split("pids held: ")[1].strip()
    time.sleep(2 * unit)
    assert not psutil.pid_exists(int(pidfile.read_text()))   # the grandchild of the fake tree is gone


def test_the_total_limit_ends_a_silent_run_whose_plan_does_not_cover_the_count(tmp_path, monkeypatch):
    unit = _unit()
    out = tmp_path / "s.out"
    _write_plan(out, 9, 0.2)                    # 9 numbers for 5303 selected tests: the plan gives no bound
    monkeypatch.setattr(merge, "STALL_POLL_SECONDS", unit / 2)
    monkeypatch.setattr(merge, "resolve_suite_total_limit", lambda: 10 * unit)
    pidfile = tmp_path / "pid"
    cmd = _suite(tmp_path, f"import subprocess, sys, time\n"
                           f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep({600 * unit})'])\n"
                           f"open({str(pidfile)!r}, 'w').write(str(c.pid))\n"
                           f"print('..', flush=True)\ntime.sleep({600 * unit})\n")
    run = merge._run_merge_suite(cmd, cmd, 1, "selected 5303 of 9000 (map abcdef12)", tmp_path, None, out)
    assert not run.ok and "total limit" in run.stuck and "last suite line: '..'" in run.stuck
    time.sleep(2 * unit)
    assert not psutil.pid_exists(int(pidfile.read_text()))


def test_the_commit_gate_reports_a_stuck_run_as_stuck_not_red_suite(tmp_path, monkeypatch):
    from tests.test_issue690_merge_select import Rig
    from tools.agentops.merge import SuiteRun, run_commit
    rig = Rig(tmp_path, monkeypatch)
    reason = "stalled: the suite run passed its total limit 3 min (merge_suite_total_limit); run ended"
    monkeypatch.setattr(merge, "_run_merge_suite",
                        lambda *a, **k: SuiteRun(False, "..\n" + reason + "\n", 1, stuck=reason + "; last suite line: '..'; pids held: 1"))
    (rig.checkout / "src").mkdir(exist_ok=True)
    (rig.checkout / "src/a.py").write_text("a = 2\n", encoding="utf-8")
    res = run_commit(["src/a.py"], "change", cwd=rig.checkout, lock_path=rig.tmp / "merge.lock", lock_timeout=30,
                     suite_cmd=rig.cmd, suite_output_dir=rig.tmp / "out", merge_log_path=rig.log)
    assert not res.ok and res.reason == "stuck" and "total limit" in res.message
    assert "| stuck |" in rig.log.read_text(encoding="utf-8")


def _quiet_run(tmp_path, monkeypatch, body: str, unit: float, limit: float):
    out = tmp_path / "s.out"
    _write_plan(out, 9, 0.2)                    # no plan bound, no total limit: only the quiet limit can act
    monkeypatch.setattr(merge, "STALL_POLL_SECONDS", unit / 2)
    monkeypatch.setattr(merge, "resolve_suite_total_limit", lambda: None)
    monkeypatch.setattr(merge, "resolve_suite_quiet_limit", lambda: limit)
    cmd = _suite(tmp_path, body)
    return merge._run_merge_suite(cmd, cmd, 1, "selected 5303 of 9000 (map abcdef12)", tmp_path, None, out)


def test_the_quiet_limit_ends_a_run_that_only_appends_non_progress_lines(tmp_path, monkeypatch):
    unit = _unit()
    body = ("import sys, time\nsys.stdout.write('..F.' + chr(10) + '.. [ 12%]' + chr(10)); sys.stdout.flush()\n"
            f"for i in range(100000):\n    print('restart poll: k_new 3, k 3, 100% done -> keep', flush=True)\n    time.sleep({unit / 4})\n")
    run = _quiet_run(tmp_path, monkeypatch, body, unit, 6 * unit)
    assert not run.ok and "merge_suite_quiet_limit" in run.stuck


def test_the_quiet_limit_spares_a_run_that_keeps_printing_progress(tmp_path, monkeypatch):
    unit = _unit()
    body = ("import sys, time\n"
            f"for i in range(30):\n    sys.stdout.write('.'); sys.stdout.flush(); time.sleep({unit})\n")
    run = _quiet_run(tmp_path, monkeypatch, body, unit, 8 * unit)
    assert run.ok and run.stuck == ""
