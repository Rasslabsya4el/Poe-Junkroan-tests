"""#531: a unique variant never pairs a Weapon 2 off-hand with a two-handed Weapon 1, whichever pick came first."""

from junkroan.search.hypothesis import item_bases
from junkroan.search.runner import PAIR_CLASS, pick_unique_variant
from junkroan.search.skeleton import Skeleton


def _one_hand_base() -> str:
    return next(rec["name"] for rec in item_bases().values() if rec.get("type") == "One Handed Sword")


def _sk() -> Skeleton:
    return Skeleton(class_name="Duelist", ascendancy="Champion", rare_bases={"Weapon 1": _one_hand_base()})


def _screen(first, second):
    return [{"slot": s, "name": n, "gain": g} for s, n, g in (first, second)]


def _pair(considered):
    return considered["unique-variant"][PAIR_CLASS]


def test_shield_first_two_hander_refused():
    var, considered = pick_unique_variant(
        _sk(), _screen(("Weapon 2", "Kaltenhalt", 0.15), ("Weapon 1", "Terminus Est", 0.12)), 0.10, 3)
    assert var.uniques == {"Weapon 2": "Kaltenhalt"}
    assert _pair(considered) == {"generated": 1, "evaluated": 0}


def test_two_hander_first_shield_refused():
    var, considered = pick_unique_variant(
        _sk(), _screen(("Weapon 1", "Terminus Est", 0.15), ("Weapon 2", "Kaltenhalt", 0.12)), 0.10, 3)
    assert var.uniques == {"Weapon 1": "Terminus Est"}
    assert _pair(considered) == {"generated": 1, "evaluated": 0}
