"""#710: the daemon counts the queue-role slot locks each running job holds. No PoB, no real slot folder."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from junkroan.pob import slot_budget
from junkroan.runs import yield_plan
from tests.test_runs_daemon import FakeLauncher, FakeSlots, _isolated_daemon_status, make_daemon  # noqa: F401

T0 = datetime(2026, 10, 10, 12, 0, 0)
BUDGET_10 = slot_budget.Budget(period="night", hours=(1, 8), total=10, others=5, min_free_ram_gb=0.0,
                               strict_reserve=False)


def _running(tmp_path, budget=BUDGET_10, slots=None):
    daemon, store, _ = make_daemon(tmp_path, launcher=FakeLauncher(), budget=budget, host="pc",
                                   slots=slots, hosts_config={"pc": {}})
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python scripts/benchmark.py --workers 1", workers=1)
    daemon.tick()
    assert store.get(job.id).state == "running"
    return daemon, job


def _status(daemon) -> dict:
    daemon.write_status(interval=5)
    return json.loads(daemon.status_path.read_text(encoding="utf-8"))


def test_row1_workers_1_holding_5_queue_locks_reports_5(tmp_path: Path) -> None:
    slots = FakeSlots()
    daemon, job = _running(tmp_path, slots=slots)
    slots.own(job.id, 5)
    slots.foreign(1, role="other")
    assert _status(daemon)["slots_in_use"] == 5


def test_row2_a_job_with_no_lock_yet_counts_max_1_workers(tmp_path: Path) -> None:
    daemon, job = _running(tmp_path, slots=FakeSlots())
    assert _status(daemon)["slots_in_use"] == 1


def test_row3_yield_plan_uses_the_locks_held(tmp_path: Path) -> None:
    budget = slot_budget.Budget(period="night", hours=(1, 8), total=4, others=5, min_free_ram_gb=0.0,
                                strict_reserve=False, reserved=3, reserved_until=T0 + timedelta(minutes=30))
    slots = FakeSlots()
    daemon, job = _running(tmp_path, budget=budget, slots=slots)
    slots.own(job.id, 5)
    daemon.timestamp = lambda: T0
    daemon._yield_root = tmp_path / "root"
    daemon.owner_pass()
    give = yield_plan.read_yield(daemon.yield_file(job.id))
    assert give == yield_plan.plan_yield({job.id: 5}, budget.limit_for(slot_budget.ROLE_QUEUE))[job.id]
    assert give >= 1
    assert yield_plan.plan_yield({job.id: 1}, budget.limit_for(slot_budget.ROLE_QUEUE))[job.id] == 0
