"""#427 witness: the transfigured variant is the best-scored movement candidate and the picker keeps it. PoB-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.skeleton import Skeleton

BASE = "Frostblink"
BEST = "Frostblink of Wintry Blast"  # a transfigured variant stands in its base gem's movement-spell slot (#1153)


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def test_picker_keeps_the_transfigured_variant_when_it_scores_best() -> None:
    skeleton = Skeleton(class_name="Ranger", ascendancy="Deadeye", main_link=["Lightning Arrow", "Added Cold Damage"])

    class Pob:
        def stats(self, keys) -> dict:
            names = {g for grp in skeleton.extra_groups for g in grp.gems}
            dps = 200.0 if BEST in names else 150.0 if BASE in names else 100.0
            return {k: 0.0 for k in keys} | {"CombinedDPS": dps, "TotalEHP": 1.0}

    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = Pob()
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=1, movement_skill_required=True,
                              movement=Rails.load().movement)
    gen.objective = Objective(maximize="CombinedDPS")
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    gen._set_main_link = lambda *_a, **_k: None
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    gen._weapon1_type = lambda: "Staff"
    gen._weapon2_is_shield = lambda: False
    gen._skill_attack_time = lambda _name: 1.5  # a slow Staff build skips the skill slot: the spell slot is the only group
    gen._linked_slot = lambda _skeleton, _n: None
    movement = gen.utility_candidates(skeleton)["movement"]
    assert BASE in movement and BEST in movement
    added = gen.pick_utilities(skeleton, max_groups=1)
    assert [g.gems for g in added] == [[BEST]]
    TRACE.flush("picks")
    row = TRACE.considered()["picks"][f"gem:{BEST}"]
    assert row["generated"] > 0 and row["evaluated"] > 0
    assert "transfigured" in TRACE.considered()["picks"]
