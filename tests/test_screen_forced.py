"""#510 unit 10: the weapon-type screen keeps a forced Weapon 1 affix. No PoB: a fake session rolls
the forced line on Wand bases only, and the real `_ceiling` / `GearFiller` / trace counter run on it."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.gear_filler import GearFiller
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from junkroan.search.forced import forced_of
from junkroan.search.generator import ONE_HAND_TYPES, TWO_HAND_TYPES, SkeletonGenerator
from junkroan.search.hypothesis import item_bases
from junkroan.search.skeleton import Skeleton

LINE = "+1 to Level of all Fire Spell Skill Gems"
FORCED_MOD = {"mod_id": "FireLvl", "group": "g_lvl", "level": 1, "type": "Suffix", "lines": ["+(1-1) to Level of all Fire Spell Skill Gems"]}
DMG_HI = {"mod_id": "SpellDmgHi", "group": "g_dmg", "level": 1, "type": "Prefix", "lines": ["(30-40)% increased Spell Damage"]}
DMG_MOD = {"mod_id": "SpellDmg", "group": "g_dmg", "level": 1, "type": "Prefix", "lines": ["(10-20)% increased Spell Damage"]}
TEXT = {"SpellDmgHi": "{range:0.5}35% increased Spell Damage", "FireLvl": "{tags:caster}+1 to Level of all Fire Spell Skill Gems", "SpellDmg": "{range:0.5}15% increased Spell Damage"}


class FakePob:
    """Wand bases roll both mods, every other base only the damage mod; Dmg = 100 + 10 per mod line."""

    def __init__(self) -> None:
        self.type_of = {rec["name"]: rec["type"] for rec in item_bases().values()}
        self.worn: dict[str, str | None] = {}
        self.trials: list[tuple[str, str]] = []  # (slot, raw) of every trial sent
        self.crafted_bases: list[str] = []

    def equip(self, items: dict) -> None:
        self.worn.update(items)

    def list_item_mods(self, base: str, **_kw) -> dict:
        return {"mods": ([FORCED_MOD] if self.type_of.get(base) == "Wand" else []) + [DMG_HI, DMG_MOD]}

    def craft_rare(self, base: str, prefixes, suffixes, **_kw) -> dict:
        self.crafted_bases.append(base)
        lines = [TEXT[m["mod_id"]] for m in [*prefixes, *suffixes]]
        return {"raw": f"Rarity: Rare\nX\n{base}\n" + "\n".join(lines) + "\n", "problems": [], "unsupported_lines": []}

    @staticmethod
    def _dmg(raw: str | None) -> float:
        return 100.0 + 10.0 * (len(str(raw).splitlines()) - 3) if raw else 0.0

    def stats(self, _keys) -> dict:
        return {"Dmg": self._dmg(self.worn.get("Weapon 1"))}

    def trial_stats(self, trials, _keys, **_kw) -> list[dict]:
        for t in trials:
            self.trials.append((t["item"]["slot"], t["item"]["raw"]))
            TRACE.count_trial(t)  # what the real session does at the PoB boundary
        return [{"ok": True, "stats": {"Dmg": self._dmg(t["item"]["raw"])}} for t in trials]


def _gen(pob: FakePob) -> SkeletonGenerator:
    gen = object.__new__(SkeletonGenerator)
    gen.rails = SimpleNamespace(gear=SimpleNamespace(item_level=84, quality=20, max_explicit_mods=6, max_prefixes=3, max_suffixes=3, wishlist=SimpleNamespace(base_level_max=84)))
    gen.pob = pob
    gen.log = lambda *_a, **_k: None
    gen.objective = Objective(maximize="Dmg")
    return gen


def _skeleton(**kw) -> Skeleton:
    return Skeleton(class_name="Witch", ascendancy="Elementalist", **kw)


def _w1(pob: FakePob) -> list[str]:
    return [raw for slot, raw in pob.trials if slot == "Weapon 1"]


def _missing(moves) -> dict[str, dict[str, int]]:
    return {c: v for m in moves.values() for c, v in m.items() if c.startswith("forced")}


def test_screen_before_the_fix_shape_scores_items_without_the_forced_line() -> None:
    """Step 1: a ceiling without `forced` (what the screen always did) is counted as forced-missing."""

    sk = _skeleton(forced_affixes={"Weapon 1": [LINE]})
    pob = FakePob()
    TRACE.reset()
    TRACE.set_forced(forced_of(sk))
    _gen(pob)._ceiling("Weapon 1", next(b for b, t in pob.type_of.items() if t == "Wand"))
    got = _missing(TRACE.considered())
    TRACE.reset()
    assert got["forced-missing:affix:Weapon 1"]["evaluated"] > 0


def test_screen_with_a_forced_affix_never_evaluates_an_item_without_it() -> None:
    sk = _skeleton(forced_affixes={"Weapon 1": [LINE]})
    pob = FakePob()
    TRACE.reset()
    TRACE.set_forced(forced_of(sk))
    chosen = _gen(pob)._screen_weapons(sk)
    got = _missing(TRACE.considered())
    TRACE.reset()
    assert got.get("forced:kept", {}).get("evaluated", 0) > 0
    assert not [c for c in got if c.startswith("forced-missing")], got
    assert _w1(pob) and all("Fire Spell Skill Gems" in raw for raw in _w1(pob))
    assert pob.type_of[chosen["Weapon 1"]] == "Wand"
    assert "Fire Spell Skill Gems" in pob.worn["Weapon 1"]
    # only Wand bases were crafted for Weapon 1: other types cannot roll the line and are not screened
    w1_bases = {b for b in pob.crafted_bases if pob.type_of[b] in ONE_HAND_TYPES + TWO_HAND_TYPES}
    assert w1_bases and {pob.type_of[b] for b in w1_bases} == {"Wand"}


def test_screen_without_a_forced_affix_screens_every_type_as_before() -> None:
    pob = FakePob()
    _gen(pob)._screen_weapons(_skeleton())
    types = {pob.type_of[b] for b in pob.crafted_bases if pob.type_of[b] in ONE_HAND_TYPES + TWO_HAND_TYPES}
    assert types == set(ONE_HAND_TYPES + TWO_HAND_TYPES) & {t for t in types} and len(types) > 3


def test_fill_slot_without_forced_is_the_old_call() -> None:
    pob = FakePob()
    wand = next(b for b, t in pob.type_of.items() if t == "Wand")
    rails = SimpleNamespace(gear=SimpleNamespace(item_level=84, quality=20, max_explicit_mods=6, max_prefixes=3, max_suffixes=3, wishlist=SimpleNamespace(base_level_max=84)))
    res = GearFiller(pob, Objective(maximize="Dmg"), rails, log=lambda _m: None).fill_slot("Weapon 1", wand)
    assert not any(s.startswith("forced") for s in res.steps)


def test_ceiling_of_a_base_that_cannot_roll_the_line_is_none() -> None:
    pob = FakePob()
    sword = next(b for b, t in pob.type_of.items() if t == "One Handed Sword")
    assert _gen(pob)._ceiling("Weapon 1", sword, forced=[LINE]) is None
