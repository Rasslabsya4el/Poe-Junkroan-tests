"""#519: the unique-variant pick never puts into Weapon 2 what PoB's equip refuses (PoB-free, rail test)."""

from junkroan.search.hypothesis import item_bases, uniques_by_name
from junkroan.search.runner import unique_pick_ok
from junkroan.search.skeleton import Skeleton


def _base_of(type_: str) -> str:
    return next(rec["name"] for rec in item_bases().values() if rec.get("type") == type_)


def _quiver() -> str:
    return next(recs[0]["name"].split(", ")[0] for recs in uniques_by_name().values() if recs[0]["type"] == "Quiver")


def _sk(w1_base: str | None = None, uniques: dict | None = None) -> Skeleton:
    rare = {"Weapon 1": w1_base} if w1_base else {}
    return Skeleton(class_name="Duelist", ascendancy="Champion", rare_bases=rare, uniques=uniques or {})


def test_shield_under_two_handed_rare_base():
    assert not unique_pick_ok(_sk("Infernal Sword"), "Weapon 2", "Kaltenhalt")


def test_shield_under_one_handed_rare_base():
    assert unique_pick_ok(_sk(_base_of("One Handed Sword")), "Weapon 2", "Kaltenhalt")


def test_quiver_needs_bow():
    q = _quiver()
    assert not unique_pick_ok(_sk(_base_of("One Handed Sword")), "Weapon 2", q)
    assert not unique_pick_ok(_sk("Infernal Sword"), "Weapon 2", q)
    assert unique_pick_ok(_sk(_base_of("Bow")), "Weapon 2", q)


def test_shield_under_two_handed_unique():
    assert not unique_pick_ok(_sk(uniques={"Weapon 1": "Terminus Est"}), "Weapon 2", "Kaltenhalt")


def test_shield_after_two_hander_picked_in_same_variant():
    sk = _sk(_base_of("One Handed Sword"))
    assert unique_pick_ok(sk, "Weapon 2", "Kaltenhalt")
    assert not unique_pick_ok(sk, "Weapon 2", "Kaltenhalt", {"Weapon 1": "Terminus Est"})
