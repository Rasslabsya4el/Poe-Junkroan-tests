"""#51 unit 1: BuildResult / StageRecord / the stage writers live in build_result.py, pipeline.py re-exports them."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from junkroan.optimizer import build_result, pipeline


class _Score:
    def __init__(self, value: float, violation: float = 0.0) -> None:
        self.value, self.violation = value, violation


class _Objective:
    stat_keys = ("CombinedDPS",)

    def __init__(self, value: float) -> None:
        self.value = value

    def score(self, full):
        return _Score(self.value)

    def derived_values(self, full):
        return {"Derived": 1.0}


class _Pob:
    def stats(self, keys):
        return {k: 1.0 for k in keys}


def _result() -> build_result.BuildResult:
    skeleton = SimpleNamespace(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball"])
    return build_result.BuildResult(skeleton=skeleton)


def test_pipeline_reexports_the_same_classes() -> None:
    assert pipeline.BuildResult is build_result.BuildResult
    assert pipeline.StageRecord is build_result.StageRecord
    assert pipeline.REPORT_KEYS is build_result.REPORT_KEYS


def test_record_stage_appends_and_logs_the_delta() -> None:
    result, lines = _result(), []
    build_result.record_stage(_Pob(), _Objective(100.0), result, "a", time.perf_counter(), "", lines.append)
    build_result.record_stage(_Pob(), _Objective(110.0), result, "b", time.perf_counter(), "n", lines.append)
    assert [s.name for s in result.stages] == ["a", "b"]
    assert result.stages[1].score_value == 110.0 and result.stages[1].stats["Derived"] == 1.0
    assert lines[1].endswith("[+10.0% vs a]") and "[" not in lines[0].split("viol")[-1]


def test_record_stage_refuses_a_moved_no_change() -> None:
    result = _result()
    build_result.record_stage(_Pob(), _Objective(100.0), result, "a", time.perf_counter(), "", lambda _m: None)
    with pytest.raises(RuntimeError, match="no change"):
        build_result.record_stage(_Pob(), _Objective(150.0), result, "b", time.perf_counter(), "no change", lambda _m: None)


def test_take_picks_copies_each_pick() -> None:
    result = _result()
    gen = SimpleNamespace(picks=[SimpleNamespace(what="support", choice="X", score=_Score(5.0), seconds=0.5)])
    build_result.take_picks(result, gen, before=1.0)
    assert result.picks == [{"what": "support", "choice": "X", "value": 5.0, "before": 1.0, "seconds": 0.5}]
