"""#735 unit 1: the merge suite's worker formula counts the `agentops full-run` tree's cpu as free."""

from __future__ import annotations

import sys
from pathlib import Path

from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings
from junkroan.runs import load_groups

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

RAM6 = 3 + 6 * SUITE_PER_WORKER_GB  # reserve 3 GB + 6 workers


def test_row1_full_run_cpu_counts_as_free():
    n, line = suite_workers_from_readings(12, 100.0, RAM6, 3, SUITE_PER_WORKER_GB, 6, 10.0, 60.0)
    assert n == 6
    assert line.startswith("workers 6: cores free 8.4 of 12 (cpu 100%, PoB workers 10%, full run 60%)")


def test_row2_without_full_run_unchanged():
    n, line = suite_workers_from_readings(12, 100.0, RAM6, 3, SUITE_PER_WORKER_GB, 6, 10.0)
    assert n == 2
    assert line == suite_workers_from_readings(12, 100.0, RAM6, 3, SUITE_PER_WORKER_GB, 6, 10.0, None)[1]
    assert "full run" not in line and line.startswith("workers 2: cores free 1.2 of 12 (cpu 100%, PoB workers 10%)")


def test_row3_full_run_own_case_unchanged():
    n, line = suite_workers_from_readings(12, 87.0, 7.1, 3, SUITE_PER_WORKER_GB, 6, 15.0)
    assert n == 6 and "full run" not in line


def _fake(table, cpu_before, cpu_after, self_pid=1):
    ppids = {pid: ppid for pid, (ppid, _) in table.items()}
    cmds = {pid: cmd for pid, (_, cmd) in table.items()}
    ticks = iter([cpu_before, cpu_after])
    state = {"cur": None}

    def cpu_reader(pid):
        return state["cur"][pid]

    def sleep(_):
        state["cur"] = cpu_after

    state["cur"] = cpu_before
    clock = iter([0.0, 1.0])
    return dict(ppids_reader=lambda: ppids, cpu_reader=cpu_reader, cmdline_reader=lambda: cmds,
                ncpu=10, clock=lambda: next(clock), sleep=sleep, self_pid=self_pid)


TABLE = {
    1: (0, ["python", "-m", "pytest", "tests/test_x.py"]),                       # the caller (unrelated pytest)
    10: (0, ["python", "-m", "tools.agentops", "full-run"]),                      # full run parent
    11: (10, ["python", "-m", "pytest", "tests"]),                                # its pytest
    12: (11, ["python", "-c", "xdist worker gw0"]),                               # xdist child
    13: (11, ["python", "-c", "xdist worker gw1"]),
    20: (0, ["python", "-m", "pytest", "other"]),                                 # unrelated pytest
}


def test_grouping_counts_only_the_full_run_tree():
    before = {pid: 0.0 for pid in TABLE}
    after = {1: 5.0, 10: 0.1, 11: 1.0, 12: 2.0, 13: 3.0, 20: 4.0}
    pob, full = load_groups.pob_and_full_run_cpu_pct({}, **_fake(TABLE, before, after))
    assert pob == 0
    assert full == 61.0  # (0.1 + 1 + 2 + 3) s / 1 s / 10 cores * 100


def test_no_full_run_gives_none():
    table = {pid: v for pid, v in TABLE.items() if pid in (1, 20)}
    pob, full = load_groups.pob_and_full_run_cpu_pct({}, **_fake(table, {1: 0.0, 20: 0.0}, {1: 1.0, 20: 1.0}))
    assert full is None


def test_the_full_runs_own_probe_does_not_count_its_tree():
    before = {pid: 0.0 for pid in TABLE}
    after = {pid: 1.0 for pid in TABLE}
    _, full = load_groups.pob_and_full_run_cpu_pct({}, **_fake(TABLE, before, after, self_pid=12))
    assert full is None


def test_probe_line_shows_full_run(monkeypatch):
    import machine_load
    from junkroan.pob import slot_budget

    class _B:
        merge_suite_reserve_gb = 3.0
        min_free_ram_gb = None  # #966: no run floor in this fake, so the count is the old formula's

        @staticmethod
        def limit_for(role):
            return 6

    def fake_shares():
        machine_load.last_full_run_cpu = 60.0
        return 100.0, 10.0

    monkeypatch.setattr(machine_load, "cpu_shares", fake_shares)
    monkeypatch.setattr(machine_load, "cpu_count", lambda: 12)
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: RAM6)
    assert machine_load.suite_workers_line(_B()).startswith("workers 6:")
