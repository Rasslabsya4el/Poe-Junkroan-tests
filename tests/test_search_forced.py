"""#510 unit 4: no skeleton the search builds drops a request's forced unique, rare base or forced affix slot.
No PoB: the generator is a bare object with a fake session, the runner helpers are pure."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.search.generator import SkeletonGenerator, forced_slots
from junkroan.search.hypothesis import item_bases, uniques_by_name
from junkroan.search.runner import apply_unique_picks, check_forced, forced_violations, unique_pick_ok, weapon_alternative_ok
from junkroan.search.skeleton import Skeleton


def _base_of(kind: str) -> str:
    return next(rec["name"] for rec in item_bases().values() if rec["type"] == kind)


def _unique_of(kind: str) -> str:
    return next(recs[0]["plain_name"] for recs in uniques_by_name().values() if recs[0]["type"] == kind)


BOW, WAND, SHIELD = _base_of("Bow"), _base_of("Wand"), _base_of("Shield")
TWO_HANDER = _unique_of("Bow")


def sk(**kw) -> Skeleton:
    return Skeleton(class_name="Witch", ascendancy="Elementalist", **kw)


# -- forced_violations --------------------------------------------------------------------

def good() -> Skeleton:
    return sk(uniques={"Helmet": "Some Helm"}, rare_bases={"Weapon 1": WAND, "Weapon 2": SHIELD, "Body Armour": "Vaal Regalia"},
              forced_uniques={"Helmet": "Some Helm"}, forced_bases={"Weapon 2": SHIELD}, forced_affixes={"Body Armour": ["+# to maximum Life"]})


def test_a_skeleton_with_its_forced_set_has_no_violation() -> None:
    assert forced_violations(good()) == []
    check_forced(good())  # does not raise


def test_a_skeleton_without_forced_fields_has_no_violation() -> None:
    assert forced_violations(sk()) == []


@pytest.mark.parametrize("broken", ["unique_gone", "unique_renamed", "base_gone", "base_changed", "affix_became_unique"])
def test_each_kind_of_dropped_direction_is_named(broken: str) -> None:
    s = good()
    if broken == "unique_gone":
        s.uniques.pop("Helmet")
    elif broken == "unique_renamed":
        s.uniques["Helmet"] = "Other Helm"
    elif broken == "base_gone":
        s.rare_bases.pop("Weapon 2")
    elif broken == "base_changed":
        s.rare_bases["Weapon 2"] = "Other Shield"
    else:
        s.uniques["Body Armour"] = "Some Chest"
    assert len(forced_violations(s)) >= 1
    with pytest.raises(ValueError, match="forced direction dropped"):
        check_forced(s)


# -- hole 1: _screen_weapons, screen_bases, screen_uniques --------------------------------

class _Score:
    def __init__(self, value: float) -> None:
        self.value = value

    def __gt__(self, other: _Score) -> bool:
        return self.value > other.value


def _generator() -> SkeletonGenerator:
    gen = object.__new__(SkeletonGenerator)
    gen.rails = SimpleNamespace(gear=SimpleNamespace(item_level=84, wishlist=SimpleNamespace(base_level_max=84)))
    gen.pob = SimpleNamespace(equip=lambda *_a, **_k: None)
    gen.log = lambda *_a, **_k: None
    gen.gear_mode = "loot"
    gen._ceiling = lambda slot, base, **_kw: (_Score(100.0 if slot == "Weapon 2" else float(len(base))), f"raw:{base}")
    return gen


def _weapon_screen(**kw) -> tuple[dict[str, str], Skeleton]:
    s = sk(weapon_types=["One Handed Sword", "Bow"], **kw)
    return _generator()._screen_weapons(s), s


def test_weapon_screen_picks_a_shield_when_weapon_2_is_free() -> None:
    chosen, _s = _weapon_screen()
    assert "Weapon 1" in chosen
    assert chosen.get("Weapon 2")  # the old behaviour: a shield or a quiver goes with the weapon


@pytest.mark.parametrize("field", ["forced_bases", "forced_affixes", "forced_uniques"])
def test_weapon_screen_leaves_a_forced_weapon_2_alone(field: str) -> None:
    value = [SHIELD] if field == "forced_affixes" else SHIELD
    chosen, s = _weapon_screen(**{field: {"Weapon 2": value}})
    assert "Weapon 1" in chosen and "Weapon 2" not in chosen
    assert all("Weapon 2" not in alt for alt in s.weapon_alternatives)


def test_screen_bases_never_overwrites_a_forced_base() -> None:
    gen = _generator()
    s = sk(rare_bases={"Weapon 2": SHIELD}, forced_bases={"Weapon 2": SHIELD})
    gen._screen_weapons = lambda skeleton: {"Weapon 1": WAND, "Weapon 2": "Some Other Shield"}
    gen._screen_armour = lambda skeleton, **kw: {"Helmet": "Some Helm Base"}
    gen.screen_bases(s)
    assert s.rare_bases == {"Weapon 1": WAND, "Weapon 2": SHIELD, "Helmet": "Some Helm Base"}


def test_screen_bases_without_forced_fields_overwrites_as_before() -> None:
    gen = _generator()
    s = sk(rare_bases={"Weapon 2": SHIELD})
    gen._screen_weapons = lambda skeleton: {"Weapon 2": "Some Other Shield"}
    gen._screen_armour = lambda skeleton, **kw: {}
    gen.screen_bases(s)
    assert s.rare_bases == {"Weapon 2": "Some Other Shield"}


def test_screen_uniques_tries_nothing_in_a_fixed_slot() -> None:
    tried: list[str] = []

    def unique_item(name: str):
        tried.append(name)
        raise RuntimeError("stop")

    gen = _generator()
    gen.rails = SimpleNamespace(unique_max_req_level=100, unique_availability=("core",), unique_allowed=lambda r: True)
    gen.pob = SimpleNamespace(unique_item=unique_item, trial_stats=lambda *a, **k: [])
    gen._score = lambda: _Score(1.0)
    gen.objective = SimpleNamespace(stat_keys=[])

    def types_tried(fixed) -> set[str]:
        tried.clear()
        gen.screen_uniques(slots=("Helmet", "Amulet"), fixed=fixed)
        return {rec["type"] for recs in uniques_by_name().values() for rec in recs if rec["plain_name"] in tried}

    assert "Amulet" in types_tried(None)
    assert "Amulet" not in types_tried(forced_slots(sk(forced_affixes={"Amulet": ["x"]})))
    only_amulet = types_tried({"Helmet"})
    assert "Helmet" not in only_amulet and "Amulet" in only_amulet


# -- hole 2 and 4: unique picks -----------------------------------------------------------

def test_no_unique_for_a_forced_base_or_forced_affix_slot() -> None:
    s = sk(forced_bases={"Weapon 2": SHIELD}, forced_affixes={"Amulet": ["x"]}, forced_uniques={"Helmet": "Some Helm"})
    for slot in ("Weapon 2", "Amulet", "Helmet"):
        assert not unique_pick_ok(s, slot, "Anything")
    assert unique_pick_ok(s, "Boots", "Anything")


def test_a_two_hander_unique_never_pushes_out_a_fixed_weapon_2() -> None:
    s = sk(forced_bases={"Weapon 2": SHIELD})
    assert not unique_pick_ok(s, "Weapon 1", TWO_HANDER)
    assert unique_pick_ok(sk(), "Weapon 1", TWO_HANDER)


def test_apply_unique_picks_keeps_a_forced_slot_s_rare_base() -> None:
    s = sk(rare_bases={"Weapon 1": WAND, "Weapon 2": SHIELD, "Boots": "B"}, forced_bases={"Weapon 2": SHIELD})
    apply_unique_picks(s, {"Weapon 1": TWO_HANDER, "Boots": "Some Boots"})
    assert s.rare_bases == {"Weapon 2": SHIELD}  # the unique slots lose their rare, the fixed shield stays
    assert s.uniques == {"Weapon 1": TWO_HANDER, "Boots": "Some Boots"}


def test_apply_unique_picks_without_forced_fields_is_the_old_behaviour() -> None:
    s = sk(rare_bases={"Weapon 1": WAND, "Weapon 2": SHIELD, "Boots": "B"})
    apply_unique_picks(s, {"Weapon 1": TWO_HANDER, "Boots": "Some Boots"})
    assert s.rare_bases == {}  # the two-hander took the shield with it
    s2 = sk(uniques={"Helmet": "H"}, rare_bases={"Amulet": "A"})
    apply_unique_picks(s2, {"Helmet": "H", "Amulet": "Some Amulet"}, replace=True)
    assert s2.uniques == {"Helmet": "H", "Amulet": "Some Amulet"} and s2.rare_bases == {}


# -- hole 3: weapon alternatives ----------------------------------------------------------

def test_weapon_alternative_never_changes_a_forced_base() -> None:
    s = sk(rare_bases={"Weapon 1": WAND, "Weapon 2": SHIELD}, forced_bases={"Weapon 2": SHIELD})
    assert weapon_alternative_ok(s, {"Weapon 1": BOW, "Weapon 2": SHIELD})
    assert not weapon_alternative_ok(s, {"Weapon 1": BOW})  # a bow would drop the shield
    assert not weapon_alternative_ok(s, {"Weapon 1": BOW, "Weapon 2": "Other Shield"})
    s1 = sk(rare_bases={"Weapon 1": WAND}, forced_bases={"Weapon 1": WAND})
    assert not weapon_alternative_ok(s1, {"Weapon 1": BOW})


def test_weapon_alternative_keeps_the_forced_affix_class() -> None:
    s = sk(rare_bases={"Weapon 1": WAND}, forced_affixes={"Weapon 1": ["x"]}, weapon_types=["Wand"])
    assert not weapon_alternative_ok(s, {"Weapon 1": BOW})
    assert weapon_alternative_ok(s, {"Weapon 1": WAND})
    s2 = sk(rare_bases={"Weapon 1": WAND}, forced_affixes={"Weapon 1": ["x"]})  # no weapon_types: the class it has now
    assert not weapon_alternative_ok(s2, {"Weapon 1": BOW})


def test_weapon_alternative_without_forced_fields_is_always_allowed() -> None:
    s = sk(rare_bases={"Weapon 1": WAND, "Weapon 2": SHIELD})
    assert weapon_alternative_ok(s, {"Weapon 1": BOW})
    assert weapon_alternative_ok(s, {"Weapon 1": BOW, "Weapon 2": "Other Shield"})


def test_a_forced_affix_slot_without_a_chosen_base_is_legal() -> None:
    """The check runs before the base screen (and the wishlist filler picks armour bases itself)."""
    s = good()
    s.rare_bases.pop("Body Armour")
    assert forced_violations(s) == []
