"""#176: the config re-derived after gear pass 1 is its own stage line; the aura line records the levels alone."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.search.skeleton import Skeleton


class _Pob:
    """`state` is what the stats read; `inputs` the config surface."""

    def __init__(self, inputs: dict) -> None:
        self.inputs = dict(inputs)
        self.state = {"CombinedDPS": 70_072.3, "Life": 5000.0}

    def config_inputs(self) -> dict:
        return dict(self.inputs)

    def stats(self, keys):
        return {key: self.state.get(key, 0.0) for key in keys}


def _stage(inputs_before: dict, inputs_after: dict, tune: dict):
    pob = _Pob(inputs_before)
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob = pob
    pipeline.log = lambda message: None

    def rejudge(skeleton):
        pob.inputs = dict(inputs_after)
        if inputs_after != inputs_before:
            pob.state["CombinedDPS"] = 60_032.16

    pipeline.judging = SimpleNamespace(rejudge=rejudge, objective=Objective(maximize="CombinedDPS", floors={"Life": 1.0}))
    pipeline._tune_flat_reservation_aura_levels = lambda skeleton: tune
    result = BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Hierophant", main_link=["Shock Nova"]))
    pipeline._record(result, "gear pass 1 (empty tree)", 0.0)
    pipeline._flat_reservation_stage(result, SimpleNamespace())
    return result.stages


def test_rail_stage_records_before_equal_after_to_the_digit() -> None:
    stages = _stage({"a": 1}, {"a": 1}, {})
    assert [s.name for s in stages] == ["gear pass 1 (empty tree)", "flat-reservation aura levels"]
    assert stages[1].notes == "rail"
    assert (stages[1].score_value, stages[1].violation) == (stages[0].score_value, stages[0].violation)


def test_changed_config_input_gets_its_own_line_with_old_and_new() -> None:
    stages = _stage({"sigilOfPowerStages": 4, "same": True}, {"sigilOfPowerStages": 2, "same": True}, {"Clarity": 14})
    assert [s.name for s in stages] == ["gear pass 1 (empty tree)", "config re-derived (after gear pass 1)", "flat-reservation aura levels"]
    assert stages[1].notes == "sigilOfPowerStages 4 -> 2"
    assert stages[1].score_value == 60_032.16
    assert stages[2].notes == "Clarity 14"
    # the aura line's before is the state after the re-derivation
    assert stages[2].score_value == stages[1].score_value


def test_several_changed_inputs_are_joined_and_no_change_writes_no_line() -> None:
    stages = _stage({"a": 1, "b": False}, {"a": 2, "b": True}, {})
    assert stages[1].notes == "a 1 -> 2, b False -> True"
    assert len(_stage({"a": 1}, {"a": 1}, {"Clarity": 14})) == 2
