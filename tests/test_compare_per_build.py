"""Pure-data tests for the --per-build table of scripts/compare_runs.py (no PoB)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("compare_runs", ROOT / "scripts" / "compare_runs.py")
compare_runs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_runs)


A_ROWS = [
    {"slug": "stormbrand", "seed": 2, "ours": 800.0, "seconds": 120.0,
     "move_rows": [{"pass": 1}, {"pass": 3}],
     "pob_calls": {"stats": {"seconds": 1.5}, "calc": 2.5}},
    {"slug": "stormbrand", "seed": 1, "ours": 1000.0, "seconds": 30.0,
     "move_rows": [], "pob_calls": {}},
    {"slug": "only_a", "seed": 1, "ours": 5.0, "seconds": 1.0,
     "move_rows": [], "pob_calls": {}},
]

B_ROWS = [
    {"slug": "stormbrand", "seed": 1, "ours": 1100.0, "seconds": 60.0,
     "move_rows": [{"pass": 4}], "pob_calls": {"stats": {"seconds": 3.0}}},
    {"slug": "stormbrand", "seed": 2, "ours": 700.0, "seconds": 90.0,
     "move_rows": [], "pob_calls": {}},
    {"slug": "only_b", "seed": 1, "ours": 9.0, "seconds": 2.0,
     "move_rows": [], "pob_calls": {}},
]


def test_matches_only_both_runs_sorted():
    rows = compare_runs.per_build_rows(A_ROWS, B_ROWS)
    assert [(r["slug"], r["seed"]) for r in rows] == [("stormbrand", 1), ("stormbrand", 2)]


def test_delta_percent():
    rows = compare_runs.per_build_rows(A_ROWS, B_ROWS)
    assert rows[0]["delta_pct"] == 10.0
    assert rows[1]["delta_pct"] == -12.5


def test_max_pass_and_pob_sum_both_shapes():
    rows = compare_runs.per_build_rows(A_ROWS, B_ROWS)
    first = rows[0]
    assert first["a_passes"] == 0
    assert first["b_passes"] == 4
    assert first["a_pob_seconds"] == 0.0
    assert first["b_pob_seconds"] == 3.0
    second = rows[1]
    assert second["a_passes"] == 3
    assert second["b_passes"] == 0
    assert second["a_pob_seconds"] == 4.0
    assert second["b_pob_seconds"] == 0.0


def test_rendered_header_line():
    table = compare_runs.per_build_table(compare_runs.per_build_rows(A_ROWS, B_ROWS))
    assert table.splitlines()[0] == (
        "| slug | seed | A value | B value | delta % | A passes | B passes | A PoB | B PoB | A build | B build |"
    )
    assert table.splitlines()[1].startswith("|---")
    assert len(table.splitlines()) == 4


def test_rendered_durations_are_human():
    table = compare_runs.per_build_table(compare_runs.per_build_rows(A_ROWS, B_ROWS))
    assert "2 min" in table
    assert "30 s" in table