"""#795 step 3: one interface for LootGear and WishlistGear. No PoB: stubs.

For each new method: LootGear answers what the loop's `not _is_template` branch does today; WishlistGear
delegates to the member the call site read before (kept private)."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from junkroan.optimizer import improvement_loop as il
from junkroan.optimizer.gear_interface import GearInterface
from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.wishlist_gear import RESISTANCE_PLAN_ATTRS, BaseChoice, WishlistGear, WishlistSlotResult


def _rails() -> SimpleNamespace:
    wishlist = SimpleNamespace(item_level_for=lambda slot: 72 if slot != "Boots" else 68, base_level_max=72)
    return SimpleNamespace(gear=SimpleNamespace(item_level=70, wishlist=wishlist))


def _loot() -> LootGear:
    loot = object.__new__(LootGear)
    loot.rails, loot.current_raw = _rails(), {}
    return loot


def _wishlist() -> WishlistGear:
    gear = object.__new__(WishlistGear)
    gear.rails, gear.current_raw = _rails(), {}
    gear._resistance_assignments, gear._extra_resistance_assignments, gear.resistance_plan = {"Helmet": "Fire"}, {"Boots": "Cold"}, None
    gear._results_by_raw = {}
    return gear


def _result(base: str, raw: str) -> WishlistSlotResult:
    result = object.__new__(WishlistSlotResult)
    result.base, result.implicit, result.raw = base, "old implicit", raw
    return result


def test_both_fillers_are_the_interface() -> None:
    assert isinstance(_loot(), GearInterface) and isinstance(_wishlist(), GearInterface)


def test_item_level_for_replaces_the_isinstance_ternary() -> None:
    rails = _rails()
    assert _loot().item_level_for("Weapon 1") == rails.gear.item_level  # improvement_loop :616, pipeline :1307 (loot branch)
    assert _wishlist().item_level_for("Boots") == 68 and _wishlist().item_level_for("default") == 72


@pytest.mark.parametrize("base", ["Imperial Bow", "Vaal Axe", "Hubris Circlet", "Not A Base"])
def test_other_weapon_bases_is_the_loops_candidate_list(base: str) -> None:
    loot, wishlist = _loot(), _wishlist()
    assert loot.other_weapon_bases(base) == il._weapon_base_candidates(loot.rails, loot, base)
    assert wishlist.other_weapon_bases(base) == il._weapon_base_candidates(wishlist.rails, wishlist, base)
    assert base not in loot.other_weapon_bases(base) and base not in wishlist.other_weapon_bases(base)
    if base == "Not A Base":
        assert loot.other_weapon_bases(base) == wishlist.other_weapon_bases(base) == []


def test_loot_answers_are_the_not_template_branches() -> None:
    loot = _loot()
    assert loot.refills_by_value is False  # :1297 `_is_template(loot) and ...`
    assert loot.pinned_roll_choices("Boots", "Two-Toned Boots") == []  # :372 adds nothing
    assert loot.preselect_bases(["Helmet"], {"Helmet": "x"}, {"Helmet": None}) == {}  # :436 `selected_bases = None`: no kwargs
    assert loot.resistance_plan_snapshot() == {}  # :1305 / :1490 `None`: nothing to restore
    assert loot.plan_snapshot() == {}  # :978 the saved dict keeps only `current_raw`
    assert loot.shopping_results() == []  # pipeline :1083
    assert loot.restore_resistance_plan({}) is None and loot.plan_restore({}) is None
    assert loot.carry_result("Weapon 1", "a", "b", base="c") is None
    assert loot.flexible_by_value is False


def test_wishlist_delegates_to_the_private_members() -> None:
    gear = _wishlist()
    assert gear.refills_by_value is True
    seen: list[tuple] = []
    gear._rank_bases = lambda slot, base, ilvl, sockets, *, bench_allowed=True: seen.append(("rank", slot, base, ilvl, sockets, bench_allowed)) or [BaseChoice(f"{slot}-pick"), BaseChoice("second")]  # type: ignore[method-assign]
    gear._plan_resistances = lambda bases: seen.append(("plan", dict(bases)))  # type: ignore[method-assign]
    chosen = gear.preselect_bases(["Helmet", "Boots"], {"Helmet": "h", "Boots": "b"}, {"Helmet": "S", "Boots": None})
    assert chosen == {"Helmet": BaseChoice("Helmet-pick"), "Boots": BaseChoice("Boots-pick")}
    assert seen == [("rank", "Helmet", "h", 72, "S", True), ("rank", "Boots", "b", 68, None, True),
                    ("plan", {"Helmet": "Helmet-pick", "Boots": "Boots-pick"})]  # every rank first, then one plan (the loop's order)
    gear._pinned_movement_mod = lambda slot, base: SimpleNamespace(mod_id="M1") if slot == "Boots" else None  # type: ignore[method-assign]
    assert gear.pinned_roll_choices("Boots", "b") == [["M1"]] and gear.pinned_roll_choices("Helmet", "h") == []


def test_wishlist_fill_kwargs_are_the_ones_the_loop_built() -> None:
    gear = _wishlist()
    calls: list[tuple] = []
    gear.fill_slot = lambda slot, base, **kw: calls.append((slot, base, kw)) or "res"  # type: ignore[method-assign]
    choice = BaseChoice("picked")
    assert gear.refill_victim_slot("Helmet", "h", n=5, sockets="S", seed=3, order="priced", preselected=choice) == "res"
    gear.refill_victim_slot("Helmet", "h", n=5, sockets="S", seed=3, order="priced")
    gear.refill_slot("Boots", "b", n=None, sockets=None, seed=4, order="floors")
    assert calls == [
        ("Helmet", "h", {"n": 5, "sockets": "S", "seed": 3, "order": "priced", "_base_candidates": (choice,)}),
        ("Helmet", "h", {"n": 5, "sockets": "S", "seed": 3, "order": "priced"}),
        ("Boots", "b", {"n": None, "sockets": None, "seed": 4, "order": "floors", "replan_resistance": True}),
    ]
    loot = _loot()
    loot_calls: list[tuple] = []
    loot.fill_slot = lambda slot, base, **kw: loot_calls.append((slot, base, kw)) or "res"  # type: ignore[method-assign]
    loot.refill_victim_slot("Helmet", "h", n=5, sockets="S", seed=3, order="priced")
    loot.refill_slot("Boots", "b", n=None, sockets=None, seed=4, order="floors")
    assert loot_calls == [("Helmet", "h", {"n": 5, "sockets": "S", "seed": 3, "order": "priced"}),
                          ("Boots", "b", {"n": None, "sockets": None, "seed": 4, "order": "floors"})]  # no replan_resistance, no _base_candidates


def test_wishlist_resistance_plan_is_the_loops_snapshot_and_restore() -> None:
    gear = _wishlist()
    assert gear.resistance_plan_snapshot() == {n: copy.deepcopy(getattr(gear, n)) for n in RESISTANCE_PLAN_ATTRS if hasattr(gear, n)}  # the loop's old snapshot, inlined
    saved = gear.resistance_plan_snapshot()
    gear._resistance_assignments["Helmet"] = "Lightning"
    assert saved["_resistance_assignments"] == {"Helmet": "Fire"}  # a deep copy
    gear.restore_resistance_plan(saved)
    assert gear._resistance_assignments == {"Helmet": "Fire"} and gear._resistance_assignments is not saved["_resistance_assignments"]
    bare = object.__new__(WishlistGear)  # a gear missing an attribute snapshots only what it has (the hasattr guard)
    bare._resistance_assignments = {}
    assert bare.resistance_plan_snapshot() == {"_resistance_assignments": {}}


def test_wishlist_plan_snapshot_restores_resistance_and_results() -> None:
    gear = _wishlist()
    gear.current_raw = {"Helmet": "raw1", "Boots": "raw2"}
    gear._results_by_raw = {("Helmet", "raw1"): _result("H", "raw1"), ("Gloves", "other"): _result("G", "other")}
    saved = gear.plan_snapshot()
    assert set(saved) == {"resistance", "current_results"} and set(saved["current_results"]) == {("Helmet", "raw1")}
    gear._results_by_raw[("Helmet", "raw1")].base = "changed"
    gear._resistance_assignments["Helmet"] = "Lightning"
    gear.plan_restore(saved)
    assert gear._results_by_raw[("Helmet", "raw1")].base == "H" and gear._resistance_assignments == {"Helmet": "Fire"}


def test_wishlist_carry_result_is_the_two_call_sites() -> None:
    gear = _wishlist()
    gear._results_by_raw = {("Amulet", "old"): _result("A", "old"), ("Weapon 1", "w0"): _result("Bow", "w0")}
    gear.carry_result("Amulet", "old", "new")  # pipeline :1604: raw only
    assert gear._results_by_raw[("Amulet", "new")].raw == "new" and gear._results_by_raw[("Amulet", "new")].implicit == "old implicit"
    assert gear._results_by_raw[("Amulet", "old")].raw == "old"  # the prior stays
    gear.carry_result("Weapon 1", "w0", "w1", base="Imperial Bow", implicit="X")  # improvement_loop :674: base, implicit, raw
    moved = gear._results_by_raw[("Weapon 1", "w1")]
    assert (moved.base, moved.implicit, moved.raw) == ("Imperial Bow", "X", "w1") and gear._results_by_raw[("Weapon 1", "w0")].base == "Bow"
    gear.carry_result("Weapon 1", "missing", "w2", base="Q")  # no prior: nothing recorded
    assert ("Weapon 1", "w2") not in gear._results_by_raw


def test_wishlist_shopping_results_is_unchanged() -> None:
    gear = _wishlist()
    gear.current_raw = {"Helmet": "raw1"}
    gear._results_by_raw = {("Helmet", "raw1"): _result("H", "raw1")}
    assert [r.base for r in gear.shopping_results()] == ["H"]
