"""#966 unit 2: under the run queue's free-RAM floor the merge suite and its line check start with one worker.

The floor is the budget's ``min_free_ram_gb`` -- the same field the runs daemon reads, loaded from the
same budget file; the suite and the line check still start (a merge is never held by memory).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from junkroan.pob import slot_budget

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import machine_load  # noqa: E402

from tools.agentops import merge  # noqa: E402
from tools.agentops.merge import MergeResult  # noqa: E402

CMD = 'python -m pytest tests -q -m "not slow and not pob" -rf'
MOMENT = datetime(2026, 10, 13, 12, 0)  # inside the "day" window (08:00-01:00)


def _machine(monkeypatch, free_ram: float, *, cores: int = 12, cpu: float = 10.0) -> None:
    """12 cores idle (cpu 10 %), the given free RAM: the readings ``machine_load.suite_workers_line`` takes."""
    monkeypatch.setattr(slot_budget, "available_ram_gb", lambda: free_ram)
    monkeypatch.setattr(machine_load, "cpu_count", lambda: cores)
    monkeypatch.setattr(machine_load, "cpu_shares", lambda: (cpu, None))
    monkeypatch.setattr(machine_load, "last_full_run_cpu", None)


def _budget(tmp_path, floor: float):
    """The budget the runs daemon loads: the "day" window with ``min_free_ram_gb`` = ``floor``."""
    path = tmp_path / "machine_budget.json"
    path.write_text(json.dumps({"day": {"hours": [8, 25], "total": 7, "others": 2, "min_free_ram_gb": floor,
                                        "merge_suite": 6, "merge_suite_reserve_gb": 3}}), encoding="utf-8")
    return slot_budget.load_budget(path=path, now=MOMENT, host="pc",
                                   reservations_path=tmp_path / "no-reservations.json",
                                   modes_file=tmp_path / "no-modes.json")


def _probe_is_machine_load(monkeypatch, budget) -> None:
    """The merge's probe is the real ``--suite-workers`` computation with this budget (no subprocess)."""
    monkeypatch.setattr(merge, "resolve_suite_workers_probe", lambda: "python scripts/machine_load.py --suite-workers")
    monkeypatch.setattr(merge, "_make_probe", lambda template, cwd: (lambda: machine_load.suite_workers_line(budget)))
    monkeypatch.setattr(merge, "_xdist_available", lambda interpreter, cwd: True)


def test_the_budget_floor_is_the_runs_setting(tmp_path):
    assert _budget(tmp_path, 8).min_free_ram_gb == 8.0
    assert _budget(tmp_path, 10).min_free_ram_gb == 10.0


def test_row2_merge_suite_at_6_9_gb_under_the_8_gb_floor_is_one_worker(monkeypatch, tmp_path):
    _machine(monkeypatch, 6.9)
    _probe_is_machine_load(monkeypatch, _budget(tmp_path, 8))
    cmd, k, head = merge._with_workers(CMD, True, tmp_path)
    assert k == 1
    assert " -n" not in cmd
    assert head.startswith("workers 1: free RAM 6.9 GB under the floor 8 GB")


def test_row3_line_check_gets_the_same_count_through_the_same_helper(monkeypatch, tmp_path):
    # tools/agentops/line_check.py:366 calls merge._with_workers (test_agentops_line_check pins that call),
    # so the line check of a waiting merge takes the count of this helper.
    _machine(monkeypatch, 6.9)
    _probe_is_machine_load(monkeypatch, _budget(tmp_path, 8))
    cmd, k, head = merge._with_workers(CMD, True, tmp_path / "check")
    assert k == 1 and " -n" not in cmd
    assert head.startswith("workers 1:")


def test_row4_at_or_over_the_floor_the_count_is_today_s(monkeypatch, tmp_path):
    # 6 = the count unchanged main gives for these inputs (12 cores idle, cap 6, 0.4 GB a worker):
    # 8.0 GB -> (8.0 - 3) / 0.4 = 12 by RAM; 20 GB -> 42 by RAM; both capped at 6.
    for free in (8.0, 20.0):
        _machine(monkeypatch, free)
        _probe_is_machine_load(monkeypatch, _budget(tmp_path, 8))
        cmd, k, head = merge._with_workers(CMD, True, tmp_path)
        assert k == 6, free
        assert cmd == CMD + " -n 6 --maxschedchunk=1"
        assert head.startswith("workers 6:")


def test_row5_the_floor_is_read_from_the_runs_setting(monkeypatch, tmp_path):
    _machine(monkeypatch, 9.0)  # 9 GB free: under a 10 GB floor, over the 8 GB default
    _probe_is_machine_load(monkeypatch, _budget(tmp_path, 10))
    cmd, k, head = merge._with_workers(CMD, True, tmp_path)
    assert k == 1 and " -n" not in cmd
    assert head.startswith("workers 1: free RAM 9.0 GB under the floor 10 GB")


def test_row5_over_the_raised_floor_the_count_is_today_s(monkeypatch, tmp_path):
    _machine(monkeypatch, 10.5)
    _probe_is_machine_load(monkeypatch, _budget(tmp_path, 10))
    assert merge._with_workers(CMD, True, tmp_path)[1] == 6


def test_row7_merge_log_line_names_the_cut(monkeypatch, tmp_path):
    _machine(monkeypatch, 6.9)
    _probe_is_machine_load(monkeypatch, _budget(tmp_path, 8))
    _cmd, k, _head = merge._with_workers(CMD, True, tmp_path)
    log = tmp_path / "merge.log"
    merge._append_merge_log("b", MergeResult(ok=True, reason="pushed", suite_duration=480.0,
                                             suite_workers=k), log_path=log)
    assert "1 worker (free RAM 6.9 GB under the floor 8 GB)" in log.read_text(encoding="utf-8")


def test_row7_uncut_log_line_is_unchanged(tmp_path):
    log = tmp_path / "merge.log"
    merge._append_merge_log("b", MergeResult(ok=True, reason="pushed", suite_duration=480.0,
                                             suite_workers=6), log_path=log)
    assert "| suite 8 min, 6 workers | 0 failed |" in log.read_text(encoding="utf-8")


def test_formula_without_a_floor_is_unchanged():
    from junkroan.pob.slot_budget import SUITE_PER_WORKER_GB, suite_workers_from_readings
    assert suite_workers_from_readings(12, 10, 6.9, 3.0, SUITE_PER_WORKER_GB, 6)[0] == 6
    assert suite_workers_from_readings(12, 10, 6.9, 3.0, SUITE_PER_WORKER_GB, 6, floor_gb=8.0)[0] == 1
