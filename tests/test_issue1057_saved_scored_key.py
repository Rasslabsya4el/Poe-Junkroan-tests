"""#1057: a saved build result carries the output the objective maximised under its own name.

No PoB: a stub session stands in for the pipeline's two `final_stats` writers; the saved Contagion JSON is read as in #1055."""

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from junkroan.optimizer.build_result import BuildResult
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.search.skeleton import Skeleton

SAVED = (Path(__file__).resolve().parents[1] / "artifacts" / "search-contagion" / "20261015-0336"
         / "01 witch_occultist_no_iron_will_prophecy_wand.json")


class _Pob:
    def __init__(self, values):
        self.values = values

    def stats(self, keys):
        return {k: self.values[k] for k in keys if k in self.values}

    def export_xml(self):
        return "<PathOfBuilding/>"


def _pipeline(maximize: str, values: dict) -> BuildPipeline:
    p = object.__new__(BuildPipeline)
    p.pob = _Pob(values)
    p.judging = SimpleNamespace(objective=None)
    p.objective = Objective(maximize=maximize)
    return p


def _result(stat: str) -> BuildResult:
    return BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Occultist", main_link=["Contagion"]), objective_stat=stat)


@pytest.mark.parametrize("stat", ["TotalDotDPS", "TotalDPS", "FullDPS", "IgniteDPS"])
def test_construction_final_stats_carry_the_maximised_key(stat):
    res = _pipeline(stat, {stat: 1234.5, "CombinedDPS": 99.0})._finish_construction(_result(stat), 0.0)
    assert res.final_stats[stat] == 1234.5
    assert res.final_stats["CombinedDPS"] == 99.0
    assert res.optimistic_stats[stat] == 1234.5


def test_saved_optimistic_names_the_maximised_key_and_combined():
    res = _result("TotalDotDPS")
    res.optimistic_stats = {"TotalDotDPS": 50000.0, "CombinedDPS": 60844.9, "Life": 4000}
    assert res.saved_optimistic() == {"TotalDotDPS": 50000.0, "CombinedDPS": 60844.9}
    res.optimistic_stats = {"CombinedDPS": 7.0}  # key absent: only what exists is saved, never a made-up zero
    assert res.saved_optimistic() == {"CombinedDPS": 7.0}


def test_report_reads_the_key_from_saved_stats_and_old_files_still_fall_back():
    res = _result("TotalDotDPS")
    res.final_stats = {"TotalDotDPS": 37844.0, "Life": 4000}
    res.optimistic_stats = {"TotalDotDPS": 50000.0}
    assert res.scored_number() == 37844.0
    assert "final: TotalDotDPS 37,844 (optimistic 50,000)" in res.summary()
    res.final_stats = {"Life": 4000}  # an old file: no key; the #1055 lookup is the stage's value
    assert res.scored_number() is None


def test_saved_contagion_file_keeps_its_real_number():
    if not SAVED.exists():
        pytest.skip(f"saved Contagion result absent: {SAVED}")
    d = json.loads(SAVED.read_text(encoding="utf-8"))
    assert isinstance(d["optimistic"], (int, float))
