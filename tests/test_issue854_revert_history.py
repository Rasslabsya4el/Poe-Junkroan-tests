"""#854 unit 1: a rejected attempt at the gear revert, the kick-tree revert and the joint-kick revert takes back
everything the attempt could have changed, `tree.history` and the Skeleton counts `Judging.rejudge` writes
(`refresh_minion_counts`: `gem_counts`, `disabled_main_gem_indices`, `main_instance_counts`, the extra groups'
`disabled_gem_indices` / `instance_counts`).

Each site runs the loop over the fakes of `loop_fakes` with `LoopPlan.moves` naming that one move. The fake tree
records a kept step per call, as `TreeOptimizer._keep` does (tree_optimizer.py:284); the fake `rejudge` writes the
counts as a function of the build PoB holds (the fake build is its `value`), as the real one does."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.improvement_loop import LoopPlan
from junkroan.optimizer.tree_optimizer import Step

from loop_fakes import _Loot, _Pob, _Tree, _skeleton, loop_over


def _step(kind: str) -> Step:
    return Step(node_id=1, name=kind, kind=kind, cost=1, added_node_ids=[], mastery_effect=None, before=None, after=None,
                candidates_evaluated=1, seconds=0.0)


class _HistoryTree(_Tree):
    """The fake tree, plus a step in `history` for every call that changes the tree (`_keep`: `history.extend(result.steps)`)."""

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        result = super().refine(max_rounds=max_rounds, repair_rounds=repair_rounds)
        self.history.append(_step(f"refine {max_rounds}"))
        return result

    def reoptimize(self, *, rounds: int, ruin_points: int, refine_rounds: int, seed: int):
        result = super().reoptimize(rounds=rounds, ruin_points=ruin_points, refine_rounds=refine_rounds, seed=seed)
        self.history.append(_step("reoptimize"))
        return result

    def allocate(self, points: int, allocated=None):
        result = super().allocate(points, allocated)
        self.history.append(_step("allocate"))
        return result


def _write_counts(skeleton, pob: _Pob) -> None:
    """What `Skeleton.refresh_minion_counts` writes, as a function of the build PoB holds."""

    n = int(pob.value)
    skeleton.gem_counts.update({"Fireball": n})  # updated in place, as the real one does
    skeleton.disabled_main_gem_indices = [n % 3]
    skeleton.main_instance_counts = [n]
    group = skeleton.extra_groups[0]
    group.disabled_gem_indices = [n % 5]
    group.instance_counts = [n]


def _counts(skeleton) -> tuple:
    group = skeleton.extra_groups[0]
    return (dict(skeleton.gem_counts), list(skeleton.disabled_main_gem_indices), list(skeleton.main_instance_counts),
            list(group.disabled_gem_indices), list(group.instance_counts))


def _rig(tree: _HistoryTree, loot: _Loot, pob: _Pob, bases: dict):
    sk = _skeleton(bases, main_link=("Fireball",))
    sk.gem_counts = {}
    sk.disabled_main_gem_indices = []
    sk.main_instance_counts = []
    sk.extra_groups = [SimpleNamespace(enabled=True, gems=["Raise Spectre"], disabled_gem_indices=[], instance_counts=[])]
    _write_counts(sk, pob)  # the counts of the build as it stands
    rig = loop_over(pob, tree=tree, gear=loot, skeleton=sk)
    rig.judging.rejudge = lambda skeleton, **_kwargs: _write_counts(skeleton, pob)  # every re-derivation re-reads the build PoB holds
    return rig, sk


def _plan(move: str) -> LoopPlan:
    return LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, kick_draws=(1, 1), moves=frozenset({move}))


def _gear_case():
    """A roll that breaks the Life floor, a repair-only refine that finds nothing: the move is judged and reverted."""

    pob = _Pob(1000.0)
    tree = _HistoryTree(pob, [], repairs=[])
    loot = _Loot(pob, {"Boots": [("b1", 1100.0, 3000.0)]})
    rig, sk = _rig(tree, loot, pob, {"Boots": "Two-Toned Boots"})
    tree.history.append(_step("kept before the move"))
    return rig, pob, tree, loot, sk


def _kick_tree_case():
    """One tree draw that moves the number by +0.1%, below min_gain: judged and reverted."""

    pob = _Pob(1000.0)
    tree = _HistoryTree(pob, [], reopt_values=[1001.0])
    loot = _Loot(pob, {})
    rig, sk = _rig(tree, loot, pob, {})
    tree.history.append(_step("kept before the move"))
    return rig, pob, tree, loot, sk


def _kick_joint_case():
    """One joint draw whose short refine moves the number by +0.1%, below min_gain: judged and reverted."""

    pob = _Pob(1000.0)
    tree = _HistoryTree(pob, [1001.0])
    loot = _Loot(pob, {})
    rig, sk = _rig(tree, loot, pob, {"Boots": "Two-Toned Boots"})
    tree.history.append(_step("kept before the move"))
    return rig, pob, tree, loot, sk


def _assert_reverted_and_history_back(rig, pob, tree, move: str) -> None:
    before = [s.name for s in tree.history]
    outcome = rig.run(_plan(move))
    assert outcome.counts["judged_and_reverted"] >= 1 and pob.value == 1000.0  # the attempt was judged and went back
    assert [s.name for s in tree.history] == before  # ... and its steps with it


def test_the_gear_revert_takes_the_attempts_tree_steps_back() -> None:
    rig, pob, tree, loot, sk = _gear_case()
    _assert_reverted_and_history_back(rig, pob, tree, "gear")
    assert ("refine", 0, 60) in tree.calls and loot.current_raw == {}  # the repair-only refine did run, and the roll is gone


def test_the_gear_revert_takes_the_skeleton_counts_back() -> None:
    rig, pob, tree, loot, sk = _gear_case()
    before = _counts(sk)
    outcome = rig.run(_plan("gear"))
    assert outcome.counts["judged_and_reverted"] >= 1 and pob.value == 1000.0
    assert _counts(sk) == before


def test_the_kick_tree_revert_takes_the_attempts_tree_steps_back() -> None:
    rig, pob, tree, loot, sk = _kick_tree_case()
    _assert_reverted_and_history_back(rig, pob, tree, "kick-tree")
    assert [c for c in tree.calls if c[0] == "reoptimize"]


def test_the_kick_tree_revert_takes_the_skeleton_counts_back() -> None:
    rig, pob, tree, loot, sk = _kick_tree_case()
    before = _counts(sk)
    outcome = rig.run(_plan("kick-tree"))
    assert outcome.counts["judged_and_reverted"] >= 1 and pob.value == 1000.0
    assert _counts(sk) == before


def test_the_joint_kick_revert_takes_the_attempts_tree_steps_back() -> None:
    rig, pob, tree, loot, sk = _kick_joint_case()
    _assert_reverted_and_history_back(rig, pob, tree, "kick-joint")
    assert [c for c in tree.calls if c[0] == "allocate"] and [c for c in tree.calls if c[0] == "refine"]  # the round allocated and refined


def test_the_joint_kick_revert_takes_the_skeleton_counts_back() -> None:
    rig, pob, tree, loot, sk = _kick_joint_case()
    before = _counts(sk)
    outcome = rig.run(_plan("kick-joint"))
    assert outcome.counts["judged_and_reverted"] >= 1 and pob.value == 1000.0
    assert _counts(sk) == before


# -- unit 2: the three reverts of the delivery (`BuildPipeline._finish`) -------------------------------------------------
# Driven on `_finish_pipeline`'s fake build. The floor is Life >= 4000 (`FLOORED`).


def _scored_step(kind: str) -> Step:
    """A step `_finish` can explain (`explain_and_map` reads each step's gain)."""

    step = _step(kind)
    step.before = step.after = SimpleNamespace(value=1.0)
    return step


def _delivery_rig(monkeypatch, *, life: float, repairs: list):
    """A pipeline over a fake build, a tree that records kept steps, and a Skeleton carrying counts and extra groups.
    The pipeline's `rejudge` writes the counts as a function of the build PoB holds, as the real one does."""

    from loop_fakes import _finish_pipeline, _finish_skeleton

    pob = _Pob(1000.0, life=life)
    tree = _HistoryTree(pob, [], repairs=repairs)
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()
    sk.gem_counts = {}
    sk.disabled_main_gem_indices = []
    sk.main_instance_counts = []
    sk.extra_groups = [SimpleNamespace(enabled=True, gems=["Raise Spectre"], disabled_gem_indices=[], instance_counts=[])]
    _write_counts(sk, pob)  # the counts of the build as it stands
    p.judging.rejudge = lambda skeleton, **_kwargs: _write_counts(skeleton, pob)
    tree.history.append(_scored_step("kept before the move"))
    return p, pob, tree, sk, logs


def test_the_repair_after_the_final_lanes_takes_the_skeleton_counts_back(monkeypatch) -> None:
    """`_repair_after_final_lanes`: the repair-only round moves the build to 900 and its `rejudge` writes the counts of
    that build; it buys nothing, the revert loads the XML back, and the counts must go back with it."""

    p, pob, tree, sk, logs = _delivery_rig(monkeypatch, life=3000.0, repairs=[(900.0, 3000.0)])
    before, history = _counts(sk), [s.name for s in tree.history]

    p._repair_after_final_lanes(sk)

    assert [m for m in logs if m.startswith("reverted: repair after the final lanes")], "the repair was not reverted"
    assert pob.value == 1000.0 and ("refine", 0, 60) in tree.calls  # the repair-only round did run, and the build is back
    assert [s.name for s in tree.history] == history
    assert _counts(sk) == before


def test_the_final_floor_repair_takes_the_skeleton_counts_back(monkeypatch) -> None:
    """`_final_floor_repair`: the round's `rejudge` writes the counts of the build at 900; nothing is kept, the restore
    loads the XML back and does not rejudge, so the counts must go back with it."""

    from junkroan.optimizer.pipeline import BuildResult

    p, pob, tree, sk, logs = _delivery_rig(monkeypatch, life=3000.0, repairs=[(900.0, 3000.0)])
    before, history = _counts(sk), [s.name for s in tree.history]

    p._final_floor_repair(BuildResult(skeleton=sk), sk)

    assert [m for m in logs if m.startswith("final floor repair round 1") and "nothing kept" in m], "the round was not reverted"
    assert pob.value == 1000.0 and ("refine", 0, 60) in tree.calls
    assert [s.name for s in tree.history] == history
    assert _counts(sk) == before


def _fallback_case(monkeypatch):
    """The D66 fallback: the extra pass of `_finish`'s fixed-point check writes the Skeleton (`main_link`, an extra group,
    `aura_levels`, `tuned_choices`), the tree's steps, and leaves the build under the Life floor; `_finish` falls back to the
    entry snapshot."""

    from loop_fakes import _finish_pipeline, _finish_skeleton

    pob = _Pob(1000.0)
    tree = _HistoryTree(pob, [], repairs=[])
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()
    sk.main_link = ["Fireball"]
    sk.aura_levels = {"Hatred": 20}
    sk.tuned_choices = {"bloodSandStance": "BLOOD"}
    sk.extra_groups = [SimpleNamespace(enabled=True, gems=["Raise Spectre"], disabled_gem_indices=[], instance_counts=[])]
    tree.history.append(_scored_step("kept before the move"))
    held = sk.tuned_choices  # whoever holds the dict (the lanes, the judging) must see the restore

    def improve(build, result, plan):
        sk.main_link = ["Ice Nova"]  # a pick (generator.rejudge_picks)
        sk.extra_groups[0].disabled_gem_indices.append(1)  # the extra group's own fields, in place
        sk.extra_groups.append(SimpleNamespace(enabled=True, gems=["Summon Raging Spirit"], disabled_gem_indices=[], instance_counts=[]))
        sk.aura_levels["Hatred"] = 21  # the aura-levels move
        sk.tuned_choices["bloodSandStance"] = "SAND"
        tree.history.append(_scored_step("the extra pass"))
        pob.life = 3000.0  # the pass leaves the build under the floor: the fallback fires
        return SimpleNamespace(kept=[], stopped="", note="stub extra pass")

    p.improve = improve
    return p, pob, tree, sk, held, logs


def _delivery_state(sk, tree) -> tuple:
    return (list(sk.main_link), [(g.enabled, list(g.gems), list(g.disabled_gem_indices), list(g.instance_counts)) for g in sk.extra_groups],
            dict(sk.aura_levels), dict(sk.tuned_choices), [s.name for s in tree.history])


def _run_fallback(p, sk, tree):
    from junkroan.optimizer.pipeline import BuildResult

    result = BuildResult(skeleton=sk)
    p._finish(result, sk, 0.0, fixed_point=dict(loot=None, tree=tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=600.0))
    return result


def test_the_d66_fallback_takes_the_extra_passs_skeleton_and_tree_steps_back(monkeypatch) -> None:
    p, pob, tree, sk, held, logs = _fallback_case(monkeypatch)
    before = _delivery_state(sk, tree)

    _run_fallback(p, sk, tree)

    assert [m for m in logs if m.startswith("final tuning reverted:")], "the fallback did not fire"
    assert pob.life == 5000.0  # the entry build is loaded
    assert _delivery_state(sk, tree) == before


def test_the_d66_fallback_puts_tuned_choices_back_in_the_same_dict(monkeypatch) -> None:
    p, pob, tree, sk, held, logs = _fallback_case(monkeypatch)

    _run_fallback(p, sk, tree)

    assert [m for m in logs if m.startswith("final tuning reverted:")], "the fallback did not fire"
    assert sk.tuned_choices is held and held == {"bloodSandStance": "BLOOD"}
