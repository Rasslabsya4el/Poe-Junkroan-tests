"""#704: the build report's floors cell and seconds cell. PoB-free: the stats frames are built from the
rails objective's own floors (every floor met by 10 %), plus the values recorded in the #617 weekly run
row impale_ballista-s4 (Life 4068; EffectiveMovementSpeedMod violation 0.0464 in its report.md, which
is 1.2 * (1 - 0.0464) observed; the row file does not keep the full stats frame)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import floors_cell, missed_constraints
from junkroan.optimizer.rails import Rails
from junkroan.report_format import human_duration

ROW = Path(__file__).resolve().parents[1] / "artifacts/benchmark/20261007-0350-P1-#617-3/rows/impale_ballista-s4.json"


def _objective():
    return Rails.load().objective().replace(relations=(), derived=())


def _met_frame(objective) -> dict[str, float]:
    return {stat: floor * 1.1 + 1.0 for stat, floor in objective.floors.items() if "+" not in stat}


def test_row1_a_build_that_holds_every_floor_reads_ok() -> None:
    obj = _objective()
    obj = obj.replace(floors={k: v for k, v in obj.floors.items() if "+" not in k})
    assert floors_cell(missed_constraints(_met_frame(obj), obj)) == "ok"


@pytest.mark.skipif(not ROW.exists(), reason="the #617 weekly run row is not linked here")
def test_row2_a_missed_floor_is_named_with_observed_and_floor() -> None:
    obj = _objective()
    obj = obj.replace(floors={k: v for k, v in obj.floors.items() if "+" not in k})
    row = json.loads(ROW.read_text(encoding="utf-8"))
    stats = _met_frame(obj)
    stats["EffectiveMovementSpeedMod"] = 1.2 * (1 - 0.0464)
    cell = floors_cell(missed_constraints(stats, obj))
    assert cell == "EffectiveMovementSpeedMod 1.144 < 1.200"
    stats["Life"] = row["ours_life"]
    cell = floors_cell(missed_constraints(stats, obj))
    assert cell == "Life 4,068 < 4,500; EffectiveMovementSpeedMod 1.144 < 1.200"


def test_more_than_three_misses_are_cut_with_a_count() -> None:
    assert floors_cell(["a 1 < 2", "b 1 < 2", "c 1 < 2", "d 1 < 2", "e 1 < 2"]) == "a 1 < 2; b 1 < 2; c 1 < 2; +2 more"


def test_row3_seconds_cell_is_human() -> None:
    assert human_duration(7560) == "2 h 06 min"
    src = (Path(__file__).resolve().parents[1] / "scripts/search.py").read_text(encoding="utf-8")
    assert "human_duration(r['seconds'])" in src and "r['seconds']:.0f" not in src


def test_row4_ranking_keys_are_untouched() -> None:
    src = (Path(__file__).resolve().parents[1] / "scripts/search.py").read_text(encoding="utf-8")
    assert 'finals.sort(key=lambda r: (not r.get("audit_errors"), r["feasible"], -r["violation"], r["value"]), reverse=True)' in src
    assert 'front = pareto_front([{"value": r["value"] if r["feasible"] and not r.get("audit_errors") else 0, "ehp": bossing_defence(r["final"] or {})}' in src
