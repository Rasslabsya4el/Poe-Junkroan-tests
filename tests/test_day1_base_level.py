"""#438: the day-1 template base cap is the owner's drop level 70 (`gear.wishlist.base_level_max`),
not the zone level `area_level` 77. Goes through the real offering call sites, no PoB."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.item_bases import base_record, bases_by_type, bases_of_type, drop_level
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear
from junkroan.search.generator import ARMOUR_SLOT_TYPES, SkeletonGenerator

RAILS = Rails.load()
CAP = RAILS.gear.wishlist.base_level_max


def _offered_by_filler(rails: Rails) -> dict[str, list[str]]:
    stub = SimpleNamespace(rails=rails)
    out = {}
    for item_type, records in bases_by_type().items():
        out[item_type] = WishlistGear.base_candidates(stub, str(records[0]["name"]))
    return out


def test_rail_is_70_and_item_levels_unchanged() -> None:
    assert CAP == 70
    assert RAILS.gear.wishlist.area_level == 77
    assert RAILS.gear.item_level == 70
    assert RAILS.gear.wishlist.item_level_for("Body Armour") == 72
    assert RAILS.gear.wishlist.item_level_for("Weapon 1") == 76


def test_no_wishlist_base_offered_above_drop_level_70() -> None:
    offered = _offered_by_filler(RAILS)
    assert offered
    for item_type, names in offered.items():
        for name in names:
            assert drop_level(base_record(name)) <= 70, (item_type, name)


def test_generator_placeholder_base_is_at_most_70() -> None:
    gen = SimpleNamespace(rails=RAILS)
    skeleton = SimpleNamespace(uniques={}, rare_bases={})
    chosen = SkeletonGenerator._screen_armour(gen, skeleton, n=1, seed=0, wishlist=True)
    assert set(chosen) == set(ARMOUR_SLOT_TYPES)
    for slot, name in chosen.items():
        assert drop_level(base_record(name)) <= 70, (slot, name)


def test_bases_of_71_to_77_are_no_longer_offered() -> None:
    old_cap = RAILS.gear.wishlist.area_level
    dropped = {
        name
        for item_type in bases_by_type()
        for name in bases_of_type(item_type, max_level=old_cap)
        if drop_level(base_record(name)) > CAP
    }
    assert {"Carnal Armour", "Convoking Wand"} <= dropped  # drop levels 71 and 72
    offered = {name for names in _offered_by_filler(RAILS).values() for name in names}
    assert not (dropped & offered)


# --- #786: the loot path takes the same drop-level cut as the wishlist path ---


def _loot_offer() -> dict[str, list[str]]:
    from junkroan.search.generator import candidate_bases

    return {t: candidate_bases(t, max_level=CAP) for t in bases_by_type()}


def test_loot_path_reads_the_base_level_max_rail_not_the_ilvl_rail() -> None:
    import inspect

    src = inspect.getsource(SkeletonGenerator)
    assert "max_level = self.rails.gear.item_level" not in src
    assert src.count("max_level = self.rails.gear.wishlist.base_level_max") == 2


def test_loot_path_offers_no_base_above_drop_level_70() -> None:
    offered = _loot_offer()
    assert any(offered.values())
    for item_type, names in offered.items():
        for name in names:
            assert drop_level(base_record(name)) <= CAP, (item_type, name)


def test_loot_offer_is_within_wishlist_offer_and_picks_its_highest_per_profile() -> None:
    # nothing the loot path offers is refused by the wishlist cut; the loot screen keeps one base per
    # attribute profile by design (its highest drop level), never a lower one while a higher one is allowed
    for item_type, names in _loot_offer().items():
        wishlist = set(bases_of_type(item_type, max_level=CAP))
        assert set(names) <= wishlist, item_type
        if item_type in ("Ring", "Amulet", "Belt"):
            continue
        top = max((drop_level(base_record(n)) for n in wishlist if drop_level(base_record(n)) > 0), default=0)
        assert max(drop_level(base_record(n)) for n in names) == top, item_type


def test_ilvl_passed_to_loot_roll_is_70_template_72_weapons_76() -> None:
    from junkroan.optimizer.loot_gear import LootGear

    seen: list[int] = []

    class Stop(Exception):
        pass

    class FakePob:
        def stats(self, keys):
            return {}

        def random_rares(self, base, *, n, ilvl, **kw):
            seen.append(ilvl)
            raise Stop

    gear = SimpleNamespace(
        rails=RAILS,
        pob=FakePob(),
        objective=SimpleNamespace(stat_keys=[], score=lambda s: 0.0),
        _forced_for=lambda slot, base: ([], []),
    )
    try:
        LootGear.fill_slot(gear, "Body Armour", "Astral Plate")
    except Stop:
        pass
    assert seen == [70]
    assert RAILS.gear.wishlist.item_level_for("Body Armour") == 72
    assert RAILS.gear.wishlist.item_level_for("Weapon 1") == 76
