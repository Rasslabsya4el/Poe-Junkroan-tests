"""#1118: a test file whose ids are parametrized from repo content (docs) runs whole, never by recorded id.

tests/test_agent_docs_refs.py builds its ids from docs/agents/**/*.md and .claude/agents/**/*.md (file and line in
the id), so an id recorded in the map vanishes once those docs change on main; pytest answers ``not found`` and the
merge read it as a red suite. Rig and helpers are the synthetic map of #690's test."""
import json

from tools.agentops import test_select as ts
from test_issue690_select import Rig, build_db, commit  # noqa: E402  (tests/ is on sys.path, as for #681)

PARAM = "tests/test_agent_docs_refs.py"
STALE = f"{PARAM}::test_section_reference_resolves_to_a_heading[docs/agents/orch.md:12-stale-id]"


def _rig(tmp_path) -> Rig:
    r = Rig(tmp_path)
    r.c0 = commit(r.root, {PARAM: "def test_section_reference_resolves_to_a_heading(): pass\n"})
    mdir = tmp_path / "map_param"
    mdir.mkdir()
    build_db(mdir / "testmondata", {
        "src/a.py": [STALE, "tests/test_a.py::t1"],
        "src/b.py": ["tests/test_b.py::t4"],
    })
    (mdir / "reads").mkdir()
    (mdir / "reads" / "reads-1.json").write_text(json.dumps({"files": {}, "dirs": {}}), encoding="utf-8")
    ts.write_meta(mdir, {"map_commit": r.c0, "total": 100, "built_at": "now", "last_green_commit": r.c0})
    r.mdir = mdir
    return r


def test_selected_param_file_runs_whole_without_its_recorded_ids(tmp_path):
    s = _rig(tmp_path).sel({"src/a.py": "2"})
    assert not s.full
    assert PARAM in s.ids, s.ids
    assert not [i for i in s.ids if i.startswith(PARAM + "::")], s.ids
    assert "tests/test_a.py::t1" in s.ids  # other mapped ids stay by id
    assert s.line == f"selected 2 of 100 tests (map {s.map_commit[:8]})", s.line  # t1 + the file's one mapped test


def test_unselected_param_file_is_not_added(tmp_path):
    s = _rig(tmp_path).sel({"src/b.py": "2"})
    assert not s.full and s.ids == ["tests/test_b.py::t4"], s.ids
