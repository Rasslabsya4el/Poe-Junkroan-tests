"""#715 rule 1: PoB workers go Idle while a merge suite runs, restored after; owner reservation keeps Idle."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from junkroan.runs import hosts as runs_hosts  # noqa: E402
from tests.test_runs_daemon import (  # noqa: E402,F401
    BUDGET_NIGHT_10, FakeLauncher, _isolated_daemon_status, make_daemon,
)
from tests.test_runs_daemon_spike import SPIKE, snap  # noqa: E402

T0 = datetime(2026, 10, 10, 12, 0, 0)
HOSTS = {"pc": {"modes": {"night": {"pob_priority": "BelowNormal"}}, "spike": SPIKE["pc"]["spike"]}}


@pytest.fixture()
def rig(tmp_path):
    modes = tmp_path / "modes.json"
    modes.write_text(json.dumps({"pc": {"mode": "night"}}), encoding="utf-8")
    daemon, store, _ = make_daemon(tmp_path, launcher=FakeLauncher(), budget=BUDGET_NIGHT_10, hosts_config=HOSTS)
    state = {"suite": 0, "t": 1_000_000.0}
    calls: list[tuple[list[int], str]] = []
    daemon.timestamp = lambda: T0
    daemon.clock = lambda: state["t"]
    daemon._modes_file = modes
    daemon._yield_root = tmp_path / "root"
    daemon._pid_finder = lambda: [11, 12]
    daemon._priority_setter = lambda pids, prio: calls.append((list(pids), prio))
    daemon._spike_reader = lambda job_pids, prev: {**snap(8000.0), "merge_suite_pytest": state["suite"]}
    for name, n in (("a", 6), ("b", 3)):
        store.submit(host="pc", priority="P1", tag=name, cmd=f"python scripts/benchmark.py --workers {n}", workers=n)
        daemon.tick()
    calls.clear()

    def tick(suite):
        state["suite"] = suite
        state["t"] += 60.0
        calls.clear()
        daemon.tick()
        return list(calls)

    return daemon, modes, tick


def test_suite_sets_idle_then_restores(rig):
    daemon, modes, tick = rig
    assert tick(0) == []
    assert tick(2) == [([11, 12], "Idle")]
    assert tick(1) == [([11, 12], "Idle")]
    assert tick(0) == [([11, 12], "BelowNormal")]
    assert tick(0) == []


def test_owner_reservation_keeps_idle_after_suite_ends(rig):
    daemon, modes, tick = rig
    runs_hosts.set_owner_reservation("pc", 2, 30, modes_file=modes, now=T0)
    assert tick(1)[-1] == ([11, 12], "Idle")
    out = tick(0)
    assert out and all(prio == "Idle" for _, prio in out)
    assert daemon._owner_idle and not daemon._suite_idle

