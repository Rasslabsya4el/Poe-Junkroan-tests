"""The daemon side of the owner's reservation (#621 unit 5). No PoB, no real var/, no real laptop."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import runs  # noqa: E402
from junkroan.pob import slot_budget  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs import yield_plan  # noqa: E402
from tests.test_runs_daemon import (  # noqa: E402,F401
    BUDGET_NIGHT_10, FakeLauncher, _isolated_daemon_status, make_daemon,
)

T0 = datetime(2026, 10, 7, 12, 0, 0)
HOSTS = {"pc": {"modes": {"night": {"pob_priority": "BelowNormal"}}}}


@pytest.fixture()
def rig(tmp_path):
    modes = tmp_path / "modes.json"
    modes.write_text(json.dumps({"pc": {"mode": "night"}}), encoding="utf-8")
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, budget=BUDGET_NIGHT_10, hosts_config=HOSTS)
    clock = {"now": T0}
    calls: list[tuple[list[int], str]] = []
    daemon.timestamp = lambda: clock["now"]
    daemon._modes_file = modes
    daemon._yield_root = tmp_path / "root"
    daemon._pid_finder = lambda: [11, 12]
    daemon._priority_setter = lambda pids, prio: calls.append((list(pids), prio))
    stopped: list = []
    launcher.stop = lambda *a, **k: stopped.append(a)
    jobs = {}
    for name, n in (("A", 6), ("B", 3), ("C", 1)):
        jobs[name] = store.submit(host="pc", priority="P1", tag=name.lower(),
                                  cmd=f"python scripts/benchmark.py --workers {n}", workers=n)
        daemon.tick()
        assert store.get(jobs[name].id).state == "running"
    calls.clear()
    return daemon, store, launcher, modes, clock, calls, jobs, stopped


def _give(daemon, jobs):
    return {n: yield_plan.read_yield(daemon.yield_file(j.id)) for n, j in jobs.items()}


def test_row1_reserve_6_shrinks_total_holds_queue_and_writes_yield(rig):
    daemon, store, launcher, modes, clock, calls, jobs, _ = rig
    until = runs_hosts.set_owner_reservation("pc", 6, 30, modes_file=modes, now=T0)
    waiting = store.submit(host="pc", priority="P1", tag="w", cmd="python scripts/benchmark.py --workers 1", workers=1)
    daemon.tick()
    status_path = daemon.status_path
    daemon.write_status(interval=5)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    assert status["slots_total"] == 4 and status["reserved"] == 6 and status["reserved_until"]
    assert status["slots_in_use"] == 10
    assert store.get(waiting.id).state == "queued"
    assert f"reserved 6 until {until:%H:%M}" in daemon._gate_status[waiting.id]["detail"]
    assert _give(daemon, jobs) == {"A": 4, "B": 2, "C": 0}
    assert not daemon.yield_file(jobs["C"].id).exists()
    assert calls and all(prio == "Idle" and pids == [11, 12] for pids, prio in calls)


def test_row4_reserve_all_yields_everything_and_kills_nothing(rig):
    daemon, store, launcher, modes, clock, calls, jobs, stopped = rig
    runs_hosts.set_owner_reservation("pc", 10, 30, modes_file=modes, now=T0)
    daemon.tick()
    assert _give(daemon, jobs) == {"A": 6, "B": 3, "C": 1}
    assert all(store.get(j.id).state == "running" for j in jobs.values())
    assert stopped == []
    budget = daemon.budget()
    assert budget.total == 0 and budget.limit_for(slot_budget.ROLE_QUEUE) == 0


def test_row4_strict_reserve_floors_the_queue_limit_at_zero():
    budget = slot_budget.Budget(period="night", hours=(1, 8), total=0, others=5, min_free_ram_gb=0.0,
                                strict_reserve=True, reserved=10)
    assert budget.limit_for(slot_budget.ROLE_QUEUE) == 0
    plain = slot_budget.Budget(period="night", hours=(1, 8), total=4, others=5, min_free_ram_gb=0.0,
                               strict_reserve=True)
    assert plain.limit_for(slot_budget.ROLE_QUEUE) == 1


def test_row5_expiry_restores_total_clears_files_and_priority(rig):
    daemon, store, launcher, modes, clock, calls, jobs, _ = rig
    runs_hosts.set_owner_reservation("pc", 6, 30, modes_file=modes, now=T0)
    daemon.tick()
    assert _give(daemon, jobs)["A"] == 4
    calls.clear()
    clock["now"] = T0 + timedelta(minutes=31)
    daemon.tick()
    daemon.write_status(interval=5)
    status = json.loads(daemon.status_path.read_text(encoding="utf-8"))
    assert status["slots_total"] == 10 and status["reserved"] == 0 and status["reserved_until"] is None
    assert _give(daemon, jobs) == {"A": 0, "B": 0, "C": 0}
    assert not any(daemon.yield_file(j.id).exists() for j in jobs.values())
    assert calls == [([11, 12], "BelowNormal")]


def test_row5_release_restores_at_once(rig):
    daemon, store, launcher, modes, clock, calls, jobs, _ = rig
    runs_hosts.set_owner_reservation("pc", 6, 30, modes_file=modes, now=T0)
    daemon.tick()
    calls.clear()
    assert runs_hosts.release_owner_reservation("pc", modes_file=modes)
    daemon.tick()
    assert daemon.budget().total == 10
    assert not any(daemon.yield_file(j.id).exists() for j in jobs.values())
    assert calls == [([11, 12], "BelowNormal")]


def test_yield_file_goes_when_the_job_ends(rig):
    daemon, store, launcher, modes, clock, calls, jobs, _ = rig
    runs_hosts.set_owner_reservation("pc", 6, 30, modes_file=modes, now=T0)
    daemon.tick()
    path = daemon.yield_file(jobs["A"].id)
    assert path.exists()
    launcher.finish(store.get(jobs["A"].id).pid, 0)
    daemon.tick()
    assert not path.exists()


def test_env_carries_the_yield_file(rig):
    daemon, store, launcher, *_ , jobs, _stopped = rig
    for started, name in zip(launcher.started, "ABC"):
        job = jobs[name]
        assert started["env"][yield_plan.ENV_VAR] == str(daemon.yield_file(job.id).resolve())


def test_status_line_with_reservation_and_minutes_left(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(tmp_path / "ds"))
    now = datetime.now()
    from datetime import timezone
    path = runs_hosts.daemon_status_path("pc")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "last_tick": datetime.now(timezone.utc).isoformat(), "slots_total": 4, "slots_in_use": 4,
        "reserved": 6, "reserved_until": (now + timedelta(minutes=25, seconds=10)).isoformat(),
    }), encoding="utf-8")
    lines = runs._slot_lines("pc")
    assert len(lines) == 1
    assert lines[0].startswith("pc: 4 of 4 slots in use, the owner reserved 6 until ")
    assert "25 min" in lines[0] and "left" in lines[0]


def test_load_budget_subtracts_the_record(tmp_path):
    doc = tmp_path / "budget.json"
    doc.write_text(json.dumps({"day": {"hours": [0, 24], "total": 10, "others": 2, "min_free_ram_gb": 0}}),
                   encoding="utf-8")
    modes = tmp_path / "modes.json"
    base = slot_budget.load_budget(now=T0, path=doc, host="pc", modes_file=modes)
    assert base.total == 10 and base.reserved == 0
    runs_hosts.set_owner_reservation("pc", 3, 30, modes_file=modes, now=T0)
    cut = slot_budget.load_budget(now=T0, path=doc, host="pc", modes_file=modes)
    assert cut.total == 7 and cut.reserved == 3 and cut.reserved_until is not None
