"""#1125 unit 2: the day-1 bundle graph builder (scripts/build_bundle_graph.py).

Seams under test: `build_graph(rows, records)` (the join) and `main(argv)` (the file and its bytes), both on a
hand-built mini corpus of three day-1 sources. Expected values are written by hand from the rule in #1125,
not produced by the code.

Mini corpus:
- notable:1 "Sets X"  sets Condition:X (a FLAG mod named Condition:X)
- notable:2 "Reads X"  reads it with tag {type: Condition, var: X}
- keystone:3 "Reads nothing"  reads nothing
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_bundle_graph import build_graph, check_vectors, main  # noqa: E402


def _mod(name, mtype, *, value=True, tags=()):
    return {"name": name, "type": mtype, "value": value, "flags": [], "keyword_flags": [], "tags": list(tags)}


def _row(line, surface, source, outcome="full"):
    return {"line": line, "surface": surface, "source": source, "outcome": outcome}


ROWS = [
    _row("Sets X", "notable", 1),
    _row("Reads X", "notable", 2),
    _row("Reads nothing", "keystone", 3),
]

RECORDS = {
    "Sets X": [_mod("Condition:X", "FLAG")],
    "Reads X": [_mod("Damage", "INC", value=10, tags=[{"type": "Condition", "var": "X"}])],
    "Reads nothing": [_mod("Life", "BASE", value=40)],
}


def _edges_of(graph):
    return [(e["kind"], e.get("var") or e.get("stat"), e["from"], e["to"]) for e in graph["edges"]]


def test_condition_edge_joins_setter_and_reader():
    graph = build_graph(ROWS, RECORDS)
    assert len(graph["nodes"]) == 3
    assert len(graph["edges"]) == 1
    assert _edges_of(graph) == [("condition", "X", "notable:1", "notable:2")]
    edge = graph["edges"][0]
    assert edge["from_line"] == "Sets X"
    assert edge["to_line"] == "Reads X"


def test_multiplier_edge():
    rows = [_row("+2 to maximum Y", "notable", 10), _row("Reads Y", "notable", 11)]
    records = {
        "+2 to maximum Y": [_mod("Multiplier:Y", "BASE", value=2)],
        "Reads Y": [_mod("Damage", "INC", value=5, tags=[{"type": "Multiplier", "var": "Y"}])],
    }
    graph = build_graph(rows, records)
    assert _edges_of(graph) == [("multiplier", "Y", "notable:10", "notable:11")]


def test_per_stat_edge():
    rows = [_row("Grants Life", "notable", 20), _row("Per Life", "notable", 21)]
    records = {
        "Grants Life": [_mod("Life", "BASE", value=40)],
        "Per Life": [_mod("Damage", "INC", value=3, tags=[{"type": "PerStat", "stat": "Life"}])],
    }
    graph = build_graph(rows, records)
    assert _edges_of(graph) == [("per_stat", "Life", "notable:20", "notable:21")]


def test_no_self_edge():
    rows = [_row("Sets and reads X", "notable", 30)]
    records = {"Sets and reads X": [_mod("Condition:X", "FLAG"), _mod("Damage", "INC", tags=[{"type": "Condition", "var": "X"}])]}
    graph = build_graph(rows, records)
    assert graph["edges"] == []


def test_line_without_record_joins_nothing():
    rows = [_row("Sets X", "notable", 1), _row("Reads X", "notable", 2, outcome="none")]
    graph = build_graph(rows, {"Sets X": RECORDS["Sets X"]})
    assert graph["edges"] == []
    assert len(graph["nodes"]) == 2


def test_rerun_is_byte_identical(tmp_path):
    rows_path = tmp_path / "rows.json"
    records_path = tmp_path / "records.json"
    rows_path.write_text(json.dumps(ROWS), encoding="utf-8")
    records_path.write_text(json.dumps(RECORDS), encoding="utf-8")
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    for out in (first, second):
        assert main(["--rows", str(rows_path), "--records", str(records_path), "--out", str(out)]) == 0
    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["counts"]["nodes"] == 3
    assert payload["counts"]["edges"] == 1


def test_check_vectors_counts_missing_pairs():
    records = dict(RECORDS)
    records["Sets X"] = [_mod("Condition:X", "FLAG"), _mod("Life", "BASE", value=40)]
    records["Reads X"] = [_mod("Damage", "INC", value=10, tags=[{"type": "PerStat", "stat": "Life"}])]
    graph = build_graph(ROWS, records)  # per_stat Life: notable:1 -> notable:2 only
    vectors = {"vectors": {
        "per:Life": {
            "kind": "per",
            "enablers": [{"source": "notable:1", "family": "notable", "name": "Sets X", "line": "Sets X"}],
            "payoffs": [
                {"source": "notable:2", "family": "notable", "name": "Reads X", "line": "Reads X",
                 "stat": "Damage", "tag": {"type": "PerStat", "stat": "Life"}},
                {"source": "keystone:3", "family": "keystone", "name": "Reads nothing", "line": "Reads nothing",
                 "stat": "Life", "tag": {"type": "PerStat", "stat": "Life"}},
            ],
        },
    }}
    result = check_vectors(graph, vectors)
    assert result["pairs"] == 2  # both payoff sources are day-1 nodes
    assert result["missing"] == 1  # notable:2 has its edge; keystone:3 reads nothing, so it has none


# --- calc_multiplier (#1125 unit 3): the 8 named pairs of --check-vectors, from a table read in PoB's calc code ---

CALC_ROWS = [
    _row("50% increased Rage Effect", "ascendancy", 57560),
    _row("Every Rage also grants 1% increased Armour", "notable", 53840),
    _row("20% increased total Power counted by Warcries", "notable", 17816),
    _row("25% increased total Power counted by Warcries", "notable", 64226),
    _row("Gain 25% increased Armour per 5 Power for 8 seconds when you Warcry", "notable", 7107),
    _row("Shares only Damage", "notable", 900),
    _row("Also only Damage", "notable", 901),
]

CALC_RECORDS = {
    "50% increased Rage Effect": [_mod("RageEffect", "INC", value=50)],
    "Every Rage also grants 1% increased Armour": [_mod("Armour", "INC", value=1, tags=[{"type": "Multiplier", "var": "RageEffect"}])],
    "20% increased total Power counted by Warcries": [_mod("WarcryPower", "INC", value=20)],
    "25% increased total Power counted by Warcries": [_mod("WarcryPower", "INC", value=25)],
    "Gain 25% increased Armour per 5 Power for 8 seconds when you Warcry": [
        _mod("Armour", "INC", value=25, tags=[{"type": "Multiplier", "var": "WarcryPower"}, {"type": "Condition", "var": "UsedWarcryInPast8Seconds"}])],
    "Shares only Damage": [_mod("Something", "INC", value=10)],
    "Also only Damage": [_mod("Damage", "INC", value=12, tags=[{"type": "Multiplier", "var": "Something"}])],
}


def test_calc_multiplier_edges_from_the_pob_table():
    graph = build_graph(CALC_ROWS, CALC_RECORDS)
    calc = [(e["var"], e["from"], e["to"]) for e in graph["edges"] if e["kind"] == "calc_multiplier"]
    # #1146: the two INC WarcryPower setters no longer join notable:7107 (PoB counts only BASE and OVERRIDE)
    assert calc == [
        ("RageEffect", "ascendancy:57560", "notable:53840"),
    ]
    rage = next(e for e in graph["edges"] if e["kind"] == "calc_multiplier" and e["var"] == "RageEffect")
    assert rage["via"] == "RageEffect"
    assert rage["pob"] == "CalcPerform.lua:887"
    assert graph["counts"]["edges_per_kind"] == {"condition": 0, "multiplier": 0, "per_stat": 0, "calc_multiplier": 1}


def test_shared_non_table_mod_name_is_not_an_edge():
    # one node has a mod named Something, the other reads Multiplier:Something: no table entry, no edge
    graph = build_graph(CALC_ROWS[-2:], CALC_RECORDS)
    assert graph["edges"] == []


def test_check_vectors_lists_pairs_whose_tag_is_not_a_graph_kind():
    graph = build_graph(CALC_ROWS, CALC_RECORDS)
    vectors = {"vectors": {"c:X": {"kind": "condition",
        "enablers": [{"source": "notable:17816", "family": "notable", "name": "a", "line": "a"}],
        "payoffs": [
            {"source": "notable:7107", "family": "notable", "name": "b", "line": "b", "stat": "Armour", "tag": {"type": "Multiplier", "var": "WarcryPower"}},
            {"source": "notable:900", "family": "notable", "name": "c", "line": "c", "stat": "Armour", "tag": {"type": "SkillName", "skillName": "Z"}},
            {"source": "notable:901", "family": "notable", "name": "d", "line": "d", "stat": "Armour", "tag": {"type": "SkillName", "skillName": "Y"}},
            {"source": "notable:901", "family": "notable", "name": "e", "line": "e", "stat": "Armour", "tag": {"type": "Other"}},
        ]}}}
    result = check_vectors(graph, vectors)
    # #1146: notable:17816 is an INC WarcryPower setter, so its Multiplier:WarcryPower pair to notable:7107 is no longer met
    assert result["missing"] == 1
    assert result["missing_examples"] == ["multiplier WarcryPower: notable:17816 -> notable:7107"]
    assert result["not_graph_kind"] == 3
    assert result["not_graph_kind_by_tag"] == {"Other": 1, "SkillName": 2}
