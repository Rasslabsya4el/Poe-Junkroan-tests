"""Forced mod lines under the wishlist gear model (#510 unit 6): a forced line is one of the item's template
lines and no pass removes it. PoB-free, on the fakes of the existing wishlist tests."""

from __future__ import annotations

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.wishlist_gear import WishlistGear, WishlistSlotResult, template_for
from junkroan.search.forced import raw_has_affix
from test_wishlist_gear import FakePob, _mod, _normal_armour_mods, _rails

FORCED = "+1 to Level of all Fire Spell Skill Gems"


class TextPob(FakePob):
    """FakePob whose items carry the mod text lines (as PoB's raw does) and which logs every item it is shown."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.shown: list[tuple[str, str]] = []

    def craft_rare(self, base, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None) -> dict:
        crafted = super().craft_rare(base, prefixes=prefixes, suffixes=suffixes, ilvl=ilvl, quality=quality, sockets=sockets)
        by_id = {mod["mod_id"]: mod for mod in self.mods}
        ids = [str(row["mod_id"]) for row in [*prefixes, *suffixes]]
        crafted["raw"] += "".join("\n" + line for mod_id in ids for line in by_id[mod_id]["lines"])
        return crafted

    def trial_stats(self, trials, keys, mode="fast"):
        self.shown.extend((trial["item"]["slot"], trial["item"]["raw"]) for trial in trials)
        return super().trial_stats(trials, keys, mode)

    def equip(self, updates):
        self.shown.extend((slot, raw) for slot, raw in updates.items() if raw)
        super().equip(updates)


def _forced_mod_row() -> dict:
    return _mod("FireGemLevel", "Prefix", mod_id="forced1", weight=5_000, line=FORCED, tags=("caster", "gem"))


def _wand_mods() -> list[dict]:
    return [_forced_mod_row(), _mod("OpenA", "Prefix", weight=5_000), _mod("OpenB", "Suffix", weight=5_000), _mod("OpenC", "Suffix", weight=5_000)]


def _wand(forced: list[str] | None) -> tuple[WishlistGear, WishlistSlotResult]:
    worth = {"forced1": 1.0, "OpenA": 10_000, "OpenB": 9_000, "OpenC": 8_000}
    gear = WishlistGear(TextPob(_wand_mods(), worth=worth), Objective(maximize="CombinedDPS"), _rails())
    if forced is not None:
        gear.forced_lines = {"Weapon 1": forced}
    return gear, gear.fill_slot("Weapon 1", "Fake Wand")


def test_a_forced_line_takes_a_template_line_and_never_adds_a_fourth() -> None:
    _plain_gear, plain = _wand(None)
    gear, forced = _wand([FORCED])

    # Same line count as the template fill, and one of the lines is the forced one.
    assert len(forced.affixes) + int(forced.bench is not None) == len(plain.affixes) + int(plain.bench is not None)
    assert len(forced.affixes) + int(forced.bench is not None) <= len(template_for("Fake Wand", "Weapon 1"))
    assert "forced1" in forced.mod_ids
    assert raw_has_affix(forced.raw, FORCED)
    assert not gear._forced_lacking("Weapon 1", forced.raw)
    # The forced line sits where the first open line would have been: the best of the others follows (#429 u3: the weapon template is 2 open + 1 craft).
    assert forced.mod_ids == ["forced1", "OpenA"]
    assert any(entry.get("forced") and entry["mod_id"] == "forced1" for entry in forced.shopping)


def test_empty_forced_lines_change_nothing() -> None:
    _gear, plain = _wand(None)
    _gear, empty = _wand([])

    assert sorted(plain.mod_ids) == ["OpenA", "OpenB"]
    assert (empty.raw, empty.mod_ids, empty.steps, empty.shopping) == (plain.raw, plain.mod_ids, plain.steps, plain.shopping)
    assert WishlistGear(FakePob([]), Objective(maximize="CombinedDPS"), _rails()).forced_lines == {}


def test_a_forced_line_the_base_cannot_roll_raises() -> None:
    gear = WishlistGear(TextPob(_wand_mods()), Objective(maximize="CombinedDPS"), _rails())
    gear.forced_lines = {"Weapon 1": ["+1 to Level of all Chaos Spell Skill Gems"]}

    with pytest.raises(ValueError, match="cannot roll on Fake Wand"):
        gear.fill_slot("Weapon 1", "Fake Wand")


def _helmet_mods() -> list[dict]:
    return [*_normal_armour_mods(), _mod("FireGemLevel", "Prefix", mod_id="forced1", line=FORCED)]


def _forced_helmet(pob: TextPob) -> tuple[WishlistGear, WishlistSlotResult]:
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear.forced_lines = {"Helmet": [FORCED]}
    gear._resistance_assignments["Helmet"] = "fire"
    result = gear.fill_slot("Helmet", "Fake Helmet")
    assert "forced1" in result.mod_ids and len(result.affixes) == 3  # life + resistance + the forced line
    return gear, result


def test_line_swap_pass_never_shows_pob_a_helmet_without_the_forced_line() -> None:
    pob = TextPob(_helmet_mods())
    gear, result = _forced_helmet(pob)
    movement = gear._mod_at_tier("Fake Helmet", result.ilvl, "MovementVelocity", 3)
    forced_mod = next(mod for mod in result.affixes if mod.mod_id == "forced1")
    # Everything but the forced line is worth less than a movement line, and the forced line itself is worth nothing:
    # dropping it would be the cheapest move there is, were it allowed.
    pob.worth = {movement.mod_id: 9_000.0}
    pob.shown.clear()

    stats = gear._line_swap_pass([result])

    assert stats["tried"] > 0
    helmet_items = [raw for slot, raw in pob.shown if slot == "Helmet"]
    assert helmet_items and all(raw_has_affix(raw, FORCED) for raw in helmet_items)
    assert forced_mod in result.affixes and raw_has_affix(result.raw, FORCED)
    assert len(result.affixes) == 3


def test_two_item_exchange_pass_never_drops_a_forced_line_on_the_receiver() -> None:
    pob = TextPob(_helmet_mods())
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails(flexible_lines=True))
    gear.forced_lines = {"Gloves": [FORCED]}
    ilvl_h, ilvl_g = (gear.rails.gear.wishlist.item_level_for(slot) for slot in ("Helmet", "Gloves"))
    life = gear._mod_at_tier("Fake Helmet", ilvl_h, "IncreasedLife", 3)
    helmet_raw = gear._raw("Fake Helmet", ilvl_h, [life], None, None)
    forced_mod = gear._forced_mod("Fake Gloves", ilvl_g, FORCED, template_for("Fake Gloves", "Gloves"))
    gloves_raw = gear._raw("Fake Gloves", ilvl_g, [forced_mod], None, None)
    pob.equip({"Helmet": helmet_raw, "Gloves": gloves_raw})
    helmet = WishlistSlotResult(slot="Helmet", base="Fake Helmet", ilvl=ilvl_h, raw=helmet_raw, affixes=[life])
    gloves = WishlistSlotResult(slot="Gloves", base="Fake Gloves", ilvl=ilvl_g, raw=gloves_raw, affixes=[forced_mod])
    for item in (helmet, gloves):
        gear.current_raw[item.slot] = item.raw
        gear._results_by_raw[(item.slot, item.raw)] = item
    movement = gear._mod_at_tier("Fake Helmet", ilvl_h, "MovementVelocity", 3)
    pob.worth = {movement.mod_id: 5_000.0}
    pob.shown.clear()

    gear._two_item_exchange_pass([helmet, gloves])

    assert all(raw_has_affix(raw, FORCED) for slot, raw in pob.shown if slot == "Gloves")
    assert forced_mod in gloves.affixes
