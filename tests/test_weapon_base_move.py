"""The improvement loop's weapon-base move, without the pinned PoB runtime."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import junkroan.optimizer.improvement_loop as improvement_loop_module
import junkroan.optimizer.item_bases as item_bases_module
from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildResult

from loop_fakes import loop_over


RAW = """Rarity: RARE
Loop Weapon
Low Base
Crafted: true
Item Level: 86
Quality: 20
Sockets: R-R-G-G
Prefix: {range:0.250}DamageMod
Suffix: {range:0.750}SpeedMod
Implicits: 0
{crafted}Adds 1 to 2 Physical Damage
"""


class _Pob:
    def __init__(self, *, actual_value: float = 200.0, actual_life: float = 5000.0) -> None:
        self.equipped = {"Weapon 1": RAW}
        self.actual_value = actual_value
        self.actual_life = actual_life
        self.crafts: list[tuple[str, tuple, tuple, int | None, int | None, str | None, tuple[str, ...]]] = []
        self.trials: list[str] = []
        self.config = {"enemyIsBoss": True}
        self._tree = {1, 2}

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": sorted(self._tree), "mastery_effect_ids": []}

    def config_inputs(self) -> dict:
        return dict(self.config)

    def equip(self, items: dict[str, str | None]) -> None:
        for slot, raw in items.items():
            if raw is None:
                self.equipped.pop(slot, None)
            else:
                self.equipped[slot] = raw

    def craft_rare(self, base, *, prefixes=(), suffixes=(), ilvl=None, quality=None, sockets=None, extra_lines=()):
        self.crafts.append((base, tuple(prefixes), tuple(suffixes), ilvl, quality, sockets, tuple(extra_lines)))
        if base == "Illegal Base":
            return {"raw": "", "problems": ["Suffix SpeedMod: cannot spawn on Illegal Base"], "unsupported_lines": []}
        return {"raw": RAW.replace("Low Base", base), "problems": [], "unsupported_lines": []}

    def trial_stats(self, trials, keys, mode="fast"):
        out = []
        for trial in trials:
            raw = trial["item"]["raw"]
            self.trials.append(raw)
            high = "High Base" in raw or "Heavy Base" in raw
            too_heavy = "Heavy Base" in raw
            stats = {
                "CombinedDPS": 300.0 if high else 100.0,
                "Life": 3000.0 if too_heavy else 5000.0,
            }
            out.append({"ok": True, "stats": {key: stats.get(key, 0.0) for key in keys}})
        return out

    def stats(self, keys):
        raw = self.equipped.get("Weapon 1", "")
        high = "High Base" in raw
        return {"CombinedDPS": self.actual_value if high else 100.0, "Life": 3000.0 if "Heavy Base" in raw else self.actual_life}


class _Loot(LootGear):
    def __init__(self, pob: _Pob) -> None:
        self.pob = pob
        self.current_raw = {"Weapon 1": RAW}
        self.rails = SimpleNamespace(gear=SimpleNamespace(item_level=86))


def _setup(monkeypatch, *, objective: Objective | None = None, pob: _Pob | None = None):
    pob = pob or _Pob()
    loot = _Loot(pob)
    skeleton = SimpleNamespace(rare_bases={"Weapon 1": "Low Base"}, uniques={})
    # the loop's wiring of the weapon-base move (`improvement_loop._weapon_base_move` with its helpers) over the fake, no pipeline
    pipeline = loop_over(pob, tree=None, gear=loot, skeleton=skeleton, objective=objective or Objective(maximize="CombinedDPS"),
                         rails=SimpleNamespace(gear=SimpleNamespace(item_level=86)))
    result = BuildResult(skeleton=skeleton)
    monkeypatch.setattr(item_bases_module, "bases_of_type", lambda _type, max_level: ["Low Base", "High Base", "Illegal Base"])  # `LootGear.other_weapon_bases` reads them here (#795)
    monkeypatch.setattr(item_bases_module, "type_of", lambda value: "One Handed Sword" if "Base" in value else "")
    monkeypatch.setattr(improvement_loop_module, "type_of", lambda value: "One Handed Sword" if "Base" in value else "")
    return pipeline, pob, loot, skeleton, result


def _state(pob, loot, skeleton):
    return {"xml": "before", "judging": None, "lanes_fresh": True}  # the loop's judging mark (none taken here)


def _restore(pob, loot, skeleton, state, **_kwargs):
    assert state["xml"] == "before"
    pob.equipped["Weapon 1"] = RAW
    loot.current_raw["Weapon 1"] = RAW
    skeleton.rare_bases["Weapon 1"] = "Low Base"


def _judge(pipeline, pob, result, loot, skeleton):
    def judge(_label, revert, _t0, **_kwargs):
        score = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys))
        current = pipeline.objective.score({"CombinedDPS": 100.0, "Life": 5000.0})
        if score > current:
            result.moves.append({"move": "weapon base", "kept": True, "before": current.value, "after": score.value})
            return True
        revert()
        result.moves.append({"move": "weapon base", "kept": False, "before": current.value, "after": current.value})
        return False
    return judge


def test_crit_heavy_fake_takes_the_high_crit_base_and_preserves_rolls(monkeypatch):
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch)
    kept, note = pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=Objective(maximize="CombinedDPS").score({"CombinedDPS": 100.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )

    assert kept and note == "Weapon 1 base Low Base -> High Base"
    assert skeleton.rare_bases["Weapon 1"] == "High Base"
    assert "High Base" in loot.current_raw["Weapon 1"]
    assert pob.crafts[0][1:] == (({"mod_id": "DamageMod", "range": 0.25},), ({"mod_id": "SpeedMod", "range": 0.75},), 86, 20, "R-R-G-G", ("{crafted}Adds 1 to 2 Physical Damage",))
    assert result.moves[-1]["move"] == "weapon base"


def test_illegal_candidates_are_skipped_and_counted_by_class(monkeypatch):
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch)
    pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=pipeline.objective.score({"CombinedDPS": 400.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )

    assert result.weapon_base_skipped == {"One Handed Sword": 1}


def test_a_requirement_violation_loses_to_a_feasible_current_item(monkeypatch):
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch, objective=Objective(maximize="CombinedDPS", floors={"Life": 4000.0}))
    monkeypatch.setattr(item_bases_module, "bases_of_type", lambda _type, max_level: ["Low Base", "Heavy Base"])
    rejected: dict[str, tuple] = {}
    kept, _note = pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=pipeline.objective.score({"CombinedDPS": 100.0, "Life": 5000.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected=rejected,
    )

    assert not kept and skeleton.rare_bases["Weapon 1"] == "Low Base"
    assert rejected


def test_judged_revert_restores_item_and_rare_base(monkeypatch):
    pob = _Pob(actual_value=50.0)
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch, pob=pob)
    pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 1", current_score=pipeline.objective.score({"CombinedDPS": 100.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )

    assert skeleton.rare_bases["Weapon 1"] == "Low Base"
    assert loot.current_raw["Weapon 1"] == RAW
    assert pob.equipped["Weapon 1"] == RAW


def test_unchanged_slot_fingerprint_skips_the_second_attempt(monkeypatch):
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch, pob=_Pob(actual_value=50.0))
    rejected: dict[str, tuple] = {}
    kwargs = dict(
        result=result, skeleton=skeleton, loot=loot, slot="Weapon 1",
        current_score=pipeline.objective.score({"CombinedDPS": 100.0}), min_gain=0.005,
        move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton),
        restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw), last_rejected=rejected,
    )
    pipeline.weapon_base_move(**kwargs)
    crafts = len(pob.crafts)
    pipeline.weapon_base_move(**kwargs)

    assert len(pob.crafts) == crafts


@pytest.mark.parametrize("base", ["Shield Base", "Quiver Base"])
def test_weapon_two_shield_and_quiver_are_swapped_and_a_unique_is_not_touched(monkeypatch, base):  # #1158: every slot with another base
    pipeline, pob, loot, skeleton, result = _setup(monkeypatch)
    skeleton.rare_bases = {"Weapon 2": base}
    loot.current_raw = {"Weapon 2": RAW.replace("Low Base", base)}
    monkeypatch.setattr(improvement_loop_module, "type_of", lambda value: "Shield" if "Shield" in value else "Quiver")
    pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 2", current_score=pipeline.objective.score({"CombinedDPS": 100.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )
    assert pob.crafts  # #1158: Shield and Quiver are swapped like a weapon
    pob.crafts.clear()

    skeleton.uniques["Weapon 2"] = "Unique"
    pipeline.weapon_base_move(
        result, skeleton, loot, "Weapon 2", current_score=pipeline.objective.score({"CombinedDPS": 100.0}),
        min_gain=0.005, move_state=_state(pob, loot, skeleton), snapshot_fresh=True, t0=0.0,
        judge=_judge(pipeline, pob, result, loot, skeleton), restore_move=lambda state, **kw: _restore(pob, loot, skeleton, state, **kw),
        last_rejected={},
    )
    assert not pob.crafts
