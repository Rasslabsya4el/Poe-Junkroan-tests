"""#553 unit 11: every objective floor the delivered build misses is an audit error; a miss inside the loop's 1e-9 slack is nothing."""

from __future__ import annotations
from conftest import pc_only

import glob
import json
from pathlib import Path

from junkroan.optimizer.audit import audit_stats
from junkroan.optimizer.benchmark_rows import VIOLATION_TOLERANCE, counted_row, last_stage_violation
from junkroan.optimizer.objective import Objective

ROWS = Path(__file__).resolve().parents[1] / "artifacts" / "benchmark" / "20261005-1220-gate-20261005" / "rows"


def _floors(stats: dict, **floors: float) -> list:
    return [f for f in audit_stats(stats, Objective(floors=floors)) if f.check == "floor"]


def test_a_missed_movement_speed_floor_is_an_error() -> None:
    found = _floors({"EffectiveMovementSpeedMod": 1.14}, EffectiveMovementSpeedMod=1.164)
    assert len(found) == 1 and found[0].severity == "error"


def test_a_miss_inside_the_slack_is_nothing() -> None:
    assert _floors({"EffectiveMovementSpeedMod": 1.1639999999}, EffectiveMovementSpeedMod=1.164) == []


def test_life_below_its_floor_stays_an_error() -> None:
    found = _floors({"Life": 3000.0}, Life=4000.0)
    assert len(found) == 1 and found[0].severity == "error"


def test_the_ramp_finding_is_not_a_floor_error() -> None:
    found = audit_stats({"RampSeconds": 4.2, "RampBudget": 2.5}, Objective())
    assert [f.check for f in found] == ["ramp"]


def test_row_ok_is_false_for_a_row_with_a_floor_error() -> None:
    row = {"ok": True, "audit": ["[error] floor: EffectiveMovementSpeedMod = 1.140 < 1.164"]}
    assert not counted_row(row)
    assert counted_row({"ok": True, "audit": []})


@pc_only
def test_gate_rows_end_feasible() -> None:
    """Rows keep no per-floor stats, only the objective's `violation` of the last stage (the sum the floors,
    ceilings and relations add up to, with the same 1e-9 slack): zero violation means no floor is missed."""

    paths = glob.glob(str(ROWS / "*.json"))
    rows = [json.loads(Path(p).read_text(encoding="utf-8")) for p in paths]
    missed = [r.get("slug") for r in rows if last_stage_violation(r) > VIOLATION_TOLERANCE]
    print(f"rows {len(rows)}, with a missed floor/ceiling/relation at the end: {len(missed)} {missed}")
    assert len(rows) == 61 and missed == []
