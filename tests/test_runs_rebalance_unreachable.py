"""#518 unit 2: no move to a host whose last remote read failed within 10 min."""

from __future__ import annotations

from junkroan.runs import remote_store as remote_store_mod
from tests.test_runs_rebalance import CMD, _fill_pc, age, rig


def _waiter(daemon, store):
    _fill_pc(daemon, store)
    job = store.submit(host="pc", priority="P2", tag="waiter", cmd=CMD, workers=1)
    age(daemon, job, 20)
    return job


def _fail_ago(daemon, minutes: float) -> None:
    now = daemon.clock
    daemon.clock = lambda: now() - minutes * 60
    daemon.note_remote_read("laptop", False)
    daemon.clock = now


def test_518_recent_failure_stays_logged_once(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = _waiter(daemon, store)
    _fail_ago(daemon, 5)
    assert daemon._rebalancer.step() == []
    assert daemon._rebalancer.step() == []
    assert calls["submit"] == 0
    assert [m for m in logged if "unreachable" in m] == [f"rebalance: job {job.id} stays; laptop unreachable 5 min ago"]


def test_518_old_failure_moves(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = _waiter(daemon, store)
    _fail_ago(daemon, 11)
    assert daemon._rebalancer.step() == [job.id]


def test_518_success_after_failure_moves(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    job = _waiter(daemon, store)
    _fail_ago(daemon, 5)
    daemon.note_remote_read("laptop", True)
    assert daemon._rebalancer.step() == [job.id]


def test_518_held_host_is_not_read(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _waiter(daemon, store)
    _fail_ago(daemon, 5)

    def no_read(cfg, host):
        raise AssertionError("ssh read of a held host")

    daemon._read_remote_snapshot = no_read
    assert daemon._rebalancer.step() == []


def test_518_rebalance_read_failure_records(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    _waiter(daemon, store)

    def boom(cfg, host):
        raise remote_store_mod.RemoteStoreUnreachable("down")

    daemon._read_remote_snapshot = boom
    assert daemon._rebalancer.step() == []
    assert daemon.remote_failed_ago("laptop") is not None


def test_518_handback_read_failure_records(tmp_path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)

    def boom(cfg, host):
        raise remote_store_mod.RemoteStoreUnreachable("down")

    daemon._read_remote = boom
    daemon._remote_pass_seconds = 0
    daemon._last_remote_pass = None
    assert daemon.remote_failed_ago("laptop") is None
    daemon.remote_handback_pass()
    assert daemon.remote_failed_ago("laptop") is not None
    daemon._read_remote = lambda cfg, host: ([], None)
    daemon._last_remote_pass = None
    daemon.remote_handback_pass()
    assert daemon.remote_failed_ago("laptop") is None
