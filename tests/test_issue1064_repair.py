"""#1064 unit 2: `BuildPipeline.repair` over a fake PoB (PoB-free).

The real TreeOptimizer runs over a small synthetic graph (the fake PoB of test_tree_plan_b: a build is worth 1000 plus
its nodes' weights), the real `Judging` over the fakes of judging_fakes, and the real pipeline code of `repair`, the
spare-point step and the weakest-leaf removal. The loop itself is replaced by one fake pass per call that runs the
real `refine` and then sets the value the case scripts (the loop's own moves are tested on the rig of loop_fakes).

What these fakes cannot show: PoB's own path allocation of a forced keystone, the real loop inside `improve`, the
real `Skeleton.apply_forced_nodes`; the calibration on real builds covers them.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace

import pytest

from junkroan.optimizer.build_result import BuildResult
from junkroan.optimizer.improvement_loop import LoopOutcome, LoopPlan
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.repair import RepairChoice, resolve_keystone_id
from junkroan.optimizer.stage_catalog import parse_log_line, step_of
from junkroan.optimizer.improvement_loop import WorkingBuild

from judging_fakes import _Reads, _judging
from loop_fakes import _Loot, _Pob as _LoopPob, _Tree, _patch_generator, _skeleton, loop_over
from test_tree_plan_b import START, _Pob, _graph, _node, _opt

A, G, K, B, K2 = 10, 11, 12, 13, 14
L1, L2, L3, L4 = 20, 21, 22, 23
R1, R2 = 30, 31
FORCED, FORBIDDEN = "Test Forced Keystone", "Test Forbidden Keystone"

WEIGHTS = {A: 5.0, G: -30.0, K: -40.0, B: 3.0, K2: 100.0, L1: 1.0, L2: 2.0, L3: 4.0, L4: 8.0, R1: 6.0, R2: 7.0}


def _tree_graph():
    nodes = {
        START: _node(START, "Witch", "class_start"),
        A: _node(A, "a", "normal"), G: _node(G, "g", "normal"), K: _node(K, FORCED, "keystone"),
        B: _node(B, "b", "normal"), K2: _node(K2, FORBIDDEN, "keystone"),
        L1: _node(L1, "l1", "normal"), L2: _node(L2, "l2", "normal"), L3: _node(L3, "l3", "normal"), L4: _node(L4, "l4", "normal"),
        R1: _node(R1, "r1", "normal"), R2: _node(R2, "r2", "normal"),
    }
    edges = [(START, A), (A, G), (G, K), (START, B), (B, K2), (START, L1), (START, L2), (START, L3), (START, L4), (START, R1), (START, R2)]
    return _graph(nodes, edges)


class _ScriptedPob(_Pob):
    """The plan-B fake plus what the repair asks of a session: remove_nodes, add_nodes, and a scripted offset on the stats."""

    def __init__(self, graph, allocated, weights) -> None:
        super().__init__(graph, allocated, weights)
        self.bonus = 0.0

    def stats(self, keys) -> dict:
        return {"CombinedDPS": self._value(self.allocated) + self.bonus}

    def remove_nodes(self, ids) -> dict:
        return self.mutate_nodes(remove=ids)

    def add_nodes(self, ids, *, mastery_effects=None) -> dict:
        return self.mutate_nodes(add=ids, mastery_effects=mastery_effects)


class _Skeleton:
    """The skeleton fields `repair` reads, with `apply_forced_nodes` over the fake session (the real one needs the real tree)."""

    class_name, ascendancy, main_link = "Witch", "Elementalist", ("Fireball",)

    def __init__(self, keystones=()) -> None:
        self.level = 40
        self.keystones = list(keystones)
        self.forbid_keystones: list[str] = []
        self.forced_nodes: list[int] = []

    def apply_forced_nodes(self, pob) -> None:
        todo = [n for n in self.forced_nodes if n not in pob.allocated]
        if todo:
            pob.add_nodes(todo)


class _CastReads(_Reads):
    def castability(self):
        return SimpleNamespace(mana_cost=None, life_cost=None)


class _Rig:
    def __init__(self, monkeypatch, *, allocated, budget, gains, keystones=(), viol=None) -> None:
        graph = _tree_graph()
        self.pob = _ScriptedPob(graph, allocated, WEIGHTS)
        self.opt = _opt(self.pob, graph)
        self.construction = _opt(self.pob, graph)  # the second tree of judging.trees()
        monkeypatch.setattr("junkroan.optimizer.pipeline.max_passive_points", lambda level, extra=0: budget)
        calls: list = []
        judging = _judging(calls)[0]
        judging.reads = _CastReads(calls)
        judging.objective = Objective(maximize="CombinedDPS")
        judging.attach("tree_construction", self.construction)
        judging.attach("tree", self.opt)
        judging.attach("gear", SimpleNamespace(objective=judging.objective, proof_holders={}, graph=None))
        judging.recut()
        self.p = p = BuildPipeline.__new__(BuildPipeline)
        p.pob, p.judging, p.log = self.pob, judging, lambda _m: None
        self.skeleton = _Skeleton(keystones)
        self.build = WorkingBuild(pob=self.pob, judging=judging, skeleton=self.skeleton, gear=None, tree=self.opt)
        self.result = BuildResult(skeleton=self.skeleton)
        self.gains = list(gains)
        self.after_pass: list[frozenset[int]] = []
        self.plans: list[LoopPlan] = []
        p._run_loop = self._fake_pass
        self._last = None
        # viol: the scripted violation after "repair pass 0", pass 1, pass 2 (None: the real, zero, violation of the fake objective)
        self.viol = list(viol) if viol is not None else None
        if self.viol is not None:
            commit = p._commit_stage
            p._commit_stage = lambda result, record: commit(result, dataclasses.replace(record, violation=self.viol[0]))

    def _fake_pass(self, build, result, plan, flags) -> LoopOutcome:
        n = plan.first_pass
        self.plans.append(plan)
        assert n <= len(self.gains), f"pass {n} ran but the script has {len(self.gains)} gains"
        self.opt.refine(max_rounds=1)  # the loop's own tree move, the real one
        before = self._last if self._last is not None else self.start
        self._last = before * (1.0 + self.gains[n - 1])
        self.pob.bonus += self._last - self.pob.stats(("CombinedDPS",))["CombinedDPS"]
        self.p._record(result, f"repair pass {n}", time.perf_counter(), "scripted")
        if self.viol is not None:
            result.stages[-1] = dataclasses.replace(result.stages[-1], violation=self.viol[n])
        self.after_pass.append(frozenset(self.pob.allocated))
        return LoopOutcome(note="", stopped="", kept=(), counts={}, passes=1)

    def run(self, choice: RepairChoice):
        self.start = self.pob.stats(("CombinedDPS",))["CombinedDPS"]
        return self.p.repair(self.build, self.result, choice)


FORCE_ALLOCATED = {START, A, B, L1, L2, L3, L4}  # 7 points: the budget is exactly spent
FORBID_ALLOCATED = {START, A, B, K2, L1, L2, L3, L4}  # 8 points, the forbidden keystone is in


def _force(monkeypatch, gains):
    return _Rig(monkeypatch, allocated=FORCE_ALLOCATED, budget=7, gains=gains)


def _forbid(monkeypatch, gains):
    return _Rig(monkeypatch, allocated=FORBID_ALLOCATED, budget=8, gains=gains, keystones=[K2])


CASES = [
    # gains of the scripted passes, passes run, verdict
    ([0.05, 0.005], 2, "take"),   # +5 % then +0.5 %: ends after pass 2, last value above start
    ([0.05, -0.10], 2, "drop"),   # the last value below start: drop by value
    ([0.05, 0.02], 2, "climbing"),
    ([0.005], 1, "take"),         # +0.5 %: ends after pass 1
    ([-0.03], 1, "drop"),
]


@pytest.mark.parametrize("direction", ["force", "forbid"])
@pytest.mark.parametrize("gains, passes, verdict", CASES)
def test_the_passes_stop_by_the_rule_and_the_choice_is_held_after_every_pass(monkeypatch, direction, gains, passes, verdict):
    rig = _force(monkeypatch, gains) if direction == "force" else _forbid(monkeypatch, gains)
    name = FORCED if direction == "force" else FORBIDDEN
    outcome = rig.run(RepairChoice(name, direction))

    assert len(rig.after_pass) == passes
    assert len(outcome.values) == passes and outcome.verdict == verdict
    assert outcome.values[0] == pytest.approx(rig.start * (1 + gains[0]))
    assert outcome.gains == pytest.approx(gains[:passes])
    assert [s.name for s in rig.result.stages] == ["repair pass 0"] + [f"repair pass {n}" for n in range(1, passes + 1)]
    assert [(plan.kind, plan.max_passes, plan.first_pass) for plan in rig.plans] == [("repair", 1, n) for n in range(1, passes + 1)]
    for held in rig.after_pass:
        if direction == "force":
            assert {K, G} <= held, "the forced keystone and its path stay in the tree after every pass"
        else:
            assert K2 not in held, "the forbidden keystone stays out of the tree after every pass"


def test_force_start_is_the_value_before_the_choice(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    outcome = rig.run(RepairChoice(FORCED, "force"))
    assert outcome.start == pytest.approx(rig.start)  # 1000 + the weights of the finished build, not of the build with K on
    assert outcome.verdict == "take" and outcome.values[0] > outcome.start


def test_force_pays_its_points_with_the_weakest_leaves_and_pins_the_node(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED.upper(), "force"))  # the name matches case-insensitively
    assert rig.skeleton.forced_nodes == [K]
    assert len(rig.pob.allocated) == 7  # the budget again: +2 for the path (G, K), -2 for the weakest leaves
    assert {A, G, K} <= rig.pob.allocated
    assert not {L1, L2} & rig.pob.allocated  # the two least valuable leaves left, nothing else
    assert {B, L3, L4} <= rig.pob.allocated
    for opt in (rig.opt, rig.construction):
        assert K in opt.protected


def test_force_over_a_build_already_above_the_rule_keeps_its_own_total(monkeypatch):
    rig = _Rig(monkeypatch, allocated=FORCE_ALLOCATED, budget=5, gains=[0.005])  # the rule says 5, the build holds 7
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORCED, "force"))
    assert len(rig.pob.allocated) == 7  # not cut to the rule's 5: the repair compares builds of one size


def test_force_without_leaves_to_remove_raises(monkeypatch):
    rig = _Rig(monkeypatch, allocated={START, A, B}, budget=3, gains=[0.005])
    rig.pob.weights[B] = 1.0
    # adding K costs two points over the budget; the leaves are B (removable) and then G / K / A (path to the pinned node): B goes, then none is left
    with pytest.raises(RuntimeError, match="no leaf to remove"):
        rig.run(RepairChoice(FORCED, "force"))


def test_force_refuses_a_forbidden_keystone_and_forbid_a_forced_one(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.skeleton.forbid_keystones.append(FORCED)
    with pytest.raises(ValueError, match="forbids"):
        rig.run(RepairChoice(FORCED, "force"))
    rig = _forbid(monkeypatch, [0.005])
    rig.skeleton.forced_nodes.append(K2)
    with pytest.raises(ValueError, match="forces"):
        rig.run(RepairChoice(FORBIDDEN, "forbid"))


def test_forbid_removes_holds_out_and_respends_the_freed_point(monkeypatch):
    rig = _forbid(monkeypatch, [0.005])
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert K2 not in rig.pob.allocated
    assert len(rig.pob.allocated) == 8  # the budget again: the keystone's point went to the best remaining node
    assert R2 in rig.pob.allocated and R1 not in rig.pob.allocated  # the spare-point step, by the objective's own values
    assert rig.skeleton.keystones == [] and rig.skeleton.forbid_keystones == [FORBIDDEN]
    for opt in (rig.opt, rig.construction):
        assert K2 in opt.excluded_nodes


def test_forbid_note_names_the_nodes_the_freed_points_were_spent_on(monkeypatch):
    rig = _forbid(monkeypatch, [0.005])
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert "1 spent on r2" in rig.result.stages[-1].notes


def test_forbid_control_without_the_exclusion_the_tree_takes_the_keystone_back(monkeypatch):
    rig = _forbid(monkeypatch, [0.005])
    rig.pob.mutate_nodes(remove=[K2])
    rig.opt.allocate(1)  # the same one-point spend, no exclusion
    assert K2 in rig.pob.allocated


def test_forbid_of_a_keystone_the_tree_never_took_only_holds_it_out(monkeypatch):
    rig = _Rig(monkeypatch, allocated=FORCE_ALLOCATED, budget=7, gains=[0.005])
    rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert K2 not in rig.after_pass[0] and len(rig.after_pass[0]) == 7
    assert K2 in rig.opt.excluded_nodes


def test_force_control_an_unprotected_refine_removes_the_forced_keystone(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.pob.mutate_nodes(add=[K])
    unprotected = rig.opt
    unprotected.refine(max_rounds=1)
    assert K not in rig.pob.allocated  # the weights are negative: the protected set is what keeps it in the repair


def test_an_unknown_keystone_raises():
    graph = _tree_graph()
    assert resolve_keystone_id(graph, "test forced keystone") == K
    with pytest.raises(ValueError, match="no keystone named"):
        resolve_keystone_id(graph, "Not A Keystone")
    with pytest.raises(ValueError, match="no keystone named"):
        resolve_keystone_id(graph, "a")  # a node that is not a keystone


@pytest.mark.parametrize("name", ["repair pass 0", "repair pass 1", "repair pass 2"])
def test_the_repair_stage_names_are_known_to_the_catalog_and_the_ledger(name):
    from junkroan.optimizer.move_ledger import LOOP_WHERE

    step = step_of(name)
    assert step is not None and step.name == "repair pass <N>"
    assert any(name.startswith(prefix) for prefix in LOOP_WHERE)


# -- the loop level: a one-pass run that starts at pass 2 -----------------------------------------------------

def test_the_loop_run_as_pass_two_alone_names_its_stage_and_moves_repair_pass_two(monkeypatch) -> None:
    logs: list[str] = []
    pob = _LoopPob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)], "Boots": [("b1", 1022.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    result = rig.started()
    plan = dataclasses.replace(LoopPlan.repair(seed=1), max_passes=1, first_pass=2)
    outcome = rig.run(plan)

    assert outcome.passes == 1
    assert [v for k, v in map(parse_log_line, logs) if k == "start"] == ["repair pass 2"]
    names = [s.name for s in result.stages]
    assert "repair pass 2" in names and "repair pass 1" not in names and "loop pass 1" not in names
    assert result.moves and {row["where"] for row in result.moves} == {"repair pass 2"}


def _forbid_viol(monkeypatch, gains, viol):
    return _Rig(monkeypatch, allocated=FORBID_ALLOCATED, budget=8, gains=gains, keystones=[K2], viol=viol)


def test_forbid_pass_that_cleared_the_violation_lets_pass_two_run(monkeypatch):
    rig = _forbid_viol(monkeypatch, [-0.0005, 0.005], viol=[2.086, 0.0, 0.0])  # pass 0 left the build infeasible, pass 1 made it feasible at -0.05 %
    outcome = rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert len(outcome.values) == 2 and len(rig.after_pass) == 2


def test_forbid_same_gain_without_a_violation_ends_after_pass_one(monkeypatch):
    rig = _forbid_viol(monkeypatch, [-0.0005], viol=[0.0, 0.0, 0.0])
    outcome = rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert len(outcome.values) == 1 and outcome.verdict == "drop"


def test_forbid_pass_one_that_ends_infeasible_is_not_a_cleared_pass(monkeypatch):
    rig = _forbid_viol(monkeypatch, [-0.0005], viol=[2.086, 0.5, 0.0])  # started infeasible, still infeasible: not cleared
    assert len(rig.run(RepairChoice(FORBIDDEN, "forbid")).values) == 1


def test_forbid_climbing_after_a_cleared_pass_one(monkeypatch):
    rig = _forbid_viol(monkeypatch, [-0.0005, 0.02], viol=[2.086, 0.0, 0.0])
    assert rig.run(RepairChoice(FORBIDDEN, "forbid")).verdict == "climbing"


@pytest.mark.parametrize("gains, verdict", [([-0.0005, 0.005], "take"), ([-0.10, 0.005], "drop")])
def test_forbid_pass_two_under_the_floor_is_take_or_drop_by_value_against_start(monkeypatch, gains, verdict):
    rig = _forbid_viol(monkeypatch, gains, viol=[2.086, 0.0, 0.0])
    outcome = rig.run(RepairChoice(FORBIDDEN, "forbid"))
    assert len(outcome.values) == 2 and outcome.verdict == verdict
    assert (outcome.values[-1] >= outcome.start) == (verdict == "take")
