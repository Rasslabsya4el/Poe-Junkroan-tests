"""#744 rows 1-7: a suite worker costs SUITE_WORKER_CORES = 0.5 core; probe and router count alike."""
import sys
from pathlib import Path

import pytest

from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, SUITE_WORKER_CORES, suite_workers_from_readings

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

RESERVE = 3.0


def ram_for(by_ram):  # free RAM that gives exactly `by_ram` workers
    return RESERVE + SUITE_PER_WORKER_GB * by_ram + 0.05


def count(cpu, pob, full, by_ram):
    return suite_workers_from_readings(12, cpu, ram_for(by_ram), RESERVE, SUITE_PER_WORKER_GB, 6, pob, full)


def test_constant():
    assert SUITE_WORKER_CORES == 0.5


@pytest.mark.parametrize("cpu,pob,full,by_ram,want", [
    (100, 29, 1, 8, 6), (100, 17, 1, 8, 4), (100, 9, 0, 8, 2), (100, 0, 0, 8, 1), (89, 32, 0, 3, 3)])
def test_rows_1_to_5(cpu, pob, full, by_ram, want):
    assert count(cpu, pob, full, by_ram)[0] == want


def test_row6_head_line_and_parse():
    from tools.agentops.merge import suite_workers
    n, line = count(100, 29, 1, 8)
    assert line.startswith("workers 6: cores free 3.6 of 12 (cpu 100%, PoB workers 29%, full run 1%), "
                           "0.5 core a worker -> 7 by CPU, RAM free ")
    assert line.endswith("-> 8 by RAM, cap 6")
    assert suite_workers(lambda: line) == (6, line)


def test_row7_router_and_probe_agree(monkeypatch):
    import machine_load
    from junkroan.pob import slot_budget
    from tools.agentops import suite_host, suite_router
    monkeypatch.setattr(machine_load, "cpu_shares", lambda: (100.0, 29.0))
    monkeypatch.setattr(machine_load, "last_full_run_cpu", 1.0)
    monkeypatch.setattr(machine_load, "cpu_count", lambda: 12)
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: ram_for(8))
    readings = suite_router.pc_readings()
    assert readings["full_run_cpu_percent"] == 1.0
    router_n, _ = suite_host._workers(readings, 6, RESERVE)
    probe_n, _ = count(100, 29, 1, 8)
    assert router_n == probe_n == 6
