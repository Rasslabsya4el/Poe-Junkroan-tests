"""#642 unit 2: the rebalancer moves no gate-reading job to a host that lacks the PC's newest gate (fake hosts, no PoB)."""

from __future__ import annotations

from pathlib import Path

from junkroan.runs.rebalance import Rebalancer, _runs_pytest
from tests.test_runs_rebalance import _fill_pc, age, rig

GATE = "20261005-1220-gate-20261005"
OLD = "20260928-1000-gate-20260928"
PROBE = "python scripts/probe_issue632_rage.py"


def _gate_rig(tmp_path: Path, monkeypatch, present: set[str], newest: str | None = GATE):
    daemon, store, laptop, logged, calls = rig(tmp_path, monkeypatch)
    held = {"laptop": present}
    daemon._rebalancer = Rebalancer(
        daemon, has_pin=lambda cfg, host, pin: True, submit_moved=daemon._rebalancer._submit_moved,
        gates_present=lambda host: held[host], newest_gate=lambda root: newest)
    _fill_pc(daemon, store)
    return daemon, store, laptop, logged, calls, held


def _stay_lines(logged: list[str]) -> list[str]:
    return [line for line in logged if "stays; laptop lacks gate" in line]


def test_gate_job_stays_once_then_moves_when_gate_arrives(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, held = _gate_rig(tmp_path, monkeypatch, set())
    job = store.submit(host="pc", priority="P2", tag="probe", cmd=PROBE, workers=1)
    age(daemon, job, 20)
    daemon.tick()
    daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0
    assert _stay_lines(logged) == [f"rebalance: job {job.id} stays; laptop lacks gate {GATE}"]
    held["laptop"].add(GATE)
    daemon.tick()
    assert store.get(job.id).state == "cancelled" and calls["submit"] == 1


def test_non_gate_job_moves_with_empty_gates(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, held = _gate_rig(tmp_path, monkeypatch, set())
    job = store.submit(host="pc", priority="P2", tag="smoke", cmd="python scripts/benchmark.py --set smoke", workers=1)
    age(daemon, job, 20)
    daemon.tick()
    assert calls["submit"] == 1 and store.get(job.id).state == "cancelled"
    assert _stay_lines(logged) == []


def test_artifact_job_stays_when_laptop_holds_only_older_gate(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, held = _gate_rig(tmp_path, monkeypatch, {OLD})
    job = store.submit(host="pc", priority="P2", tag="art", workers=1,
                       cmd=f"python scripts/x.py artifacts/benchmark/{GATE}/smite-s4.pob.txt")
    age(daemon, job, 20)
    daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0
    assert len(_stay_lines(logged)) == 1


def test_gate_job_stays_when_pc_has_no_gate(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, logged, calls, held = _gate_rig(tmp_path, monkeypatch, {GATE}, newest=None)
    job = store.submit(host="pc", priority="P2", tag="probe", cmd=PROBE, workers=1)
    age(daemon, job, 20)
    daemon.tick()
    assert store.get(job.id).state == "queued" and calls["submit"] == 0
    assert logged.count(f"rebalance: job {job.id} stays; laptop lacks gate none") == 1


def test_bare_pytest_pob_command_is_never_movable() -> None:
    assert _runs_pytest("pytest tests/test_issue632_rage_candidate.py -m pob")
    assert not Rebalancer._movable(type("J", (), {
        "is_filler": False, "moved_from": None, "rc_is_reading": False, "host_fixed": False,
        "cmd": "pytest tests/test_issue632_rage_candidate.py -m pob"})())
