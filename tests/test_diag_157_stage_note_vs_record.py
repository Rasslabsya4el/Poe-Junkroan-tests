"""#157: the note of `tree rebuilt on gear` and the stage record disagree on the violation.

One state, two code paths:

* the stage record -- `BuildPipeline._record`, `src/junkroan/optimizer/pipeline.py:249-252`:
  `self.objective.score(self.pob.stats(self.objective.stat_keys))`, the FULL objective;
* the note -- before #170 `BuildPipeline._rebuild_tree` printed `tree.current_score()`, the construction
  objective (`self.objective.without("EffectiveMovementSpeedMod").without_sustain()`); since #170 it reads
  `BuildPipeline._delivered_score`, the record's own number.

On the recorded state of `z327_assassin_poison_spark` s6
(run `20260926-0200-ziz-main3-s4`, recorded final violation 0.1924) the record reads
0.19244 and the note reads 0.000: the whole gap is the `EffectiveMovementSpeedMod >= 1.164`
floor the construction tree drops (PoB reads `EffectiveMovementSpeedMod` 0.940).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline

FIXTURE = Path(__file__).parent / "fixtures" / "diag_157" / "poison_spark_s6_state.json"


def _state():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _full(state) -> Objective:
    return Objective(
        maximize=state["maximize"],
        floors=dict(state["floors"]),
        relations=tuple(tuple(r) for r in state["relations"]),
    )


def test_fixture_reproduces_the_recorded_violation():
    """The stage record's own code path on the fixture state = the number the run recorded."""

    state = _state()
    score = _full(state).score(state["stats"])  # pipeline.py:252
    assert score.violation == pytest.approx(0.1924, abs=5e-5)


def test_stage_note_and_stage_record_agree_on_one_state():
    """#170: the decision of `_rebuild_tree` (and its note) reads `BuildPipeline._delivered_score`, the
    `self.objective.score(...)` that `_record` writes; on the fixture state they are equal to the digit."""

    state = _state()
    stats = state["stats"]
    pob = SimpleNamespace(stats=lambda keys: {k: stats[k] for k in keys if k in stats})
    full = _full(state)

    record = full.score(pob.stats(full.stat_keys))  # `_record`
    decision = BuildPipeline._delivered_score(SimpleNamespace(pob=pob, objective=full))  # what `_rebuild_tree` reads

    assert decision.violation == record.violation
    assert decision.value == record.value
