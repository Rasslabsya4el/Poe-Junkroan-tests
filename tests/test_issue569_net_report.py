"""#569: the report says how many rows the loop's 2-hour safety net stopped."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import benchmark  # noqa: E402
from test_benchmark_counted_rows import full_row  # noqa: E402


def test_net_line_counts_time_rows_and_names_them() -> None:
    rows = [full_row(name, 1, 1.0, loop_stop=stop) for name, stop in
            [("a", "time"), ("b", "converged"), ("c", "time"), ("d", "converged"), ("e", "converged")]]
    report = benchmark.render_report(rows, stamp="fixture")
    line = next(l for l in report.splitlines() if l.startswith("Loop safety net"))
    assert "hit: 2 of 5 rows" in line
    assert line.endswith(": a s1, c s1")
    assert "7200" not in line


def test_net_line_with_no_hits_names_nothing() -> None:
    rows = [full_row(name, 1, 1.0, loop_stop="converged") for name in "abc"]
    line = next(l for l in benchmark.render_report(rows, stamp="fixture").splitlines() if l.startswith("Loop safety net"))
    assert line.endswith("hit: 0 of 3 rows")


def test_loop_seconds_default_is_no_clock() -> None:  # #956: it was the two-hour net
    assert benchmark.LOOP_SECONDS_DEFAULT is None
    import inspect
    assert inspect.signature(benchmark.run_one).parameters["loop_seconds"].default is None
