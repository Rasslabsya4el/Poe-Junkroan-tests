"""The base screen's order: the weapon before the armour and jewellery slots (no PoB).

Until 2026-09-18 `SkeletonGenerator.screen_bases` screened the eight armour and jewellery
slots first, with nothing in the main hand: an attack build deals no damage at all then, so
every candidate base scored the same 0 CombinedDPS under the same violation and only the
floors could tell one from another -- the same defect `RARE_SLOT_ORDER` fixed for the fillers.

The fake PoB below is exactly that build (its damage is 0 while "Weapon 1" is empty) and
records what every screen was judged on, so the order and the numbers behind it are both
readable without the runtime.
"""

from __future__ import annotations

import re

from junkroan.optimizer.loot_gear import ordered_slots
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.search.generator import ARMOUR_SLOT_TYPES, SkeletonGenerator
from junkroan.search.skeleton import Skeleton

ARMOUR_SLOTS = tuple(ARMOUR_SLOT_TYPES)
WEAPON_SLOTS = ("Weapon 1", "Weapon 2")
_AFFIXES = re.compile(r"#d(\d+)l(\d+)$")


class _Pob:
    """Answers only what the base screen asks. A rare is its base plus "#d<damage>l<life>";
    the build's damage is 0 whenever "Weapon 1" is empty, so a slot screened before the
    weapon is judged on no damage at all."""

    def __init__(self) -> None:
        self.equipped: dict[str, str | None] = {}
        self.judged: list[tuple[str, float]] = []  # (slot, CombinedDPS) of every item trial, in order
        self.rolled: list[str] = []  # the bases random_rares was asked for

    # -- the build -----------------------------------------------------------

    def _stats(self, equipped) -> dict[str, float]:
        damage = life = 0
        for raw in equipped.values():
            m = _AFFIXES.search(raw or "")
            if m:
                damage += int(m.group(1))
                life += int(m.group(2))
        dps = 0.0 if not equipped.get("Weapon 1") else 1000.0 * (1 + damage)
        return {"CombinedDPS": dps, "Life": 1000.0 + 100.0 * life}

    def stats(self, keys) -> dict[str, float]:
        return {k: v for k, v in self._stats(self.equipped).items() if k in keys}

    def equip(self, mapping) -> None:
        self.equipped.update(mapping)

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        out = []
        for trial in trials:
            item = trial["item"]
            stats = self._stats({**self.equipped, item["slot"]: item["raw"]})
            self.judged.append((item["slot"], stats["CombinedDPS"]))
            out.append({"ok": True, "stats": {k: v for k, v in stats.items() if k in keys}})
        return out

    # -- loot and crafting ----------------------------------------------------

    def random_rares(self, base, *, n, ilvl=None, quality=None, seed=None) -> list[dict]:
        self.rolled.append(base)
        return [{"raw": f"{base}#d{i % 2}l{i % 3}"} for i in range(n)]

    def list_item_mods(self, base, ilvl=None) -> dict:
        return {"mods": [
            {"mod_id": "dmg1", "group": "Damage", "type": "Prefix", "level": 1, "lines": ["+1 damage"]},
            {"mod_id": "life1", "group": "Life", "type": "Suffix", "level": 1, "lines": ["+1 life"]},
        ]}

    def craft_rare(self, base, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None) -> dict:
        return {"raw": f"{base}#d{len(prefixes)}l{len(suffixes)}", "problems": [], "unsupported_lines": []}


def _generator(pob: _Pob, gear_mode: str) -> SkeletonGenerator:
    objective = Objective(maximize="CombinedDPS", floors={"Life": 2000.0})
    return SkeletonGenerator(pob, Rails.load(), objective=objective, log=lambda _m: None, gear_mode=gear_mode)


def _skeleton() -> Skeleton:
    return Skeleton(class_name="Ranger", ascendancy="Deadeye", level=77, main_link=["Lightning Arrow"], weapon_types=["Bow"])


def test_the_weapon_is_screened_before_every_armour_and_jewellery_slot() -> None:
    pob = _Pob()
    sk = _skeleton()
    chosen = _generator(pob, "loot").screen_bases(sk, n=3)

    weapons = [i for i, (slot, _dps) in enumerate(pob.judged) if slot in WEAPON_SLOTS]
    armour = [i for i, (slot, _dps) in enumerate(pob.judged) if slot in ARMOUR_SLOTS]
    assert weapons and armour
    assert max(weapons) < min(armour)  # the whole weapon screen, shield and quiver included, first
    assert set(chosen) == {"Weapon 1", "Weapon 2", *ARMOUR_SLOTS} == set(sk.rare_bases)


def test_the_armour_screen_sees_a_real_damage_number_and_the_fillers_slot_order() -> None:
    pob = _Pob()
    _generator(pob, "loot").screen_bases(_skeleton(), n=3)

    armour_dps = [dps for slot, dps in pob.judged if slot in ARMOUR_SLOTS]
    assert armour_dps and all(dps > 0 for dps in armour_dps)  # a weapon was in hand for every one of them
    seen = list(dict.fromkeys(slot for slot, _dps in pob.judged if slot in ARMOUR_SLOTS))
    assert seen == ordered_slots(ARMOUR_SLOTS)  # one definition of the order, shared with the fillers


def test_in_wishlist_mode_only_the_weapon_screen_runs() -> None:
    """D73: the armour and jewellery bases are the filler's own choice, so the screen only
    names their class -- but which weapon the build fights with is still screened, first."""

    pob = _Pob()
    sk = _skeleton()
    chosen = _generator(pob, "wishlist").screen_bases(sk, n=3)

    assert chosen["Weapon 1"] and set(ARMOUR_SLOTS) <= set(chosen)
    assert pob.rolled == []  # no loot rolled for an armour base
    assert {slot for slot, _dps in pob.judged} <= set(WEAPON_SLOTS)
