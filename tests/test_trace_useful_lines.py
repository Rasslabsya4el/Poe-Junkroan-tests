"""Trace classes of the `g-useful-n` rule (#437 unit 6, on #498's counter): no PoB."""

from __future__ import annotations

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE, classify, output_counts
from tests.test_loot_useful_lines_fill import _FakePob, _raw, _rare


def _trial(raw: str) -> dict:
    return {"item": {"slot": "Ring 1", "raw": raw}}


def test_rare_lines_class_counts_the_affix_lines_and_skips_uniques() -> None:
    assert "rare-lines:4" in classify(_trial(_raw("r", ["A", "B", "C", "D"])))
    unique = "Rarity: UNIQUE\nSome Ring\nIron Ring\nImplicits: 0\n+10 to Strength"
    assert not [c for c in classify(_trial(unique)) if c.startswith("rare-lines:")]
    assert "rare-lines:4" in output_counts([_raw("r", ["A", "B", "C", "D"])], [])


def test_fill_slot_counts_line_value_and_counted_batches_generated_and_evaluated() -> None:
    weights = {"A": 40.0, "B": 25.0, "C": 10.0, "D": 3.0, "Z": 0.0, "Bad": -8.0}
    pob = _FakePob(weights, {"Iron Ring": [_rare("only", ["A", "B", "C", "D", "Z", "Bad"])]})
    loot = LootGear(pob, Objective(maximize="CombinedDPS"), Rails.load(), log=lambda _m: None)
    TRACE.reset()
    with TRACE.move("gear"):
        loot.fill_slot("Ring 1", "Iron Ring", n=1, bench=False)
    cells = TRACE.considered()["gear"]
    for cls in ("useful-lines:counted", "useful-lines:line-value"):
        assert cells[cls]["generated"] > 0 and cells[cls]["evaluated"] > 0, cls
    assert cells["rare-lines:6"]["generated"] > 0
    assert all(c["evaluated"] <= c["generated"] for c in cells.values())
    TRACE.reset()
