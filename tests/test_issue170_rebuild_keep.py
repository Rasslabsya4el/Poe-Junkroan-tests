"""#170: `tree rebuilt on gear` keeps or reverts the rebuilt tree on the objective the build is delivered on.

Fakes only, no PoB. The tree is grown on the construction objective (no EffectiveMovementSpeedMod floor,
no per-second sustain relation); the keep / revert and the sum-or-cover pick read `self.objective`, the one
`BuildPipeline._record` scores with, so the note and the record of one state are one number.

The violations are those of poison_spark s5 of `20260927-0322-ziz-tpl-main3-s4`: the record read 1.088 before
and 1.174 after, while the construction score improved and the old decision kept the tree.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline

# Life is a floor the construction objective keeps; EffectiveMovementSpeedMod and the PerSecond relation are the
# parts it drops
FULL = Objective(
    maximize="CombinedDPS",
    floors={"Life": 1000.0, "EffectiveMovementSpeedMod": 1.0},
    relations=(("LifeRegen", "LifeDegenPerSecond", 1.0),),
)
CONSTRUCTION = FULL.without("EffectiveMovementSpeedMod").without_sustain()

BEFORE = {"CombinedDPS": 46378.0, "Life": 912.0, "EffectiveMovementSpeedMod": 0.0, "LifeRegen": 100.0, "LifeDegenPerSecond": 100.0}  # delivered 1.088, construction 0.088
# construction 0.000 at 18,528 beats construction 0.088 at 46,378; delivered 0.000 + 0.100 + 1.074 = 1.174
WORSE_DELIVERED = {"CombinedDPS": 18528.0, "Life": 1000.0, "EffectiveMovementSpeedMod": 0.9, "LifeRegen": -7.4, "LifeDegenPerSecond": 100.0}
BETTER_DELIVERED = {"CombinedDPS": 40000.0, "Life": 1000.0, "EffectiveMovementSpeedMod": 0.5, "LifeRegen": 100.0, "LifeDegenPerSecond": 100.0}  # delivered 0.500


def _rig(states: dict[str, dict]):
    """A BuildPipeline stand-in whose PoB is a state name: `before`, then the state the regrow of `mode` lands on."""

    pob = SimpleNamespace(current="before")
    pob.export_xml = lambda: pob.current
    pob.load_xml = lambda xml: setattr(pob, "current", xml)
    pob.set_tree = lambda **_kw: None
    pob.add_nodes = lambda _nodes: None
    pob.stats = lambda keys: {k: states[pob.current][k] for k in keys if k in states[pob.current]}

    tree = SimpleNamespace(history=[], repair_estimate_mode="sum", objective=CONSTRUCTION)
    tree.allocate = lambda _points: setattr(pob, "current", tree.repair_estimate_mode)
    tree.refine = lambda max_rounds: None
    tree.current_score = lambda: (lambda stats: (CONSTRUCTION.score(stats), stats))(pob.stats(CONSTRUCTION.stat_keys))

    rig = SimpleNamespace(pob=pob, objective=FULL, log=lambda _m: None, judging=SimpleNamespace(rejudge=lambda _skeleton: None), _jewel_args=lambda: {})
    rig._points_used = lambda: 0
    rig._delivered_score = lambda: BuildPipeline._delivered_score(rig)
    rig._restore_fixed_tree = lambda sk, t: BuildPipeline._restore_fixed_tree(rig, sk, t)  # #510: no forced nodes here, keystones []
    skeleton = SimpleNamespace(class_name="Shadow", ascendancy="Assassin", ascendancy_nodes=[], keystones=[], scaling=None)
    return rig, pob, tree, skeleton


def _rebuild(states):
    rig, pob, tree, skeleton = _rig({"before": BEFORE, **states})
    note = BuildPipeline._rebuild_tree(rig, skeleton, tree, 100)
    return note, pob, rig


def test_construction_gain_with_a_higher_delivered_violation_is_reverted():
    states = {"sum": WORSE_DELIVERED, "cover": WORSE_DELIVERED}
    assert CONSTRUCTION.score(WORSE_DELIVERED) > CONSTRUCTION.score(BEFORE)  # the old decision's reading: keep
    assert FULL.score(BEFORE).violation == pytest.approx(1.088)
    assert FULL.score(WORSE_DELIVERED).violation == pytest.approx(1.174)

    note, pob, _ = _rebuild(states)
    assert pob.current == "before"
    assert "reverted" in note and "kept" not in note
    assert "(viol 1.088)" in note and "(viol 1.174)" in note  # the numbers the decision read, as the record writes them


def test_delivered_gain_is_kept_and_the_note_is_the_record_number():
    states = {"sum": BETTER_DELIVERED, "cover": BETTER_DELIVERED}
    note, pob, rig = _rebuild(states)
    assert pob.current in ("sum", "cover")
    assert note.startswith("46,378 (viol 1.088) -> 40,000 (viol 0.500) kept")
    assert rig._delivered_score().violation == pytest.approx(0.5)  # `_record` reads this state next


def test_sum_or_cover_is_picked_on_the_delivered_objective():
    # sum looks better on the construction objective (60,000 against 50,000, both feasible there) but misses
    # the movement floor harder; cover wins the delivered comparison
    sum_state = {"CombinedDPS": 60000.0, "Life": 1000.0, "EffectiveMovementSpeedMod": 0.2, "LifeRegen": 100.0, "LifeDegenPerSecond": 100.0}
    cover_state = {"CombinedDPS": 50000.0, "Life": 1000.0, "EffectiveMovementSpeedMod": 0.8, "LifeRegen": 100.0, "LifeDegenPerSecond": 100.0}
    assert CONSTRUCTION.score(sum_state) > CONSTRUCTION.score(cover_state)
    note, pob, _ = _rebuild({"sum": sum_state, "cover": cover_state})
    assert pob.current == "cover"
    assert "-> 50,000 (viol 0.200) kept" in note
