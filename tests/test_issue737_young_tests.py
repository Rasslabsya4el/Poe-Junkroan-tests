"""#737 rule B: a test file added or changed on main between the map's commit and ``base`` runs whole in a selection."""
from tools.agentops import test_select as ts
from tests.test_issue690_select import Rig, commit, sh


def _rig_with_young(tmp_path):
    r = Rig(tmp_path)  # map commit = r.c0
    base = commit(r.root, {"tests/test_young.py": "def test_y1(): pass\n\ndef test_y2(): pass\n",
                           "tests/test_a.py": "def test_x(): pass\n# changed on main\n"})
    return r, base


def test_row6_test_added_to_main_after_the_map_is_selected_whole(tmp_path):
    r, base = _rig_with_young(tmp_path)
    head = commit(r.root, {"src/a.py": "2"})
    s = ts.select_for_diff(r.root, base, head, r.mdir)
    assert not s.full, s.reason
    assert "tests/test_young.py" in s.ids  # added after the map: no rows, runs whole
    assert "tests/test_a.py" in s.ids      # changed after the map: whole, its mapped ids not repeated
    assert not any(i.startswith("tests/test_a.py::") for i in s.ids)
    assert s.line.startswith("selected "), s.line


def test_young_file_counted_once_when_the_branch_also_changes_it(tmp_path):
    r, base = _rig_with_young(tmp_path)
    one = ts.select_for_diff(r.root, base, commit(r.root, {"src/a.py": "2"}), r.mdir)
    sh(r.root, "reset", "-q", "--hard", base)
    two = ts.select_for_diff(r.root, base, commit(r.root, {"tests/test_young.py": "def test_y1(): pass\n\ndef test_y2(): pass\n# b\n"}), r.mdir)
    assert two.ids.count("tests/test_young.py") == 1 and "tests/test_young.py" in one.ids


def test_young_deleted_test_is_not_selected(tmp_path):
    r, base = _rig_with_young(tmp_path)
    head = commit(r.root, {"src/a.py": "2"}, delete=["tests/test_young.py"])
    s = ts.select_for_diff(r.root, base, head, r.mdir)
    assert not s.full and "tests/test_young.py" not in s.ids


def test_unreachable_map_commit_falls_back_to_full(tmp_path):
    r, base = _rig_with_young(tmp_path)
    ts.write_meta(r.mdir, {**ts.read_meta(r.mdir), "map_commit": "f" * 40})
    s = ts.select_for_diff(r.root, base, commit(r.root, {"src/a.py": "2"}), r.mdir)
    assert s.full and s.reason.startswith("selection failed") or s.full, s.reason


def test_row11_test_file_deleted_on_main_after_the_map_selects_none_of_its_ids(tmp_path):
    r = Rig(tmp_path)  # map commit = r.c0; the map ties tests/test_a.py::t1,t2 to src/a.py
    base = commit(r.root, {}, delete=["tests/test_a.py"])
    head = commit(r.root, {"src/a.py": "2"})
    s = ts.select_for_diff(r.root, base, head, r.mdir)
    assert not s.full, s.reason
    assert not any(i.split("::", 1)[0] == "tests/test_a.py" for i in s.ids), s.ids


def test_row11_test_file_renamed_on_main_runs_whole_under_its_new_name(tmp_path):
    r = Rig(tmp_path)
    sh(r.root, "mv", "tests/test_a.py", "tests/test_a2.py")
    base = commit(r.root, {})
    head = commit(r.root, {"src/a.py": "2"})
    s = ts.select_for_diff(r.root, base, head, r.mdir)
    assert not s.full, s.reason
    assert "tests/test_a2.py" in s.ids and not any(i.startswith("tests/test_a.py") for i in s.ids), s.ids
