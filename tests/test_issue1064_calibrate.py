"""#1064 unit 3: scripts/repair_calibrate.py, PoB-free.

Pair discovery runs on a fixture folder built in tmp_path (plain parents, `-no-` and `-with-` variants, row JSON);
verdicts (agree, missed take, false take, uncounted, climbing) on hand-made values; the repair call on a fake pipeline
standing in for `BuildPipeline.repair`; the report on rows built here (human durations, the compute row). No PobSession."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import repair_calibrate as rc  # noqa: E402
from junkroan.optimizer.repair import RepairChoice, RepairOutcome, repair_gains, repair_verdict  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402


def _write_row(run: Path, stem: str, *, ours: float, seconds: float, variant: str = "", slug: str = "alpha", seed: int = 4) -> None:
    rows = run / "rows"
    rows.mkdir(parents=True, exist_ok=True)
    (rows / f"{stem}.json").write_text(json.dumps({"ok": True, "slug": slug, "seed": seed, "variant": variant, "ours": ours,
                                                   "seconds": seconds, "stat": "CombinedDPS", "gear_mode": "wishlist"}), encoding="utf-8")
    (run / f"{stem}.pob.txt").write_text("eNpzdummy", encoding="utf-8")


@pytest.fixture()
def gate_run(tmp_path: Path) -> Path:
    """alpha: plain 1000, no foo_bar 1200 (take, counted), with baz 500 (drop, counted);
    beta: plain 1000, no qux 990 (ratio 0.99, uncounted); gamma: plain 1000, no zed 300 (drop, counted)."""

    run = tmp_path / "run"
    _write_row(run, "alpha-s4", ours=1000.0, seconds=100.0, slug="alpha")
    _write_row(run, "alpha-s4-no-foo_bar", ours=1200.0, seconds=300.0, variant="no Foo Bar", slug="alpha")
    _write_row(run, "alpha-s4-with-baz", ours=500.0, seconds=200.0, variant="with Baz", slug="alpha")
    _write_row(run, "beta-s5", ours=1000.0, seconds=100.0, slug="beta", seed=5)
    _write_row(run, "beta-s5-no-qux", ours=990.0, seconds=50.0, variant="no Qux", slug="beta", seed=5)
    _write_row(run, "gamma-s6", ours=1000.0, seconds=100.0, slug="gamma", seed=6)
    _write_row(run, "gamma-s6-no-zed", ours=300.0, seconds=80.0, variant="no Zed", slug="gamma", seed=6)
    return run


def _pair(name: str, direction: str = "forbid", keystone: str = "Foo Bar", run: Path | None = None) -> rc.Pair:
    run = run or Path("unused")
    return rc.Pair(parent_row=run / "rows" / "alpha-s4.json", variant_row=run / "rows" / f"{name}.json", keystone=keystone, direction=direction)


def test_stem_parsing_reads_plain_no_and_with_variants():
    assert rc.parse_stem("alpha-s4") == ("alpha", "4", None, None)
    assert rc.parse_stem("absolution_minions-s12-no-mind_over_matter") == ("absolution_minions", "12", "no", "mind_over_matter")
    assert rc.parse_stem("spark-s4-with-chaos_inoculation") == ("spark", "4", "with", "chaos_inoculation")
    assert rc.parse_stem("notabuild") is None


def test_discovery_forbid_pairs_each_plain_parent_with_its_no_variants(gate_run: Path):
    pairs = rc.discover_pairs(gate_run, "forbid")
    assert [pair.name for pair in pairs] == ["alpha-s4-no-foo_bar", "beta-s5-no-qux", "gamma-s6-no-zed"]
    assert [pair.keystone for pair in pairs] == ["Foo Bar", "Qux", "Zed"]
    assert pairs[0].parent_row == gate_run / "rows" / "alpha-s4.json"
    assert pairs[0].parent_pob == gate_run / "alpha-s4.pob.txt"
    assert all(pair.direction == "forbid" for pair in pairs)


def test_discovery_force_takes_only_with_variants(gate_run: Path):
    pairs = rc.discover_pairs(gate_run, "force")
    assert [pair.name for pair in pairs] == ["alpha-s4-with-baz"]
    assert pairs[0].keystone == "Baz"
    assert pairs[0].direction == "force"


def test_discovery_skips_a_variant_without_its_plain_parent(tmp_path: Path):
    run = tmp_path / "run"
    _write_row(run, "orphan-s7-no-thing", ours=1.0, seconds=1.0, variant="no Thing", slug="orphan", seed=7)
    assert rc.discover_pairs(run, "forbid") == []


def test_keystone_name_falls_back_to_the_stem_when_the_row_has_no_variant(tmp_path: Path):
    run = tmp_path / "run"
    _write_row(run, "alpha-s4", ours=1000.0, seconds=1.0)
    _write_row(run, "alpha-s4-no-mind_over_matter", ours=900.0, seconds=1.0, variant="")
    assert rc.discover_pairs(run, "forbid")[0].keystone == "mind over matter"


def test_list_triples_parse_windows_drive_letters_and_keystones_with_spaces():
    text = "C:/run/rows/alpha-s4.json:C:/run/rows/alpha-s4-no-x.json:Chaos Inoculation;D:/run2/rows/b.json:D:/run2/rows/b-with-y.json:Blood Magic"
    pairs = rc.parse_pairs_list(text, "forbid")
    assert pairs[0].parent_row == Path("C:/run/rows/alpha-s4.json")
    assert pairs[0].variant_row == Path("C:/run/rows/alpha-s4-no-x.json")
    assert pairs[0].keystone == "Chaos Inoculation"
    assert pairs[1].variant_row == Path("D:/run2/rows/b-with-y.json")
    assert pairs[1].keystone == "Blood Magic"
    with pytest.raises(ValueError):
        rc.parse_pairs_list("just-one-field", "force")
    with pytest.raises(ValueError):
        rc.parse_pairs_list("a.json:b.json:K", "sideways")


def test_recorded_verdict_takes_drops_and_the_uncounted_band():
    parent = {"ours": 1000.0}
    assert rc.recorded_of(parent, {"ours": 1200.0, "seconds": 300.0}) == rc.Recorded(1000.0, 1200.0, 300.0, 1.2, "take", True)
    drop = rc.recorded_of(parent, {"ours": 500.0, "seconds": 200.0})
    assert (drop.recorded_verdict, drop.counted) == ("drop", True)
    uncounted = rc.recorded_of(parent, {"ours": 990.0, "seconds": 50.0})
    assert (uncounted.recorded_verdict, uncounted.counted) == ("drop", False)
    assert rc.recorded_of(parent, {"ours": 1050.0, "seconds": 1.0}).counted is False  # 1.05 is inside the band
    assert rc.recorded_of(parent, {"ours": 1051.0, "seconds": 1.0}).counted is True
    missing = rc.recorded_of(parent, {"seconds": 1.0})
    assert (missing.ratio, missing.recorded_verdict, missing.counted) == (None, None, False)


def test_agreement_kinds():
    assert rc.agreement("take", "take", True) == "yes"
    assert rc.agreement("drop", "drop", True) == "yes"
    assert rc.agreement("drop", "take", True) == "no: missed take"
    assert rc.agreement("take", "drop", True) == "no: false take"
    assert rc.agreement("climbing", "drop", True) == "climbing"
    assert rc.agreement("drop", "take", False) == "not counted"
    assert rc.agreement("take", None, False) == "not counted"


class FakePipeline:
    """Stands in for `BuildPipeline.repair`: a start of 1000 and the given value after each pass."""

    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.calls: list[tuple[object, object, RepairChoice]] = []

    def repair(self, working, result, choice):
        self.calls.append((working, result, choice))
        start = 1000.0
        return RepairOutcome(start=start, values=list(self.values), gains=repair_gains(start, self.values),
                             verdict=repair_verdict(start, self.values), seconds=0.0)


def test_repair_with_hands_the_choice_to_the_pipeline_and_returns_its_values():
    pair = _pair("alpha-s4-no-foo_bar", keystone="Foo Bar")
    fake = FakePipeline([1050.0, 1071.0])
    out = rc.repair_with(fake, "working", "result", pair)
    assert fake.calls[0][2] == RepairChoice("Foo Bar", "forbid")
    assert fake.calls[0][:2] == ("working", "result")
    assert out["ok"] and out["verdict"] == "climbing"
    assert out["start"] == 1000.0 and out["values"] == [1050.0, 1071.0]
    assert out["gains"] == pytest.approx([0.05, 1071.0 / 1050.0 - 1.0])
    assert out["seconds"] >= 0.0


def test_repair_with_force_direction_and_a_take_verdict():
    pair = _pair("alpha-s4-with-baz", direction="force", keystone="Baz")
    fake = FakePipeline([1050.0, 1055.0])
    out = rc.repair_with(fake, None, None, pair)
    assert fake.calls[0][2] == RepairChoice("Baz", "force")
    assert out["verdict"] == "take"


class _FakeResult:
    def summary(self) -> str:
        return "stage rows\n  repair pass 0: forbid Foo Bar: 3 points freed, 0 spent\n  loop pass 1"


def test_repair_with_carries_the_result_summary_as_a_trace():
    out = rc.repair_with(FakePipeline([1050.0]), None, _FakeResult(), _pair("alpha-s4-no-foo_bar", keystone="Foo Bar"))
    assert "repair pass 0: forbid Foo Bar: 3 points freed, 0 spent" in out["trace"]
    assert rc.repair_with(FakePipeline([1050.0]), None, None, _pair("x")).get("trace") == ""


def test_trace_text_names_the_pair_and_the_log_lines():
    text = rc.trace_text("alpha-s4-no-foo_bar", {"trace": "stage rows", "log": ["a line", "b line"]})
    assert text.splitlines()[0].startswith("=== alpha-s4-no-foo_bar")
    assert "stage rows" in text and "a line" in text and "b line" in text


def test_trace_text_lists_every_move_entry_with_its_values_and_the_start():
    repair = {"trace": "rows", "start": 1000.0, "values": [990.0, 1100.0],
              "moves": [{"pass": 1, "where": "slot 3", "move": "gear", "before": 1000.0, "after": 990.0, "kept": False}]}
    text = rc.trace_text("alpha", repair)
    assert "start 1,000" in text and "990" in text
    assert "pass 1" in text and "gear" in text and "slot 3" in text and "1,000 -> 990" in text and "kept=False" in text


def _outcome(verdict: str, values: list[float], seconds: float) -> dict:
    return {"ok": True, "start": 1000.0, "values": values, "gains": repair_gains(1000.0, values), "verdict": verdict, "seconds": seconds}


def test_calibrate_fixture_forbid_counts_misses_uncounted_and_compute(gate_run: Path):
    pairs = rc.discover_pairs(gate_run, "forbid")
    results = {
        "alpha-s4-no-foo_bar": _outcome("drop", [900.0], 30.0),  # recorded take (1.2x): a missed take
        "beta-s5-no-qux": _outcome("take", [1010.0], 20.0),  # uncounted (0.99x)
        "gamma-s6-no-zed": _outcome("take", [1000.0], 10.0),  # recorded drop (0.3x): a false take
    }
    rows = rc.calibrate(pairs, workers=1, repair=lambda pair: results[pair.name])
    by_name = {row["pair"]: row for row in rows}
    assert by_name["alpha-s4-no-foo_bar"]["agree"] == "no: missed take"
    assert by_name["gamma-s6-no-zed"]["agree"] == "no: false take"
    assert by_name["beta-s5-no-qux"]["agree"] == "not counted"
    summary = rc.summarize(rows)
    assert (summary["missed_takes"], summary["false_takes"], summary["climbing"], summary["counted"]) == (1, 1, 0, 2)
    assert [row["pair"] for row in summary["uncounted"]] == ["beta-s5-no-qux"]
    # compute: repair 30 + 10 s over the counted pairs; recorded full 300 + 80 s
    assert summary["repair_side"] == pytest.approx(40.0)
    assert summary["full_side"] == pytest.approx(380.0)


def test_calibrate_climbing_agrees_and_adds_the_recorded_full_time(gate_run: Path):
    pairs = rc.discover_pairs(gate_run, "forbid")
    results = {
        "alpha-s4-no-foo_bar": _outcome("climbing", [1050.0, 1080.0], 30.0),  # climbing: agreeing, not a miss
        "beta-s5-no-qux": _outcome("drop", [900.0], 5.0),
        "gamma-s6-no-zed": _outcome("drop", [900.0], 10.0),  # recorded drop: agrees
    }
    rows = rc.calibrate(pairs, workers=1, repair=lambda pair: results[pair.name])
    by_name = {row["pair"]: row for row in rows}
    assert by_name["alpha-s4-no-foo_bar"]["agree"] == "climbing"
    summary = rc.summarize(rows)
    assert summary["climbing"] == 1 and summary["missed_takes"] == 0 and summary["false_takes"] == 0
    # repair side: 30 + 10 (own) + the climbing pair's recorded 300; full side: 300 + 80
    assert summary["repair_side"] == pytest.approx(340.0)
    assert summary["full_side"] == pytest.approx(380.0)


def test_calibrate_names_a_pair_without_its_row_and_a_failed_repair(gate_run: Path, tmp_path: Path):
    (gate_run / "rows" / "gamma-s6-no-zed.json").unlink()
    pairs = rc.discover_pairs(gate_run, "forbid")
    rows = rc.calibrate(pairs, workers=1, repair=lambda pair: {"ok": False, "error": "RuntimeError: boom", "seconds": 1.0})
    by_name = {row["pair"]: row for row in rows}
    assert by_name["gamma-s6-no-zed"]["ok"] is False and "no variant row" in by_name["gamma-s6-no-zed"]["error"]
    assert by_name["alpha-s4-no-foo_bar"]["error"] == "RuntimeError: boom"
    assert rc.summarize(rows)["counted"] == 0


def test_report_renders_human_durations_verdicts_and_the_compute_row(gate_run: Path):
    pairs = rc.discover_pairs(gate_run, "forbid")
    results = {
        "alpha-s4-no-foo_bar": _outcome("drop", [900.0], 30.0),
        "beta-s5-no-qux": _outcome("take", [1010.0], 20.0),
        "gamma-s6-no-zed": _outcome("take", [1000.0], 10.0),
    }
    rows = rc.calibrate(pairs, workers=1, repair=lambda pair: results[pair.name])
    text = rc.render_report(rows, stamp="20261015-1200-gate", direction="forbid", workers=2, seconds=7200.0)
    assert "# Repair calibration (#1064)" in text
    assert "Misses: missed takes 1 / false takes 1, over 2 counted pairs." in text
    assert "Climbing: 0 pair(s)" in text
    assert "beta-s5-no-qux (ratio 0.990)" in text
    assert "| alpha-s4-no-foo_bar | forbid | 1,000 | 900 | -10.00% | drop | take (ratio 1.200) | no: missed take |" in text
    assert "## Compute (forbid)" in text
    assert "Ratio repair / recorded full: 0.105" in text
    # durations in words, never bare seconds: 300 s reads as 5 min, 380 s as 6.3 min
    assert human_duration(300.0) == "5 min"
    assert f"| recorded full time over the same 2 counted pairs | {human_duration(380.0)} |" in text
    assert "| recorded full time over the same" in text
    # no bare count of seconds in the markdown (seconds are shown only under ~90 s, by human_duration)
    assert not re.search(r"\b\d{3,}\s?s\b", text)
    assert "| 30 s |" in text
    assert "2 h" in text  # the wall time of 7200 s


def test_report_says_not_met_above_the_bar(tmp_path: Path):
    run = tmp_path / "run"
    _write_row(run, "alpha-s4", ours=1000.0, seconds=1.0)
    _write_row(run, "alpha-s4-no-foo_bar", ours=500.0, seconds=60.0, variant="no Foo Bar")
    rows = rc.calibrate(rc.discover_pairs(run, "forbid"), workers=1, repair=lambda pair: _outcome("drop", [400.0], 3600.0))
    text = rc.render_report(rows, stamp="s", direction="forbid", workers=1, seconds=3600.0)
    assert "not met" in text
    assert human_duration(3600.0) == "60 min"
    assert "| repair time (+ recorded full time of climbing pairs) | 60 min |" in text


def test_report_lists_a_failed_pair_with_its_error(tmp_path: Path):
    run = tmp_path / "run"
    _write_row(run, "alpha-s4", ours=1000.0, seconds=1.0)
    _write_row(run, "alpha-s4-no-foo_bar", ours=500.0, seconds=60.0, variant="no Foo Bar")
    rows = rc.calibrate(rc.discover_pairs(run, "forbid"), workers=1,
                        repair=lambda pair: {"ok": False, "error": "RuntimeError: no PoB here", "seconds": 0.0})
    text = rc.render_report(rows, stamp="s", direction="forbid", workers=1, seconds=0.0)
    assert "Not repaired: alpha-s4-no-foo_bar: RuntimeError: no PoB here." in text
    assert "not repaired: RuntimeError: no PoB here" in text
