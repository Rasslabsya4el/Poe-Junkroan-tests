"""#617: `tree rebuilt on gear` grows the new tree on the loop's tree view (with sustain), not the construction view.

No PoB. summon_raging_spirits s4 "sum": construction viol 0.000, delivered viol 0.836, all of it the mana sustain floor.
`BuildPipeline.run` is too big to stub whole, so the call site is pinned on its source and the optimizer it passes is
built by the real `_tree_optimizers` over a recording `Judging`.
"""

from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

import pytest

from junkroan.optimizer import pipeline as pipeline_mod
from junkroan.optimizer.judging import VIEWS
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline

SUSTAIN = ("ManaRegenRecovery+ManaLeechGainRate+ManaRecoup", "ManaPerSecondCost", 1.0)
FULL = Objective(maximize="CombinedDPS", floors={"Life": 1000.0, "EffectiveMovementSpeedMod": 1.0}, relations=(SUSTAIN,))

# the "sum" tree: sustain 10 + 5 + 0 against a cost of 100
SUM_STATS = {"CombinedDPS": 901000.0, "Life": 1000.0, "EffectiveMovementSpeedMod": 1.0,
             "ManaRegenRecovery": 10.0, "ManaLeechGainRate": 5.0, "ManaRecoup": 0.0, "ManaPerSecondCost": 100.0}


def test_rebuild_call_receives_the_tree_view_optimizer(monkeypatch):
    cuts: dict[str, Objective] = {}

    class FakeTree:
        def __init__(self, pob, objective, **_kw):
            self.objective = objective

    monkeypatch.setattr(pipeline_mod, "TreeOptimizer", FakeTree)
    judging = SimpleNamespace(cut=lambda name: cuts.setdefault(name, VIEWS[name].cut(FULL)), attach=lambda *_a: None)
    rig = SimpleNamespace(judging=judging, rails=SimpleNamespace(attribute_plus30_nodes_max=30), log=lambda _m: None)
    tree, tree_full = BuildPipeline._tree_optimizers(rig, None, 1, 1, None, False)
    assert tree.objective.relations == () and tree_full.objective.relations == (SUSTAIN,)

    src = inspect.getsource(BuildPipeline.run)
    assert re.search(r"self\._rebuild_tree\(skeleton, tree_full, points\)", src)
    assert not re.search(r"self\._rebuild_tree\(skeleton, tree,", src)


def test_tree_view_reports_the_sustain_floor_the_construction_view_drops():
    tree_view = VIEWS["tree"].cut(FULL)
    construction = VIEWS["tree_construction"].cut(FULL)

    viol = tree_view.violations(SUM_STATS)
    assert sum(viol.values()) > 0
    assert len(viol) == 1 and "ManaRegenRecovery+ManaLeechGainRate+ManaRecoup" in next(iter(viol))
    assert next(iter(viol.values())) == pytest.approx(0.85)
    assert construction.violations(SUM_STATS) == {}
    assert construction.score(SUM_STATS).violation == 0.0 and tree_view.score(SUM_STATS).violation > 0
