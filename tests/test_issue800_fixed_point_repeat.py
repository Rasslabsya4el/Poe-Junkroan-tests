"""#800: the delivered build is a fixed point of the extra pass (no PoB).

`_fixed_point_check` repeats the extra pass until one keeps nothing, at most FIXED_POINT_MAX_EXTRA_PASSES times and inside
the check's time budget. A move a pass keeps stays in the build; `fixed_point_gain` / `fixed_point_note` are the LAST
pass's (what the delivered build still found); the warning / error line (1 % boundary) is raised only when the limit,
not a clean pass, ended the repeats, and it names the limit.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent))

from junkroan.optimizer.improvement_loop import FIXED_POINT_MAX_EXTRA_PASSES, FIXED_POINT_SEED_OFFSET  # noqa: E402
from junkroan.optimizer.seeds import PURPOSE_JOINT_FILL_SLOT, derive_seed  # noqa: E402

import junkroan.optimizer.pipeline as pipeline_module  # noqa: E402
from loop_fakes import _Loot, _Pob, _Tree, _skeleton  # noqa: E402
from test_improvement_loop import _pipeline, _started  # noqa: E402


def _check(pob, tree, loot, calls, *, max_seconds=600.0, p=None):
    p = p or _pipeline(pob, [], calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)
    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=max_seconds)
    return result, findings


def _passes(result) -> list:
    return [s for s in result.stages if s.name == "fixed point check"]


def test_the_extra_pass_repeats_while_a_pass_keeps_a_move_and_the_build_holds_every_move() -> None:
    """Pass 1 keeps the tree refine (+1 %), pass 2 the Boots roll (+2 %), pass 3 keeps nothing: three passes, the build holds
    both moves, and the check reports the fixed point (on main one pass ran and the +1 % went out as the finding)."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1010.0], calls=calls)
    loot = _Loot(pob, {"Boots": [("b0", 1010.0), ("b1", 1030.2)]}, calls=calls)  # the first roll equals the incumbent: no gain in pass 1

    result, findings = _check(pob, tree, loot, calls)

    assert len(_passes(result)) == 3 and [c[0] for c in calls].count("fill_slot") == 3
    assert [s.notes for s in _passes(result)] == ["refine +1.0%", "Boots +2.0%", "no change"]
    assert pob.value == 1030.2 and loot.current_raw == {"Boots": "b1"}, "both moves stay in the delivered build"
    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == "kept nothing"
    assert result.fixed_point_moved and result.fixed_point_passes == 3
    assert findings == []


def test_a_landscape_that_never_settles_gets_exactly_three_extra_passes_and_the_finding_names_the_limit() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    values = [1000.0 * 1.008 ** k for k in range(1, 7)]  # +0.8 % a pass, as many as anyone could ask for
    tree = _Tree(pob, values, calls=calls)
    loot = _Loot(pob, {}, calls=calls)

    result, findings = _check(pob, tree, loot, calls)

    assert FIXED_POINT_MAX_EXTRA_PASSES == 3
    assert len(_passes(result)) == 3 and result.fixed_point_passes == 3
    assert pob.value == values[2], "three passes kept, the fourth never ran"
    assert abs(result.fixed_point_gain - 0.008) < 1e-9 and result.fixed_point_note == "refine +0.8%"
    assert [(f.severity, f.check) for f in findings] == [("warning", "fixed point")]
    assert findings[0].detail == ("the loop was not at a fixed point: one more pass gained +0.8% (refine +0.8%); "
                                  "the limit of 3 extra passes ended the repeats")
    # every repeat rolls its own gear (no pass re-rolls what the pass before it rolled)
    seeds = [c[5] for c in calls if c[0] == "fill_slot"]
    assert seeds == [derive_seed(1 + k * FIXED_POINT_SEED_OFFSET, PURPOSE_JOINT_FILL_SLOT, 1, 0) for k in (1, 2, 3)]


def test_a_gain_over_one_percent_on_the_last_pass_is_still_an_error() -> None:
    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1000.0 * 1.02 ** k for k in range(1, 6)], calls=calls)

    result, findings = _check(pob, tree, _Loot(pob, {}, calls=calls), calls)

    assert [(f.severity, f.check) for f in findings] == [("error", "fixed point")]
    assert "gained +2.0%" in findings[0].detail and findings[0].detail.endswith("the limit of 3 extra passes ended the repeats")


def _clocked(monkeypatch, p, seconds_per_pass: float):
    """The pipeline's `time` is a fake clock that every extra pass advances by `seconds_per_pass`; the plans handed to `improve` are recorded."""

    now = [0.0]
    monkeypatch.setattr(pipeline_module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    plans: list = []
    real = p.improve

    def improve(build, result, plan):
        plans.append(plan)
        out = real(build, result, plan)
        now[0] += seconds_per_pass
        return out

    p.improve = improve
    return plans


def test_a_repeat_gets_what_is_left_of_the_time_budget_and_no_pass_runs_when_none_is_left(monkeypatch) -> None:
    pob = _Pob(1000.0)
    calls: list = []
    p = _pipeline(pob, [], calls=calls)
    plans = _clocked(monkeypatch, p, 100.0)
    tree = _Tree(pob, [1000.0 * 1.008 ** k for k in range(1, 7)], calls=calls)

    result, findings = _check(pob, tree, _Loot(pob, {}, calls=calls), calls, max_seconds=150.0, p=p)

    # pass 1 has the whole 150 s; pass 2 what is left after 100 s; at 200 s the budget is spent: no third pass
    assert [pl.max_seconds for pl in plans] == [150.0, 50.0]
    assert len(_passes(result)) == 2 and result.fixed_point_passes == 2
    assert [(f.severity, f.check) for f in findings] == [("warning", "fixed point")]
    assert findings[0].detail == ("the loop was not at a fixed point: one more pass gained +0.8% (refine +0.8%); "
                                  "the time budget ended the repeats after 2 extra passes")


def test_without_a_time_budget_the_repeats_run_to_the_pass_limit(monkeypatch) -> None:
    pob = _Pob(1000.0)
    calls: list = []
    p = _pipeline(pob, [], calls=calls)
    plans = _clocked(monkeypatch, p, 10_000.0)
    tree = _Tree(pob, [1000.0 * 1.008 ** k for k in range(1, 7)], calls=calls)

    result, findings = _check(pob, tree, _Loot(pob, {}, calls=calls), calls, max_seconds=None, p=p)

    assert [pl.max_seconds for pl in plans] == [None, None, None]
    assert findings[0].detail.endswith("the limit of 3 extra passes ended the repeats")


def test_a_first_pass_that_keeps_nothing_is_the_only_pass() -> None:
    """Identical to the check before #800: one pass, the seed offset once, no finding, "kept nothing"."""

    pob = _Pob(1000.0)
    calls: list = []
    tree = _Tree(pob, [1001.0], calls=calls)  # +0.1 %, below min_gain
    loot = _Loot(pob, {"Boots": [("b1", 1002.0)]}, calls=calls)

    result, findings = _check(pob, tree, loot, calls)

    assert [s.name for s in result.stages] == ["tree rebuilt on gear", "fixed point check"]
    assert result.stages[-1].notes == "no change" and [c[0] for c in calls].count("fill_slot") == 1
    assert [c[5] for c in calls if c[0] == "fill_slot"] == [derive_seed(1 + FIXED_POINT_SEED_OFFSET, PURPOSE_JOINT_FILL_SLOT, 1, 0)]
    assert result.fixed_point_gain == 0.0 and result.fixed_point_note == "kept nothing"
    assert not result.fixed_point_moved and result.fixed_point_passes == 1
    assert findings == [] and pob.value == 1000.0
