"""#758 rows 7, 8: the suite plan file writer (tools.agentops.suite_plan_plugin). PoB-free."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agentops import full_run
from tools.agentops.suite_plan_plugin import plan_seconds

ROOT = Path(__file__).resolve().parents[1]


def _child(tmp_path, args, extra_env):
    env = {k: v for k, v in os.environ.items() if k not in ("SUITE_PLAN_FILE", "SUITE_DURATIONS_FILE", "TESTMON_DATAFILE", "PYTEST_ADDOPTS")}
    env.update(extra_env)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "--basetemp", str(tmp_path.parent / (tmp_path.name + "-bt")), *args],
                          cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


def _make_suite(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "import time\n"
        "def test_x(): time.sleep(0.05)\n"
        "def test_y(): time.sleep(0.2)\n"
        "def test_z(): time.sleep(0.4)\n", encoding="utf-8")
    return tmp_path / "plan.json", tmp_path / "tm.db"


def test_row7_child_pytest_writes_the_stored_numbers_in_run_order(tmp_path):
    plan, db = _make_suite(tmp_path)
    first = _child(tmp_path, ["--testmon", "-p", "tools.agentops.suite_plan_plugin"], {"TESTMON_DATAFILE": str(db)})
    assert first.returncode == 0, first.stdout + first.stderr
    assert not plan.exists()  # env var unset: no file, even with stored durations

    import sqlite3
    con = sqlite3.connect(db)
    stored = dict(con.execute("SELECT test_name, duration FROM test_execution").fetchall())
    con.close()
    assert len(stored) == 3 and all(d > 0 for d in stored.values())

    second = _child(tmp_path, ["--testmon", "--testmon-noselect", "-p", "tools.agentops.suite_plan_plugin"],
                    {"TESTMON_DATAFILE": str(db), "SUITE_PLAN_FILE": str(plan)})
    assert second.returncode == 0, second.stdout + second.stderr
    seconds = json.loads(plan.read_text(encoding="utf-8"))["seconds"]
    assert len(seconds) == 3
    assert abs(sum(seconds) - sum(stored.values())) < 1e-9
    assert seconds == sorted(seconds, reverse=True)  # #755: descending by stored duration


def test_row7_unset_writes_no_file(tmp_path):
    plan, db = _make_suite(tmp_path)
    _child(tmp_path, ["--testmon", "-p", "tools.agentops.suite_plan_plugin"], {"TESTMON_DATAFILE": str(db)})
    r = _child(tmp_path, ["--testmon", "--testmon-noselect", "-p", "tools.agentops.suite_plan_plugin"],
               {"TESTMON_DATAFILE": str(db)})
    assert r.returncode == 0
    assert not plan.exists()


def test_durations_env_is_preferred_over_the_testmon_datafile(tmp_path):
    plan, db = _make_suite(tmp_path)
    _child(tmp_path, ["--testmon", "-p", "tools.agentops.suite_plan_plugin"], {"TESTMON_DATAFILE": str(db)})
    fresh = tmp_path / "fresh.db"  # empty: nothing stored
    r = _child(tmp_path, ["--testmon", "--testmon-noselect", "-p", "tools.agentops.suite_plan_plugin"],
               {"TESTMON_DATAFILE": str(fresh), "SUITE_DURATIONS_FILE": str(db),
                "SUITE_PLAN_FILE": str(plan)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert len(json.loads(plan.read_text(encoding="utf-8"))["seconds"]) == 3


def test_xdist_path_writes_the_plan(tmp_path):
    pytest.importorskip("xdist")
    plan, db = _make_suite(tmp_path)
    _child(tmp_path, ["--testmon", "-p", "tools.agentops.suite_plan_plugin"], {"TESTMON_DATAFILE": str(db)})
    r = _child(tmp_path, ["--testmon", "--testmon-noselect", "-n", "2", "-p", "tools.agentops.suite_plan_plugin"],
               {"TESTMON_DATAFILE": str(db), "SUITE_PLAN_FILE": str(plan)})
    assert r.returncode == 0, r.stdout + r.stderr
    seconds = json.loads(plan.read_text(encoding="utf-8"))["seconds"]
    print("xdist plan:", seconds)
    assert len(seconds) == 3 and seconds == sorted(seconds, reverse=True)


def test_row8_a_test_without_a_stored_duration_gets_the_median():
    stored = {"a": 1.0, "b": 3.0, "c": 9.0}
    assert plan_seconds(["a", "new", "b", "c"], stored) == [1.0, 3.0, 3.0, 9.0]


def test_no_stored_duration_at_all_writes_nothing():
    assert plan_seconds(["a", "b"], {}) is None


def test_full_run_one_run_carries_the_plugin_flag_and_the_env_var(tmp_path, monkeypatch):
    seen = {}

    class Stop(Exception):
        pass

    def fake_suite(cmd, wt, env, out_path, head, **kw):
        seen.update(cmd=cmd, env=env, out=out_path)
        raise Stop

    (tmp_path / "var" / "agentops" / "test_map").mkdir(parents=True)
    (tmp_path / "var" / "agentops" / "test_map" / "testmondata").write_text("x")
    monkeypatch.setattr(full_run, "ensure_suite_worktree", lambda *a, **k: tmp_path)
    monkeypatch.setattr(full_run, "run_suite_by_merge_state", fake_suite)
    monkeypatch.setattr(full_run._merge, "_augmented_suite_cmd", lambda c: c)
    monkeypatch.setattr(full_run._merge, "_with_workers", lambda c, p, wt: (c, 1, ""))
    with pytest.raises(Stop):
        full_run._one_run("abcdef1234567890", tmp_path, "python -m pytest tests -q", {}, None, None)
    assert "-p tools.agentops.suite_plan_plugin" in seen["cmd"]
    assert seen["env"]["SUITE_PLAN_FILE"] == str(seen["out"]) + ".plan.json"
    assert seen["env"]["SUITE_PLAN_FILE"].endswith("abcdef12.out.plan.json")
    assert seen["env"]["SUITE_DURATIONS_FILE"] == str(full_run.map_dir(tmp_path) / "testmondata")
