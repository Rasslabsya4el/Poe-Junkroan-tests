import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("compare_calls", Path(__file__).resolve().parents[1] / "scripts" / "compare_calls.py")
compare_calls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_calls)


def _xml_call(seq: int, length: int, digest: str) -> dict:
    return {"seq": seq, "method": "load_xml", "args": digest,
            "preview": json.dumps({"args": [{"len": length, "sha256": digest}], "kwargs": {}}, separators=(",", ":"))[:64]}


def _write(path: Path, calls: list[dict]) -> Path:
    path.write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    return path


def test_load_xml_of_equal_length_matches_unless_strict(tmp_path, monkeypatch):
    stats = {"seq": 2, "method": "stats", "args": "aa", "preview": ""}
    left = _write(tmp_path / "l.jsonl", [_xml_call(1, 47846, "0b28c14a"), stats])
    right = _write(tmp_path / "r.jsonl", [_xml_call(1, 47846, "a93fe79a"), stats])
    assert compare_calls.compare_pair("x", left, right)
    monkeypatch.setattr(compare_calls, "STRICT_XML", True)
    assert not compare_calls.compare_pair("x", left, right)


def test_load_xml_of_another_length_differs(tmp_path):
    left = _write(tmp_path / "l.jsonl", [_xml_call(1, 47846, "0b28c14a")])
    right = _write(tmp_path / "r.jsonl", [_xml_call(1, 47847, "0b28c14a")])
    assert not compare_calls.compare_pair("x", left, right)
