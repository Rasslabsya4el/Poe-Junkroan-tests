"""#600: every day-1 Boots template rolls the movement line as exactly `30% increased Movement Speed`."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from junkroan.optimizer import trace_600  # noqa: F401  (registers the classes)
from junkroan.optimizer.trace import classify
from junkroan.optimizer.wishlist_gear import _templates

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
_POB_CACHE = Path(os.environ.get("JUNKROAN_TEST_POB_CACHE") or PROJECT_ROOT / "var" / "cache" / "pob")
# the boots ladder lives in the pinned tag's Data/ModExplicit.lua (v2.64 called it Data/ModItem.lua)
MOD_ITEM = _POB_CACHE / LOCK["tag"] / LOCK["extract_subdir"] / "Data" / "ModExplicit.lua"
if not MOD_ITEM.is_file():
    pytest.skip(f"pinned PoB {LOCK['tag']} not extracted: missing {MOD_ITEM}", allow_module_level=True)
DAY1_ILVL = 72  # WishlistRails.item_level default for every armour / jewellery slot

BOOTS = """Rarity: RARE
Gale Step
Sorcerer Boots
Prefix: {range:0.5}IncreasedLife8
Prefix: {range:0.5}MovementVelocity5
Suffix: {range:0.5}FireResist4
Suffix: None
Suffix: None
Implicits: 0
+85 to maximum Life
MOVE
+38% to Fire Resistance"""


def _boots(movement_line: str) -> str:
    return BOOTS.replace("MOVE", movement_line)


def _classes(raw: str, slot: str = "Boots") -> set[str]:
    return classify({"item": {"slot": slot, "raw": raw}})


def _boots_ladder() -> list[tuple[int, str]]:
    """(level, text) of every MovementVelocity prefix PoB can roll on boots, best (highest level) first."""

    rows = []
    for line in MOD_ITEM.read_text(encoding="utf-8").splitlines():
        if '["MovementVelocity' not in line or 'group = "MovementVelocity"' not in line or 'type = "Prefix"' not in line:
            continue
        weights = re.search(r'weightKey = \{([^}]*)\}, weightVal = \{([^}]*)\}', line)
        keys = [k.strip().strip('"') for k in weights.group(1).split(",") if k.strip()]
        vals = [int(v) for v in weights.group(2).split(",") if v.strip()]
        if dict(zip(keys, vals)).get("boots", 0) <= 0:
            continue
        level = int(re.search(r"level = (\d+)", line).group(1))
        rows.append((level, re.search(r'"(\d+% increased Movement Speed)"', line).group(1)))
    return sorted(rows, reverse=True)


def test_boots_template_tier_is_the_30_percent_line_legal_at_day1_ilvl() -> None:
    templates, _aliases = _templates()
    line = next(entry for entry in templates["Boots"] if entry.kind == "movement")
    ladder = _boots_ladder()
    level, text = ladder[int(line.tier) - 1]  # tier N = whole-ladder rank N, best first
    assert text == "30% increased Movement Speed"
    assert level <= DAY1_ILVL, (level, DAY1_ILVL)


def test_class_counts_boots_without_the_line() -> None:
    classes = _classes(_boots("20% increased Movement Speed"))
    assert "boots-without-30-movement" in classes
    assert "boots-with-30-movement" not in classes


def test_class_counts_boots_with_the_line() -> None:
    classes = _classes(_boots("{range:0.5}30% increased Movement Speed"))
    assert "boots-with-30-movement" in classes
    assert "boots-without-30-movement" not in classes


def test_class_ignores_unfinished_boots_and_other_slots() -> None:
    nl = "\n"
    unfinished = _boots("")
    for drop in ("Prefix: {range:0.5}MovementVelocity5", "Suffix: {range:0.5}FireResist4", "+38% to Fire Resistance"):
        unfinished = unfinished.replace(drop, "")
    unfinished = nl.join(ln for ln in unfinished.split(nl) if ln)
    assert not {"boots-with-30-movement", "boots-without-30-movement"} & _classes(unfinished)
    assert not {"boots-with-30-movement", "boots-without-30-movement"} & _classes(_boots("30% increased Movement Speed"), slot="Gloves")


def test_headroom_probe_rolls_of_a_template_boots_carry_the_pinned_movement_line() -> None:
    """#600 unit 2: the loop's headroom probes (`kick joint`) rolled random Boots with no 30% line and sent them to PoB."""

    from types import SimpleNamespace

    from junkroan.optimizer.improvement_loop import _slots_with_damage_headroom
    from junkroan.optimizer.wishlist_gear import WishlistGear

    class Gear(WishlistGear):
        def __init__(self) -> None:  # no PoB: only the surface the headroom ranking reads
            self.current_raw: dict[str, str] = {}

        def pinned_roll_choices(self, slot: str, base: str) -> list[list[str]]:
            return [["MovementVelocity5"]] if slot == "Boots" else []

    calls: list[dict] = []

    class Pob:
        def stats(self, keys):
            return {}

        def random_rares(self, base, **kw):
            calls.append({"base": base, **kw})
            return []

        def trial_stats(self, trials, keys, mode="fast"):
            return []

    class Objective:
        stat_keys = ("Life",)

        def replace(self, **_kw):
            return self

        def score(self, _stats):
            return SimpleNamespace(value=0.0)

    rails = SimpleNamespace(gear=SimpleNamespace(item_level=72, quality=20, loot_best_of_n=160))
    skeleton = SimpleNamespace(rare_bases={"Boots": "Sorcerer Boots", "Helmet": "Hubris Circlet"}, sockets={}, forced_affixes={})
    _slots_with_damage_headroom(Pob(), Objective(), rails, skeleton, Gear(), ["Boots", "Helmet"], None, 1)
    by_base = {call["base"]: call for call in calls}
    assert by_base["Sorcerer Boots"]["forced"] == [["MovementVelocity5"]]
    assert "forced" not in by_base["Hubris Circlet"]


def test_extra_resistance_trial_of_a_template_boots_carries_the_pinned_movement_line() -> None:
    """#600 unit 3: the fourth-line resistance payment was judged on [life, resistance, resistance] before the movement line
    existed, a finished-looking 3-line Boots without the 30% line sent to PoB (PoB-free, on the wishlist tests' fakes)."""

    from junkroan.optimizer.objective import Objective
    from junkroan.optimizer.wishlist_gear import WishlistGear
    from test_wishlist_gear import FakePob, _normal_armour_mods, _rails

    class Pob(FakePob):
        def __init__(self, mods) -> None:
            super().__init__(mods)
            self.shown: list[str] = []

        def trial_stats(self, trials, keys, mode="fast"):
            self.shown.extend(trial["item"]["raw"] for trial in trials if trial["item"]["slot"] == "Boots")
            return super().trial_stats(trials, keys, mode)

    pob = Pob(_normal_armour_mods())
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), _rails())
    gear._resistance_assignments["Boots"] = "fire"
    gear._extra_resistance_assignments["Boots"] = "cold"
    result = gear.fill_slot("Boots", "Fake Boots")

    finished = [raw.split("|")[1:] for raw in pob.shown if len(raw.split("|")) - 1 >= 3]
    assert finished, "the extra-resistance trial must reach PoB as a 3+-line item"
    assert all(any(mod_id.startswith("MovementVelocity") for mod_id in ids) for ids in finished), finished
    assert any(mod.group == "ColdResistance" for mod in result.affixes) and any(mod.group == "MovementVelocity" for mod in result.affixes)


# ---- #600 unit d: the move loops (line swap, two-item exchange, base re-choice) never show PoB a finished Boots without the pinned line


def _boots_gear(mods=None, worth=None):
    """A WishlistGear on a PoB-free fake whose crafted raws carry real `Prefix:`/`Suffix:` headers (the shape the guard reads)."""

    from junkroan.optimizer.objective import Objective
    from junkroan.optimizer.wishlist_gear import WishlistGear
    from test_wishlist_gear import FakePob, _normal_armour_mods, _rails

    class Pob(FakePob):
        def __init__(self) -> None:
            super().__init__(_normal_armour_mods() if mods is None else mods)
            self.trials: list[str] = []

        def craft_rare(self, base, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None):
            headers = [f"Prefix: {{range:0.5}}{row['mod_id']}" for row in prefixes] + [f"Suffix: {{range:0.5}}{row['mod_id']}" for row in suffixes]
            return {"raw": "\n".join(["Rarity: RARE", "Test Boots", base, *headers, "Implicits: 0"]), "problems": [], "unsupported_lines": []}

        def _stats(self, items, keys):
            from junkroan.search.forced import raw_header_ids

            ids = [mod_id for raw in items.values() for mod_id in raw_header_ids(raw)]
            return {key: 0.0 for key in keys} | {"CombinedDPS": 1_000.0 + sum((worth or {}).get(mod_id, 0.0) for mod_id in ids)}

        def trial_stats(self, trials, keys, mode="fast"):
            self.trials.extend(trial["item"]["raw"] for trial in trials if trial["item"]["slot"] == "Boots")
            return super().trial_stats(trials, keys, mode)

    pob = Pob()
    rails = _rails(flexible_lines=True, boots_movement_floor=True)
    gear = WishlistGear(pob, Objective(maximize="CombinedDPS"), rails)
    gear._resistance_assignments["Boots"] = "fire"
    return gear, pob


def _boots_result(gear, affixes):
    from junkroan.optimizer.wishlist_gear import WishlistSlotResult

    base, slot = "Fake Boots", "Boots"
    ilvl = gear.rails.gear.wishlist.item_level_for(slot)
    raw = gear._raw(base, ilvl, affixes, None, None)
    gear.pob.equip({slot: raw})
    result = WishlistSlotResult(slot=slot, base=base, ilvl=ilvl, raw=raw, affixes=list(affixes), mod_ids=[mod.mod_id for mod in affixes])
    gear.current_raw[slot] = raw
    gear._results_by_raw[(slot, raw)] = result
    return result


def test_line_swap_never_shows_pob_a_finished_boots_without_the_pinned_movement_line(monkeypatch) -> None:
    """The leak: a Boots that has no movement line (a 3-line [life, resistance, extra resistance]) gets every legal MovementVelocity
    tier from the flexible pool, so [life, resistance, MovementVelocity<k>] of the 7 other tiers reached PoB (finished, no `30%`)."""

    import junkroan.optimizer.wishlist_gear as wishlist_module

    gear, pob = _boots_gear(worth={"MovementVelocity5": 9_000.0, "MovementVelocity2": 50.0})
    ilvl = gear.rails.gear.wishlist.item_level_for("Boots")
    pinned = gear._pinned_movement_mod("Boots", "Fake Boots")
    result = _boots_result(gear, [
        gear._mod_at_tier("Fake Boots", ilvl, "IncreasedLife", 2),
        gear._resistance_mod("Fake Boots", ilvl, "fire", 3),
        gear._resistance_mod("Fake Boots", ilvl, "cold", 3),
    ])
    counted: list[str] = []
    monkeypatch.setattr(wishlist_module, "_count_items", lambda slot, raws: counted.extend(raws))

    stats = gear._line_swap_pass([result])

    from junkroan.search.forced import raw_header_ids

    finished = [raw for raw in pob.trials if len(raw_header_ids(raw)) >= 3]
    assert finished, "the pool must still offer the pinned movement line"
    assert all(pinned.mod_id in raw_header_ids(raw) for raw in finished), [sorted(raw_header_ids(raw)) for raw in finished]
    assert set(pob.trials) <= set(counted)  # every trial PoB saw was counted as generated first
    assert stats["kept"] == 1 and pinned.mod_id in raw_header_ids(result.raw)  # the pinned tier wins, not the better-valued tier 5


def test_pinned_movement_guard_reads_only_a_finished_boots_whose_base_can_roll_the_line() -> None:
    gear, _pob = _boots_gear()
    base, slot = "Fake Boots", "Boots"
    ilvl = gear.rails.gear.wishlist.item_level_for(slot)
    life = gear._mod_at_tier(base, ilvl, "IncreasedLife", 2)
    fire = gear._resistance_mod(base, ilvl, "fire", 3)
    cold = gear._resistance_mod(base, ilvl, "cold", 3)
    pinned = gear._pinned_movement_mod(slot, base)
    other_tier = next(mod for mod in gear._group_tiers(base, ilvl, "MovementVelocity") if mod.mod_id != pinned.mod_id)

    def raw(*mods):
        return gear._raw(base, ilvl, list(mods), None, None)

    assert gear._lacks_pinned_movement(slot, base, raw(life, fire, cold))
    assert gear._lacks_pinned_movement(slot, base, raw(life, fire, other_tier))  # another tier of the line is not the line
    assert not gear._lacks_pinned_movement(slot, base, raw(life, fire, pinned))
    assert not gear._lacks_pinned_movement(slot, base, raw(life, fire))  # still being filled
    assert not gear._lacks_pinned_movement("Helmet", base, raw(life, fire, cold))  # another slot
    gear.forced_lines = {"Boots": ["a forced line"]}  # a forced line takes the movement line's template position
    assert not gear._lacks_pinned_movement(slot, base, raw(life, fire, cold))

    no_movement, _ = _boots_gear(mods=[mod for mod in __import__("test_wishlist_gear")._normal_armour_mods() if mod["group"] != "MovementVelocity"])
    assert no_movement._pinned_movement_mod(slot, base) is None  # a base that cannot roll the line: nothing to hold, the boots is built as the template allows
    assert not no_movement._lacks_pinned_movement(slot, base, raw(life, fire, cold))
