"""#1146: a WarcryPower setter joins its readers only through a mod type PoB adds into the value they read.

PoB sums BASE and takes OVERRIDE into `output.WarcryPower` (CalcPerform.lua:1311); an INC WarcryPower goes only
into the warcry buff's power (CalcPerform.lua:2327), so it never reaches the PerStat reader (Brinerot Flag) or the
Multiplier reader (the Armour-per-Power notable). Seam under test: `build_graph(rows, records)`. Expected values are
written by hand from #1146, not produced by the code.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_bundle_graph import build_graph  # noqa: E402


def _mod(name, mtype, *, value=True, tags=()):
    return {"name": name, "type": mtype, "value": value, "flags": [], "keyword_flags": [], "tags": list(tags)}


def _row(line, surface, source):
    return {"line": line, "surface": surface, "source": source, "outcome": "full"}


RECORDS = {
    "setter inc": [_mod("WarcryPower", "INC", value=20)],
    "setter base": [_mod("WarcryPower", "BASE", value=20)],
    "setter override": [_mod("WarcryPower", "OVERRIDE", value=20)],
    "setter armour": [_mod("Armour", "INC", value=10)],
    "warcry reader": [
        _mod("ArcaneSurgeEffect", "INC", value=10, tags=[{"type": "PerStat", "stat": "WarcryPower", "div": 5}]),
        _mod("Armour", "INC", value=25, tags=[{"type": "Multiplier", "var": "WarcryPower", "div": 5}]),
    ],
    "armour reader": [_mod("Life", "BASE", value=5, tags=[{"type": "PerStat", "stat": "Armour"}])],
}

READER = _row("warcry reader", "unique", "Reader")


def _edges_of(graph):
    return sorted((e["kind"], e.get("var") or e.get("stat"), e["from"], e["to"]) for e in graph["edges"])


def test_inc_warcry_power_setter_makes_no_edge():
    graph = build_graph([_row("setter inc", "notable", 1), READER], RECORDS)
    assert _edges_of(graph) == []


def test_base_warcry_power_setter_joins_both_readers():
    graph = build_graph([_row("setter base", "notable", 2), READER], RECORDS)
    assert _edges_of(graph) == [
        ("calc_multiplier", "WarcryPower", "notable:2", "unique:Reader"),
        ("per_stat", "WarcryPower", "notable:2", "unique:Reader"),
    ]


def test_override_warcry_power_setter_joins_both_readers():
    graph = build_graph([_row("setter override", "notable", 3), READER], RECORDS)
    assert _edges_of(graph) == [
        ("calc_multiplier", "WarcryPower", "notable:3", "unique:Reader"),
        ("per_stat", "WarcryPower", "notable:3", "unique:Reader"),
    ]


def test_inc_setter_of_another_stat_keeps_its_per_stat_edge():
    rows = [_row("setter armour", "notable", 4), _row("armour reader", "notable", 5)]
    graph = build_graph(rows, RECORDS)
    assert _edges_of(graph) == [("per_stat", "Armour", "notable:4", "notable:5")]
