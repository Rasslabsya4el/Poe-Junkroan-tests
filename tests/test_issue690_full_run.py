"""#690 unit 2: the full run on main, all stubbed (stub `python -m pytest` on PYTHONPATH, recorder for gh, a tiny git repo)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agentops import full_run as fr
from tools.agentops import merge as merge_mod
from tools.agentops.test_select import map_dir, read_meta

STUB = '''
import json, os, sqlite3, sys
from pathlib import Path
home = Path(os.environ["STUB_HOME"])
beh = json.loads((home / "behavior.json").read_text())
argv = sys.argv[1:]
with open(home / "argv.log", "a") as fh:
    fh.write(json.dumps(argv) + "\\n")
recheck = any("::" in a for a in argv)
if recheck:
    fail = beh.get("recheck_fail", [])
else:
    fail = beh.get("fail", [])
    if "--testmon" in argv:
        con = sqlite3.connect(os.environ["TESTMON_DATAFILE"])
        con.executescript("create table test_execution(id integer primary key, test_name text);"
                          "create table file_fp(id integer primary key, filename text);"
                          "create table test_execution_file_fp(test_execution_id int, fingerprint_id int);")
        for i in range(beh.get("total", 5)):
            con.execute("insert into test_execution(test_name) values (?)", ("tests/test_x.py::t%d" % i,))
        con.commit(); con.close()
        out = Path(os.environ["SELREPLAY_OUT"]); out.mkdir(parents=True, exist_ok=True)
        (out / "reads-1.json").write_text("{}")
    if beh.get("pending_on_first") and not (home / "pending_done").exists():
        (home / "pending_done").write_text("x")
        Path(os.environ["STUB_PENDING"]).write_text("whatever")
for f in fail:
    print("FAILED " + f)
if fail:
    print("%d failed, 3 passed in 1.00s" % len(fail))
    sys.exit(1)
print("3 passed, %d skipped in 1.00s" % beh["skipped"] if "skipped" in beh else "3 passed in 1.00s")
'''


def sh(root, *a):
    return subprocess.run(["git", "-C", str(root), *a], capture_output=True, text=True, check=True).stdout.strip()


def commit(root, name, content="x"):
    (Path(root) / name).write_text(content, encoding="utf-8")
    sh(root, "add", "-A")
    sh(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", f"add {name}")
    return sh(root, "rev-parse", "HEAD")


class Env:
    pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    c1 = commit(repo, "a.txt")
    sh(repo, "checkout", "-q", "-b", "orch-1")
    commit(repo, "b.txt")
    sh(repo, "checkout", "-q", "main")
    commit(repo, "c.txt")
    sh(repo, "-c", "user.name=t", "-c", "user.email=t@t", "merge", "--no-ff", "-q", "orch-1",
       "-m", "Merge branch 'orch-1'")
    c3 = sh(repo, "rev-parse", "HEAD")
    home = tmp_path / "stub"
    (home / "pytest").mkdir(parents=True)
    (home / "pytest" / "__main__.py").write_text(STUB, encoding="utf-8")
    (home / "pytest" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(merge_mod, "resolve_suite_workers_probe", lambda: None)
    monkeypatch.setattr(merge_mod, "resolve_suite_shared", lambda: ())
    calls = []

    def gh(args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "https://github.com/x/y/issues/1\n", "")

    e = Env()
    e.repo, e.c1, e.c3, e.home, e.gh_calls = repo, c1, c3, home, calls
    e.cmd = f'"{sys.executable}" -m pytest -q'
    e.suite_env = {"PYTHONPATH": str(home), "STUB_HOME": str(home), "STUB_PENDING": str(fr.pending_path(repo))}

    def behave(**kw):
        (home / "behavior.json").write_text(json.dumps(kw), encoding="utf-8")
    behave()
    e.behave = behave

    def run(commit_, **kw):
        kw.setdefault("resolve_head", lambda: c3)
        return fr.run_full(commit_, root=repo, suite_cmd=e.cmd, suite_env=e.suite_env, gh=gh, **kw)
    e.run = run

    def runs():
        p = home / "argv.log"
        if not p.exists():
            return []
        return [json.loads(l) for l in p.read_text().splitlines() if "--testmon" in l]
    e.runs = runs
    return e


def test_green_run_writes_map_and_meta(env):
    env.behave(total=7)
    assert env.run(env.c1) == 0
    mdir = map_dir(env.repo)
    assert (mdir / "testmondata").is_file() and (mdir / "reads" / "reads-1.json").is_file()
    meta = read_meta(mdir)
    assert meta["map_commit"] == env.c1 and meta["last_green_commit"] == env.c1 and meta["total"] == 7
    assert meta["built_at"]
    argv = env.runs()[0]
    assert "--testmon" in argv and "--testmon-forceselect" in argv and "-rf" in argv
    assert "tools.agentops.test_reads_plugin" in argv
    assert env.gh_calls == []
    assert not fr.lock_path(env.repo).exists()
    assert not list(mdir.parent.glob("test_map.*"))


def test_green_run_records_skipped_count_and_keeps_it_when_absent(env):
    env.behave(total=7, skipped=80)
    assert env.run(env.c1) == 0
    assert read_meta(map_dir(env.repo))["skipped"] == 80
    env.behave(total=7)
    assert env.run(env.c3) == 0
    assert read_meta(map_dir(env.repo))["skipped"] == 80


def test_red_run_opens_one_issue_and_keeps_last_green(env):
    assert env.run(env.c1) == 0
    env.behave(total=9, fail=["tests/test_x.py::t1", "tests/test_x.py::t2"],
               recheck_fail=["tests/test_x.py::t2"])
    assert env.run(env.c3) == 1
    meta = read_meta(map_dir(env.repo))
    assert meta["map_commit"] == env.c3 and meta["last_green_commit"] == env.c1 and meta["total"] == 9
    creates = [c for c in env.gh_calls if c[:2] == ["issue", "create"]]  # #849: a list call precedes it
    assert len(creates) == 1
    args = creates[0]
    assert args[:2] == ["issue", "create"]
    assert args[args.index("--title") + 1] == "Full suite on main is red: tests/test_x.py::t2"
    assert args.count("--label") == 2 and "needs-triage" in args and "area:orchestration" in args
    body = args[args.index("--body") + 1]
    assert "tests/test_x.py::t2" in body and "tests/test_x.py::t1" not in body  # t1 passed the re-check
    assert "Merge branch 'orch-1'" in body and env.c1 in body
    assert body.startswith("## For the human") and "## For the agent" in body


def test_red_without_previous_green_says_so_and_counts_more(env):
    env.behave(fail=["tests/test_x.py::a", "tests/test_x.py::b"],
               recheck_fail=["tests/test_x.py::a", "tests/test_x.py::b"])
    assert env.run(env.c3) == 1
    args = [c for c in env.gh_calls if c[:2] == ["issue", "create"]][0]
    assert args[args.index("--title") + 1] == "Full suite on main is red: tests/test_x.py::a (+1 more)"
    assert "No previous green run" in args[args.index("--body") + 1]
    assert read_meta(map_dir(env.repo))["last_green_commit"] is None


def test_flaky_failure_green_after_recheck(env):
    env.behave(fail=["tests/test_x.py::t1"], recheck_fail=[])
    assert env.run(env.c1) == 0
    assert env.gh_calls == [] and read_meta(map_dir(env.repo))["last_green_commit"] == env.c1


def test_second_call_during_a_run_writes_pending_and_returns_0(env):
    fr.lock_path(env.repo).parent.mkdir(parents=True, exist_ok=True)
    fr.lock_path(env.repo).write_text(json.dumps({"pid": os.getppid(), "started": "now"}), encoding="utf-8")
    assert env.run(env.c1) == 0
    assert fr.pending_path(env.repo).read_text() == env.c1
    assert env.runs() == []
    assert fr.lock_path(env.repo).exists()


def test_dead_pid_lock_is_taken_over(env):
    fr.lock_path(env.repo).parent.mkdir(parents=True, exist_ok=True)
    fr.lock_path(env.repo).write_text(json.dumps({"pid": 4000000, "started": "then"}), encoding="utf-8")
    assert env.run(env.c1) == 0
    assert len(env.runs()) == 1


def test_pending_triggers_one_follow_up_on_the_new_commit_and_not_a_third(env):
    env.behave(pending_on_first=True)
    assert env.run(env.c1) == 0
    assert len(env.runs()) == 2
    assert read_meta(map_dir(env.repo))["map_commit"] == env.c3
    assert not fr.pending_path(env.repo).exists()


def test_pending_for_the_same_commit_runs_nothing_more(env):
    env.behave(pending_on_first=True)
    assert env.run(env.c3) == 0
    assert len(env.runs()) == 1


def test_cli_registers_full_run():
    from tools.agentops import cli
    with pytest.raises(SystemExit) as e:
        cli.main(["full-run", "--help"])
    assert e.value.code == 0
