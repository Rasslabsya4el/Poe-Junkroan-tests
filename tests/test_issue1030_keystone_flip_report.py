"""#1030 unit 3: `scripts/keystone_flip_report.py` joins the parse JSON and the flip JSONs into a markdown table.

Small fixture dicts that mirror `keystone_parse` rows and `keystone_flip` JSON (3 keystones, 2 builds: spark has a
pob_refused row, smite has a remove flip and a row with p None). No PoB runs here."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import keystone_flip_report as rep  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

DELTAS = {
    "CombinedDPS": -10.0,
    "Life": -99.9,
    "EnergyShield": None,
    "Mana": 0.0,
    "ManaUnreserved": 12.5,
    "TotalEHP": -50.0,
    "PhysicalMaximumHitTaken": None,
    "ChaosResist": None,
    "objective": -10.0,
}


def _numbers(life: float, mana_unreserved: float = 400) -> dict:
    return {
        "CombinedDPS": 5000.0,
        "Life": life,
        "EnergyShield": 0,
        "Mana": 900,
        "ManaUnreserved": mana_unreserved,
        "TotalEHP": 20000.0,
        "PhysicalMaximumHitTaken": 1500,
        "ChaosResist": -60,
        "objective": 5000.0,
        "objective_stat": "CombinedDPS",
        "violation": 0.0,
        "violations": {},
        "priced": 4800.0,
    }


def _share(count: float, value: float, n: int) -> dict:
    return {"n": n, "n_collapsed": round(count * n), "share_count": count, "value_total": 100.0, "value_collapsed": 100.0 * value, "share_value": value, "collapsed": []}


def _row(name, node_id, flip, status, *, seconds, state2=None, priced_none=False, reason=None, skill_dead=False):
    if status == "pob_refused":
        return {"keystone": name, "node_id": node_id, "flip": flip, "status": status, "reason": reason, "seconds": seconds,
                "state1": _numbers(4000), "state2": None, "delta_pct": None, "collapsed": None}
    numbers2 = dict(state2 or _numbers(1))
    collapsed = {"value": {"nodes": _share(0.5, 0.25, 6), "lines": _share(0.25, 0.1, 4)},
                 "priced": None if priced_none else {"nodes": _share(0.4, 0.2, 5), "lines": _share(0.0, 0.0, 4)}}
    row = {"keystone": name, "node_id": node_id, "flip": flip, "status": status, "reason": reason, "seconds": seconds,
           "state1": _numbers(4000), "state2": numbers2, "delta_pct": dict(DELTAS), "collapsed": collapsed}
    if skill_dead:
        row["status"], row["reason"], row["collapsed"] = "skill_dead", "objective_stat = 0.0 in state 2", None
    return row


def _baseline(tmp_path: Path, label: str, seconds: float) -> dict:
    cache = tmp_path / f"{label}.baseline.json"
    cache.write_text(json.dumps({"seconds": seconds}), encoding="utf-8")
    return {"numbers": _numbers(4000), "n_nodes": 42, "n_lines": 17, "cache": str(cache)}


def _flip_spark(tmp_path: Path) -> dict:
    return {
        "build": "spark", "main_skill": "Fireball", "mode": "CALCS", "objective": {"maximize": "CombinedDPS"},
        "baseline": _baseline(tmp_path, "spark", 4000.0),
        "rows": [
            _row("Acrobatics", 9, "add", "pob_refused", seconds=4.2, reason="RuntimeError: no path to node 9"),
            _row("Blood Magic", 7, "add", "ok", seconds=312.4, state2=_numbers(4000, 1200)),
            _row("Chaos Inoculation", 3, "add", "ok", seconds=3725.0),
        ],
    }


def _flip_smite(tmp_path: Path) -> dict:
    return {
        "build": "smite", "main_skill": "Smite", "mode": "CALCS", "objective": {"maximize": "CombinedDPS"},
        "baseline": _baseline(tmp_path, "smite", 95.0),
        "rows": [
            _row("Acrobatics", 9, "add", "ok", seconds=7.5, skill_dead=True),
            _row("Blood Magic", 7, "remove", "ok", seconds=61.0, state2=_numbers(4000, 1000)),
            _row("Chaos Inoculation", 3, "add", "ok", seconds=45.0, priced_none=True),
        ],
    }


def _parse_rows() -> list[dict]:
    return [
        {"keystone": "Acrobatics", "lines": [{"text": "x", "kind": "add", "mods": []}, {"text": "y", "kind": "unparsed", "mods": []}], "kinds": ["add", "unparsed"]},
        {"keystone": "Blood Magic", "lines": [{"text": "z", "kind": "redirect", "mods": []}], "kinds": ["redirect"]},
        {"keystone": "Chaos Inoculation", "lines": [{"text": "w", "kind": "zero", "mods": []}], "kinds": ["zero"]},
    ]


@pytest.fixture()
def inputs(tmp_path):
    parse = tmp_path / "parse.json"
    parse.write_text(json.dumps(_parse_rows()), encoding="utf-8")
    spark = tmp_path / "spark.json"
    spark.write_text(json.dumps(_flip_spark(tmp_path)), encoding="utf-8")
    smite = tmp_path / "smite.json"
    smite.write_text(json.dumps(_flip_smite(tmp_path)), encoding="utf-8")
    return parse, spark, smite


def _report(inputs, tmp_path) -> str:
    parse, spark, smite = inputs
    out = tmp_path / "table.md"
    assert rep.main(["--parse", str(parse), "--flip", f"spark={spark}", f"smite={smite}", "--out", str(out)]) == 0
    return out.read_text(encoding="utf-8")


def _section(md: str, title: str) -> list[str]:
    lines = md.splitlines()
    start = lines.index(title)
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ") or lines[i].startswith("### ")), len(lines))
    return lines[start + 1:end]


def _after(md: str, title: str) -> list[str]:
    lines = md.splitlines()
    return lines[lines.index(title) + 1:]


def _table(md: str, build: str) -> list[dict[str, str]]:
    section = _section(md, f"## {build}")
    head = next(line for line in section if line.startswith("| keystone |"))
    names = [c.strip() for c in head.strip("|").split("|")]
    rows = []
    for line in section:
        if line.startswith("| ") and not line.startswith("| keystone") and not line.startswith("| ---"):
            cells = [c.strip() for c in line.strip("|").split(" | ")]
            rows.append(dict(zip(names, cells)))
    return rows


def test_table_one_row_per_keystone(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    for build in ("spark", "smite"):
        rows = _table(md, build)
        assert sorted(r["keystone"] for r in rows) == ["Acrobatics", "Blood Magic", "Chaos Inoculation"]
    assert md.count("| Chaos Inoculation |") == 2  # once per build table, none in the refused list
    assert "| zero |" in md and "| redirect |" in md and "| add, unparsed |" in md  # parsed kinds, PARSE_KINDS order


def test_refused_row_shows_reason_in_table_and_section(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    acro = next(r for r in _table(md, "spark") if r["keystone"] == "Acrobatics")
    assert acro["status"] == "pob_refused: RuntimeError: no path to node 9"
    assert acro["CombinedDPS, %"] == "-"  # no state 2, no percentage
    refused = _after(md, "## Keystones PoB could not flip on this tree")
    spark_refused = refused[refused.index("### spark") + 1:refused.index("### smite")]
    assert any("Acrobatics" in line and "RuntimeError: no path to node 9" in line for line in spark_refused)
    smite_refused = refused[refused.index("### smite") + 1:]
    assert any("Acrobatics" in line and "skill_dead" in line for line in smite_refused)
    assert not any("Chaos Inoculation" in line for line in refused)  # ok rows are not listed


def test_flip_remove_and_p_none_dash(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    smite = {r["keystone"]: r for r in _table(md, "smite")}
    assert smite["Blood Magic"]["flip"] == "remove"
    assert smite["Blood Magic"]["ManaUnreserved, %"] == "+12.5%"
    assert smite["Chaos Inoculation"]["collapsed nodes p, count"] == "-"
    assert smite["Chaos Inoculation"]["collapsed nodes p, value"] == "-"
    assert smite["Chaos Inoculation"]["collapsed nodes v, count"] == "50.0%"
    assert smite["Chaos Inoculation"]["collapsed nodes v, value"] == "25.0%"
    spark = {r["keystone"]: r for r in _table(md, "spark")}
    assert spark["Chaos Inoculation"]["collapsed nodes p, count"] == "40.0%"


def test_lines_collapsed_columns_next_to_nodes(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    head = next(line for line in md.splitlines() if line.startswith("| keystone |"))
    names = [c.strip() for c in head.strip("|").split("|")]
    assert names.index("collapsed lines v, count") == names.index("collapsed nodes p, value") + 1
    spark = {r["keystone"]: r for r in _table(md, "spark")}
    chaos = spark["Chaos Inoculation"]
    assert chaos["collapsed lines v, count"] == "25.0%"
    assert chaos["collapsed lines v, value"] == "10.0%"
    assert chaos["collapsed lines p, count"] == "0.0%"
    assert chaos["collapsed lines p, value"] == "0.0%"
    smite = {r["keystone"]: r for r in _table(md, "smite")}
    assert smite["Chaos Inoculation"]["collapsed lines p, count"] == "-"  # priced None drops both scopes
    assert smite["Chaos Inoculation"]["collapsed lines v, value"] == "10.0%"


def test_durations_are_human_and_match_human_duration(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    spark = {r["keystone"]: r for r in _table(md, "spark")}
    assert spark["Acrobatics"]["time"] == human_duration(4.2)  # "4.2 s"
    assert spark["Chaos Inoculation"]["time"] == human_duration(3725.0)  # "62 min"
    assert spark["Blood Magic"]["time"] == human_duration(312.4)
    assert re.search(r"\b\d{3,}(\.\d+)? s\b", md) is None  # no bare count of seconds in the hundreds+
    total = 4.2 + 312.4 + 3725.0 + 4000.0 + 7.5 + 61.0 + 45.0 + 95.0
    assert f"Total wall time: {human_duration(total)}" in md


def test_build_header_has_baseline_and_counts(inputs, tmp_path):
    md = _report(inputs, tmp_path)
    head = "\n".join(_section(md, "## spark"))
    assert "main skill: Fireball" in head
    assert "CombinedDPS 5000" in head and "Life 4000" in head and "ManaUnreserved 400" in head
    assert "baseline nodes 42" in head and "baseline rare-gear lines 17" in head


def test_sanity_mode_prints_both_rows(inputs, capsys):
    parse, spark, smite = inputs
    assert rep.main(["--parse", str(parse), "--flip", f"spark={spark}", f"smite={smite}", "--sanity"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    chaos, blood = lines
    assert chaos.startswith("Chaos Inoculation on spark (flip add): Life 4000 -> 1 (-99.9%)")
    assert "collapsed nodes 3 of 6, by count 50.0%, by value 25.0%" in chaos
    assert "collapsed lines 1 of 4, by count 25.0%, by value 10.0%" in chaos
    assert blood.startswith("Blood Magic on smite (flip remove): ManaUnreserved 400 -> 1000 (+12.5%)")
    assert "collapsed nodes 3 of 6, by count 50.0%, by value 25.0%" in blood
    assert "collapsed lines 1 of 4, by count 25.0%, by value 10.0%" in blood


def test_cli_needs_out_or_sanity(inputs):
    parse, spark, smite = inputs
    with pytest.raises(SystemExit):
        rep.main(["--parse", str(parse), "--flip", f"spark={spark}"])
