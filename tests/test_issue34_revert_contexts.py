"""#34 unit 4: a revert by a bare `load_xml` also puts the judging contexts back (no PoB).

A trial that re-judges (the tree's `after_apply_hook`, an explicit `rejudge`) moves the main objective,
the gear filler's objective and the trees' proof holders to those of the rejected build; the revert
must leave all of them as they were before the trial. One test per bare-revert site of `_finish`
(`_guarded_step`, the repair path's revert, the final fallback to the entry snapshot)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from junkroan.optimizer.improvement_loop import LoopPlan  # noqa: E402
from junkroan.optimizer.pipeline import BuildResult  # noqa: E402

from loop_fakes import FLOORED, _Pob, _Tree, _finish_pipeline, _finish_skeleton  # noqa: E402


def _setup(monkeypatch, lanes: dict):
    pob = _Pob(1000.0)
    tree = _Tree(pob, [], repairs=[])
    p, derived, logs = _finish_pipeline(monkeypatch, pob, tree, lanes)
    tree.proof_holders = {}
    gear = SimpleNamespace(objective=FLOORED, proof_holders={}, current_raw={}, resistance_plan_snapshot=lambda: {}, restore_resistance_plan=lambda saved: None,
                           shopping_results=lambda: [])
    p.judging.attach("gear", gear)
    state = {"n": 0}

    def drift(*_a, **_k):
        """What a `rejudge` of a rejected build does to the contexts."""
        state["n"] += 1
        objective = FLOORED.replace(floors={"Life": 4000 + state["n"]})
        p.judging.objective = objective
        gear.objective = objective
        tree.objective = objective
        tree.proof_holders = {state["n"]: {"usePowerCharges": (True, None)}}

    def contexts():
        return (p.judging.objective, gear.objective, tree.objective, copy.deepcopy(tree.proof_holders))

    return p, pob, tree, gear, logs, drift, contexts


def _run(p, **kwargs):
    sk = _finish_skeleton()
    p._finish(BuildResult(skeleton=sk), sk, 0.0, **kwargs)


def test_a_reverted_guarded_step_puts_the_contexts_back(monkeypatch) -> None:
    p, pob, _tree, _gear, logs, drift, contexts = _setup(monkeypatch, {})
    before = contexts()

    def identity(_sk, _d) -> dict:
        drift()  # the tree's after_apply_hook inside `_spend_extra_points`
        pob.value, pob.life = 9000.0, 3600.0
        return {"pantheon_major": "Lunaris"}

    p._tune_identity = identity
    _run(p)

    assert [m for m in logs if m.startswith("reverted: identity")], "the step was not reverted"
    assert contexts() == before


def test_a_reverted_repair_puts_the_contexts_back(monkeypatch) -> None:
    p, _pob, tree, _gear, _logs, drift, contexts = _setup(monkeypatch, {"Life": 3000.0})
    before = contexts()
    refine = tree.refine
    tree.refine = lambda **kw: (drift(), refine(**kw))[1]
    seen: list = []
    record = p._record

    def spy(result, label, *a, **k):
        if label.startswith("config (final lanes)"):
            seen.append(contexts())
        return record(result, label, *a, **k)

    p._record = spy
    _run(p)

    assert seen, "the stage after the repair never ran"
    assert seen[0] == before  # right after the repair revert, before the final fallback could mask it


def test_the_final_fallback_puts_the_contexts_back(monkeypatch) -> None:
    p, pob, _tree, _gear, logs, drift, contexts = _setup(monkeypatch, {})
    before = contexts()

    def fixed_point(result, _sk, **_kw):
        drift()  # the extra pass's judged moves
        pob.life = 3000.0
        return []

    p._fixed_point_check = fixed_point
    _run(p, fixed_point={"x": 1})

    assert [m for m in logs if m.startswith("final tuning reverted:")]
    assert contexts() == before


def test_a_judged_revert_of_a_kick_draw_puts_the_contexts_back() -> None:
    """`judge`'s revert: a kick draw is judged under re-judged contexts and reverted by `load_xml`
    of a fresh snapshot (no re-derivation after it), so the mark taken with the snapshot must put
    the contexts back, not only the castability."""

    from loop_fakes import _Loot, _skeleton, loop_over

    pob = _Pob(1000.0)
    tree = _Tree(pob, [1001.0], [1001.0], reopt_values=[1001.0, 1002.0, 1003.0])
    tree.proof_holders = {}
    gear = _Loot(pob, {})
    gear.proof_holders = {}
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=gear, skeleton=sk)
    p.started()

    def drift(_sk, **_kw) -> None:
        """A re-judge derives the contexts from the build PoB holds NOW (the fake build is its value)."""
        objective = FLOORED.replace(floors={"Life": 4000 + int(pob.value)})
        p.judging.objective = objective
        for view in (tree, gear):
            view.objective = objective
        tree.proof_holders = {int(pob.value): {}}

    def contexts():
        return (p.judging.objective, gear.objective, tree.objective, copy.deepcopy(tree.proof_holders))

    drift(sk)
    before = contexts()
    p.judging.rejudge = drift
    stale: list = []
    after_load = {"flag": False}
    load_xml, stats = pob.load_xml, pob.stats

    def watched_load(token):
        load_xml(token)
        after_load["flag"] = True

    def watched_stats(keys):
        if after_load["flag"]:  # the first score read after a revert is the one judged next
            after_load["flag"] = False
            if p.judging.objective.floors["Life"] != 4000 + int(pob.value):
                stale.append((pob.value, p.judging.objective.floors["Life"]))
        return stats(keys)

    pob.load_xml, pob.stats = watched_load, watched_stats
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5))

    assert pob.value == 1000.0 and len(pob.loaded) == 5, "every move was judged and reverted"
    assert not stale, f"the score after a revert was read under the contexts of the rejected build: {stale}"
    assert contexts() == before
