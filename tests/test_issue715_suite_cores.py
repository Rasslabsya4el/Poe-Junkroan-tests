"""#715 rule 2: the suite's free cores do not count the cpu share burnt by the runs daemon's PoB workers."""

import sys
from pathlib import Path

from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_pob_share_counts_as_free_cores():
    n, line = suite_workers_from_readings(12, 100.0, 6.5, 3, SUITE_PER_WORKER_GB, 6, 83.0)
    assert n == 6
    assert "cpu 100%" in line and "PoB workers 83%" in line


def test_ram_still_binds():
    n, _ = suite_workers_from_readings(12, 100.0, 2.3, 3, SUITE_PER_WORKER_GB, 6, 83.0)
    assert n == 1


def test_no_pob_share_equals_old_result():
    old = suite_workers_from_readings(12, 100.0, 6.5, 3, SUITE_PER_WORKER_GB, 6)
    assert old[0] == 1
    assert suite_workers_from_readings(12, 100.0, 6.5, 3, SUITE_PER_WORKER_GB, 6, None) == old
    assert "PoB" not in old[1]
    assert suite_workers_from_readings(12, 40.0, 6.5, 3, SUITE_PER_WORKER_GB, 6)[0] == 6


def test_probe_prints_both_shares(monkeypatch, capsys):
    import machine_load
    from junkroan.pob import slot_budget

    monkeypatch.delenv(machine_load.POB_NOT_STEPPED_DOWN_ENV, raising=False)  # #811: the full run sets it for its own tree
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "night")  # #847: the cap is 3 by day in mode normal (#839), 6 by night
    monkeypatch.setattr(machine_load, "last_full_run_cpu", None)
    monkeypatch.setattr(machine_load, "cpu_shares", lambda: (100.0, 83.0))
    monkeypatch.setattr(machine_load, "cpu_count", lambda: 12)
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: 6.5)
    line = machine_load.suite_workers_line(slot_budget.load_budget())
    assert line.startswith("workers 6") and "cpu 100%" in line and "PoB workers 83%" in line
