"""#1064 unit 1: the repair rule (stop rule and verdict), the repair's loop plan, and the `repair pass N` names.

PoB-free: the stop rule is pure arithmetic; the plan and the names are checked on the loop over the fake PoB of
loop_fakes (the same rig test_issue711_loop_lines.py runs)."""

from __future__ import annotations

import dataclasses

import pytest

from junkroan.optimizer.improvement_loop import LOOP_MOVES, LoopPlan, kick_plan
from junkroan.optimizer.move_ledger import LOOP_WHERE, reentry_rows
from junkroan.optimizer.repair import (
    REPAIR_GAIN_FLOOR, REPAIR_MAX_PASSES, REPAIR_PATIENCE, RepairChoice, RepairOutcome, repair_gains, repair_verdict,
    should_continue, step_gain,
)
from junkroan.optimizer.stage_catalog import STEPS, group_of, loop_move_line, parse_log_line, start_line, step_of

from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over

START = 1000.0


def test_constants_are_the_budget_of_1040():
    assert (REPAIR_GAIN_FLOOR, REPAIR_MAX_PASSES, REPAIR_PATIENCE) == (0.01, 2, 1)


def test_step_gain_is_relative_to_the_value_before_and_guards_zero():
    assert step_gain(1000.0, 1050.0) == pytest.approx(0.05)
    assert step_gain(1000.0, 1005.0) == pytest.approx(0.005)
    assert step_gain(1000.0, 990.0) == pytest.approx(-0.01)
    assert step_gain(0.0, 500.0) == 0.0
    assert step_gain(-3.0, 500.0) == 0.0


def test_gains_are_pass_by_pass_against_the_pass_before():
    assert repair_gains(START, [1050.0, 1071.0]) == pytest.approx([0.05, 1071.0 / 1050.0 - 1.0])


def test_five_then_half_percent_ends_after_pass_two():
    gains = repair_gains(START, [1050.0, 1055.25])
    assert gains[1] == pytest.approx(0.005)
    assert should_continue(gains[:1]) is True  # +5 %: pass 2 runs
    assert should_continue(gains) is False  # +0.5 % after it: the second pass is the last
    assert repair_verdict(START, [1050.0, 1055.25]) == "take"  # not climbing (+0.5 %), last value above start


def test_five_then_half_percent_verdict_follows_the_value_against_start():
    assert repair_verdict(1000.0, [1050.0, 1055.25]) == "take"  # last value 1055.25 >= start 1000
    assert repair_verdict(1100.0, [1050.0, 1055.25]) == "drop"  # last value 1055.25 < start 1100
    assert repair_verdict(1055.25, [1050.0, 1055.25]) == "take"  # equal to the last value counts as take


def test_five_then_two_percent_is_climbing():
    gains = repair_gains(START, [1050.0, 1071.0])
    assert gains[1] == pytest.approx(0.02)
    assert should_continue(gains) is False  # two passes ran: the cap, climbing or not
    assert repair_verdict(START, [1050.0, 1071.0]) == "climbing"
    assert repair_verdict(5000.0, [1050.0, 1071.0]) == "climbing"  # climbing wins over a drop below start


def test_pass_two_at_exactly_the_floor_is_climbing():
    assert repair_verdict(START, [1000.0, 1010.0]) == "climbing"  # +1.0 % over pass 1 >= floor
    assert repair_verdict(START, [1000.0, 1009.9]) == "take"  # +0.99 %: not climbing


def test_half_percent_ends_after_pass_one():
    gains = repair_gains(START, [1005.0])
    assert gains == pytest.approx([0.005])
    assert should_continue(gains) is False  # the first pass under the floor ends the repair (k = 1)
    assert repair_verdict(START, [1005.0]) == "take"
    assert repair_verdict(START, [995.0]) == "drop"  # one pass, value under start


def test_a_drop_ends_the_repair_after_pass_one():
    gains = repair_gains(START, [900.0])
    assert gains[0] < 0
    assert should_continue(gains) is False


def test_the_first_pass_always_runs():
    assert should_continue([]) is True
    assert should_continue([0.05]) is True


def test_a_pass_gain_at_the_floor_does_not_end_the_repair():
    assert should_continue([0.01]) is True  # under the floor is < 1 %; exactly 1 % keeps going


def test_verdict_takes_one_or_two_values_only():
    with pytest.raises(ValueError):
        repair_verdict(START, [])
    with pytest.raises(ValueError):
        repair_verdict(START, [1.0, 1.0, 1.0])


def test_choice_validates_its_direction():
    assert RepairChoice("Chaos Inoculation", "force").direction == "force"
    assert RepairChoice("Mind Over Matter", "forbid").direction == "forbid"
    with pytest.raises(ValueError, match="sideways"):
        RepairChoice("Chaos Inoculation", "sideways")


def test_outcome_is_a_plain_dataclass():
    outcome = RepairOutcome(start=START, values=[1050.0], gains=[0.05], verdict="take", seconds=12.5)
    assert dataclasses.is_dataclass(outcome)
    assert (outcome.start, outcome.values, outcome.gains, outcome.verdict, outcome.seconds) == (START, [1050.0], [0.05], "take", 12.5)


# -- the repair's loop plan ----------------------------------------------------------------------------

def test_loop_plan_repair_fields():
    plan = LoopPlan.repair(seed=7)
    assert plan.kind == "repair"
    assert plan.max_passes == REPAIR_MAX_PASSES == 2
    assert plan.gain_floor == REPAIR_GAIN_FLOOR == 0.01
    assert plan.max_seconds is None  # no time limit
    assert plan.kick_draws == ()  # no kicks
    assert plan.moves is None  # the loop's own moves
    assert (plan.local_only, plan.opening_lanes, plan.stage_name) == (False, False, None)
    assert plan.order == "priced"
    assert plan.seed == 7


def test_loop_plan_repair_runs_no_kicks():
    plan = LoopPlan.repair(seed=7)
    for notes in ([], ["refine +1.0%"]):
        assert kick_plan(notes=notes, stopped="", local_only=False, moves=plan.moves, kick_draws=plan.kick_draws) == []


def test_loop_plan_repair_names_its_passes_and_moves():
    plan = LoopPlan.repair(seed=7)
    assert plan.pass_prefix == "repair"
    assert plan.pass_label(1) == "repair pass 1"
    assert plan.pass_label(2) == "repair pass 2"
    assert loop_move_line(1, "gear", None, prefix=plan.pass_prefix) == "repair pass 1 move gear"
    assert loop_move_line(2, "refine", None) == "loop pass 2 move refine"  # the default prefix is unchanged


def test_other_kinds_keep_the_loop_names_and_plans():
    loop = LoopPlan(seed=1, max_passes=3, max_seconds=None)
    assert loop.pass_prefix == "loop" and loop.pass_label(3) == "loop pass 3"
    assert loop.gain_floor == 0.0 and loop.kick_draws == (3, 4)
    assert kick_plan(notes=[], stopped="", local_only=False, moves=None, kick_draws=loop.kick_draws) == [("kick-tree", 3), ("kick-joint", 4)]
    assert LoopPlan.replay("loop", seed=5, passes=3).pass_label(1) == "loop pass 1"


def test_loop_plan_kinds_accept_repair_and_reject_unknown():
    LoopPlan(seed=1, max_passes=2, max_seconds=None, kind="repair")
    with pytest.raises(ValueError, match="nonsense"):
        LoopPlan(seed=1, max_passes=2, max_seconds=None, kind="nonsense")  # type: ignore[arg-type]


# -- the names: stage catalog and move ledger ----------------------------------------------------------

@pytest.mark.parametrize("name", ["repair pass 1", "repair pass 2", "repair pass 10"])
def test_repair_pass_names_resolve_in_the_catalog(name):
    step = step_of(name)
    assert step is not None and step.name == "repair pass <N>"
    assert group_of(name) == "improvement loop"


def test_repair_pass_is_one_step_next_to_the_loop_pass():
    names = [s.name for s in STEPS]
    assert names.index("repair pass <N>") == names.index("loop pass <N>") + 1
    assert step_of("repair pass") is None  # the number is required
    assert step_of("repair pass x") is None


def test_repair_passes_are_the_loop_own_rows_in_the_ledger():
    assert "repair pass" in LOOP_WHERE
    rows = [
        {"where": "repair pass 1", "move": "gear", "seconds": 2.0},
        {"where": "fixed point check", "move": "gear", "seconds": 3.0},
    ]
    assert reentry_rows(rows) == [rows[1]]  # a repair pass is not a re-entry


def test_repair_moves_reuse_the_loop_move_names():
    assert {"refine", "swaps", "gear", "weapon-base", "picks", "aura levels", "lanes"} <= LOOP_MOVES


# -- the wiring: the loop writes the repair's own start and move lines over the fake PoB ---------------

def test_repair_plan_runs_two_named_passes_and_no_kicks(monkeypatch) -> None:
    logs: list[str] = []
    pob = _Pob(1000.0)
    tree = _Tree(pob, [])
    loot = _Loot(pob, {"Gloves": [("g1", 1020.0)], "Boots": [("b1", 1022.0)]})
    sk = _skeleton({"Boots": "Two-Toned Boots", "Gloves": "Fingerless Silk Gloves"})
    _patch_generator(monkeypatch, [])
    p = loop_over(pob, tree=tree, gear=loot, skeleton=sk, log=logs.append)
    result = p.started()
    outcome = p.run(LoopPlan.repair(seed=1))

    parsed = [parse_log_line(m) for m in logs]
    starts = [v for k, v in parsed if k == "start"]
    assert starts == ["repair pass 1", "repair pass 2"]  # no "loop opening": the repair does not open lanes
    assert 1 <= outcome.passes <= REPAIR_MAX_PASSES
    assert not any(m.startswith("loop pass") for m in logs)
    assert not any("kick" in m for m in logs)
    assert start_line("repair pass 1") in logs
    names = [s.name for s in result.stages]
    assert "repair pass 1" in names and "loop pass 1" not in names


def test_a_pass_that_cleared_a_violation_is_not_under_the_floor():
    assert should_continue([-0.0005], [True]) is True  # -0.05 %: the pass made the build feasible, so a pass 2 runs
    assert should_continue([-0.0005], [False]) is False  # same gain, nothing cleared: ends
    assert should_continue([-0.0005], None) is False  # no flags: today's behaviour


def test_the_cleared_flag_never_lifts_the_cap_of_two_passes():
    assert should_continue([-0.0005, -0.0005], [True, True]) is False
    assert should_continue([-0.0005, 0.02], [True, False]) is False  # two passes ran
    assert should_continue([-0.0005, -0.0005]) is False
