"""#802 unit 2a: the Vaal half is never counted (rail + default + trace class `vaal`). PoB-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityMetrics
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_gems import count_evaluated, count_generated, gem_classes
from junkroan.pob.headless_runtime_adapter import (
    PinnedPoBHeadlessRuntimeAdapter,
    PoBHeadlessCallbackRuntimeAdapter,
    PoBHeadlessHostContractError,
    vaal_gem_flags,
)
from junkroan.search.generator import SkeletonGenerator
from junkroan.search.hypothesis import active_gems
from junkroan.search.skeleton import Skeleton

VAAL = next(r["name"] for r in active_gems().values() if r.get("is_vaal_gem") and r["name"] == "Vaal Grace")


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _payload(*gems: dict) -> dict:
    return {"skill_sets": [{"skill_set_id": "s", "socket_groups": [{"label": "g", "gems": list(gems)}]}]}


def _gems(payload: dict) -> list[dict]:
    return payload["skill_sets"][0]["socket_groups"][0]["gems"]


def test_vaal_gem_without_flags_gets_false_true_and_plain_gem_is_untouched() -> None:
    out = _gems(vaal_gem_flags(_payload({"gem_name": VAAL}, {"gem_name": "Grace"}, {"gem_name": "Fireball"})))
    assert (out[0]["enable_global_1"], out[0]["enable_global_2"]) == (False, True)
    assert "enable_global_1" not in out[1] and "enable_global_2" not in out[2]


def test_vaal_gem_with_the_vaal_half_on_or_plain_half_off_is_refused() -> None:
    for bad in ({"enable_global_1": True}, {"enable_global_2": False}, {"enable_global_1": True, "enable_global_2": True}):
        with pytest.raises(PoBHeadlessHostContractError):
            vaal_gem_flags(_payload({"gem_name": VAAL, **bad}))
    ok = _gems(vaal_gem_flags(_payload({"gem_name": VAAL, "enable_global_1": False, "enable_global_2": True})))
    assert (ok[0]["enable_global_1"], ok[0]["enable_global_2"]) == (False, True)


def test_both_adapters_apply_the_rule_before_pob() -> None:
    seen: list[dict] = []
    pinned = object.__new__(PinnedPoBHeadlessRuntimeAdapter)
    pinned._call_worker = lambda _h, request: seen.append(request["skill_payload"])
    pinned.apply_skill_state(None, _payload({"gem_name": VAAL}))
    callback = PoBHeadlessCallbackRuntimeAdapter(SimpleNamespace(apply_skill_state=lambda _h, p: seen.append(p)))
    callback.apply_skill_state(None, _payload({"gem_name": VAAL}))
    assert [(_gems(p)[0]["enable_global_1"], _gems(p)[0]["enable_global_2"]) for p in seen] == [(False, True)] * 2
    for adapter in (pinned, callback):
        with pytest.raises(PoBHeadlessHostContractError):
            adapter.apply_skill_state(None, _payload({"gem_name": VAAL, "enable_global_1": True}))
    assert len(seen) == 2  # the refused calls reached nothing


def test_trace_class_vaal() -> None:
    assert gem_classes(VAAL, role="gem") == {f"gem:{VAAL}", "vaal"}
    assert gem_classes("Fireball", role="gem") == {"gem:Fireball"}
    count_generated(["Fireball"], role="gem")
    count_evaluated("Fireball", role="gem")
    count_generated([VAAL], role="gem")
    TRACE.flush("picks")
    row = TRACE.considered()["picks"]["vaal"]
    assert row["generated"] > 0 and row["evaluated"] == 0  # evaluated(vaal) = 0: nothing measured it


def test_utility_pool_offers_no_vaal_gem_row7() -> None:
    gen = SkeletonGenerator.__new__(SkeletonGenerator)
    gen.rails = SimpleNamespace(gems=SimpleNamespace(level=18, quality=0, main_quality=0), utility_max_groups=1, movement_skill_required=False)
    gen.objective = Objective(maximize="CombinedDPS")
    gen.log = lambda _m: None
    gen.picks = []
    gen.castability_context = None
    gen.castability_metrics = CastabilityMetrics()
    skeleton = Skeleton(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball", "Added Fire Damage"])
    pools = gen.utility_candidates(skeleton)
    names = [n for family in pools.values() for n in family]
    assert names, "the pool must not be empty or the pin proves nothing"
    assert "Grace" in pools["aura"]
    count_generated(names, role="gem")
    TRACE.flush("picks")
    rows = TRACE.considered()["picks"]
    assert "vaal" not in rows  # generated(vaal) = 0
    assert not [n for n in names if (active_gems().get(n.lower()) or {}).get("is_vaal_gem") or n.startswith("Vaal ")]
