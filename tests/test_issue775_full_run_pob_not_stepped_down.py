"""#775 row 3: a full run's head line does not count PoB's cores as free (PoB is not stepped down for it)."""
import sys
from pathlib import Path

from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

RAM6 = 3 + 6 * SUITE_PER_WORKER_GB


def test_not_stepped_down_does_not_read_3_1_free():
    n, line = suite_workers_from_readings(12, 100.0, RAM6, 3, SUITE_PER_WORKER_GB, 6, 25.0,
                                          pob_stepped_down=False)
    assert "cores free 3.1" not in line
    assert line.startswith("workers 1: cores free 0.0 of 12 (cpu 100%, PoB workers 25%, PoB not stepped down)")
    assert n == 1


def test_merge_suite_count_for_same_readings_unchanged():
    n, line = suite_workers_from_readings(12, 100.0, RAM6, 3, SUITE_PER_WORKER_GB, 6, 25.0)
    assert n == 6 and line.startswith("workers 6: cores free 3.0 of 12 (cpu 100%, PoB workers 25%), ")


def test_probe_flag_from_env(monkeypatch):
    import machine_load
    from junkroan.pob import slot_budget
    monkeypatch.setattr(machine_load, "cpu_shares", lambda: (100.0, 25.0))
    monkeypatch.setattr(machine_load, "last_full_run_cpu", None)
    monkeypatch.setattr(machine_load, "cpu_count", lambda: 12)
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: RAM6)
    budget = slot_budget.load_budget()
    monkeypatch.delenv("JUNKROAN_POB_NOT_STEPPED_DOWN", raising=False)
    assert "PoB not stepped down" not in machine_load.suite_workers_line(budget)
    monkeypatch.setenv("JUNKROAN_POB_NOT_STEPPED_DOWN", "1")
    assert "PoB workers 25%, PoB not stepped down" in machine_load.suite_workers_line(budget)


def test_full_run_sets_env_for_its_probes(monkeypatch):
    import os
    from tools.agentops import full_run
    seen = {}
    monkeypatch.setattr(full_run, "try_lock", lambda root: True)
    monkeypatch.setattr(full_run, "unlock", lambda root: None)
    monkeypatch.setattr(full_run, "restart_lock", lambda root: None)
    monkeypatch.setattr(full_run, "take_pending", lambda root: None)
    monkeypatch.setattr(full_run, "_one_run",
                        lambda *a, **k: seen.setdefault("v", os.environ.get("JUNKROAN_POB_NOT_STEPPED_DOWN")) and 0)
    full_run.run_full("abc", root=Path("."), suite_cmd="x", suite_env={}, gh=object())
    assert seen["v"] == "1"
    assert "JUNKROAN_POB_NOT_STEPPED_DOWN" not in os.environ
