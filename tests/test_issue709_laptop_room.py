"""#709: a laptop budget that does not read is named in the log, extra keys never zero the room, and
recovery is logged (fakes only, no ssh, no PoB)."""

from __future__ import annotations

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs import placement
from junkroan.runs.remote_store import RemoteSnapshot
from tests.test_runs_rebalance import CONFIG, _fill_pc, age, host_status, rig

NORMAL = runs_hosts.mode_budget(CONFIG["laptop"], "laptop", "normal")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setattr(runs_hosts, "read_modes", lambda *a, **k: {})
    placement._unreadable_logged.clear()
    placement.unreadable_cause.clear()
    yield
    placement._unreadable_logged.clear()
    placement.unreadable_cause.clear()


def _setup(tmp_path, monkeypatch, budget_holder, jobs=lambda laptop: laptop.jobs()):
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    daemon._read_remote_snapshot = lambda cfg, host: RemoteSnapshot(
        jobs=jobs(laptop), daemon_status=host_status(daemon), budget=budget_holder["b"])
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd="python scripts/benchmark.py --workers 1", workers=1)
    age(daemon, job, 16)
    return daemon, store, laptop, logged, calls, job


def _room0(logged):
    return [m for m in logged if m.startswith("placement: laptop budget unreadable or matches no mode")]


def _stay(logged):
    return [m for m in logged if "stays; laptop room 0" in m]


def test_missing_budget_names_cause_then_recovers_and_moves(tmp_path, monkeypatch):
    holder = {"b": None}
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, holder)
    daemon.tick()
    daemon.tick()
    assert len(_room0(logged)) == 1 and "file missing, empty or unparsable" in _room0(logged)[0]
    assert _room0(logged)[0].endswith("room 0 until it reads again")
    assert _stay(logged) == [f"rebalance: job {job.id} stays; laptop room 0 (file missing, empty or unparsable)"]
    assert calls["submit"] == 0 and store.get(job.id).state == "queued"
    holder["b"] = NORMAL
    daemon.tick()
    assert "placement: laptop budget readable again; room 3" in logged
    assert calls["submit"] == 1 and store.get(job.id).state == "cancelled"
    assert len(_room0(logged)) == 1


def test_extra_key_still_matches_normal(tmp_path, monkeypatch):
    holder = {"b": {**NORMAL, "merge_suite_reserve_gb": 8, "merge_suite": True}}
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, holder)
    daemon.tick()
    assert _room0(logged) == [] and _stay(logged) == []
    assert calls["submit"] == 1


def test_total_differs_names_key(tmp_path, monkeypatch):
    holder = {"b": {**NORMAL, "day": {**NORMAL["day"], "total": 5}}}
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, holder)
    daemon.tick()
    assert len(_room0(logged)) == 1 and "differs from 'normal' in day.total" in _room0(logged)[0]
    assert len(_stay(logged)) == 1 and "day.total" in _stay(logged)[0]
    assert calls["submit"] == 0


def test_full_laptop_logs_neither(tmp_path, monkeypatch):
    holder = {"b": NORMAL}
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, holder)
    for i in range(3):
        laptop.submit(host="laptop", priority="P0", tag=f"lb{i}", cmd="python scripts/benchmark.py", workers=1)
    daemon.tick()
    assert _room0(logged) == [] and _stay(logged) == []
    assert calls["submit"] == 0
