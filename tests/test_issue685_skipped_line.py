"""#685 row 1c: a laptop suite's merge line prints `skipped N (pc last M)`; a PC suite's line does not."""

from __future__ import annotations

import json

from tests.test_issue685_merge_wiring import PC_IDLE, rig  # noqa: F401  (fixture)
from tools.agentops import merge, suite_host, test_select

SUMMARY = "=== 4261 passed, 88 skipped, 3 deselected in 341.00s (0:05:41) ===\n"


def _meta(root, **kw):
    d = root / "var" / "agentops" / "test_map"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"map_commit": "x", "total": 1, **kw}), encoding="utf-8")


def _line(run, tmp_path):
    result = merge.MergeResult(ok=True, reason="pushed", suite_workers=run.workers, suite_host=run.host,
                               skipped_note=run.skipped_note)
    log = tmp_path / "m.log"
    merge._append_merge_log("b", result, log_path=log)
    return log.read_text(encoding="utf-8")


def test_laptop_line_has_skipped_and_the_stored_pc_value(rig, tmp_path, monkeypatch):
    _meta(tmp_path, skipped=80)
    monkeypatch.setattr(test_select, "map_dir", lambda root: tmp_path / "var" / "agentops" / "test_map")
    rig.laptop_rc, rig.laptop_text = 0, SUMMARY
    assert "host laptop, skipped 88 (pc last 80)" in _line(rig.run(tmp_path), tmp_path)


def test_no_stored_value_says_unknown(rig, tmp_path, monkeypatch):
    _meta(tmp_path)
    monkeypatch.setattr(test_select, "map_dir", lambda root: tmp_path / "var" / "agentops" / "test_map")
    rig.laptop_rc, rig.laptop_text = 0, SUMMARY
    assert "skipped 88 (pc last unknown)" in _line(rig.run(tmp_path), tmp_path)


def test_pc_suite_line_has_no_skipped_text(rig, tmp_path):
    rig.pc = PC_IDLE
    line = _line(rig.run(tmp_path), tmp_path)
    assert "host pc" in line and "skipped" not in line


def test_parse_skipped_reads_the_summary_line():
    assert suite_host.parse_skipped(SUMMARY) == 88
    assert suite_host.parse_skipped("4000 passed\n") is None
