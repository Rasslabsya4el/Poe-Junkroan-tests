"""A build of the control lost in the candidate fails the verdict; the moved list (#725). No PoB."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
_spec = importlib.util.spec_from_file_location("compare_runs", ROOT / "scripts" / "compare_runs.py")
compare_runs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_runs)


def _row(slug, points):
    if points is None:
        return {"slug": slug, "seed": 1, "ok": False, "error": "PoBHeadlessHostContractError: Timed out\nTraceback..."}
    return {"slug": slug, "seed": 1, "ok": True, "ratio_lane": points / 100.0, "ours": 1.0}


def _run(tmp_path, name, values):
    d = tmp_path / name
    d.mkdir()
    (d / "results.json").write_text(json.dumps({"rows": [_row(k, v) for k, v in values.items()]}), encoding="utf-8")
    return str(d)


def _compare(tmp_path, capsys, base, head):
    a, b = _run(tmp_path, "a", base), _run(tmp_path, "b", head)
    sys.argv = ["compare_runs", a, b]
    code = compare_runs.main()
    return code, capsys.readouterr().out


def test_three_failed_in_head_fail(tmp_path, capsys):
    base = {"r1": 100.0, "r2": 110.0, "r3": 120.0, "r4": 130.0, "r5": 140.0}
    head = {"r1": 100.0, "r2": 110.0, "r3": None, "r4": None, "r5": None}
    code, out = _compare(tmp_path, capsys, base, head)
    assert code == 1
    line = next(l for l in out.splitlines() if l.startswith("FAIL:"))
    assert all(n in line for n in ("r3", "r4", "r5")) and "Timed out" in line


def test_none_failed_verdict_as_today(tmp_path, capsys):
    base = {"r1": 100.0, "r2": 110.0, "r3": 120.0}
    head = {"r1": 101.0, "r2": 111.0, "r3": 121.0}
    code, out = _compare(tmp_path, capsys, base, head)
    assert code == 0
    assert "delta +1.0 (min -5.0): PASS" in out
    assert "FAIL:" not in out and "moved more than" not in out


def test_moved_list(tmp_path, capsys):
    base = {"a": 149.9, "b": 115.8, "c": 52.8, "d": 100.0}
    head = {"a": 121.5, "b": 189.0, "c": 44.6, "d": 90.0}
    _, out = _compare(tmp_path, capsys, base, head)
    moved = out.split("moved more than 15 %:")[1]
    assert "- a: 149.9 -> 121.5" in moved and "- b: 115.8 -> 189.0" in moved and "- c: 52.8 -> 44.6" in moved
    assert "- d:" not in moved
