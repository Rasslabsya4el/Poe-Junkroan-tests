"""#690 unit 1: select_for_diff on a synthetic map (sqlite in testmon's schema, a reads dump, a tiny git repo)."""
import json
import sqlite3
import subprocess
from pathlib import Path

from tools.agentops import test_select as ts

DEPS = {  # file -> tests that executed it
    "src/a.py": ["tests/test_a.py::t1", "tests/test_a.py::t2", "tests/test_b.py::t3"],
    "src/b.py": ["tests/test_b.py::t4"],
    "tests/test_a.py": ["tests/test_a.py::t1", "tests/test_a.py::t2"],
    "tests/test_b.py": ["tests/test_b.py::t3", "tests/test_b.py::t4"],
}
ALL = sorted({t for v in DEPS.values() for t in v})


def sh(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()


def commit(root, files: dict, delete=(), msg="c"):
    for f, c in files.items():
        p = Path(root) / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(c, encoding="utf-8")
    for f in delete:
        (Path(root) / f).unlink()
    sh(root, "add", "-A")
    sh(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", msg)
    return sh(root, "rev-parse", "HEAD")


def build_db(path, deps):
    con = sqlite3.connect(path)
    con.executescript("create table test_execution(id integer primary key, test_name text);"
                      "create table file_fp(id integer primary key, filename text);"
                      "create table test_execution_file_fp(test_execution_id int, fingerprint_id int);")
    tid, fid = {}, {}
    for f, ts_ in deps.items():
        fid[f] = len(fid) + 1
        con.execute("insert into file_fp values (?,?)", (fid[f], f))
        for t in ts_:
            if t not in tid:
                tid[t] = len(tid) + 1
                con.execute("insert into test_execution values (?,?)", (tid[t], t))
            con.execute("insert into test_execution_file_fp values (?,?)", (tid[t], fid[f]))
    con.commit()
    con.close()


class Rig:
    def __init__(self, tmp_path, green="map"):
        self.root = tmp_path / "repo"
        self.root.mkdir(parents=True)
        sh(self.root, "init", "-q")
        self.c0 = commit(self.root, {"src/a.py": "1", "src/b.py": "1", "tests/test_a.py": "def test_x(): pass\n",
                                     "config/c.json": "{}", "tests/fixtures/f.xml": "x", "docs/d.md": "d"})
        self.mdir = tmp_path / "map"  # outside the repo (var/ is git-ignored in real life)
        assert ts.map_dir(self.root) == self.root / "var" / "agentops" / "test_map"
        self.mdir.mkdir(parents=True)
        build_db(self.mdir / "testmondata", DEPS)
        (self.mdir / "reads").mkdir()
        # config/ is a DATA_CHANGE_PREFIX (core, #41 rule 2): a change there is the full suite, so the opener is a src/ json
        (self.mdir / "reads" / "reads-1.json").write_text(json.dumps({
            "files": {"tests/test_b.py::t3": ["src/data.json"]},
            "dirs": {"tests/test_b.py::t4": ["tests/fixtures"]}}), encoding="utf-8")
        ts.write_meta(self.mdir, {"map_commit": self.c0, "total": 100, "built_at": "now",
                                  "last_green_commit": self.c0 if green == "map" else green})

    def sel(self, files: dict, delete=()):
        head = commit(self.root, files, delete)
        out = ts.select_for_diff(self.root, self.c0, head, self.mdir)
        sh(self.root, "reset", "-q", "--hard", self.c0)  # every sel() is one branch over c0
        return out


def test_py_change_selects_what_the_map_says(tmp_path):
    s = Rig(tmp_path).sel({"src/a.py": "2"})
    assert not s.full and s.ids == ["tests/test_a.py::t1", "tests/test_a.py::t2", "tests/test_b.py::t3"]
    assert s.line == f"selected 3 of 100 tests (map {s.map_commit[:8]})" and s.new_tests == 0


def test_data_file_selects_openers_and_dir_listers(tmp_path):
    r = Rig(tmp_path)
    assert r.sel({"src/data.json": '{"a":1}'}).ids == ["tests/test_b.py::t3"]
    assert r.sel({"config/c.json": '{"a":1}'}).reason == "data change"  # core: config/ is a data-change prefix
    s = r.sel({"tests/fixtures/new.xml": "n"})
    assert s.ids == ["tests/test_b.py::t4"] and not s.full


def test_unknown_modified_py_nobody_reaches_selects_nothing_and_is_named(tmp_path):  # #737 rule C (was: full suite)
    s = Rig(tmp_path).sel({"src/a.py": "2", "src/zzz.py": "1"})  # zzz added: fine
    assert not s.full
    r = Rig(tmp_path / "x")
    commit(r.root, {"src/new.py": "1"})  # now known to git but not to the map
    r.c0 = sh(r.root, "rev-parse", "HEAD")
    s = r.sel({"src/new.py": "2"})
    assert not s.full and s.reason == "no test reaches src/new.py" and s.ids == []
    assert s.line == f"selected 0 of 100 tests (map {s.map_commit[:8]}); {s.reason}"


def test_blind_data_file_full_docs_only_empty(tmp_path):
    r = Rig(tmp_path)
    s = r.sel({"tools/blind.txt": "x"})
    assert s.full and "tools/blind.txt" in s.reason
    s = r.sel({"docs/d.md": "changed"})
    assert not s.full and s.ids == [] and s.line == f"selected 0 of 100 tests (map {r.c0[:8]})"


def test_no_map_full(tmp_path):
    r = Rig(tmp_path)
    (r.mdir / "testmondata").unlink()
    s = r.sel({"src/a.py": "2"})
    assert s.full and s.reason == "no map"
    r2 = Rig(tmp_path / "y")
    (r2.mdir / "meta.json").write_text("{not json", encoding="utf-8")
    assert r2.sel({"src/a.py": "2"}).reason == "no map"


def test_no_green_full_and_a_newer_last_green_selects_as_usual(tmp_path):
    # core update 55cb3006 dropped the "map older than the last green full run" rule: a newer last green is not full
    r = Rig(tmp_path, green=None)
    assert r.sel({"src/a.py": "2"}).reason == "no green full run"
    r2 = Rig(tmp_path / "z")
    newer = commit(r2.root, {"src/b.py": "9"})
    ts.write_meta(r2.mdir, {**ts.read_meta(r2.mdir), "last_green_commit": newer})
    s = ts.select_for_diff(r2.root, r2.c0, newer, r2.mdir)
    assert not s.full and s.ids == ["tests/test_b.py::t4"]


def test_selection_failure_full(tmp_path):
    r = Rig(tmp_path)
    (r.mdir / "testmondata").write_bytes(b"garbage, not sqlite" * 50)
    s = r.sel({"src/a.py": "2"})
    assert s.full and s.reason.startswith("selection failed:") and "\n" not in s.reason


def test_added_and_changed_test_files_are_in_ids(tmp_path):
    r = Rig(tmp_path)
    s = r.sel({"tests/test_x.py": "def test_p(): pass\n\ndef test_q(): pass\n",
               "tests/test_a.py": "def test_x(): pass\n#"})
    assert s.new_tests == 2 and not s.full
    assert s.ids == ["tests/test_a.py", "tests/test_x.py"]
    assert s.line == f"selected 4 of 100 tests in the map (+2 added since, map {r.c0[:8]})"  # 2 mapped in test_a + 2 new
    s = r.sel({"src/a.py": "3", "tests/test_a.py": "def test_x(): pass\n#2"})
    assert s.ids == ["tests/test_b.py::t3", "tests/test_a.py"] and s.new_tests == 0
