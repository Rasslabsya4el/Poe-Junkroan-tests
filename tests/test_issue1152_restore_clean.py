"""#1152 (brain's decision, 2026-10-17): a restriction is hard. A rejected trial's revert never puts back an item a
current restriction refuses (`gear.weapon_forbidden_lines`, `gear.bases_excluded_by_loadout`): the trial's clean item
stays even when it scores lower. One shared predicate (`loot_gear.raw_refused` / `base_refused`) and one restore
decision (`loot_gear.replaced_refused`), used by the `gear <slot>` move's revert, the joint kick's revert and
`gear_move_base` (#1154). A forced line / a forced base stays exempt.

The loop runs over the fakes of `loop_fakes`; PoB-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import junkroan.optimizer.improvement_loop as improvement_loop
from junkroan.optimizer import loot_gear
from junkroan.optimizer.improvement_loop import LoopPlan, gear_move_base
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE

from loop_fakes import _Loot, _Pob, _Tree, _TemplateLoot, _patch_generator, _skeleton, loop_over

ALL = "+1 to Level of all Spell Skill Gems"
CHAOS = "+1 to Level of all Chaos Spell Skill Gems"
HEAD = "Rarity: RARE\nRandom 134\nDemon Dagger\nItem Level: 70\nImplicits: 0\n"
DIRTY = HEAD + "{range:0.328}{tags:caster,gem}{prefix}" + ALL
CLEAN = HEAD + "{tags:caster,chaos,gem}{prefix}" + CHAOS
PRISMATIC = "Prismatic Ring"
RING_HEAD = "Rarity: RARE\nLoop Item\n{base}\nItem Level: 86\nImplicits: 0\n"
FORBIDDEN = Rails.load().gear.weapon_forbidden_lines


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


class _Template(_TemplateLoot):
    def fill_slot(self, slot, base, *, replan_resistance=False, _base_candidates=None, **kwargs):
        return super().fill_slot(slot, base, **kwargs)


def _ring(base: str) -> str:
    return RING_HEAD.format(base=base)


def _rig(monkeypatch, loot_cls, slot: str, base: str, script, incumbent: str, *, forced_base: str | None = None, forced_lines=None):
    pob = _Pob(1000.0)
    loot = loot_cls(pob, {slot: script})
    loot.rails = Rails.load()  # day 1
    loot.current_raw[slot] = incumbent
    if forced_lines:
        loot.forced_lines = {slot: forced_lines}
    skeleton = _skeleton({slot: base})
    skeleton.forced_bases = {slot: forced_base} if forced_base else {}
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=_Tree(pob, []), gear=loot, skeleton=skeleton)
    return rig, pob, loot, skeleton


def _gear_move(rig) -> None:
    rig.run(LoopPlan.replay("gear", seed=1, passes=1))


# ---- the predicate ----------------------------------------------------------------------------------------------

def test_the_predicate_names_what_it_refuses() -> None:
    loot = SimpleNamespace(rails=Rails.load(), forced_lines={})
    assert loot_gear.raw_refused(loot, "Weapon 1", DIRTY)
    assert not loot_gear.raw_refused(loot, "Weapon 1", CLEAN)
    assert not loot_gear.raw_refused(loot, "Ring 1", DIRTY)  # the rule is a weapon slot's
    assert loot_gear.raw_refused(loot, "Ring 1", _ring(PRISMATIC))
    assert not loot_gear.raw_refused(loot, "Ring 1", _ring("Amethyst Ring"))
    assert not loot_gear.raw_refused(loot, "Ring 1", _ring(PRISMATIC), forced_base=PRISMATIC)  # a base the request names stays
    loot.forced_lines = {"Weapon 1": [ALL]}
    assert not loot_gear.raw_refused(loot, "Weapon 1", DIRTY)  # a forced line is exempt (unforced_forbidden)
    assert loot_gear.base_refused(Rails.load(), PRISMATIC) and not loot_gear.base_refused(Rails.load(), PRISMATIC, forced_base=PRISMATIC)


def test_gear_move_base_asks_the_same_predicate() -> None:
    assert improvement_loop.base_refused is loot_gear.base_refused  # one check, not a second copy
    loot = SimpleNamespace(rails=Rails.load(), refills_by_value=False, other_weapon_bases=lambda base: ["Amethyst Ring"])
    skeleton = SimpleNamespace(rare_bases={"Ring 1": PRISMATIC}, forced_bases={})
    assert gear_move_base("Ring 1", skeleton=skeleton, loot=loot) == "Amethyst Ring"  # #1154: the loot filler too is handed an allowed base
    skeleton.forced_bases = {"Ring 1": PRISMATIC}
    assert gear_move_base("Ring 1", skeleton=skeleton, loot=loot) == PRISMATIC


# ---- the gear move's revert -------------------------------------------------------------------------------------

def test_a_forbidden_incumbent_is_not_restored_by_the_revert_a_lower_scoring_clean_candidate_stays(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(CLEAN, 600.0)], DIRTY)
    _gear_move(rig)
    assert loot.current_raw.get("Weapon 1") == CLEAN  # kept although 600 < 1000
    assert pob.value == 600.0
    assert not loot_gear.raw_refused(loot, "Weapon 1", loot.current_raw["Weapon 1"])


def test_with_no_clean_candidate_the_forbidden_incumbent_is_still_not_restored(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(None, 600.0)], DIRTY)
    _gear_move(rig)
    assert loot.current_raw.get("Weapon 1") != DIRTY  # the slot takes what the filler gave (nothing), never the refused item


def test_a_clean_incumbent_is_restored_by_the_revert_as_before(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(HEAD + "{prefix}" + "+60 to maximum Life", 600.0)], CLEAN)
    _gear_move(rig)
    assert loot.current_raw.get("Weapon 1") == CLEAN and pob.value == 1000.0


def test_a_forced_line_incumbent_is_restored_as_before(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(CLEAN, 600.0)], DIRTY, forced_lines=[ALL])
    _gear_move(rig)
    assert loot.current_raw.get("Weapon 1") == DIRTY and pob.value == 1000.0


def test_an_excluded_base_incumbent_is_not_restored_but_a_forced_base_is(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Template, "Ring 1", "Amethyst Ring", [(_ring("Amethyst Ring"), 600.0)], _ring(PRISMATIC))
    _gear_move(rig)
    assert loot.current_raw.get("Ring 1") == _ring("Amethyst Ring") and pob.value == 600.0

    TRACE.reset()
    rig, pob, loot, _sk = _rig(monkeypatch, _Template, "Ring 1", PRISMATIC, [(_ring("Amethyst Ring"), 600.0)], _ring(PRISMATIC), forced_base=PRISMATIC)
    _gear_move(rig)
    assert loot.current_raw.get("Ring 1") == _ring(PRISMATIC) and pob.value == 1000.0


# ---- the joint kick's revert ------------------------------------------------------------------------------------

def _kick_joint(rig) -> None:
    rig.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, kick_draws=(0, 1), moves=frozenset({"kick-joint"})))


def test_a_rejected_joint_kick_does_not_bring_a_forbidden_victim_back(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(CLEAN, 600.0)], DIRTY)
    _kick_joint(rig)
    assert loot.current_raw.get("Weapon 1") == CLEAN and pob.value == 600.0


def test_a_rejected_joint_kick_still_restores_a_clean_victim(monkeypatch) -> None:
    rig, pob, loot, _sk = _rig(monkeypatch, _Loot, "Weapon 1", "Demon Dagger", [(HEAD + "{prefix}" + "+60 to maximum Life", 600.0)], CLEAN)
    _kick_joint(rig)
    assert loot.current_raw.get("Weapon 1") == CLEAN and pob.value == 1000.0
