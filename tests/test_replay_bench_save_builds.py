"""#437: replay_bench keeps each ok row's final build as XML for check_useful_lines.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from replay_bench import save_final_builds  # noqa: E402


def test_final_builds_are_written_and_dropped_from_the_rows(tmp_path: Path) -> None:
    rows = [
        {"ok": True, "reference": "stormbrand", "final_xml": "<PathOfBuilding>a</PathOfBuilding>"},
        {"ok": True, "reference": "stormbrand", "final_xml": "<PathOfBuilding>b</PathOfBuilding>"},
        {"ok": True, "reference": "cold_dot", "final_xml": "<PathOfBuilding>c</PathOfBuilding>"},
        {"ok": False, "reference": "bleed_bow", "error": "boom"},
    ]

    written = save_final_builds(rows, tmp_path)

    assert sorted(p.name for p in written) == ["cold_dot.xml", "stormbrand-2.xml", "stormbrand.xml"]
    assert (tmp_path / "builds" / "stormbrand.xml").read_text(encoding="utf-8") == "<PathOfBuilding>a</PathOfBuilding>"
    assert (tmp_path / "builds" / "stormbrand-2.xml").read_text(encoding="utf-8") == "<PathOfBuilding>b</PathOfBuilding>"
    assert all("final_xml" not in row for row in rows)
    assert [bool(row.get("final_build")) for row in rows] == [True, True, True, False]
    json.dumps(rows)  # results.json stays serialisable


def test_no_ok_row_writes_no_folder(tmp_path: Path) -> None:
    assert save_final_builds([{"ok": False, "reference": "x", "error": "e"}], tmp_path) == []
    assert not (tmp_path / "builds").exists()


def test_input_block_is_the_start_builds_option_classes_and_lands_in_results(tmp_path: Path) -> None:
    from replay_bench import input_output
    from junkroan.optimizer.trace_output import trace_output_from_xml

    xml = '<PathOfBuilding><Tree activeSpec="1"><Spec nodes="1,2,3"/></Tree></PathOfBuilding>'

    class Raw:
        def export_xml(self) -> str:
            return xml

    block = input_output(Raw())
    assert block == trace_output_from_xml(xml)
    rows = [{"ok": True, "reference": "stormbrand", "final_xml": "<x/>", "input": block}]
    save_final_builds(rows, tmp_path)
    assert json.loads(json.dumps(rows))[0]["input"] == block
