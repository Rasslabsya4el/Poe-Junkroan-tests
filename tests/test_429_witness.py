"""#429 witness: the extra resistance line goes to a build 10 % under the cap (at most 2 items), never to one at the cap;
and the trace classes of the rule parse item raws (PoB-free)."""

from __future__ import annotations

from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import classify
from junkroan.optimizer.trace_429 import template_classes
from junkroan.optimizer.wishlist_gear import solve_resistances

_FIXED = [("Body Armour", {"fire": 40.0})]


def _slots(value: float):
    return [(s, {"fire": value, "cold": value, "lightning": value}) for s in ("Helmet", "Gloves", "Boots", "Belt")]


def test_witness_extra_line_kept_under_cap_and_none_at_cap() -> None:
    mx = Rails.load().gear.wishlist.extra_resistance_items
    under = solve_resistances({"FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 65.0}, _FIXED, floor=75.0,
                              extra_slots=_slots(12.0), max_extra=mx)
    assert 1 <= len(under.extra_assignments) <= 2
    assert set(under.extra_assignments.values()) == {"lightning"}
    assert not any(under.shortfall.values())
    at_cap = solve_resistances({"FireResist": 75.0, "ColdResist": 75.0, "LightningResist": 75.0}, _FIXED, floor=75.0,
                               extra_slots=_slots(12.0), max_extra=mx)
    assert at_cap.extra_assignments == {}


def _raw(mods: list[str], weapon: bool = False) -> str:
    head = ["Rarity: RARE", "Doom Grip", "Vaal Axe"]
    if weapon:
        head.append("Physical Damage: 100-200")
    return "\n".join(head + ["Implicits: 1", "+10% to Fire Resistance"] + mods)


def test_trace_classes_read_resistance_tier_and_weapon_lines() -> None:
    t3 = {"item": {"slot": "Helmet", "raw": _raw(["{crafted}+38% to Cold Resistance", "+80 to maximum Life"])}}
    assert {"res-line:36-41", "res-lines:1"} <= classify(t3)
    t2 = {"item": {"slot": "Helmet", "raw": _raw(["+30% to Cold Resistance"])}}
    assert "res-line:other" in classify(t2)
    w = {"item": {"slot": "Weapon 1", "raw": _raw(["+1 a", "+2 b", "+3 c"], weapon=True)}}
    assert "weapon-lines:3" in set(template_classes(w))


def test_weapon_lines_counted_from_gear_move_raw_without_header_lines() -> None:
    """The gear move stores PoB's BuildRaw: no "Physical Damage:" line, the slot says it is a weapon."""
    raw = "\n".join(["Rarity: RARE", "Doom Grip", "Vaal Axe", "Crafted: true", "Item Level: 84", "Quality: 20",
                     "Implicits: 1", "40% increased Global Accuracy Rating",
                     "{range:0.5}+30% to Global Critical Strike Multiplier", "{range:0.5}Adds 10 to 20 Fire Damage",
                     "{crafted}+10% increased Attack Speed"])
    assert "weapon-lines:3" in classify({"item": {"slot": "Weapon 1", "raw": raw}})
    assert not any(c.startswith("weapon-lines") for c in classify({"item": {"slot": "Helmet", "raw": raw}}))
    shield = raw.replace("Vaal Axe", "Colossus Tower Shield")
    assert not any(c.startswith("weapon-lines") for c in classify({"item": {"slot": "Weapon 2", "raw": shield}}))


def test_weapon_lines_count_affixes_not_text_lines() -> None:
    """#429 u3: a hybrid 2-line mod, one more mod and a 2-line bench craft are three affixes (the stormbrand raw: 5 text lines)."""
    raw = "\n".join(["Rarity: RARE", "Crafted Item", "Opal Sceptre", "Crafted: true",
                     "Prefix: {range:0.5}HybridPrefix1", "Prefix: None", "Prefix: None",
                     "Suffix: {range:0.5}IncreasedCastSpeed5", "Suffix: None", "Suffix: None",
                     "Item Level: 76", "Quality: 20", "Implicits: 1", "40% increased Elemental Damage",
                     "{tags:life}{prefix}+30 to maximum Life", "{prefix}+20 to maximum Mana",
                     "{tags:caster,speed}{suffix}23% increased Cast Speed",
                     "{crafted}Adds 8 to 11 Physical Damage", "{crafted}35% chance to cause Bleeding on Hit"])
    assert "weapon-lines:3" in classify({"item": {"slot": "Weapon 1", "raw": raw}})
    no_header = "\n".join(["Rarity: RARE", "X", "Opal Sceptre", "Implicits: 0", "+1 a", "{crafted}+2 b", "{crafted}+3 c"])
    assert "weapon-lines:2" in classify({"item": {"slot": "Weapon 1", "raw": no_header}})
