"""#917: the PC moves a job to the laptop only where the laptop's own gate (slots AND RAM) would start it."""

from __future__ import annotations

from junkroan.runs import daemon as daemon_mod
from junkroan.runs.remote_store import RemoteSnapshot
from tests.test_runs_daemon import BUDGET_NIGHT_10
from tests.test_runs_rebalance import CMD, _fill_pc, age, host_status, rig

CMD3 = "python scripts/benchmark.py --workers 3"


def _setup(tmp_path, monkeypatch, status_of):
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    base = daemon._read_remote_snapshot
    daemon._read_remote_snapshot = lambda cfg, host: RemoteSnapshot(
        jobs=base(cfg, host).jobs, daemon_status=status_of(daemon), budget=base(cfg, host).budget)
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD3, workers=3)
    age(daemon, job, 15)
    return daemon, store, laptop, logged, calls, job


def _ram(logged):
    return [m for m in logged if "RAM" in m and "stays" in m]


def test_917_ram_holds_less_than_need_not_moved(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, lambda d: host_status(d, 1))
    assert daemon._rebalancer.step() == []
    assert daemon._rebalancer.step() == []
    assert calls["submit"] == 0
    assert _ram(logged) == [f"rebalance: job {job.id} stays; laptop RAM holds 1 workers, need 3"]


def test_917_ram_holds_enough_moves(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, lambda d: host_status(d, 3))
    assert daemon._rebalancer.step() == [job.id]
    assert _ram(logged) == []


import pytest


@pytest.mark.parametrize("status", [
    lambda d: None,
    lambda d: {"last_tick": d._utcnow().isoformat()},
    lambda d: host_status(d, None),
], ids=["no status", "key missing", "null"])
def test_917_key_missing_or_null_not_moved(tmp_path, monkeypatch, status) -> None:
    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, status)
    assert daemon._rebalancer.step() == []
    assert _ram(logged) == [f"rebalance: job {job.id} stays; laptop RAM not readable"]


def test_917_stale_status_not_moved(tmp_path, monkeypatch) -> None:
    def stale(d):
        from datetime import timedelta
        return {"ram_bound": 9, "last_tick": (d._utcnow() - timedelta(minutes=11)).isoformat(timespec="seconds")}

    daemon, store, laptop, logged, calls, job = _setup(tmp_path, monkeypatch, stale)
    assert daemon._rebalancer.step() == []
    assert _ram(logged) == [f"rebalance: job {job.id} stays; laptop RAM not readable"]


def test_917_status_carries_ram_bound(tmp_path) -> None:
    from tests.test_runs_daemon import make_daemon
    daemon, store, _ = make_daemon(
        tmp_path, budget=BUDGET_NIGHT_10,
        hosts_config={"pc": {"ssh": None, "ram_per_worker_gb": 4.0}})
    daemon._status_file = tmp_path / "status.json"
    daemon._ram_reader = lambda: 4.0 * 3 + BUDGET_NIGHT_10.min_free_ram_gb
    daemon.write_status(interval=30)
    assert daemon_mod.read_daemon_status(tmp_path / "status.json")["ram_bound"] == 3
    daemon._ram_reader = lambda: (_ for _ in ()).throw(OSError("no reading"))
    daemon.write_status(interval=30)
    assert daemon_mod.read_daemon_status(tmp_path / "status.json")["ram_bound"] is None
