"""Template v4 (docs/specs/2026-09-22-template-v4-flexible-lines.md): the line COUNT and the
bench-craft count stay the only hard-code; every line's KIND is flexible under three switches
(quiver_weapon_shape, flexible_lines, boots_movement_floor), all on by default (the owner, #8 (a)); the
pinned fixed-template tests in test_wishlist_gear.py turn flexible_lines and boots_movement_floor off in
their own rails (``_rails``). No PoB runtime needed: item_bases is static corpus data and FakePob (from
test_wishlist_gear) fakes the rest.
"""

from __future__ import annotations

from dataclasses import replace

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails, _wishlist_rails
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistSlotResult, template_for
from test_wishlist_gear import FakePob, _normal_armour_mods, _rails


def test_wishlist_rails_flexible_switches_default_on() -> None:
    defaults = _wishlist_rails({})
    assert defaults.quiver_weapon_shape is True
    assert defaults.flexible_lines is True
    assert defaults.boots_movement_floor is True


def test_wishlist_rails_flexible_switches_parse_true() -> None:
    on = _wishlist_rails({"quiver_weapon_shape": True, "flexible_lines": True, "boots_movement_floor": True})
    assert (on.quiver_weapon_shape, on.flexible_lines, on.boots_movement_floor) == (True, True, True)


def test_rails_default_json_ships_the_three_switches_on() -> None:
    """The shipped default file: all three template v4 switches on (spec 2026-09-22 requirement 6)."""

    wishlist = Rails.load().gear.wishlist
    assert (wishlist.quiver_weapon_shape, wishlist.flexible_lines, wishlist.boots_movement_floor) == (True, True, True)


def test_quiver_takes_the_armour_shape_by_default() -> None:
    template = template_for("Blazing Arrow Quiver", "Weapon 2")
    assert [line.kind for line in template] == ["fixed", "resistance", "open_or_craft"]


def test_quiver_weapon_shape_switch_gives_the_weapon_shape() -> None:
    """Requirement 1: a quiver follows the weapon rule (natural open lines + one craft)."""

    template = template_for("Blazing Arrow Quiver", "Weapon 2", weapon_open_lines=3, quiver_weapon_shape=True)
    assert [line.kind for line in template] == ["open", "open", "open", "craft"]


def test_buys_value_recognises_a_flexible_quiver_as_a_weapon_shape() -> None:
    """``_buys_value`` (rule 2's value-first switch) must read the per-instance rails,
    not the bare module default, or a quiver under the switch would still be judged
    violation-first like an armour slot."""

    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(quiver_weapon_shape=True))
    assert gear._buys_value("Blazing Arrow Quiver", "Weapon 2") is True
    gear_off = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails(quiver_weapon_shape=False))
    assert gear_off._buys_value("Blazing Arrow Quiver", "Weapon 2") is False


def test_improve_flexible_lines_is_a_noop_when_both_switches_are_off() -> None:
    gear = WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails())
    assert gear.improve_flexible_lines([]) == {}


def test_flexible_pool_offers_every_boots_movement_tier() -> None:
    """Requirement 5: not just the template's fixed T3 -- every legal tier is a candidate,
    so the floor (not the template) decides which one is worth buying."""

    mods = _normal_armour_mods()
    gear = WishlistGear(FakePob(mods), Objective(maximize="CombinedDPS"), _rails(boots_movement_floor=True))
    gear._resistance_assignments["Boots"] = "fire"
    ilvl = gear.rails.gear.wishlist.item_level_for("Boots")
    pool = gear._flexible_pool(
        "Fake Boots", "Boots", ilvl, [], None,
        pure_es=False, bench_allowed=True, allow_attributes=True, payment_budget_used=0,
    )
    movement_tiers = {mod.tier for mod, craft in pool if mod is not None and mod.group == "MovementVelocity"}
    assert movement_tiers == set(range(1, 9))


def test_flexible_pool_prices_life_and_resistance_at_the_slot_tier_not_the_open_rule() -> None:
    """Requirement 3: IncreasedLife and a resistance stay ordinary candidates, but each
    keeps today's tier rule for its kind wherever it is offered."""

    mods = _normal_armour_mods()
    gear = WishlistGear(FakePob(mods), Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear._resistance_assignments["Helmet"] = "fire"
    ilvl = gear.rails.gear.wishlist.item_level_for("Helmet")
    pool = gear._flexible_pool(
        "Fake Helmet", "Helmet", ilvl, [], None,
        pure_es=False, bench_allowed=True, allow_attributes=True, payment_budget_used=0,
    )
    life_candidates = [mod for mod, craft in pool if mod is not None and mod.group == "IncreasedLife"]
    fire_candidates = [mod for mod, craft in pool if mod is not None and mod.group == "FireResistance"]
    assert len(life_candidates) == 1  # exactly the slot's anchor tier, not the whole ladder
    assert life_candidates[0].tier == gear._mod_at_tier("Fake Helmet", ilvl, "IncreasedLife", 3).tier
    assert len(fire_candidates) == 1
    assert fire_candidates[0].tier == gear._resistance_mod("Fake Helmet", ilvl, "fire", 3).tier  # #429: every slot's resistance line at tier 3 (36-41 %)


def test_line_swap_pass_replaces_the_life_line_when_a_candidate_scores_higher() -> None:
    """Requirement 2's mechanism, isolated: any occupied line may become any other
    legal group once a candidate for it beats the item as it stands (better_score)."""

    mods = _normal_armour_mods()
    pob = FakePob(mods)
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear._resistance_assignments["Helmet"] = "fire"
    base, slot = "Fake Helmet", "Helmet"
    ilvl = gear.rails.gear.wishlist.item_level_for(slot)
    life_mod = gear._mod_at_tier(base, ilvl, "IncreasedLife", 3)
    open_mod = next(mod for mod in gear._median_mods(base, ilvl, affix_type="either") if mod.group == "OpenDamage")
    pob.worth = {open_mod.mod_id: 9_000.0}
    raw = gear._raw(base, ilvl, [life_mod], None, None)
    assert raw is not None
    pob.equip({slot: raw})
    result = WishlistSlotResult(slot=slot, base=base, ilvl=ilvl, raw=raw, affixes=[life_mod])
    gear.current_raw[slot] = raw
    gear._results_by_raw[(slot, raw)] = result

    stats = gear._line_swap_pass([result])

    assert stats["tried"] > 0
    assert stats["kept"] >= 1
    assert [mod.group for mod in result.affixes] == ["OpenDamage"]
    assert gear.current_raw[slot] == result.raw
    # The delivered shopping list follows the item: the life entry left, the new line is on it.
    assert [(line["kind"], line["mod_id"]) for line in result.shopping] == [("objective_line", open_mod.mod_id)]


def test_two_item_exchange_pass_moves_a_floor_line_and_retiers_it_on_the_receiver() -> None:
    """Requirement 4b: judged as one move over the WHOLE build, and the moved line is
    retiered to the RECEIVER's own slot-kind tier (requirement 3), not the giver's."""

    mods = _normal_armour_mods()
    pob = FakePob(mods)
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear._resistance_assignments["Helmet"] = "fire"
    gear._resistance_assignments["Gloves"] = "fire"
    ilvl_helmet = gear.rails.gear.wishlist.item_level_for("Helmet")
    ilvl_gloves = gear.rails.gear.wishlist.item_level_for("Gloves")

    # Giver (Helmet): today's fixed life line and nothing else.
    helmet_base = "Fake Helmet"
    life_mod = gear._mod_at_tier(helmet_base, ilvl_helmet, "IncreasedLife", 3)
    helmet_raw = gear._raw(helmet_base, ilvl_helmet, [life_mod], None, None)
    pob.equip({"Helmet": helmet_raw})
    helmet = WishlistSlotResult(slot="Helmet", base=helmet_base, ilvl=ilvl_helmet, raw=helmet_raw, affixes=[life_mod])
    gear.current_raw["Helmet"] = helmet_raw
    gear._results_by_raw[("Helmet", helmet_raw)] = helmet

    # Receiver (Gloves): one ordinary OpenDamage line, no life line yet.
    gloves_base = "Fake Gloves"
    open_mod = next(mod for mod in gear._median_mods(gloves_base, ilvl_gloves, affix_type="either") if mod.group == "OpenDamage")
    gloves_raw = gear._raw(gloves_base, ilvl_gloves, [open_mod], None, None)
    pob.equip({"Gloves": gloves_raw})
    gloves = WishlistSlotResult(slot="Gloves", base=gloves_base, ilvl=ilvl_gloves, raw=gloves_raw, affixes=[open_mod])
    gear.current_raw["Gloves"] = gloves_raw
    gear._results_by_raw[("Gloves", gloves_raw)] = gloves

    # The giver's best replacement for the line it gives up is worth a lot; the receiver's
    # OpenDamage line it gives up is worth nothing, so the exchange strictly improves the build.
    replacement = next(mod for mod in gear._median_mods(helmet_base, ilvl_helmet, affix_type="either") if mod.group == "MovementVelocity")
    pob.worth = {replacement.mod_id: 5_000.0}

    stats = gear._two_item_exchange_pass([helmet, gloves])

    assert stats["tried"] > 0
    assert stats["kept"] == 1
    assert [mod.group for mod in helmet.affixes] == ["MovementVelocity"]
    assert "IncreasedLife" in [mod.group for mod in gloves.affixes]
    # Retiered to Gloves' OWN life tier (T2), not Helmet's (T3).
    moved = next(mod for mod in gloves.affixes if mod.group == "IncreasedLife")
    assert moved.tier == gear._mod_at_tier(gloves_base, ilvl_gloves, "IncreasedLife", 2).tier


def test_base_reroll_pass_switches_base_when_the_alternate_scores_higher() -> None:
    """Requirement 4c: the base's implicit is judged by what the whole finished (flexible)
    item does with it, so a plain base-name value difference alone can move the choice."""

    mods = _normal_armour_mods()
    pob = FakePob(mods, worth={"Barbute Helmet": 5_000.0})
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear._resistance_assignments["Helmet"] = "fire"
    base, slot = "Aventail Helmet", "Helmet"
    ilvl = gear.rails.gear.wishlist.item_level_for(slot)
    life_mod = gear._mod_at_tier(base, ilvl, "IncreasedLife", 3)
    raw = gear._raw(base, ilvl, [life_mod], None, None)
    pob.equip({slot: raw})
    result = WishlistSlotResult(slot=slot, base=base, ilvl=ilvl, raw=raw, affixes=[life_mod])
    gear.current_raw[slot] = raw
    gear._results_by_raw[(slot, raw)] = result

    stats = gear._base_reroll_pass([result])

    assert stats["tried"] > 0
    assert stats["kept"] >= 1
    assert result.base == "Barbute Helmet"
    assert gear.current_raw[slot] == result.raw
    assert pob.items[slot] == result.raw  # a later, rejected alternate did not leave the first item back on


def test_line_swap_pass_keeps_the_life_line_when_nothing_beats_it() -> None:
    """The move loop starts from today's set and never regresses it (requirement 4
    preamble): with no candidate worth more, the fixed life line survives untouched."""

    mods = _normal_armour_mods()
    pob = FakePob(mods)
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear._resistance_assignments["Helmet"] = "fire"
    base, slot = "Fake Helmet", "Helmet"
    ilvl = gear.rails.gear.wishlist.item_level_for(slot)
    life_mod = gear._mod_at_tier(base, ilvl, "IncreasedLife", 3)
    raw = gear._raw(base, ilvl, [life_mod], None, None)
    pob.equip({slot: raw})
    result = WishlistSlotResult(slot=slot, base=base, ilvl=ilvl, raw=raw, affixes=[life_mod])
    gear.current_raw[slot] = raw
    gear._results_by_raw[(slot, raw)] = result

    stats = gear._line_swap_pass([result])

    assert stats["kept"] == 0
    assert [mod.group for mod in result.affixes] == ["IncreasedLife"]
