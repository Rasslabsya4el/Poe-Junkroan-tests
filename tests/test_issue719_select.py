"""#719 unit 1: a root-level Markdown file no test opens selects nothing (never the full suite);
one the tests open (GLOSSARY.md) selects exactly its readers."""
import json

from tools.agentops import test_select as ts
from tests.test_issue690_select import Rig


def _rig_with_readers(tmp_path):
    r = Rig(tmp_path)
    reads = r.mdir / "reads" / "reads-1.json"
    data = json.loads(reads.read_text(encoding="utf-8"))
    data["files"]["tests/test_a.py::t1"] = ["NOTES.md"]
    data["files"]["tests/test_a.py::t2"] = ["NOTES.md"]
    reads.write_text(json.dumps(data), encoding="utf-8")
    return r


def test_a_root_md_no_test_reads_is_suite_free_like_docs(tmp_path):
    r = Rig(tmp_path)
    s = r.sel({"NOTES.md": "x"})
    assert not s.full and s.ids == [] and s.line == f"selected 0 of 100 tests (map {r.c0[:8]})"


def test_b_root_md_read_by_tests_selects_its_readers_only(tmp_path):
    r = _rig_with_readers(tmp_path)
    s = r.sel({"NOTES.md": "n", "docs/adr/0001-x.md": "a"})
    assert not s.full and s.ids == ["tests/test_a.py::t1", "tests/test_a.py::t2"]
    assert len(s.ids) < 100


def test_b2_glossary_is_a_data_change_by_the_core_rule(tmp_path):
    # core update 55cb3006: GLOSSARY.md is in DATA_CHANGE_FILES (tests read it through open()), so it runs the full suite
    r = _rig_with_readers(tmp_path)
    assert r.sel({"GLOSSARY.md": "g"}).reason == "data change"


def test_c_a_blind_file_outside_docs_and_root_md_is_still_full(tmp_path):
    r = Rig(tmp_path)
    assert r.sel({"tools/blind.txt": "x"}).full
    assert r.sel({"sub/NOTES.md": "x"}).full  # only a root document is a document
    assert ts._is_root_md("GLOSSARY.md") and not ts._is_root_md("a/B.md") and not ts._is_root_md("x.txt")
