"""#779 unit 4: the merge line holds in play (D117). Rows 5 and 6. Real ``run_merge`` threads with a stub suite,
no pytest, no PoB; ``AGENTOPS_MACHINE_DIR`` is a tmp dir, the real mode file is never written."""

from __future__ import annotations

import time

import pytest

from tests.test_agentops_merge import (
    NO_LOAD_REACHES, _protect_real_agentops_var, _green_default_commit_suite,
)
from tests.test_agentops_merge_line_check import Scenario, _stub_is_not_pytest
from tools.agentops import machine_mode, merge as merge_module

_ = (_protect_real_agentops_var, _green_default_commit_suite, _stub_is_not_pytest)


@pytest.fixture(autouse=True)
def _machine_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTOPS_MACHINE_DIR", str(tmp_path / "machine"))
    monkeypatch.setattr(merge_module, "HOLD_POLL_SECONDS", 0.05)


def test_row5_two_queued_entries_wait_in_play_and_land_after_normal(tmp_path):
    s = Scenario(tmp_path)
    s.branch("a", "a.py")
    s.branch("b", "b2.py")
    (s.dir / "napped").write_text("x")  # no suite naps: every suite is plain
    machine_mode.set_mode("play")
    s.add_waiter("a")
    s.add_waiter("b")
    time.sleep(2.0)
    assert s.calls() == [], s.calls()  # 0 suites, 0 line checks
    assert s.results == {}  # waiting: not failed, not timed out, not dropped
    assert not s.lock.exists()
    queue = s.lock.with_name(s.lock.name + ".queue")
    assert len(list(queue.iterdir())) == 2
    machine_mode.set_mode("normal")
    s.join()
    assert s.results["a"].ok and s.results["b"].ok, {k: v.render() for k, v in s.results.items()}
    assert s.suite_fulls(), "a suite ran after normal"
    assert not any(r.reason == "lock-timeout" for r in s.results.values())


def test_row5_line_check_starts_nothing_in_play_with_a_live_holder(tmp_path):
    s = Scenario(tmp_path)
    s.branch("h", "h.py")
    s.branch("c", "c.py")
    s.start_holder()  # normal: the holder's suite is running (napping)
    machine_mode.set_mode("play")
    s.add_waiter("c")
    time.sleep(2.0)
    assert s.check_calls() == [], s.check_calls()
    assert "c" not in s.results
    machine_mode.set_mode("normal")
    s.wait(lambda: s.check_calls() or "c" in s.results, "the check of c after normal")
    s.release()
    s.join()
    assert s.results["h"].ok and s.results["c"].ok


def test_unreadable_mode_starts_nothing(tmp_path, monkeypatch):
    d = tmp_path / "machine"
    d.mkdir(parents=True, exist_ok=True)
    (d / "machine_mode.json").write_text("{not json", encoding="utf-8")
    assert merge_module.machine_holds() is True


def test_row6_landing_in_play_spawns_no_full_run_and_one_after_normal(tmp_path, monkeypatch):
    spawned: list[list[str]] = []
    monkeypatch.setattr(merge_module.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
    machine_mode.set_mode("play")
    problem = merge_module._spawn_map_run(tmp_path, "abc123")
    assert spawned == [] and problem
    machine_mode.set_mode("normal")
    assert merge_module._spawn_map_run(tmp_path, "abc123") == ""
    assert len(spawned) == 1 and "map-run" in spawned[0] and "abc123" in spawned[0]
