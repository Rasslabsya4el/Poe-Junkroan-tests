"""#666: the ``merge_suite`` budget role: capped by its own key, no PoB slot, never refused for full slots."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from junkroan.pob import slot_budget

ROOT = Path(__file__).resolve().parents[1]


def _budget(**overrides) -> slot_budget.Budget:
    values = dict(period="day", hours=(0, 24), total=7, others=2, min_free_ram_gb=8.0, merge_suite=4)
    values.update(overrides)
    return slot_budget.Budget(**values)


def test_go_while_every_other_slot_is_full(tmp_path):
    budget = _budget()
    go, line = slot_budget.verdict(4, "merge_suite", directory=tmp_path, budget=budget, ram_reader=lambda: 20.0)
    assert go and "'merge_suite'" in line and line.startswith("GO")
    # other role is capped at 2: asking 3 waits
    go, _ = slot_budget.verdict(3, "other", directory=tmp_path, budget=budget, ram_reader=lambda: 20.0)
    assert not go


def test_over_the_cap_waits(tmp_path):
    go, line = slot_budget.verdict(5, "merge_suite", directory=tmp_path, budget=_budget(), ram_reader=lambda: 20.0)
    assert not go and line.startswith("WAIT")


def test_ram_floor_waits(tmp_path):
    go, line = slot_budget.verdict(1, "merge_suite", directory=tmp_path, budget=_budget(), ram_reader=lambda: 5.1)
    assert not go and "RAM free 5.1 GB < 8 GB" in line


def test_missing_key_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")  # #847: the file names only the day window
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"day": {"hours": [0, 24], "total": 7, "others": 2, "min_free_ram_gb": 8}}))
    budget = slot_budget.load_budget(path=path)
    assert budget.limit_for("merge_suite") == slot_budget.DEFAULT_BUDGET["day"]["merge_suite"] == 6
    path.write_text(json.dumps({"day": {"hours": [0, 24], "total": 7, "others": 2, "min_free_ram_gb": 8, "merge_suite": 5}}))
    assert slot_budget.load_budget(path=path).limit_for("merge_suite") == 5


def test_cli_role_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_FORCE_PERIOD", "day")  # #847: the file names only the day window
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"day": {"hours": [0, 24], "total": 7, "others": 2, "min_free_ram_gb": 0, "merge_suite": 4}}))
    env = {**os.environ, "JUNKROAN_POB_BUDGET": str(path), "JUNKROAN_POB_SLOT_DIR": str(tmp_path / "locks")}
    run = lambda n: subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "machine_load.py"), "--need", str(n), "--role", "merge_suite", "--quiet"],
        env=env, capture_output=True, text=True, cwd=ROOT,
    )
    assert run(4).returncode == 0
    assert run(5).returncode == 3
