"""Corpus-only parts of the skeleton generator (no PoB)."""

from junkroan.optimizer.objective import Objective
from junkroan.search.generator import ONE_HAND_TYPES, TWO_HAND_TYPES, candidate_bases

from conftest import needs_skill_source


def test_candidate_bases_are_droppable_and_one_per_attribute_profile() -> None:
    body = candidate_bases("Body Armour", max_level=70)
    assert "Vaal Regalia" in body and 4 <= len(body) <= 7  # one top base per str/dex/int combination
    for bad in ("Golden Plate", "Energy Blade One Handed", "Transfer-attuned Spirit Shield", "Grasping Mail"):
        for t in ("Body Armour", "Shield", *ONE_HAND_TYPES, *TWO_HAND_TYPES):
            assert bad not in candidate_bases(t, max_level=70)
    assert "Simplex Amulet" not in candidate_bases("Amulet", max_level=70)
    rings = candidate_bases("Ring", max_level=70)
    assert "Cryonic Ring" not in rings and "Amethyst Ring" in rings and "Moonstone Ring" in rings
    assert "Two-Stone Ring (Fire/Cold)" in candidate_bases("Ring", max_level=70) or "Two-Stone Ring" in candidate_bases("Ring", max_level=70)


def test_the_base_screen_leaves_armour_and_jewellery_to_the_wishlist_filler() -> None:
    """In wishlist mode (D71) the screen does not roll loot for a base it would be overruled on:
    the filler judges every base of the class itself. The slot still names its class, and the
    screen must not touch PoB to do it."""

    from junkroan.optimizer.item_bases import type_of
    from junkroan.optimizer.rails import Rails
    from junkroan.search.generator import ARMOUR_SLOT_TYPES, SkeletonGenerator
    from junkroan.search.skeleton import Skeleton

    class _NoPob:
        def __getattr__(self, name):  # a wishlist screen that calls PoB is the bug this catches
            raise AssertionError(f"the wishlist base screen must not call PoB ({name})")

    sk = Skeleton(class_name="Witch", ascendancy="Elementalist", level=77, main_link=["Fireball"],
                  rare_bases={"Weapon 1": "Prophecy Wand", "Weapon 2": "Titanium Spirit Shield"})
    chosen = SkeletonGenerator(_NoPob(), Rails.load(), objective=Objective(maximize="CombinedDPS"), gear_mode="wishlist").screen_bases(sk)

    assert set(chosen) == set(ARMOUR_SLOT_TYPES)
    assert all(type_of(base) == ARMOUR_SLOT_TYPES[slot] for slot, base in chosen.items())
    assert sk.rare_bases["Weapon 1"] == "Prophecy Wand"  # the weapon the skeleton came with is untouched


def test_objective_without_drops_only_the_named_floor() -> None:
    o = Objective(maximize="CombinedDPS", floors={"Life": 3700, "EffectiveMovementSpeedMod": 1.2}, relations=(("Str", "ReqStr", 1.0),))
    w = o.without("EffectiveMovementSpeedMod")
    assert w.floors == {"Life": 3700} and w.relations == o.relations and "EffectiveMovementSpeedMod" not in w.stat_keys


def test_utility_candidates_are_base_gems_by_family() -> None:
    from junkroan.search.generator import SkeletonGenerator
    from junkroan.search.skeleton import Skeleton

    gen = SkeletonGenerator.__new__(SkeletonGenerator)  # corpus-only method, no PoB needed
    cands = gen.utility_candidates(Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball", "Spell Echo"]))
    assert "Herald of Ash" in cands["herald"] and "Purity of Fire" in cands["aura"]
    assert "Summon Carrion Golem" in cands["golem"] and "Summon Carrion Golem of Hordes" in cands["golem"]
    assert cands["movement"][0] in ("Dash", "Flame Dash", "Frostblink", "Quickstep") and "Cyclone" not in cands["movement"]
    assert "Vaal Haste" not in cands["aura"] and "Smite" not in cands["aura"] and "Flammability" in cands["curse"]


def test_parts_named_maximum_are_assumptions_not_states() -> None:
    from junkroan.search.generator import part_is_assumption

    assert part_is_assumption("Maximum Hits") and part_is_assumption("Max Overlap")
    assert not part_is_assumption("10 Blades") and not part_is_assumption("1 Hit") and not part_is_assumption("")


@needs_skill_source
def test_uptime_limited_buffs_are_known_and_never_utility_picks() -> None:
    from junkroan.optimizer.audit import audit_buff_uptime
    from junkroan.pob.skill_facts import buff_uptime, cooldown_seconds

    assert cooldown_seconds("Ambush") == 5.0 and abs(buff_uptime("Ambush") - 0.3) < 1e-9
    assert buff_uptime("Hatred") is None and buff_uptime("BloodRage") is None  # always-on is right for these
    assert buff_uptime("FlameDash") == 1.0
    assert any(f.check == "buff uptime" and "30%" in f.detail for f in audit_buff_uptime("Ambush"))
    assert audit_buff_uptime("Hatred") == [] and audit_buff_uptime("No Such Gem") == []
