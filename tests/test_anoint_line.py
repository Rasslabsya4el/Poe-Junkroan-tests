"""The anoint enchant line written into an amulet raw, and the two gear generators carrying it (#432)."""

from __future__ import annotations

from junkroan.optimizer.anoint_line import anoint_line, anoint_of, apply_anoint, can_anoint, cannot_be_anointed_bases
from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.wishlist_gear import WishlistGear

ORDINARY = "Amber Amulet"
TALISMAN = sorted(cannot_be_anointed_bases())[0]


def _raw(base: str = ORDINARY, implicits: int = 1) -> str:
    imps = "\n".join(["+(20-30) to Strength"] * implicits)
    return f"Rarity: RARE\nRandom 1\n{base}\nCrafted: true\nItem Level: 84\nPrefix: {{range:0.5}}IncreasedLife2\nImplicits: {implicits}\n{imps}"


def test_apply_replace_and_remove() -> None:
    once = apply_anoint(_raw(), "Heart of Oak")
    lines = once.splitlines()
    assert once.count("Allocates") == 1 and anoint_line("Heart of Oak") in lines
    assert lines.index("Implicits: 2") + 1 == lines.index("{enchant}Allocates Heart of Oak")
    assert anoint_of(once) == "Heart of Oak"
    twice = apply_anoint(once, "Whispers of Doom")
    assert anoint_of(twice) == "Whispers of Doom" and twice.count("Allocates") == 1 and "Implicits: 2" in twice.splitlines()
    gone = apply_anoint(twice, None)
    assert anoint_of(gone) is None and gone == _raw()


def test_a_cannot_be_anointed_base_gets_none_and_an_ordinary_one_exactly_one() -> None:
    assert len(cannot_be_anointed_bases()) > 0 and not can_anoint(TALISMAN) and can_anoint(ORDINARY)
    assert anoint_of(apply_anoint(_raw(TALISMAN), "Heart of Oak")) is None
    assert apply_anoint(_raw(ORDINARY), "Heart of Oak").count("Allocates") == 1


def test_a_non_amulet_raw_is_untouched() -> None:
    raw = _raw("Two-Toned Boots")
    assert apply_anoint(raw, "Heart of Oak") == raw


class _LootPob:
    def __init__(self) -> None:
        self.equipped: list[dict] = []

    def stats(self, keys):
        return {k: 0.0 for k in keys} | {"CombinedDPS": 1000.0}

    def random_rares(self, base, n=None, ilvl=None, quality=None, sockets=None, seed=None):
        return [{"raw": _raw(base), "mod_ids": {"IncreasedLife2"}}]

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": {k: 0.0 for k in keys} | {"CombinedDPS": 1500.0}} for _ in trials]

    def list_item_mods(self, base):
        return {"mods": []}

    def list_bench_mods(self, base, ilvl=None):
        return {"mods": []}

    def equip(self, items):
        self.equipped.append(items)


def test_loot_amulet_raws_carry_the_set_anoint_and_a_changed_one_replaces_it() -> None:
    loot = LootGear(_LootPob(), Objective(maximize="CombinedDPS"), Rails.load())
    loot.anoint = "Heart of Oak"
    first = loot.fill_slot("Amulet", ORDINARY, n=1, bench=False)
    assert anoint_of(first.raw) == "Heart of Oak" and first.raw.count("Allocates") == 1
    loot.anoint = "Whispers of Doom"
    second = loot.fill_slot("Amulet", ORDINARY, n=1, bench=False)
    assert anoint_of(second.raw) == "Whispers of Doom" and second.raw.count("Allocates") == 1
    boots = loot.fill_slot("Boots", "Two-Toned Boots", n=1, bench=False)
    assert "Allocates" not in boots.raw


class _WishPob:
    def craft_rare(self, base, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None):
        return {"raw": _raw(base), "problems": [], "unsupported_lines": []}


def test_wishlist_amulet_raw_carries_the_set_anoint() -> None:
    gear = WishlistGear(_WishPob(), Objective(maximize="CombinedDPS"), Rails.load())
    gear.anoint = "Heart of Oak"
    raw = gear._raw(ORDINARY, 84, [], None, None)
    assert anoint_of(raw) == "Heart of Oak" and raw.count("Allocates") == 1
    gear.anoint = "Whispers of Doom"
    assert anoint_of(gear._raw(ORDINARY, 84, [], None, None)) == "Whispers of Doom"
    assert "Allocates" not in gear._raw("Two-Toned Boots", 84, [], None, None)
