"""A real `PobSession` takes a machine-wide PoB slot and gives it back.

Skipped when the pinned runtime is not present (var/cache/pob/<tag>/app), like every other
PoB-backed test. The lock directory and the budget are redirected into a temp directory, so this
test never touches the machine's real counter.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from junkroan.pob import slot_budget
from junkroan.pob.session import PobSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def test_a_live_session_holds_one_slot_and_releases_it(monkeypatch, tmp_path):
    slots = tmp_path / "locks"
    budget_file = tmp_path / "machine_budget.json"
    budget_file.write_text(
        json.dumps({"day": {"hours": [0, 24], "total": 4, "others": 2, "min_free_ram_gb": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("JUNKROAN_POB_SLOT_DIR", str(slots))
    monkeypatch.setenv("JUNKROAN_POB_BUDGET", str(budget_file))
    monkeypatch.delenv("JUNKROAN_POB_SLOTS", raising=False)
    monkeypatch.delenv("JUNKROAN_POB_ROLE", raising=False)

    budget = slot_budget.load_budget(path=budget_file)
    with PobSession(run_id="test-slot", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        rows = slot_budget.busy_slots(slots, budget=budget)
        assert [(row["slot"], row["pid"], row["role"]) for row in rows] == [(1, os.getpid(), "other")]
        assert pob.stats(["Life"])["Life"] >= 0  # the runtime really is up behind that slot

    assert slot_budget.busy_slots(slots, budget=budget) == [], "the slot is given back when the session closes"
