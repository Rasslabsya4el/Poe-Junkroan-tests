"""#737 rule D: a changed core_manifest.txt entry also selects the map's tests of tools/agentops/core_check.py.
The map is synthetic (a Rig in tmp_path with the edges below): the real var/agentops/test_map holds 0 tests."""
from tools.agentops import test_select as ts
from tools.agentops.core_check import read_manifest
from tests.test_issue690_select import Rig, build_db

CC = "tests/test_agentops_merge.py::test_core_check_stays_clean_with_the_new_module"
CC_DEPS = {  # file -> tests that executed it
    "tools/agentops/merge.py": ["tests/test_b.py::t3"],       # in core_manifest.txt
    "tools/agentops/other.py": ["tests/test_b.py::t4"],       # not in core_manifest.txt
    "tools/agentops/core_check.py": [CC],
    "tests/test_agentops_no_window.py": ["tests/test_agentops_no_window.py::test_guard"],  # #950: any tools/agentops change
}


def _core_rig(tmp_path):
    r = Rig(tmp_path)
    (r.mdir / "testmondata").unlink()
    build_db(r.mdir / "testmondata", CC_DEPS)
    return r


def test_row7_merge_py_selects_the_core_check_test(tmp_path):
    s = _core_rig(tmp_path).sel({"tools/agentops/merge.py": "x = 2\n"})
    assert not s.full and CC in s.ids, (s.full, len(s.ids), s.line)


def test_a_non_manifest_file_does_not_add_it(tmp_path):
    assert "tools/agentops/merge.py" in read_manifest()
    s = _core_rig(tmp_path).sel({"tools/agentops/other.py": "x = 2\n"})
    assert not s.full and "tests/test_b.py::t4" in s.ids and CC not in s.ids


def test_manifest_read_failure_is_the_full_fallback(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError("manifest gone")
    monkeypatch.setattr("tools.agentops.core_check.read_manifest", boom)
    s = _core_rig(tmp_path).sel({"tools/agentops/merge.py": "x = 2\n"})
    assert s.full and "selection failed" in s.reason, (s.full, s.reason)
