"""#839 row 2: the merge suite's cap on the PC is 3 by day and 6 by night (mode normal)."""
import json
from pathlib import Path

import pytest

from junkroan.pob import slot_budget
from junkroan.runs import hosts

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = json.loads((_ROOT / "config" / "hosts.json").read_text(encoding="utf-8"))


def _budget_file(tmp_path, monkeypatch):
    doc = hosts.mode_budget(_CONFIG["pc"], "pc", "normal")
    path = tmp_path / "machine_budget.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(path))
    return path


@pytest.mark.parametrize("period,expected", [("day", 3), ("night", 6)])
def test_suite_workers_idle_machine(tmp_path, monkeypatch, period, expected):
    _budget_file(tmp_path, monkeypatch)
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", period)
    budget = slot_budget.load_budget(host="pc")
    assert budget.period == period
    cap = budget.limit_for(slot_budget.ROLE_MERGE_SUITE)
    n, line = slot_budget.suite_workers_from_readings(
        12, 5, 20.0, budget.merge_suite_reserve_gb, slot_budget.SUITE_PER_WORKER_GB, cap)
    assert n == expected and line.endswith(f"cap {expected}")


def test_other_pc_modes_and_laptop_unchanged():
    modes = _CONFIG["pc"]["modes"]
    assert modes["normal"]["day"]["merge_suite"] == 3 and modes["normal"]["night"]["merge_suite"] == 6
    for m in ("play", "pause", "off"):
        assert modes[m]["day"]["merge_suite"] == 6
