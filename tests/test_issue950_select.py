"""#950: a change under tools/agentops/ selects tests/test_agentops_no_window.py. The guard reads every
walked module as text (ast), which neither the testmon map nor the audit-hook read map records, so
no dependency edge can select it on its own. Rig and helpers are the synthetic map of #690's test.
The guard is committed BEFORE the map's commit, so rule B (a test file younger than the map) cannot
be what selects it: only the tools/agentops/ rule can."""
from tools.agentops import test_select as ts
from test_issue690_select import Rig, commit  # noqa: E402  (tests/ is on sys.path, as for #681)

GUARD = "tests/test_agentops_no_window.py"


def _rig_with_guard_before_map(tmp_path) -> Rig:
    r = Rig(tmp_path)
    r.c0 = commit(r.root, {"tools/agentops/orphans.py": "1\n", GUARD: "def test_guard(): pass\n"})
    ts.write_meta(r.mdir, {"map_commit": r.c0, "total": 100, "built_at": "now", "last_green_commit": r.c0})
    return r


def test_change_under_tools_agentops_selects_the_no_window_guard(tmp_path):
    s = _rig_with_guard_before_map(tmp_path).sel({"tools/agentops/orphans.py": "2\n"})
    assert not s.full
    assert GUARD in s.ids, s.ids


def test_change_outside_tools_agentops_does_not_select_the_guard(tmp_path):
    r = _rig_with_guard_before_map(tmp_path)
    s = r.sel({"src/a.py": "2"})
    assert not s.full and GUARD not in s.ids
    assert s.ids == ["tests/test_a.py::t1", "tests/test_a.py::t2", "tests/test_b.py::t3"]
