"""#617: `tree rebuilt on gear` logs, per attempt, the construction and the delivered score with the floors missed.

Fakes only, no PoB. "sum" meets every floor on the construction objective (which has no FireMaximumHitTaken floor)
but misses it on the delivered one; the kept tree is the one `tests/test_issue170_rebuild_keep.py` style picks.
"""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline

FULL = Objective(maximize="CombinedDPS", floors={"Life": 1000.0, "FireMaximumHitTaken": 5000.0, "EffectiveMovementSpeedMod": 1.0})
CONSTRUCTION = FULL.without("FireMaximumHitTaken", "EffectiveMovementSpeedMod")

BEFORE = {"CombinedDPS": 40000.0, "Life": 1000.0, "FireMaximumHitTaken": 4500.0, "EffectiveMovementSpeedMod": 1.0}  # delivered 0.100
SUM = {"CombinedDPS": 90000.0, "Life": 1000.0, "FireMaximumHitTaken": 3950.0, "EffectiveMovementSpeedMod": 1.0}  # delivered 0.210
COVER = {"CombinedDPS": 50000.0, "Life": 1000.0, "FireMaximumHitTaken": 5000.0, "EffectiveMovementSpeedMod": 1.0}  # delivered 0.000


def test_each_attempt_logs_both_objectives_with_the_missed_floor_and_the_pick_is_unchanged():
    states = {"before": BEFORE, "sum": SUM, "cover": COVER}
    pob = SimpleNamespace(current="before")
    pob.export_xml = lambda: pob.current
    pob.load_xml = lambda xml: setattr(pob, "current", xml)
    pob.set_tree = lambda **_kw: None
    pob.stats = lambda keys: {k: states[pob.current][k] for k in keys if k in states[pob.current]}
    tree = SimpleNamespace(history=[], repair_estimate_mode="sum", objective=CONSTRUCTION)
    tree.allocate = lambda _p: setattr(pob, "current", tree.repair_estimate_mode)
    tree.refine = lambda max_rounds: None
    tree.current_score = lambda: (lambda stats: (CONSTRUCTION.score(stats), stats))(pob.stats(CONSTRUCTION.stat_keys))
    lines: list[str] = []
    rig = SimpleNamespace(pob=pob, objective=FULL, log=lines.append, judging=SimpleNamespace(rejudge=lambda _s: None), _jewel_args=lambda: {})
    rig._points_used = lambda: 0
    rig._delivered_score = lambda: BuildPipeline._delivered_score(rig)
    rig._restore_fixed_tree = lambda sk, t: BuildPipeline._restore_fixed_tree(rig, sk, t)
    skeleton = SimpleNamespace(class_name="Shadow", ascendancy="Assassin", ascendancy_nodes=[], keystones=[], scaling=None)

    note = BuildPipeline._rebuild_tree(rig, skeleton, tree, 100)

    assert lines == [
        "rebuild before: construction 40,000 (viol 0.000) | delivered 40,000 (viol 0.100: FireMaximumHitTaken 0.1)",
        "rebuild sum: construction 90,000 (viol 0.000) | delivered 90,000 (viol 0.210: FireMaximumHitTaken 0.21)",
        "rebuild cover: construction 50,000 (viol 0.000) | delivered 50,000 (viol 0.000)",
    ]
    assert pob.current == "cover"  # feasible delivered beats the higher value with a miss
    assert "-> 50,000 (viol 0.000) kept" in note and "FireMaximumHitTaken 0.21" in note
