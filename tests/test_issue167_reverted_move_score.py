"""#167: after a move the loop reverted, the Score must equal the Score before the move.

Measured in PoB on ziz-tpl `z326_berserker_volcanic_fissure` seed 4, `loop pass 3`,
pinned @42565a9 (`artifacts/meas167/replay_pass3.py`, job `j-20260927-1432-d956`):
`judge()` tries the `refine` move, rejects it and reverts it with `restores_exact=True`
(`src/junkroan/optimizer/pipeline.py:1088` at the pin, :1100 on `main` -- the bodies are
byte-identical, only the line offset differs), so the revert is `restore_move`'s
`self.pob.load_xml(state["xml"])` (:1011 / :1023) and `_reconfigure` is skipped, then
`cur = score_now()` (:1091 / :1103).

The revert itself is faithful: the build before the move and the build after the revert
are the same to every one of PoB's 712 outputs. What is not equal is the Score the loop
CARRIES into the move (`cur`, which `record_move` writes as the row's `before`) and the
Score PoB gives for the very same build: `cur` says violation 0, PoB says 0.307692 --
`ManaCostPool` 36 against `CostedManaCost` 52, (52 - 36) / 52. The next move
(`path swaps`) is judged against the second, is therefore compared against an infeasible
`cur`, and `better_score` keeps it at -13.7% value.

The fixture holds those three numbers: the loop's carried `cur`, and the PoB outputs the
objective reads in the two states (derived stats of `optimizer/ramp.py` and
`optimizer/castability.py` already merged in), so this test needs no PoB runtime and
reproduces `Objective.score` (`optimizer/objective.py`, byte-identical at the pin and on
`main`) on both.

Fixed by #181: the loop reads the Score again after the pass-start refresh; the first test below drives the
production loop over the fixture's build and is the bar that fix delivered (it was `xfail(strict=True)`).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.objective import Objective

from test_issue181_pass_start_reread import fixture_objective, run_pass_with_a_refreshed_cost

FIXTURE = Path(__file__).resolve().parents[0] / "fixtures" / "regressions" / "issue167_pass3_refine_revert.json"


def _load() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _objective(spec: dict) -> Objective:
    """The objective the loop judged pass 3 with. `derived` is empty on purpose: the
    fixture's stat dicts already carry the derived values PoB does not output, so
    `violations()` reads them as plain stats and returns the same numbers."""

    return Objective(
        maximize=spec["maximize"],
        floors=dict(spec["floors"]),
        ceilings=dict(spec["ceilings"]),
        relations=tuple(tuple(rel) for rel in spec["relations"]),
    )


def test_reverted_move_leaves_the_score_it_started_from(monkeypatch) -> None:
    """The production loop over the fixture's build: the frozen `CostedManaCost` goes 34.437 -> 52.0 at the
    pass-start refresh (`ManaCostPool` 36.0), the first move (`refine`) is refused and reverted, and the
    Score it leaves equals the Score the loop carried into it, to the digit -- and that Score is the fresh
    one PoB gives for the build (#181 reads it again after the refresh)."""

    data = _load()
    objective, stats = fixture_objective()
    result, _pob = run_pass_with_a_refreshed_cost(monkeypatch, objective, stats, (194890.40957763, stats["Life"]))

    (row,) = [m for m in result.moves if m["move"] == "refine"]
    fresh = _objective(data["objective"]).score(data["after_revert"]["stats"])
    assert not row["kept"]
    assert (row["after"], row["violation_after"]) == (row["before"], row["violation_before"])
    assert (row["before"], row["violation_before"]) == pytest.approx((fresh.value, fresh.violation), abs=1e-12)


def test_the_revert_itself_is_faithful() -> None:
    """The measured half that is NOT broken: the build before the move and the build
    after the revert score the same, to the digit. Keeps a later fix from being aimed at
    `restore_move`'s `load_xml` round trip, which this build shows is not the cause."""

    data = _load()
    objective = _objective(data["objective"])
    before = objective.score(data["before_move"]["stats"])
    after = objective.score(data["after_revert"]["stats"])
    assert (after.violation, after.value) == (before.violation, before.value)
    assert data["pob_outputs_that_differ"] == 0


def test_fixture_reproduces_the_recorded_move_row() -> None:
    """Guard on the fixture: these are the `refine` row of `loop pass 3` as
    `artifacts/benchmark/20260927-0322-ziz-tpl-main3-s4/results.json` recorded it, so the
    test above fails for the measured reason and not because the fixture drifted."""

    data = _load()
    objective = _objective(data["objective"])
    recorded = data["recorded_move_row"]
    carried = data["score_the_loop_carried_in"]
    after = objective.score(data["after_revert"]["stats"])
    assert carried["value"] == pytest.approx(recorded["before"], rel=1e-9)
    assert carried["violation"] == pytest.approx(recorded["violation_before"], abs=1e-9)
    assert after.value == pytest.approx(recorded["after"], rel=1e-9)
    assert after.violation == pytest.approx(recorded["violation_after"], abs=1e-9)
