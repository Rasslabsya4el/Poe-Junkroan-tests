"""#941: a kept move is judged against the skill costs the move left, and the loop never hands over a build whose last
pass kept a move without that check having run on the final state.

Measured on the weekly run's delivered ignite_penance_brand s5 (the rig of #941): ManaUnreserved 39, Flammability's
ManaCost 46.4, the search's freshly frozen CostedManaCost 46.4; the search's check equals `audit_castability`'s on a fresh
freeze, but the freeze (`Judging.refresh_castability`) was taken once per pass, so a move kept inside a pass was judged
under the cost before it, and a loop that ended after such a pass handed the build over unchecked.

No PoB: a fake session whose build is (value, cost, mana); the loop, the judging context, the castability floors and
`audit_castability` are the production ones.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from junkroan.optimizer.audit import audit_castability
from junkroan.optimizer.castability import CastabilityContext, CostedSkill
from junkroan.optimizer import improvement_loop as loop_module
from junkroan.optimizer.improvement_loop import LoopFlags, LoopPlan
from junkroan.optimizer.objective import Objective
from junkroan.report_format import human_duration

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

POOL = 100.0  # ManaUnreserved
OLD_COST = 50.0  # Flammability's ManaCost before the move
RAISED_COST = 120.0  # after it: above the pool


class _CostPob(_Pob):
    """A build that is its value, Flammability's ManaCost and its Mana; ManaUnreserved is the pool the cost is paid from."""

    def __init__(self, value: float, *, cost: float = OLD_COST, mana: float = 100.0, unreserved: float = POOL, reserved_percent: float = 0.0) -> None:
        super().__init__(value)
        self.cost, self.mana, self.unreserved = cost, mana, unreserved
        self.reserved_percent = reserved_percent  # the skill's own reservation (the audit lets it pay from what it reserves)

    def stats(self, keys):
        return ({k: 0 for k in keys} | {"CombinedDPS": self.value, "Life": self.life, "ManaUnreserved": self.unreserved,
                                        "Mana": self.mana, "EnergyShield": 0, "EnergyShieldProtectsMana": 0})

    def export_xml(self) -> str:
        token = f"xml{len(self._snapshots) + 1}"
        self._snapshots[token] = (self.value, self.life, self.cost, self.mana)
        return token

    def load_xml(self, token: str) -> None:
        self.value, self.life, self.cost, self.mana = self._snapshots[token]


class _CostTree(_Tree):
    """`refine` (the loop's move) leaves the build at `moved`; the repair-only refine at `repaired`, each (value, cost, mana)."""

    def __init__(self, pob: _CostPob, moved: tuple, repaired: tuple | None = None) -> None:
        super().__init__(pob, [])
        self.moved, self.repaired = moved, repaired

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        self.calls.append(("refine", max_rounds, repair_rounds))
        target = self.moved if max_rounds else self.repaired
        if target is not None:
            self.pob.value, self.pob.cost, self.pob.mana = target
        return SimpleNamespace(steps=[])


def _requirement(pob: _CostPob, *, cost: float | None = None) -> float:
    """`castability._cost_requirement`: what a skill needs from the pool after the part of its cost it reserves."""

    return max(0.0, (pob.cost if cost is None else cost) - math.ceil(pob.mana * pob.reserved_percent / 100.0))


def _context(pob: _CostPob) -> CastabilityContext:
    return CastabilityContext((), _requirement(pob), None, ())


def _audit_errors(pob: _CostPob) -> list:
    skill = CostedSkill("Flammability", "Flammability", "Flammability", pob.cost, None, pob.reserved_percent, None, False)
    return audit_castability(pob, skills=(skill,))


def run_one_pass(monkeypatch, pob: _CostPob, tree: _CostTree):
    return run_one_pass_outcome(monkeypatch, pob, tree)[0]


def run_one_pass_outcome(monkeypatch, pob: _CostPob, tree: _CostTree):
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=_Loot(pob, {}), skeleton=sk, objective=Objective(maximize="CombinedDPS"))
    p.judging.refresh_castability(_context(pob))  # the objective the loop's opening judged with
    p.judging.reads.castability = lambda: _context(pob)  # what a refresh reads from the build as it stands
    _patch_generator(monkeypatch, [])
    result = p.started()
    outcome = p.run(LoopPlan(seed=1, max_passes=1, max_seconds=None, min_gain=0.005, loot_n=5, moves=frozenset({"refine"})),
                    flags=LoopFlags(local_only=False, opening_lanes=False, stage_name=None))
    return result, outcome


def test_a_move_that_raises_a_cost_past_the_pool_is_judged_under_that_cost(monkeypatch) -> None:
    pob = _CostPob(1000.0)
    tree = _CostTree(pob, moved=(1010.0, RAISED_COST, 100.0))  # +1.0 %: kept under the old cost 50, priced out under 120 > 100

    result = run_one_pass(monkeypatch, pob, tree)

    (row,) = [m for m in result.moves if m["move"] == "refine"]
    assert row["kept"] is False and row["reverted_by_judge"] is True  # was kept: its violation 0 under the cost frozen before it
    assert (pob.value, pob.cost) == (1000.0, OLD_COST)  # the move is out
    assert _audit_errors(pob) == []


def test_a_kept_move_carries_the_violation_of_the_cost_it_raised(monkeypatch) -> None:
    pob = _CostPob(1000.0)
    tree = _CostTree(pob, moved=(3000.0, RAISED_COST, 100.0))  # the gain pays the priced violation: kept, and the row says what it cost

    result = run_one_pass(monkeypatch, pob, tree)

    (row,) = [m for m in result.moves if m["move"] == "refine"]
    assert row["kept"] is True
    assert row["violation_before"] == 0.0
    assert row["violation_after"] == pytest.approx((RAISED_COST - POOL) / RAISED_COST, abs=1e-12)
    assert row["violation_after"] > 0.0  # was 0.0 on main: a violation of that same move that the search never saw


def test_a_move_that_lowers_the_mana_under_the_frozen_requirement_is_a_violation_of_that_move(monkeypatch) -> None:
    # the frozen requirement is cost - ceil(Mana * reservation %): Mana 100 -> 40 takes 50 off the reservation, so the
    # requirement of cost 120 goes 70 -> 100 against a pool of 80, and the frozen 70 fits it
    pob = _CostPob(1000.0, cost=RAISED_COST, mana=100.0, unreserved=80.0, reserved_percent=50.0)
    tree = _CostTree(pob, moved=(1010.0, RAISED_COST, 40.0))

    result = run_one_pass(monkeypatch, pob, tree)

    (row,) = [m for m in result.moves if m["move"] == "refine"]
    assert row["kept"] is False and (pob.value, pob.mana) == (1000.0, 100.0)  # was kept: 70 <= 80 under the frozen number


def test_the_loop_that_ends_after_a_pass_that_kept_such_a_move_hands_over_a_castable_build(monkeypatch) -> None:
    pob = _CostPob(1000.0)
    # the move is worth keeping at a priced violation (value 3000); the loop's last act buys the cost back (value 2800, cost 50)
    tree = _CostTree(pob, moved=(3000.0, RAISED_COST, 100.0), repaired=(2800.0, OLD_COST, 100.0))

    result = run_one_pass(monkeypatch, pob, tree)  # max_passes 1: the pass kept a move and no next pass refreshes the freeze

    assert any(m["move"] == "refine" and m["kept"] for m in result.moves)
    assert _audit_errors(pob) == []  # red on main: Flammability 120 > 100 unreserved + its own reservation
    assert (pob.value, pob.cost) == (2800.0, OLD_COST)
    assert "repair" in result.stages[-1].notes


def test_the_loop_leaves_a_castable_build_alone(monkeypatch) -> None:
    pob = _CostPob(1000.0)
    tree = _CostTree(pob, moved=(1200.0, 60.0, 100.0))  # kept, cost 60 <= pool 100: nothing to repair

    result = run_one_pass(monkeypatch, pob, tree)

    assert any(m["move"] == "refine" and m["kept"] for m in result.moves)
    assert ("refine", 0, 60) not in tree.calls
    assert (pob.value, _audit_errors(pob)) == (1200.0, [])


class _SwapTree(_CostTree):
    """The repair-only refine keeps `swaps` tree changes (one `Step` each, as `TreeOptimizer.refine` returns them) and takes `repair_seconds` on `clock`."""

    def __init__(self, pob: _CostPob, moved: tuple, repaired: tuple, *, swaps: int = 2, clock: list | None = None, repair_seconds: float = 0.0) -> None:
        super().__init__(pob, moved, repaired)
        self.swaps, self.clock, self.repair_seconds = swaps, clock, repair_seconds

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        super().refine(max_rounds=max_rounds, repair_rounds=repair_rounds)
        if max_rounds:
            return SimpleNamespace(steps=[])
        if self.clock is not None:
            self.clock[0] += self.repair_seconds
        return SimpleNamespace(steps=[object()] * self.swaps)


def test_the_closing_repair_counts_the_tree_changes_it_kept_beside_the_moves_kept(monkeypatch) -> None:
    # #1008: the repair keeps 2 tree changes after the last pass; `kept` (moves) is what it is without the repair
    repaired = _CostPob(1000.0)
    _, with_repair = run_one_pass_outcome(monkeypatch, repaired, _SwapTree(repaired, (3000.0, RAISED_COST, 100.0), (2800.0, OLD_COST, 100.0)))
    castable = _CostPob(1000.0)
    result, without = run_one_pass_outcome(monkeypatch, castable, _SwapTree(castable, (3000.0, 60.0, 100.0), (2800.0, OLD_COST, 100.0)))

    assert without.counts["closing_repair_kept"] == 0  # nothing to repair: the run the 2 are counted against
    assert with_repair.counts["closing_repair_kept"] == 2  # was not in the report at all
    assert with_repair.counts["kept"] == without.counts["kept"] == 1  # the moves kept: the repair is no move of the plan
    assert with_repair.counts["not_kept"] == without.counts["not_kept"]
    assert "2 tree changes kept in the closing repair" in with_repair.note and "closing repair" not in without.note
    assert [m["move"] for m in result.moves] == ["refine"]  # no phantom move row in the per-move ledger


def test_a_closing_repair_the_judge_reverts_counts_no_tree_change(monkeypatch) -> None:
    pob = _CostPob(1000.0)
    tree = _SwapTree(pob, (3000.0, RAISED_COST, 100.0), (2900.0, RAISED_COST, 100.0))  # the same violation at a lower value: restored

    _, outcome = run_one_pass_outcome(monkeypatch, pob, tree)

    assert outcome.counts["closing_repair_kept"] == 0
    assert (pob.value, pob.cost) == (3000.0, RAISED_COST)


def test_the_closing_repair_time_is_in_the_pass_note_through_human_duration(monkeypatch) -> None:
    now = [100.0]
    monkeypatch.setattr(loop_module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    pob = _CostPob(1000.0)
    tree = _SwapTree(pob, (3000.0, RAISED_COST, 100.0), (2800.0, OLD_COST, 100.0), clock=now, repair_seconds=125.0)

    result, _ = run_one_pass_outcome(monkeypatch, pob, tree)

    assert f"closing repair {human_duration(125.0)}, 2 tree changes kept" in result.stages[-1].notes
    assert "closing repair 2.1 min, 2 tree changes kept" in result.stages[-1].notes
