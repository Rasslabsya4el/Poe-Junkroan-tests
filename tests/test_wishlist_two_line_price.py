"""Rulebook g-rarity (day1, #428): an open mod with a group share in [0.2 %, 1 %) occupies two template lines."""

from __future__ import annotations

from dataclasses import replace

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear
from tests.test_wishlist_gear import FakePob, _mod

TOTAL = 100_000


def _fill(rare_weight: int, *, rare_worth: float = 50_000.0):
    """A weapon with three open lines; one rare prefix of the given weight, two common prefixes."""

    rest = (TOTAL - rare_weight) // 2
    mods = [
        _mod("Rare", "Prefix", weight=rare_weight, line="+1 to Level of all Fire Spell Skill Gems"),
        _mod("CommonA", "Prefix", weight=rest),
        _mod("CommonB", "Prefix", weight=rest),
    ]
    pob = FakePob(mods, worth={"Rare": rare_worth, "CommonA": 100.0, "CommonB": 90.0})
    rails = Rails.load()
    rails = replace(rails, gear=replace(rails.gear, wishlist=replace(rails.gear.wishlist, weapon_open_lines=3)))
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), rails)
    return gear, gear.fill_slot("Weapon 1", "Fake Void Sceptre")


def _rare(gear: WishlistGear):
    return next(mod for mod in gear._median_mods("Fake Void Sceptre", 76, affix_type="Prefix") if mod.group == "Rare")


def test_the_rail_is_one_percent_in_the_default_rails() -> None:
    assert Rails.load().gear.wishlist.open_mod_two_lines_below_share == 0.01


def test_a_037_percent_mod_takes_two_lines_and_leaves_one_for_the_rest() -> None:
    gear, result = _fill(370)  # 0.37 %

    assert _rare(gear).share == 0.0037 and _rare(gear).line_cost == 2
    assert [mod.group for mod in result.affixes] == ["Rare", "CommonA"]
    assert next(line for line in result.shopping if line.get("mod_id") == "Rare")["line_cost"] == 2


def test_a_12_percent_mod_costs_one_line_and_leaves_two() -> None:
    gear, result = _fill(1_200)  # 1.2 %

    assert _rare(gear).line_cost == 1
    assert [mod.group for mod in result.affixes] == ["Rare", "CommonA", "CommonB"]


def test_a_01_percent_mod_is_blocked_unchanged() -> None:
    gear, result = _fill(100)  # 0.1 %

    assert "Rare" not in {mod.group for mod in gear._median_mods("Fake Void Sceptre", 76, affix_type="Prefix")}
    assert [mod.group for mod in result.affixes] == ["CommonA", "CommonB"]


def test_a_two_line_mod_that_loses_to_the_best_ordinary_pair_is_dropped() -> None:
    # Rare is the best single line (120 > 100) but worth less than CommonA + CommonB (190).
    _gear, result = _fill(370, rare_worth=120.0)

    assert any("loses to the best ordinary pair" in step for step in result.steps)
    assert result.affixes[0].group == "CommonA"


def test_a_two_line_mod_needs_a_second_free_line() -> None:
    """On a one-flexible-line template there is no second line to pay with."""

    pob = FakePob([_mod("Rare", "Prefix", weight=370), _mod("Common", "Prefix", weight=99_630)], worth={"Rare": 50_000.0})
    result = WishlistGear(pob, Objective(maximize="CombinedDPS"), Rails.load()).fill_slot("Helmet", "Fake Helmet")

    assert "Rare" not in {mod.group for mod in result.affixes}
