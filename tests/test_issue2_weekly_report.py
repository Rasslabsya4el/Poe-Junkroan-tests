"""#538: the weekly gate report, PoB-free, on built run folders."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import weekly_report  # noqa: E402


def _row(slug, seed, pct, errors=0):
    return {"ok": True, "slug": slug, "seed": seed, "ratio_lane": pct / 100.0, "audit_errors": errors,
            "audit": ["[error] x: y"] * errors, "fixed_point_gain": 0.004, "seconds": 10.0, "stages": [{"violation": 0.0}]}


def _folder(root: Path, name: str, a, b):
    d = root / name
    d.mkdir()
    rows = [_row("A", s, v) for s, v in enumerate(a)] + [_row("B", s, v) for s, v in enumerate(b)]
    rows += [_row("C", 0, 100), _row("C", 1, 101), _row("C", 2, 102, errors=1)]
    (d / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    return d


def test_report_table_summary_and_exit(tmp_path, capsys):
    gate = _folder(tmp_path, "gate", [103, 101, 98], [120, 95, 110])
    prev = _folder(tmp_path, "prev", [99, 99, 99], [90, 100, 80])
    assert weekly_report.main(["--core", str(gate), "--previous", str(prev)]) == 0
    text = (gate / "report-weekly.md").read_text(encoding="utf-8")
    assert capsys.readouterr().out.strip() == text.strip()
    rows = {l.split("|")[1].strip(): [c.strip() for c in l.split("|")[2:-1]] for l in text.splitlines()
            if l.startswith("| ") and "---" not in l and "reference" not in l}
    assert rows["A"][1:3] == ["101.0 %", "5.0"] and rows["A"][6] == "+2.0" and rows["A"][7] == "stable"
    assert rows["B"][1:3] == ["110.0 %", "25.0"] and rows["B"][6] == "+20.0" and rows["B"][7] == "covered"
    assert rows["C"][1] == "-" and rows["C"][3] == "1" and rows["C"][7] == "infeasible (clean 2)"
    assert "Covered 2 of 3, stable 1 of 3" in text
    assert "PASS" not in text and "FAIL" not in text


def test_exit_zero_when_previous_better_and_first_gate(tmp_path):
    gate = _folder(tmp_path, "gate", [103, 101, 98], [120, 95, 110])
    better = _folder(tmp_path, "better", [150, 150, 150], [150, 150, 150])
    assert weekly_report.main(["--core", str(gate), "--previous", str(better)]) == 0
    assert weekly_report.main(["--core", str(gate)]) == 0
    text = (gate / "report-weekly.md").read_text(encoding="utf-8")
    assert "first weekly core run" in text and "first run" in text
    assert "gate" not in text.replace(gate.name, "RUN").lower()  # #588


def test_gate_flag_is_gone(tmp_path):  # #578: --gate renamed --core
    gate = _folder(tmp_path, "gate", [103, 101, 98], [120, 95, 110])
    import pytest
    with pytest.raises(SystemExit):
        weekly_report.main(["--gate", str(gate)])
