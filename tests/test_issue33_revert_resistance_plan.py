"""#33: a reverted gear move puts back `_extra_resistance_assignments` and `resistance_plan`.

PoB-free: a fake wishlist filler whose plan step rewrites the three resistance attributes the way
`WishlistGear._plan_resistances` does (wishlist_gear.py:1730-1731, :1850).
"""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.wishlist_gear import WishlistGear


class FakeFiller(WishlistGear):  # the public snapshot / restore are WishlistGear's own (#795)
    def __init__(self) -> None:  # no super: no PoB
        self._resistance_assignments = {"Helmet": "fire"}
        self._extra_resistance_assignments = {"Boots": "cold"}
        self.resistance_plan = SimpleNamespace(extra=["a"], assignments={"Helmet": "fire"})

    def plan_resistances(self) -> None:
        self._resistance_assignments = {"Helmet": "chaos", "Gloves": "fire"}
        self._extra_resistance_assignments = {**self._extra_resistance_assignments, "Gloves": "lightning"}
        self.resistance_plan = SimpleNamespace(extra=["b"], assignments={"Gloves": "fire"})

    def fill(self) -> None:
        self._extra_resistance_assignments.pop("Boots", None)  # in place, as :1850 does
        self.resistance_plan.extra.append("c")  # in place on the shared plan object


def _state(gear: FakeFiller) -> tuple:
    return (dict(gear._resistance_assignments), dict(gear._extra_resistance_assignments),
            (list(gear.resistance_plan.extra), dict(gear.resistance_plan.assignments)))


def test_restore_puts_back_extra_assignments_and_plan() -> None:
    gear = FakeFiller()
    before = _state(gear)
    saved = gear.resistance_plan_snapshot()
    gear.plan_resistances()
    gear.fill()
    assert _state(gear) != before
    gear.restore_resistance_plan(saved)
    assert _state(gear) == before


def test_in_place_change_after_restore_does_not_leak_into_snapshot() -> None:
    gear = FakeFiller()
    before = _state(gear)
    saved = gear.resistance_plan_snapshot()
    gear.fill()  # mutates the live objects in place
    gear.restore_resistance_plan(saved)
    gear.fill()  # mutates the restored objects: the snapshot must stay clean
    gear.restore_resistance_plan(saved)
    assert _state(gear) == before


def test_snapshot_is_empty_on_the_loot_filler() -> None:
    loot = LootGear.__new__(LootGear)
    saved = loot.resistance_plan_snapshot()
    assert saved == {}
    loot.restore_resistance_plan(saved)
    assert not hasattr(loot, "resistance_plan")
