"""#553 unit 4 (D116): the last step before delivery repairs any floor still broken (no PoB).

`_finish` driven on the fake PoB (`_finish_pipeline`). The floor is Life >= 4000 (`FLOORED`). `_finish`'s own repair
after the final lanes runs first and takes the first entry of `repairs`; the entries after it are what the final floor
repair reaches. A feasible build costs no call."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from junkroan.optimizer.pipeline import FINAL_FLOOR_REPAIR_ROUNDS, BuildResult  # noqa: E402

from loop_fakes import _Pob, _Tree, _finish_pipeline, _finish_skeleton  # noqa: E402


def _run(monkeypatch, *, life: float, repairs: list):
    pob = _Pob(1000.0, life=life)
    tree = _Tree(pob, [], repairs=repairs)
    p, _derived, logs = _finish_pipeline(monkeypatch, pob, tree, {})
    sk = _finish_skeleton()
    result = p._finish(BuildResult(skeleton=sk), sk, 0.0)
    final_rounds = [m for m in logs if m.startswith("final floor repair round")]
    return pob, tree, result, logs, final_rounds


def _repair_calls(tree) -> list:
    return [c for c in tree.calls if c[0] == "refine" and c[1] == 0]


def test_a_loop_that_ends_infeasible_is_repaired_by_the_last_step(monkeypatch) -> None:
    # `_finish`'s own repair takes (1000, 3000) and buys nothing; the final repair reaches (900, 4500)
    pob, tree, result, logs, rounds = _run(monkeypatch, life=3000.0, repairs=[(1000.0, 3000.0), (900.0, 4500.0)])

    assert pob.life == 4500.0 and pob.value == 900.0  # violation 0
    assert rounds == ["final floor repair round 1: violation 0.250 -> 0.000 (kept)"]
    assert len(_repair_calls(tree)) == 2  # `_finish`'s own repair, then the final one
    rows = [m for m in result.moves if m["move"] == "final floor repair"]
    assert len(rows) == 1
    assert rows[0]["kept"] is True and rows[0]["violation_before"] == 0.25 and rows[0]["violation_after"] == 0.0
    assert "final feasibility: ok" in logs


def test_a_loop_that_ends_feasible_makes_no_repair_call(monkeypatch) -> None:
    pob, tree, result, logs, rounds = _run(monkeypatch, life=5000.0, repairs=[(900.0, 4500.0)])

    assert rounds == []
    assert tree.calls == []  # not one refine, so no PoB call of its own
    assert [m for m in result.moves if m["move"] == "final floor repair"] == []
    assert pob.life == 5000.0 and pob.value == 1000.0
    assert "final feasibility: ok" in logs


def test_a_repair_that_cannot_help_stops_after_the_first_round(monkeypatch) -> None:
    pob, tree, result, logs, rounds = _run(monkeypatch, life=3000.0, repairs=[])

    assert rounds == ["final floor repair round 1: violation 0.250 -> 0.250 (nothing kept)"]
    assert len(_repair_calls(tree)) == 2  # `_finish`'s own repair + exactly one final round
    rows = [m for m in result.moves if m["move"] == "final floor repair"]
    assert len(rows) == 1 and rows[0]["kept"] is False and rows[0]["reverted_by_judge"] is True
    assert pob.life == 3000.0  # nothing kept: the build is as it was
    assert any(m.startswith("final feasibility: ") and "ok" not in m for m in logs)  # still infeasible, left to the audit


def test_the_rounds_are_bounded(monkeypatch) -> None:
    # every round buys some violation but none reaches the floor: the fifth entry stays unused
    steps = [(1000.0, 1000.0), (1000.0, 1500.0), (1000.0, 2000.0), (1000.0, 2500.0), (1000.0, 3000.0), (1000.0, 3500.0)]
    pob, tree, result, _logs, rounds = _run(monkeypatch, life=1000.0, repairs=list(steps))

    assert FINAL_FLOOR_REPAIR_ROUNDS == 4
    assert len(rounds) == 4 and all(r.endswith("(kept)") for r in rounds)
    assert len(_repair_calls(tree)) == 5  # `_finish`'s own + four final rounds
    assert pob.life == 3000.0 and tree.repairs == [(1000.0, 3500.0)]
    assert len([m for m in result.moves if m["move"] == "final floor repair"]) == 4
