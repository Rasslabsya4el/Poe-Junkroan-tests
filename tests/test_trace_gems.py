"""The gem path's counters (#498): generated / evaluated per option class under the `picks` move. PoB-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_gems import gem_classes
from junkroan.search.generator import SkeletonGenerator, _is_transfigured
from junkroan.search.hypothesis import active_gems
from junkroan.search.skeleton import Skeleton


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


class _Pob:
    def __init__(self) -> None:
        self.link: list[str] = []
        self.calls = 0

    def set_skills(self, *, main_link, **_kw) -> None:
        self.link = list(main_link)

    def stats(self, keys) -> dict:
        self.calls += 1
        dps = 150.0 if len(self.link) > 1 and self.link[1] == "Sup13" else 100.0
        return {key: 0.0 for key in keys} | {"CombinedDPS": dps, "Life": 100.0, "TotalEHP": 1.0, "EnemyCurseLimit": 1.0}  # a real build always has a curse slot (#784)


def _gen(pob: _Pob) -> SkeletonGenerator:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.pob = pob
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=1, movement_skill_required=False)
    gen.objective = Objective(maximize="CombinedDPS")
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    return gen


def _by_kind(considered: dict, label: str, prefix: str) -> tuple[int, int]:
    rows = {c: v for c, v in considered[label].items() if c.startswith(prefix)}
    return sum(v["generated"] for v in rows.values()), sum(v["evaluated"] for v in rows.values())


def test_gem_classes_plain_and_transfigured() -> None:
    plain = gem_classes("Fireball", role="gem", link_size=1)
    assert plain == {"gem:Fireball", "links:1"}
    name = next(r["name"] for r in active_gems().values() if _is_transfigured(r))  # the repo's own data
    assert gem_classes(name, role="gem") == {f"gem:{name}", "transfigured"}
    assert gem_classes("Not A Gem", role="support", link_size=3) == {"support:Not A Gem", "links:3"}


def test_rejudge_counts_the_whole_legal_list_and_only_the_measured_shortlist() -> None:
    # 14 legal supports; Sup13 wins slot 1 in sweep 1, so a second sweep runs on the 12-name shortlists:
    # generated 4 slot-sweeps x 14 = 56; evaluated 14 + 13 (Sup13 is in the link) + 11 + 12 = 50
    legal = [f"Sup{i:02d}" for i in range(14)]
    pob = _Pob()
    gen = _gen(pob)
    gen.legal_supports = lambda _sk: legal
    gen._reconfigure = lambda *_a, **_k: None
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=["Spark", "A", "B"])
    pob.link = list(skeleton.main_link)
    gen.rejudge_picks(skeleton, max_sweeps=3)
    TRACE.flush("picks")
    generated, evaluated = _by_kind(TRACE.considered(), "picks", "support:")
    assert (generated, evaluated) == (56, 50)
    assert _by_kind(TRACE.considered(), "picks", "links:3") == (56, 50)


def test_pick_utilities_counts_pool_and_measured() -> None:
    pob = _Pob()
    gen = _gen(pob)
    gen.utility_candidates = lambda _sk: {"aura": ["Grace", "Haste"], "curse": ["Frostbite"]}
    gen._set_main_link = lambda *_a, **_k: None
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    skeleton = Skeleton(class_name="Shadow", ascendancy="Assassin", main_link=["Spark"])
    gen.pick_utilities(skeleton, max_groups=1)
    TRACE.flush("picks")
    assert _by_kind(TRACE.considered(), "picks", "gem:") == (3, 3)
