"""#438 witness: for a Wand slot of a minion build the better "Minions deal (26-30)% increased Damage"
base (Convoking Wand, drop level 72) is no longer offered, and the best minion-damage wand within drop
level 70 (Convening Wand, 50) is offered and wins a selection on that implicit. The stand-in score is the
top of the implicit's range; PoB is not the judge here, the offering is."""

from __future__ import annotations

import re
from types import SimpleNamespace

from junkroan.optimizer.item_bases import base_record, bases_of_type, drop_level, implicit_of
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear

RAILS = Rails.load()


def _score(name: str) -> float:
    return max((float(x) for x in re.findall(r"\d+(?:\.\d+)?", implicit_of(name))), default=0.0)


def _minion_best(pool: list[str]) -> str:
    return max((n for n in pool if implicit_of(n).startswith("Minions deal")), key=lambda n: (_score(n), n))


def test_best_minion_wand_within_70_offered_and_kept_above_70_not_offered() -> None:
    stub = SimpleNamespace(rails=RAILS)
    old_pool = bases_of_type("Wand", max_level=RAILS.gear.wishlist.area_level)
    assert _minion_best(old_pool) == "Convoking Wand" and drop_level(base_record("Convoking Wand")) == 72
    offered = WishlistGear.base_candidates(stub, "Prophecy Wand")
    assert "Convoking Wand" not in offered
    best = _minion_best(offered)
    assert best == "Convening Wand" and drop_level(base_record(best)) == 50 <= 70
    assert best in offered and _score(best) < _score("Convoking Wand")


def test_trace_class_by_drop_level() -> None:
    from junkroan.optimizer.trace import classify

    def cls(base: str) -> set[str]:
        return classify({"item": {"slot": "Weapon 1", "raw": "\n".join(["Rarity: Rare", "X", base])}})

    assert "base-level:<=70" in cls("Convening Wand")
    assert "base-level:>70" in cls("Convoking Wand")
