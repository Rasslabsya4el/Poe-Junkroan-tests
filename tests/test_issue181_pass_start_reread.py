"""#181: the Score the loop carries is the Score of the current build under the CURRENT objective.

The improvement loop refreshes the frozen skill cost (`Judging.refresh_castability`, ADR 0085) as the
first statement of every pass. Measured in #167 (ziz-tpl `z326_berserker_volcanic_fissure` s4, pass 3):
the frozen `CostedManaCost` went 34.437 -> 52.0 against a `ManaCostPool` of 36.0, so the very same build
was 215,143 / violation 0.000000 before the refresh and 215,143 / violation 0.307692 after it, and the loop
went on carrying the first number. The fix reads the Score again (`cur = score_now()`) right after the
refresh; a kept move that lowers the value now prints both violations in the pass note.

No PoB: the build is a fake session that answers one stat dict; the loop, the judging context and the
castability floors are the production ones.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.castability import CastabilityContext
from junkroan.optimizer.objective import Objective

from junkroan.optimizer.improvement_loop import LoopFlags, LoopPlan

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

FIXTURE = Path(__file__).resolve().parents[0] / "fixtures" / "regressions" / "issue167_pass3_refine_revert.json"

STALE_COST = 34.437086092715  # the frozen CostedManaCost at the end of pass 2 (#167, trace row 1099)
FRESH_COST = 52.0  # the same build's CostedManaCost after the pass-3 refresh (trace row 1100)
POOL = 36.0  # ManaCostPool
FRESH_VIOLATION = (FRESH_COST - POOL) / FRESH_COST  # 0.307692


def _context(mana_cost: float | None) -> CastabilityContext:
    return CastabilityContext((), mana_cost, None, ())


class _StatsPob(_Pob):
    """A `_Pob` whose build answers a whole stat dict (CombinedDPS and Life stay the two moving numbers)."""

    def __init__(self, stats: dict) -> None:
        super().__init__(float(stats["CombinedDPS"]), life=float(stats["Life"]))
        self.base = {k: v for k, v in stats.items() if k not in ("CostedManaCost", "ManaCostPool")}  # derived by the objective

    def stats(self, keys):
        return {k: 0 for k in keys} | self.base | {"CombinedDPS": self.value, "Life": self.life}


class _MoveTree(_Tree):
    """A refine that leaves (value, life) at the next scripted pair."""

    def __init__(self, pob, moves) -> None:
        super().__init__(pob, [])
        self.moves = list(moves)

    def refine(self, *, max_rounds: int, repair_rounds: int = 60):
        self.calls.append(("refine", max_rounds, repair_rounds))
        if max_rounds and self.moves:
            self.pob.value, self.pob.life = self.moves.pop(0)
        return SimpleNamespace(steps=[])


def run_pass_with_a_refreshed_cost(monkeypatch, objective: Objective, stats: dict, refine_to: tuple[float, float], *, fresh_cost: float | None = FRESH_COST):
    """One pass (the `refine` move only) of the production loop, whose frozen cost is STALE_COST until the
    pass-start refresh and `fresh_cost` after it. Returns (result, pob)."""

    pob = _StatsPob(stats)
    tree = _MoveTree(pob, [refine_to])
    loot = _Loot(pob, {})
    sk = _skeleton({}, main_link=("Fireball",))
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, objective=objective)
    p.judging.refresh_castability(_context(STALE_COST))  # the objective the loop's opening judged with
    p.judging.reads.castability = lambda: _context(fresh_cost)  # what the pass-start refresh reads from the build
    _patch_generator(monkeypatch, [])
    result = p.started()
    # `opening_lanes=False` without a count budget is a combination no `LoopPlan` kind gives: the flags say it
    p.run(LoopPlan(seed=1, max_passes=1, max_seconds=600.0, min_gain=0.005, loot_n=5, moves=frozenset({"refine"})),
          flags=LoopFlags(local_only=False, opening_lanes=False, stage_name=None))
    return result, pob


def fixture_objective() -> tuple[Objective, dict]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec = data["objective"]
    objective = Objective(maximize=spec["maximize"], floors=dict(spec["floors"]), ceilings=dict(spec["ceilings"]),
                          relations=tuple(tuple(rel) for rel in spec["relations"]))
    return objective, data["before_move"]["stats"]


def test_the_score_carried_into_the_first_move_is_read_under_the_refreshed_cost(monkeypatch) -> None:
    objective, stats = fixture_objective()

    result, pob = run_pass_with_a_refreshed_cost(monkeypatch, objective, stats, (190000.0, stats["Life"]))

    (row,) = [m for m in result.moves if m["move"] == "refine"]
    assert row["violation_before"] == pytest.approx(0.307692, abs=1e-6)  # was 0.0 before the fix
    assert row["violation_before"] == pytest.approx(FRESH_VIOLATION, abs=1e-12)
    assert row["before"] == stats["CombinedDPS"]
    assert not row["kept"]
    assert (row["before"], row["violation_before"]) == (row["after"], row["violation_after"])  # #167: a reverted move leaves the Score it started from
    assert result.stages[-1].violation == pytest.approx(FRESH_VIOLATION, abs=1e-12)  # the pass's own record carries the same number


def test_a_kept_move_that_lowers_the_value_names_both_violations(monkeypatch) -> None:
    life_floor = Objective(maximize="CombinedDPS", floors={"Life": 4000})
    stats = {"CombinedDPS": 1000.0, "Life": 3000.0}  # violation (4000 - 3000) / 4000 = 0.250

    result, pob = run_pass_with_a_refreshed_cost(monkeypatch, life_floor, stats, (800.0, 5000.0), fresh_cost=None)

    assert result.stages[-1].notes.startswith("refine -20.0% (viol 0.250 -> 0.000)")
    assert pob.value == 800.0


def test_a_kept_move_that_raises_the_value_prints_no_violation(monkeypatch) -> None:
    life_floor = Objective(maximize="CombinedDPS", floors={"Life": 4000})
    stats = {"CombinedDPS": 1000.0, "Life": 3000.0}

    result, _pob = run_pass_with_a_refreshed_cost(monkeypatch, life_floor, stats, (1200.0, 5000.0), fresh_cost=None)

    assert result.stages[-1].notes.startswith("refine +20.0%;") and "viol" not in result.stages[-1].notes
