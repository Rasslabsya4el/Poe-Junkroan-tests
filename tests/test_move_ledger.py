"""Report-only move ledger measurements."""

from __future__ import annotations

import re
from types import SimpleNamespace

from junkroan.optimizer.move_ledger import (aggregate_move_tables, reentry_line, render_move_table, render_pob_calls, summarize_moves,
                                            tree_churn, tree_churn_metrics)
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
from junkroan.pob.session import PobSession

from judging_fakes import pob_judging


def test_tree_churn_matches_the_spec_example() -> None:
    assert tree_churn(range(1, 11), [*range(1, 9), 11, 12]) == 1 - 8 / 12


def test_tree_churn_metrics_uses_graph_cascades_for_trunk() -> None:
    graph = SimpleNamespace(cascade_if_removed=lambda nodes, node: nodes if node == 1 else {node})
    metrics = tree_churn_metrics({1, 2, 3}, {2, 3, 4}, graph=graph, trunk_threshold=1)
    assert metrics["all"] == 0.5
    assert metrics["trunk"] == 1.0
    assert metrics["trunk_share"] == 0.0


def test_summary_table_aggregates_only_kept_gains() -> None:
    moves = [
        {"move": "refine", "seconds": 2, "before": 100, "after": 110, "kept": True},
        {"move": "refine", "seconds": 3, "before": 110, "after": 105, "kept": False},
        {"move": "gear Boots", "seconds": 5, "before": 110, "after": 120, "kept": True},
    ]
    rows = summarize_moves(moves)
    assert rows[0]["tries"] == 2 and rows[0]["kept"] == 1
    assert rows[0]["gain"] == 10 and rows[0]["gain per minute"] == 120
    assert rows[1]["share of the loop's gain"] == 0.5
    assert "| refine | 2 | 1 | 5 s | 10 | 120.0 | 50.0% |" in "\n".join(render_move_table(moves))


def test_the_fixed_point_checks_rows_are_aggregated_with_the_rest_but_counted_apart() -> None:
    """`_fixed_point_check` re-enters the loop after the ledger's identity is taken, so its rows
    carry its stage name instead of "loop pass N" and are named under the table."""

    moves = [
        {"where": "loop opening", "move": "lanes", "seconds": 1.0, "before": 100, "after": 100, "kept": False},
        {"where": "loop pass 1", "move": "refine", "seconds": 2.0, "before": 100, "after": 110, "kept": True},
        {"where": "fixed point check", "move": "refine", "seconds": 4.0, "before": 110, "after": 110, "kept": False},
    ]

    assert reentry_line(moves) == ["of which fixed point check: 1 tries, 4 s"]
    table = "\n".join(render_move_table(moves))
    assert "| refine | 2 | 1 | 6 s |" in table  # aggregated over every row, as before
    assert table.endswith("of which fixed point check: 1 tries, 4 s")
    assert reentry_line([{"move": "refine", "seconds": 2.0}]) == []  # a row persisted before `where` existed


def test_rendered_move_table_uses_human_time_and_a_per_minute_rate() -> None:
    table = "\n".join(render_move_table([
        {"move": "refine", "seconds": 2856.0, "before": 100.0, "after": 120.0, "kept": True},
    ]))

    assert "| move | tries | kept | time |" in table
    assert "gain per minute" in table
    assert "48 min" in table
    assert not re.search(r"\d{3,} ?s\b", table)
    assert "| seconds |" not in table


def test_pob_call_table_uses_human_time() -> None:
    table = "\n".join(render_pob_calls({"fast trials": {"count": 12, "seconds": 2856.0}}))

    assert "| PoB call | calls | time |" in table
    assert "| fast trials | 12 | 48 min |" in table
    assert not re.search(r"\d{3,} ?s\b", table)


def test_benchmark_aggregation_has_median_and_total() -> None:
    rows = [
        {"ok": True, "moves": [{"move": "refine", "seconds": 2, "before": 100, "after": 110, "kept": True}]},
        {"ok": True, "moves": [{"move": "refine", "seconds": 4, "before": 100, "after": 120, "kept": True}]},
    ]
    median, total = aggregate_move_tables(rows)
    assert median[0]["seconds"] == 3
    assert total[0]["seconds"] == 6 and total[0]["gain"] == 30


def test_session_call_counter_is_report_only() -> None:
    session = PobSession.__new__(PobSession)
    session._call_counts = {}
    session._call_seconds = {}
    result = session._measured_call("stats", lambda: 42)
    assert result == 42
    assert session.pob_calls()["stats"]["count"] == 1
    session.reset_pob_calls()
    assert session.pob_calls() == {}


def test_stage_log_stays_a_stage_line_after_moves_exist() -> None:
    pob = SimpleNamespace(stats=lambda keys: {key: 1000.0 for key in keys})
    lines: list[str] = []
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob = pob
    pipeline.log = lines.append
    pipeline.judging = pob_judging(pipeline)
    pipeline.objective = Objective(maximize="CombinedDPS")
    result = BuildResult(
        skeleton=SimpleNamespace(class_name="Witch", ascendancy="Elementalist", main_link=["Fireball"]),
        moves=[{"move": "refine", "seconds": 1.0, "before": 900.0, "after": 1000.0, "kept": True}],
    )

    pipeline._record(result, "loop pass 1", 0.0)

    assert lines[0].lstrip().startswith("loop pass 1")
    assert "| refine |" not in lines[0]
