"""#959: a diff with a file under ``mods/<mod>/`` selects that mod's ``bin/test_*.py`` pytest files.

Synthetic map as in #690 (tests/test_issue690_select.py): the pane's ``hooks/register.tsx`` is read by one test
of the map, the pane's bin tests are not in the map at all (the merge suite never ran them).
"""
import json

from tools.agentops import test_select as ts
from tests.test_issue690_select import Rig, commit

BIN = "mods/pob-slots/bin/test_generic_words_pane.py"
BIN_OTHER = "mods/pob-slots/bin/test_other.py"


def _rig(tmp_path):
    r = Rig(tmp_path)
    base = commit(r.root, {
        BIN: "def test_w(): pass\n",
        BIN_OTHER: "def test_o(): pass\n",
        "mods/pob-slots/bin/collect.py": "x = 1\n",
        "mods/pob-slots/hooks/register.tsx": "// r\n",
        "mods/pob-slots/hooks/kit.tsx": "// k\n",
        "mods/other/bin/test_z.py": "def test_z(): pass\n",
    })
    r.c0 = base  # the map is built at this commit: the mods files are known to the diff base
    ts.write_meta(r.mdir, {"map_commit": base, "total": 100, "built_at": "now", "last_green_commit": base})
    (r.mdir / "reads" / "reads-1.json").write_text(json.dumps({
        "files": {"tests/test_b.py::t3": ["config/c.json", "mods/pob-slots/hooks/register.tsx"]},
        "dirs": {"tests/test_b.py::t4": ["tests/fixtures"]}}), encoding="utf-8")
    return r


def test_hook_diff_selects_the_pane_bin_test(tmp_path):  # acceptance (1): red before the change
    s = _rig(tmp_path).sel({"mods/pob-slots/hooks/register.tsx": "// r2\n"})
    assert not s.full
    assert BIN in s.ids
    assert BIN_OTHER in s.ids           # every bin test of the touched mod
    assert "mods/other/bin/test_z.py" not in s.ids  # another mod's bin tests stay out
    assert "tests/test_b.py::t3" in s.ids  # the map's own selection stays


def test_bin_tests_are_counted_in_the_selected_line(tmp_path):  # acceptance (3): the line prints them
    r = _rig(tmp_path)
    s = r.sel({"mods/pob-slots/hooks/register.tsx": "// r2\n"})
    # t3 (mapped) + one def in each of the two bin files; the bin files are not in the map's tests, so they are
    # counted as added since the map (test_select.py: new_tests = defs of every whole file the map does not know)
    assert s.line == f"selected 3 of 100 tests in the map (+2 added since, map {r.c0[:8]})"


def test_changed_bin_test_file_is_not_unmapped(tmp_path):  # the changed bin test itself is run, not "no test reaches"
    s = _rig(tmp_path).sel({BIN_OTHER: "def test_o(): pass\n#"})
    assert not s.full and s.reason == ""
    assert BIN_OTHER in s.ids and BIN in s.ids


def test_added_bin_test_file_counts_its_tests_once(tmp_path):
    r = _rig(tmp_path)
    s = r.sel({"mods/pob-slots/bin/test_new.py": "def test_a(): pass\n\ndef test_b(): pass\n"})
    # 2 new + 1 + 1 in the two older bin files: all four are whole files the map does not know, so all are "added"
    assert "mods/pob-slots/bin/test_new.py" in s.ids and s.new_tests == 4
    assert s.line == f"selected 4 of 100 tests in the map (+4 added since, map {r.c0[:8]})"


def test_diff_outside_mods_selects_no_bin_test(tmp_path):  # acceptance (2): same set as before the rule
    r = _rig(tmp_path)
    s = r.sel({"src/a.py": "2"})
    assert s.ids == ["tests/test_a.py::t1", "tests/test_a.py::t2", "tests/test_b.py::t3"]
    assert s.line == f"selected 3 of 100 tests (map {r.c0[:8]})"
    assert not any(i.startswith("mods/") for i in s.ids)
