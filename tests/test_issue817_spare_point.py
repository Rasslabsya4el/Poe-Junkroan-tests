"""#817 / #865: one passive point stayed unspent BY the rule "a node is taken only if it improves the objective" (0 PoB).
#865 changes the spare-point step only: a tie is judged again on the objective's floor margins, a Score-lowering node is
never taken, and `allocate` anywhere else keeps its stop on a tie.

Smoke build summon_raging_spirits: `_spend_extra_points` saw ExtraPoints 1, points_used 100, spare 1;
`ALLOCATE(1) spent 0, stopped: no candidate improves the objective`. The real `TreeOptimizer.allocate`
and the real `BuildPipeline._spend_extra_points` run here on a fake PoB (the plan-B fake: value = 1000 + weights)."""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

import pytest  # noqa: E402

from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline  # noqa: E402
from junkroan.optimizer.rails import max_passive_points  # noqa: E402

from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402

from test_tree_plan_b import START, _Pob, _graph, _node, _opt  # noqa: E402

A, B, C = 10, 11, 12
LEVEL = 90


class _SpareLoadPob(_Pob):
    """The plan-B fake plus the two reads `_spend_extra_points` makes: ExtraPoints 1 and points_used one short of the cap."""

    def stats(self, keys) -> dict:
        return {"ExtraPoints": 1} if tuple(keys) == ("ExtraPoints",) else super().stats(keys)

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        if not add and not remove:
            return {"points_used": max_passive_points(LEVEL, 1) - 1}
        return super().mutate_nodes(add, remove, mastery_effects)


def _case(weights: dict[int, float], pob_class=_Pob):
    nodes = {START: _node(START, "Witch", "class_start"), A: _node(A, "a", "normal"), B: _node(B, "b", "notable")}
    graph = _graph(nodes, [(START, A), (A, B)])
    pob = pob_class(graph, {START}, weights)
    return pob, _opt(pob, graph)


def _pipeline(pob, opt, full: Objective | None = None, lines: list[str] | None = None) -> BuildPipeline:
    """The real `_spend_extra_points` on a judging stand-in: `view`, the full `objective` and `lend` with the real
    contract (the view holds the lent objective inside the block, its own back on exit, also on an exception)."""

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob = pob
    p.log = (lines if lines is not None else []).append

    @contextmanager
    def lend(role, objective):
        view = opt if role == "tree" else None
        own = view.objective
        view.objective = objective
        try:
            yield view
        finally:
            view.objective = own

    p.judging = SimpleNamespace(view=lambda name: opt if name == "tree" else None, objective=full if full is not None else opt.objective, lend=lend)
    return p


def test_allocate_one_spends_nothing_when_no_candidate_improves() -> None:
    pob, opt = _case({A: 0.0, B: 0.0})  # every candidate scores <= the current 1000
    before = set(pob.allocated)

    result = opt.allocate(1)

    assert result.points_spent == 0
    assert result.stopped_reason == "no candidate improves the objective"
    assert pob.allocated == before and pob.mutations == []


def test_allocate_one_spends_the_point_when_a_candidate_improves() -> None:
    pob, opt = _case({A: 5.0, B: 0.0})  # positive control: the same setup, A improves

    result = opt.allocate(1)

    assert result.points_spent == 1
    assert pob.allocated == {START, A}


def test_spend_extra_points_spends_the_spare_point_on_a_tie() -> None:
    pob, opt = _case({A: 0.0, B: 0.0}, _SpareLoadPob)  # every candidate ties the current 1000 (no floors to tell them apart)

    spent = _pipeline(pob, opt)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert spent == 1  # #865: ExtraPoints 1, spare 1, a node that does not lower the Score takes it (was 0 under #817)
    assert len(pob.allocated) == 2


def test_spend_extra_points_spends_the_spare_point_when_a_candidate_improves() -> None:
    pob, opt = _case({A: 5.0, B: 0.0}, _SpareLoadPob)

    spent = _pipeline(pob, opt)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert spent == 1 and pob.allocated == {START, A}


# -- #865 rules 1-3: the spare point judged again on the objective's own floors ---------------------------------

FLOORS = {"Life": 100.0, "Res": 50.0}  # base Life 110 (margin 0.10), Res 60 (margin 0.20)


class _FloorPob(_SpareLoadPob):
    """The spare-load fake with two more stats: Life and Res, each node adding `deltas[node]` to the base."""

    def __init__(self, graph, allocated, weights, deltas: dict[int, dict[str, float]]) -> None:
        super().__init__(graph, allocated, weights)
        self.deltas = deltas

    def _stats(self, nodes) -> dict:
        out = {"CombinedDPS": self._value(nodes), "Life": 110.0, "Res": 60.0, "EffectiveMovementSpeedMod": 1.10}
        for n in nodes:
            for key, delta in self.deltas.get(int(n), {}).items():
                out[key] += delta
        return out

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        out = super().trial_stats(trials, keys, mode)
        for trial, entry in zip(trials, out):
            entry["stats"] = self._stats((self.allocated | set(entry["added_node_ids"])) - set(entry["removed_node_ids"]))
        return out

    def stats(self, keys) -> dict:
        return {"ExtraPoints": 1} if tuple(keys) == ("ExtraPoints",) else self._stats(self.allocated)


def _floor_case(weights: dict[int, float], deltas: dict[int, dict[str, float]]):
    nodes = {START: _node(START, "Witch", "class_start")}
    nodes.update({n: _node(n, f"n{n}", "normal") for n in (A, B, C, 13)})
    graph = _graph(nodes, [(START, n) for n in (A, B, C, 13)])
    pob = _FloorPob(graph, {START}, weights, deltas)
    lines: list[str] = []
    return pob, TreeOptimizer(pob, Objective(maximize="CombinedDPS", floors=FLOORS), graph=graph, log=lines.append), lines


def test_spare_point_tie_goes_to_the_candidate_with_the_largest_smallest_floor_margin() -> None:
    # all three tie on value 1000; smallest margins: A Life 105 -> 0.05, B Life 110 / Res 58 -> 0.10, C Res 52 -> 0.04.
    # D lowers the value, E lowers Life under its floor (violation): both are out before the margins are looked at.
    pob, opt, lines = _floor_case(
        {A: 0.0, B: 0.0, C: 0.0, 13: -1.0},
        {A: {"Life": -5.0}, B: {"Res": -2.0}, C: {"Life": 10.0, "Res": -8.0}, 13: {"Life": 50.0, "Res": 40.0}},
    )

    spent = _pipeline(pob, opt)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert spent == 1  # red on main: 0 spent, "no candidate improves the objective"
    assert pob.allocated == {START, B}
    assert not any("left unspent" in line for line in lines)


def test_spare_point_stays_unspent_and_is_logged_when_every_candidate_lowers_the_score() -> None:
    pob, opt, lines = _floor_case({A: -3.0, B: -1.0, C: -2.0, 13: 0.0}, {13: {"Life": -20.0}})  # 13 ties the value but breaks Life 100

    spent = _pipeline(pob, opt)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert spent == 0 and pob.allocated == {START} and pob.mutations == []
    unspent = [line for line in lines if "left unspent" in line]
    assert len(unspent) == 1 and "4 candidates measured" in unspent[0]
    assert "value -1, violation +0.0000" in unspent[0]  # the smallest loss by the Score's order: B (violation first: 13 breaks Life, A and C lose more)


def test_allocate_outside_the_spare_point_step_still_stops_on_a_tie_with_floors() -> None:
    pob, opt, lines = _floor_case({A: 0.0, B: 0.0, C: 0.0, 13: 0.0}, {B: {"Res": -2.0}})

    result = opt.allocate(1)  # the default: no spare-point rule

    assert result.points_spent == 0 and result.stopped_reason == "no candidate improves the objective"
    assert pob.allocated == {START} and not lines


# -- #865 rule 4: the spare-point step judges under the objective the delivered numbers are read under ------------------

MOVE = {"EffectiveMovementSpeedMod": 1.1543}  # the floor the "tree" view is cut without (judging._without_movement)


def _move_case():
    """The view's objective has no movement floor, the full one has it (base 1.10, short by 0.0457). All four tie on
    value 1000. B raises Life (the biggest smallest-margin under the view's floors: 0.20 against C's 0.10); only C lifts
    movement over its floor (1.16)."""

    pob, opt, lines = _floor_case({A: 0.0, B: 0.0, C: 0.0, 13: 0.0}, {B: {"Life": 20.0}, C: {"EffectiveMovementSpeedMod": 0.06}})
    full = Objective(maximize="CombinedDPS", floors={**FLOORS, **MOVE})
    return pob, opt, lines, full


def test_spare_point_is_judged_under_the_full_objective_and_the_view_gets_its_own_back() -> None:
    pob, opt, lines, full = _move_case()
    own = opt.objective

    spent = _pipeline(pob, opt, full, lines)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert spent == 1 and pob.allocated == {START, C}  # red on a1d5b3ef: the view's floors see no shortfall, B (Life margin) takes the point
    assert opt.objective is own  # identity: the view's own objective is back


def test_the_view_objective_is_back_when_allocate_raises() -> None:
    pob, opt, lines, full = _move_case()
    own = opt.objective

    def boom(*_a, **_k):
        raise RuntimeError("PoB went away")

    opt.allocate = boom
    with pytest.raises(RuntimeError):
        _pipeline(pob, opt, full, lines)._spend_extra_points(SimpleNamespace(level=LEVEL))

    assert opt.objective is own


def test_the_step_logs_the_violation_under_the_view_and_under_the_delivered_objective() -> None:
    pob, opt, lines, full = _move_case()

    _pipeline(pob, opt, full, lines)._spend_extra_points(SimpleNamespace(level=LEVEL))

    logged = [line for line in lines if line.startswith("spare-point step:")]
    assert len(logged) == 1
    numbers = re.findall(r"\d+\.\d{6}", logged[0])
    assert numbers == ["0.000000", f"{(1.1543 - 1.10) / 1.1543:.6f}"]  # the movement shortfall only the full objective sees
    assert logged[0] == f"spare-point step: violation under the tree view {numbers[0]}, under the delivered objective {numbers[1]}"
