import subprocess
import sys

from junkroan.runs import self_restart as sr
from junkroan.runs.self_restart import REPLACES_ENV, WATCHED_PATHS, RestartWatch


class FakeGit:
    def __init__(self, heads, diffs=None, fail=False):
        self.heads = list(heads)
        self.diffs = diffs or {}
        self.fail = fail
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if self.fail:
            raise RuntimeError("boom")
        if args[0] == "rev-parse":
            return self.heads.pop(0) + "\n"
        paths = args[args.index("--") + 1 :]
        names = self.diffs.get(args[2], "").splitlines()
        kept = [n for n in names if any(n == q or n.startswith(q + "/") for q in paths)]
        return "\n".join(kept)

    def diff_calls(self):
        return [c for c in self.calls if c[0] == "diff"]


def test_head_unchanged():
    git = FakeGit(["A"])
    assert RestartWatch("A", git).due() is None
    assert git.diff_calls() == []


def test_clean_head_cached():
    git = FakeGit(["B", "B"], {"A..B": "\n"})
    w = RestartWatch("A", git)
    assert w.due() is None
    assert w.due() is None
    assert len(git.diff_calls()) == 1


def test_watched_change():
    git = FakeGit(["B"], {"A..B": "src/junkroan/runs/daemon.py\n"})
    assert RestartWatch("A", git).due() == ("A", "B")
    assert git.diff_calls() == [["diff", "--name-only", "A..B", "--", *WATCHED_PATHS]]


def test_agentops_change_is_watched():
    git = FakeGit(["B"], {"A..B": "tools/agentops/dispatch.py"})
    assert RestartWatch("A", git).due() == ("A", "B")


def test_run_queue_script_change_is_watched():
    """#920: the daemon loads scripts/run_queue.py by path, so a change to only it restarts the daemon."""
    git = FakeGit(["B"], {"A..B": "scripts/run_queue.py"})
    assert RestartWatch("A", git).due() == ("A", "B")


def test_every_path_loaded_script_is_watched():
    """#920: each script the daemon loads by file path at runtime is a watched path."""
    for script in ("scripts/run_queue.py", "scripts/compare_runs.py", "scripts/benchmark.py"):
        assert script in WATCHED_PATHS
        assert RestartWatch("A", FakeGit(["B"], {"A..B": script})).due() == ("A", "B")


def test_unwatched_file_next_to_scripts_not_watched():
    git = FakeGit(["B"], {"A..B": "docs/x.md\nscripts/other_tool.py"})
    assert RestartWatch("A", git).due() is None


def test_docs_only_change_not_watched():
    git = FakeGit(["B"], {"A..B": "docs/STATE.md"})
    assert RestartWatch("A", git).due() is None


def test_clean_then_changed():
    git = FakeGit(["B", "C"], {"A..B": "", "A..C": "scripts/runs.py\n"})
    w = RestartWatch("A", git)
    assert w.due() is None
    assert w.due() == ("A", "C")


def test_git_failure_logged():
    lines = []
    w = RestartWatch("A", FakeGit([], fail=True), log=lines.append)
    assert w.due() is None
    assert len(lines) == 1 and "git failed" in lines[0]


def test_respawn():
    seen = {}

    class P:
        pid = 4242

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return P()

    assert sr.respawn(["x.py", "--a"], executable="py", popen=popen, pid=7) == 4242
    assert seen["cmd"] == ["py", "x.py", "--a"]
    assert seen["kw"]["env"][REPLACES_ENV] == "7"
    assert seen["kw"]["stdin"] == subprocess.DEVNULL
    if sys.platform == "win32":
        assert seen["kw"]["creationflags"] == (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        assert seen["kw"]["start_new_session"] is True


class Clock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s
        self.sleeps += 1


def test_wait_no_env():
    called = []
    assert sr.wait_for_predecessor({}, lambda p: called.append(p) or True) is None
    assert sr.wait_for_predecessor({REPLACES_ENV: "x"}, lambda p: called.append(p)) is None
    assert called == []


def test_wait_dies_after_three_polls():
    c = Clock()
    answers = iter([True, True, True, False])
    r = sr.wait_for_predecessor(
        {REPLACES_ENV: "9"}, lambda p: next(answers), sleep=c.sleep, clock=c.now
    )
    assert r == 9 and c.sleeps == 3


def test_wait_timeout():
    c = Clock()
    r = sr.wait_for_predecessor(
        {REPLACES_ENV: "9"}, lambda p: True, timeout=5.0, poll=1.0, sleep=c.sleep, clock=c.now
    )
    assert r == 9 and c.sleeps == 5
