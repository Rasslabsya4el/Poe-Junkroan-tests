"""#690 unit 3: the merge suite runs only the selected tests (an @argsfile), falls back to the full suite on any
doubt, runs no pytest on an empty selection, and spawns the full run on main after a landing.

A bare repo stands in for GitHub (helpers of test_agentops_merge); the map is a synthetic testmon sqlite in the
main checkout's ``var/agentops/test_map``; the suite is a stub that records its argv and its argsfile."""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from timing_bound import bound

from tests.test_agentops_merge import _commit, _git, _local_main_head, _push_branch, _world
from tools.agentops import merge as merge_module
from tools.agentops import test_select as ts
from tools.agentops.merge import _selected_cmd, run_merge

STUB = """\
import json, pathlib, sys
record, flag, rest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3:]
lines = []
for a in rest:
    if a.startswith("@"):
        lines += pathlib.Path(a[1:]).read_text(encoding="utf-8").splitlines()
with record.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps({"argv": rest, "args": lines}) + chr(10))
if flag.exists():
    for i in [a for a in rest + lines if "::" in a and not a.startswith("-")]:
        print("FAILED " + i + " - boom")
    print("2 failed in 0.1s")
    sys.exit(1)
print("2 passed in 0.1s")
"""

ID_PLAIN = "tests/test_a.py::test_one"
ID_SPACE = "tests/test_a.py::test_p[a b]"
ID_NEST = "tests/test_a.py::test_p[c[d]]"
DEPS = {"src/a.py": [ID_PLAIN, ID_SPACE, ID_NEST], "tests/test_a.py": [ID_PLAIN, ID_SPACE, ID_NEST]}


def _build_db(path: Path, deps: dict) -> None:
    con = sqlite3.connect(path)
    con.executescript("create table test_execution(id integer primary key, test_name text);"
                      "create table file_fp(id integer primary key, filename text);"
                      "create table test_execution_file_fp(test_execution_id int, fingerprint_id int);")
    tid, fid = {}, {}
    for f, names in deps.items():
        fid[f] = len(fid) + 1
        con.execute("insert into file_fp values (?,?)", (fid[f], f))
        for t in names:
            if t not in tid:
                tid[t] = len(tid) + 1
                con.execute("insert into test_execution values (?,?)", (tid[t], t))
            con.execute("insert into test_execution_file_fp values (?,?)", (tid[t], fid[f]))
    con.commit()
    con.close()


class Rig:
    def __init__(self, tmp_path: Path, monkeypatch, *, with_map: bool = True, select: bool = True):
        self.tmp = tmp_path
        self.bare, self.checkout = _world(tmp_path)
        seed = tmp_path / "seed"
        (seed / "src").mkdir()
        (seed / "tests").mkdir()
        _commit(seed, "src/a.py", "a = 1\n", "add a")
        _commit(seed, "tests/test_a.py", "def test_one(): pass\n", "add test_a")
        (seed / "docs").mkdir()
        _commit(seed, "docs/note.md", "words\n", "add docs")
        _git("push", "-q", "origin", "main", cwd=seed)
        _git("pull", "-q", "--ff-only", cwd=self.checkout)
        self.c0 = _local_main_head(self.checkout)
        self.mdir = ts.map_dir(self.checkout)
        if with_map:
            (self.mdir / "reads").mkdir(parents=True)
            _build_db(self.mdir / "testmondata", DEPS)
            ts.write_meta(self.mdir, {"map_commit": self.c0, "total": 50, "built_at": "now",
                                      "last_green_commit": self.c0})
        self.record, self.flag = tmp_path / "record.jsonl", tmp_path / "fail.flag"
        stub = tmp_path / "stub.py"
        stub.write_text(STUB, encoding="utf-8")
        self.cmd = (f'"{sys.executable}" "{stub}" "{self.record}" "{self.flag}" '
                    f'-m pytest tests -q -m "not slow and not pob"')
        self.spawned: list[tuple[Path, str]] = []
        self.log = tmp_path / "merge.log"
        # tmp_path holds "pytest-of-<user>": only `-m pytest` marks the stub as a pytest command
        monkeypatch.setattr(merge_module, "_PYTEST_RE", re.compile(r"-m pytest"))
        monkeypatch.setattr(merge_module, "resolve_suite_workers_probe", lambda: None)
        monkeypatch.setattr(merge_module, "resolve_select_tests", lambda: select)
        monkeypatch.setattr(merge_module, "_spawn_map_run",
                            lambda cwd, sha: self.spawned.append((cwd, sha)) or "")

    def land(self, branch: str, file_name: str, content: str):
        _push_branch(self.bare, self.tmp, f"w-{branch}", branch, file_name, content)
        _git("fetch", "-q", "origin", cwd=self.checkout)
        return run_merge(f"origin/{branch}", self.cmd, cwd=self.checkout, lock_path=self.tmp / "merge.lock",
                         lock_timeout=30, suite_output_dir=self.tmp / "out", merge_log_path=self.log)

    def calls(self) -> list[dict]:
        if not self.record.exists():
            return []
        return [json.loads(x) for x in self.record.read_text(encoding="utf-8").splitlines()]


def _line1(result) -> str:
    return Path(result.suite_output_path).read_text(encoding="utf-8").splitlines()[0]


def test_a_selected_run_gets_the_argsfile_with_exactly_the_selected_ids(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    result = rig.land("feature-a", "src/a.py", "a = 2\n")
    assert result.ok and result.reason == "pushed", result.message
    (call,) = rig.calls()
    assert call["args"] == sorted([ID_PLAIN, ID_SPACE, ID_NEST])
    assert "tests" not in call["argv"] and any(a.startswith("@") and a.endswith(".out.args") for a in call["argv"])
    assert call["argv"][:2] == ["-m", "pytest"] and "not slow and not pob" in call["argv"]  # the flags stay
    assert _line1(result) == f"selected 3 of 50 tests (map {rig.c0[:8]})"


def test_b_no_map_runs_the_full_command(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, with_map=False)
    result = rig.land("feature-b", "src/a.py", "a = 2\n")
    assert result.ok, result.message
    (call,) = rig.calls()
    assert call["args"] == [] and "tests" in call["argv"] and not any(a.startswith("@") for a in call["argv"])
    assert _line1(result) == "full suite: no map"


def test_b2_shape_not_recognised_falls_back(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.cmd = rig.cmd.replace("pytest tests -q", "pytest -q tests")
    result = rig.land("feature-b2", "src/a.py", "a = 2\n")
    assert result.ok, result.message
    (call,) = rig.calls()
    assert call["args"] == [] and _line1(result) == "full suite: suite command shape not recognised"


def test_c_zero_selected_runs_no_pytest_and_lands(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    result = rig.land("feature-c", "docs/note.md", "other words\n")
    assert result.ok and result.reason == "pushed", result.message
    assert rig.calls() == []
    assert _line1(result) == f"selected 0 of 50 tests (map {rig.c0[:8]})"
    # bound = max(floor, factor x a CPU spin timed here) (#826)
    bound_s = bound(5.0, 33.0)
    assert result.suite_duration < bound_s, f"suite_duration {result.suite_duration:.2f}s, bound {bound_s:.2f}s"
    assert rig.spawned and rig.spawned[0][1] == _local_main_head(rig.checkout)


def test_d_failing_selected_test_is_red_and_rechecked_once(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.flag.write_text("fail", encoding="utf-8")
    result = rig.land("feature-d", "src/a.py", "a = 2\n")
    assert not result.ok and result.reason == "red-suite"
    # (FAILED_ID_RE takes `\S+`, so the id with a space is cut to `...[a`: the old re-check's own limit, not this unit's)
    assert ID_PLAIN in result.failed_tests and ID_NEST in result.failed_tests
    first, recheck = rig.calls()  # the selected run, then the ONE re-check of the failed ids
    assert first["args"] and recheck["args"] == [] and recheck["argv"][:3] == ["-m", "pytest", ID_PLAIN]
    assert rig.spawned == []  # a red result starts no full run
    assert f"selected 3 of 50 tests (map {rig.c0[:8]})" in rig.log.read_text(encoding="utf-8")


def test_e_merge_log_line_carries_the_text_next_to_the_suite_time(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.land("feature-e", "src/a.py", "a = 2\n")
    (line,) = rig.log.read_text(encoding="utf-8").splitlines()
    assert re.search(rf"\| suite [\d.]+ s \| 0 failed \| selected 3 of 50 tests \(map {rig.c0[:8]}\) \| output ", line)
    # merge_status and the restart estimate still read the line, and a selected run is no full-suite yardstick
    from tools.agentops.merge_status import _log_facts
    assert _log_facts(rig.log) == ([], None)
    assert merge_module.last_full_suite_by_workers(rig.log) == {}
    (rig.mdir / "testmondata").unlink()
    rig.land("feature-e2", "src/a.py", "a = 3\n")
    full = rig.log.read_text(encoding="utf-8").splitlines()[-1]
    assert "| full suite: no map | output " in full
    assert len(_log_facts(rig.log)[0]) == 1 and len(merge_module.last_full_suite_by_workers(rig.log)) == 1


def test_f_setting_off_is_todays_command_untouched(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, select=False)
    result = rig.land("feature-f", "src/a.py", "a = 2\n")
    assert result.ok, result.message
    (call,) = rig.calls()
    assert call["argv"] == ["-m", "pytest", "tests", "-q", "-m", "not slow and not pob", "-rf"]
    assert result.selection == "" and rig.spawned == []
    assert not Path(result.suite_output_path).read_text(encoding="utf-8").startswith(("selected", "full suite"))
    assert "selected" not in rig.log.read_text(encoding="utf-8") and "full suite" not in rig.log.read_text(encoding="utf-8")


def test_g_full_run_spawned_once_with_the_pushed_sha_after_a_landing(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    result = rig.land("feature-g", "src/a.py", "a = 2\n")
    assert result.ok
    assert rig.spawned == [(rig.checkout, _local_main_head(rig.checkout))]
    assert _git("rev-parse", "origin/main", cwd=rig.checkout).stdout.strip() == rig.spawned[0][1]


def test_g2_spawn_failure_is_logged_and_never_fails_the_merge(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    monkeypatch.setattr(merge_module, "_spawn_map_run", lambda cwd, sha: "cannot start python")
    result = rig.land("feature-g2", "src/a.py", "a = 2\n")
    assert result.ok and result.reason == "pushed"
    assert "| map-run-not-started |" in rig.log.read_text(encoding="utf-8")


def test_spawn_command_is_the_cli_form_hidden_not_waited_for(tmp_path, monkeypatch):
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen["argv"], seen["kw"] = argv, kw

    monkeypatch.setattr(merge_module.subprocess, "Popen", FakePopen)
    assert merge_module._spawn_map_run(tmp_path, "abc123") == ""
    assert seen["argv"] == [sys.executable, "-m", "tools.agentops", "map-run", "--commit", "abc123", "--detach"]
    assert seen["kw"]["creationflags"] == merge_module.no_window_flags() and seen["kw"]["cwd"] == str(tmp_path)


def test_h_argsfile_keeps_double_colon_spaces_and_brackets_on_a_real_pytest(tmp_path):
    toy = tmp_path / "toy"
    (toy / "tests").mkdir(parents=True)
    (toy / "tests" / "test_t.py").write_text(
        "import pytest\n"
        "@pytest.mark.parametrize('v', ['a b', 'c[d]', 'e'])\n"
        "def test_p(v): pass\n"
        "def test_other(): pass\n", encoding="utf-8")
    ids = ["tests/test_t.py::test_p[a b]", "tests/test_t.py::test_p[c[d]]"]
    cmd = _selected_cmd(f'"{sys.executable}" -m pytest tests -q -p no:cacheprovider', ids, tmp_path / "args dir" / "x.out.args")
    assert cmd is not None and "@" in cmd and " tests " not in cmd
    done = subprocess.run(cmd, shell=True, cwd=toy, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "2 passed" in re.sub(r"\x1b\[[0-9;]*m", "", done.stdout), done.stdout
