"""#428 witness: a [0.2 %, 1 %) mod that is the known-best line is kept at its two-line price; the share bands are traced."""

from __future__ import annotations

from junkroan.optimizer.trace import TRACE
from tests.test_wishlist_two_line_price import _fill, _rare


def _flat() -> dict:
    return {c: v for classes in TRACE.considered().values() for c, v in classes.items()}


def test_best_two_line_mod_is_kept_and_item_has_one_open_line_fewer() -> None:
    TRACE.reset()
    gear, result = _fill(370, rare_worth=50_000.0)  # 0.37 %, far better than any pair of common mods

    assert _rare(gear).line_cost == 2
    assert [mod.group for mod in result.affixes] == ["Rare", "CommonA"]  # 3 open lines: 2 + 1, not 1 + 1 + 1
    assert any("beats the best ordinary pair" in step for step in result.steps)
    band = _flat()["mod-share:0.2-1%"]
    assert band["generated"] > 0 and band["evaluated"] > 0


def test_a_below_02_percent_mod_is_counted_generated_and_never_evaluated() -> None:
    TRACE.reset()
    _fill(100)  # 0.1 %
    band = _flat()["mod-share:<0.2%"]
    assert band["generated"] > 0 and band["evaluated"] == 0
