"""#616 unit 4: the report prints the output classes by build."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import render_report  # noqa: E402


def _row(ref: str, **extra: object) -> dict[str, object]:
    row: dict[str, object] = {
        "ok": True, "reference": ref, "source": f"{ref}.txt", "recorded_value": 1.0, "replayed_value": 1.0,
        "value_before": 1.0, "value_after": 1.0, "replayed_over_recorded": 1.0, "gain_percent": 0.0, "seconds": 1.0,
        "kept": 0, "violation_before": 0.0, "violation_after": 0.0, "audit_errors": 0, "considered": {},
    }
    row.update(extra)
    return row


def _render(trace: bool) -> str:
    rows = [
        _row("a", output={"zeta": 2, "alpha": 1}, input={"alpha": 1, "zeta": 2}),
        _row("b", output={"alpha": 0}, input={"alpha": 1}),
        {"ok": False, "reference": "failed-one", "source": "f.txt", "error": "boom"},
    ]
    return render_report(rows, stamp="t", move="loop", passes=1, workers=1, seconds=3.0, trace=trace)


def test_output_section_table() -> None:
    report = _render(True)
    assert "## Trace: output classes by build" in report
    section = report.split("## Trace: output classes by build")[1]
    assert "| class | a | b |" in section
    assert "| alpha | 1 | 1 -> 0 |" in section
    assert "| zeta | 2 | - |" in section
    assert "failed-one" not in section


def test_output_section_absent_without_trace() -> None:
    assert "output classes by build" not in _render(False)


def test_output_section_drops_per_id_and_all_zero_columns() -> None:
    out = {"node:12": 1, "node-rm:5": 1, "node-kind:small": 3, "oil:7": 1, "zero": 0, "flask-zero": 0, "gone": 0, "keep": 2}
    rows = [_row("a", output=out, input={"gone": 4}), _row("b", output={"keep": 1})]
    report = render_report(rows, stamp="t", move="loop", passes=1, workers=1, seconds=3.0, trace=True)
    header = [line for line in report.split("## Trace: output classes by build")[1].splitlines() if line.startswith("| class")][0]
    assert header == "| class | a | b |"
    rows_ = [line.split(" |")[0] for line in report.split("## Trace: output classes by build")[1].splitlines() if line.startswith("| ") and not line.startswith("| class")]
    assert rows_ == ["| flask-zero", "| gone", "| keep"]
