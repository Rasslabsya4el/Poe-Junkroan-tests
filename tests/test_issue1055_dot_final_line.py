"""#1055: the `final:` line and the `Numbers:` line print the output the objective maximised, with its real number.

The saved Contagion result (dot mode) kept no TotalDotDPS key in `final`, so both lines read 0 / None.
No PoB: the saved JSON is read, the synthetic fixtures are small hand-built results."""

import json
from pathlib import Path

import pytest

from junkroan.optimizer.build_result import BuildResult, StageRecord
from junkroan.optimizer.explain import explain
from junkroan.optimizer.objective_select import maximized_stat
from junkroan.search.skeleton import Skeleton

SAVED = (Path(__file__).resolve().parents[1] / "artifacts" / "search-contagion" / "20261015-0336"
         / "01 witch_occultist_no_iron_will_prophecy_wand.json")


def _saved_result() -> BuildResult:
    if not SAVED.exists():
        pytest.skip(f"saved Contagion result absent: {SAVED}")
    d = json.loads(SAVED.read_text(encoding="utf-8"))
    sk = Skeleton.from_json(d["skeleton"])
    res = BuildResult(skeleton=sk, objective_stat=maximized_stat(sk.main_link[0], sk.mode))
    res.final_stats = dict(d["final"])
    res.optimistic_stats = {"CombinedDPS": d["optimistic"]}  # the saved file keeps only the conditional CombinedDPS
    res.stages = [StageRecord(name=s["name"], seconds=s["seconds"], stats={}, score_value=s["value"], violation=s["violation"], notes=s.get("notes", ""))
                  for s in d["stages"]]
    res.config_reasons = dict(d.get("config_reasons") or {})
    res.keystones = list(d.get("keystones") or [])
    return res


def _final_line(res: BuildResult) -> str:
    return [ln for ln in res.summary().splitlines() if ln.startswith("  final:")][0]


def _numbers_line(res: BuildResult) -> str:
    return [ln for ln in explain(res).splitlines() if ln.startswith("- Numbers:")][0]


def test_saved_dot_result_names_tdotdps_and_prints_its_real_number():
    res = _saved_result()
    assert res.scored_stat == "TotalDotDPS"
    ln = _final_line(res)
    assert ln.startswith("  final: TotalDotDPS 37,844 (optimistic ")
    assert "TotalDotDPS 0 " not in ln and "TotalDotDPS None" not in ln


def test_saved_dot_result_numbers_line_carries_the_number_not_none():
    ln = _numbers_line(_saved_result())
    assert ln.startswith("- Numbers: TotalDotDPS 37,844 conservative;")
    assert "None" not in ln.split(";")[0]


def _fixture(stat: str, final: dict, optimistic: dict, stages: list | None = None) -> BuildResult:
    res = BuildResult(skeleton=Skeleton(class_name="Witch", ascendancy="Occultist", main_link=["Contagion"]), objective_stat=stat)
    res.final_stats = final
    res.optimistic_stats = optimistic
    res.stages = stages or []
    return res


_BASE = {"Life": 4000, "PhysicalMaximumHitTaken": 5000, "FireMaximumHitTaken": 5200, "ColdMaximumHitTaken": 5100, "LightningMaximumHitTaken": 5300,
         "TotalEHP": 9000, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "ChaosResist": 0, "Str": 100, "Dex": 150, "Int": 200,
         "ReqStr": 0, "ReqDex": 0, "ReqInt": 0, "EffectiveMovementSpeedMod": 1.25}
_TAIL = " life 4000 max hit 5,000 ehp 9,000 res 75/75/75/0 attr 100/150/200 req 0/0/0 ms 1.25"


@pytest.mark.parametrize("stat, value, opt, expected", [
    ("TotalDPS", 81234.4, 120000.0, "  final: TotalDPS 81,234 (optimistic 120,000)" + _TAIL),
    ("IgniteDPS", 12345.6, 15000.0, "  final: IgniteDPS 12,346 (optimistic 15,000)" + _TAIL),
    ("TotalPoisonDPS", 23456.7, 30000.0, "  final: TotalPoisonDPS 23,457 (optimistic 30,000)" + _TAIL),
    ("BleedDPS", 9876.4, 12000.0, "  final: BleedDPS 9,876 (optimistic 12,000)" + _TAIL),
])
def test_hit_ignite_poison_bleed_final_lines_are_unchanged(stat, value, opt, expected):
    final = {**_BASE, "CombinedDPS": value, stat: value}
    assert _final_line(_fixture(stat, final, {stat: opt})) == expected


def test_minion_final_line_is_unchanged():
    final = {**_BASE, "CombinedDPS": 0, "FullDPS": 53095.277}
    res = _fixture("FullDPS", final, {"CombinedDPS": 0, "FullDPS": 104509.0})
    assert _final_line(res) == "  final: FullDPS 53,095 (optimistic 104,509)" + _TAIL


def test_dot_final_line_reads_the_key_when_final_holds_it():
    final = {**_BASE, "CombinedDPS": 37844.14, "TotalDotDPS": 37844.14}
    assert _final_line(_fixture("TotalDotDPS", final, {"TotalDotDPS": 60844.9})).startswith("  final: TotalDotDPS 37,844 (optimistic 60,845)")


def test_dot_without_its_key_and_without_stages_prints_n_a_not_zero():
    res = _fixture("TotalDotDPS", {**_BASE, "CombinedDPS": 37844.14}, {})
    ln = _final_line(res)
    assert ln.startswith("  final: TotalDotDPS n/a (optimistic n/a)")
    assert "TotalDotDPS 0" not in ln
    assert "- Numbers: TotalDotDPS n/a conservative" in explain(res)


def test_dot_without_its_key_takes_the_last_stage_score():
    stage = StageRecord(name="config (final lanes)", seconds=1.0, stats={}, score_value=37844.14, violation=0.0)
    res = _fixture("TotalDotDPS", {**_BASE, "CombinedDPS": 37844.14}, {}, stages=[stage])
    assert _final_line(res).startswith("  final: TotalDotDPS 37,844 (optimistic n/a)")
