"""#664 unit 3: the detached runner hands a merge result back to its issues (comment + label).
`pushed_sha` of the unit cases comes from a real temp git world (`--cwd` at its checkout, which has
an origin/main); the gh calls go through a fake runner behind a real `GhCli`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from tools.agentops import detach
from tools.agentops.dispatch import GhCli
from tests.test_agentops_merge import _git, _push_branch, _world

ROOT = Path(__file__).resolve().parents[1]


def make_gh(tmp_path, boom_on_comment=False):
    calls = []

    def fake(args, stdin):
        calls.append((args, stdin))
        if args[:2] == ["issue", "view"]:
            return subprocess.CompletedProcess(args, 0, json.dumps({"state": "OPEN", "labels": [], "assignees": []}), "")
        if boom_on_comment and args[:2] == ["issue", "comment"]:
            raise RuntimeError("gh exploded")
        return subprocess.CompletedProcess(args, 0, "", "")

    return GhCli(repo="o/r", cwd=tmp_path, runner=fake), calls


def run(tmp_path, code, extra, kind="merge", boom=False):
    _bare, checkout = _world(tmp_path)
    gh, calls = make_gh(tmp_path, boom)
    result, log = tmp_path / "r.json", tmp_path / "merge.log"
    argv = [sys.executable, "-c", code, "--cwd", str(checkout), *extra]
    rc = detach.run_and_record(argv, result, kind, "feat", merge_log=log, gh=gh)
    return rc, calls, result, log


def verbs(calls):
    return [tuple(c[0][:3]) for c in calls]


STATS = "print('merge-stats: in_line_s=65 suite_s=1020 failed=0')"


def test_landed(tmp_path):
    rc, calls, result, _ = run(tmp_path, STATS, ["--issue", "5"])
    assert rc == 0
    sha = json.loads(result.read_text(encoding="utf-8"))["pushed_sha"]
    assert verbs(calls) == [("issue", "view", "5"), ("issue", "comment", "5"), ("issue", "edit", "5")]
    assert calls[1][1].startswith("<!-- merge result -->") and f"landed on main {sha[:12]}" in calls[1][1]
    assert calls[2][0][-2:] == ["--add-label", "ready-for-agent"]


def test_red_suite(tmp_path):
    rc, calls, _, _ = run(tmp_path, "print('not merged (red-suite)'); raise SystemExit(1)", ["--issue", "5"])
    assert rc == 1 and "did not land (red-suite)" in calls[1][1]


def test_nothing_to_merge_makes_no_gh_call(tmp_path):
    _, calls, _, _ = run(tmp_path, "print('not merged (nothing-to-merge)'); raise SystemExit(1)", ["--issue", "5"])
    assert calls == []


def test_two_issues_in_order(tmp_path):
    _, calls, _, _ = run(tmp_path, STATS, ["--issue", "5", "--issue", "7"])
    assert [v for v in verbs(calls) if v[1] != "view"] == [
        ("issue", "comment", "5"), ("issue", "edit", "5"), ("issue", "comment", "7"), ("issue", "edit", "7")]


def test_commit_kind_makes_no_gh_call(tmp_path):
    _, calls, _, _ = run(tmp_path, STATS, ["--issue", "5"], kind="commit")
    assert calls == []


def test_gh_failure_changes_nothing_but_the_log(tmp_path):
    rc, calls, result, log = run(tmp_path, STATS, ["--issue", "5"], boom=True)
    assert rc == 0
    rec = json.loads(result.read_text(encoding="utf-8"))
    assert rec["rc"] == 0 and rec["issues"] == [5]
    # post_merge_result swallows a failed comment itself; the label still goes out and nothing is logged
    # as a failure, so force the escaping path below
    from tools.agentops import merge_handback

    class Boom:
        def issue_status(self, n):
            raise RuntimeError("no gh")

    def explode(*a, **k):
        raise RuntimeError("gh exploded")
    orig, merge_handback.post_merge_result = merge_handback.post_merge_result, explode
    try:
        log.write_text("", encoding="utf-8")
        rc2 = detach.run_and_record([sys.executable, "-c", STATS, "--issue", "5"], tmp_path / "r2.json",
                                    "merge", "feat", merge_log=log, gh=Boom())
    finally:
        merge_handback.post_merge_result = orig
    assert rc2 == 0 and json.loads((tmp_path / "r2.json").read_text(encoding="utf-8"))["rc"] == 0
    lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if "hand-back failed" in ln]
    assert len(lines) == 1 and lines[0].endswith("| feat | hand-back failed: RuntimeError: gh exploded")


STUB = '''import json, sys
from pathlib import Path
out = Path(sys.argv[0]).with_name("gh_calls.jsonl")
stdin = sys.stdin.read() if "comment" in sys.argv[1:3] else ""
with open(out, "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"t": __import__("time").time(), "args": sys.argv[1:], "stdin": stdin}) + "\\n")
if sys.argv[1:3] == ["issue", "view"]:
    print(json.dumps({"state": "OPEN", "labels": [], "assignees": []}))
'''


def test_real_detached_merge_posts_to_its_issue(tmp_path):
    bare, checkout = _world(tmp_path)
    _push_branch(bare, tmp_path, "worker-a", "feature-a", "a.py", "a = 1\n")
    _git("fetch", "-q", "origin", cwd=checkout)
    stub = tmp_path / "gh_stub.py"
    stub.write_text(STUB, encoding="utf-8")
    results = tmp_path / "results"
    env = {**os.environ, detach.ENV_RESULTS_DIR: str(results),
           detach.ENV_MERGE_LOG: str(tmp_path / "merge.log"), detach.ENV_GH_STUB: str(stub)}
    starter = subprocess.run(
        [sys.executable, "-m", "tools.agentops", "merge", "origin/feature-a", "--issue", "1",
         "--suite", f'"{sys.executable}" -c "pass"', "--cwd", str(checkout),
         "--lock", str(tmp_path / "merge.lock"), "--timeout", "120", "--detach"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)
    assert starter.returncode == 0 and starter.stdout.startswith("detached: result "), starter.stdout
    calls_file = tmp_path / "gh_calls.jsonl"

    def wait(pred, what, bound=120.0):
        end = time.time() + bound
        while time.time() < end:
            v = pred()
            if v:
                return v
            time.sleep(0.3)
        raise AssertionError(f"timed out waiting for {what}")

    found = wait(lambda: list(results.glob("*-merge-origin_feature-a.json")), "the result file")
    rec = json.loads(found[0].read_text(encoding="utf-8"))
    assert rec["rc"] == 0 and rec["issues"] == [1], rec

    def calls():
        return [json.loads(x) for x in calls_file.read_text(encoding="utf-8").splitlines()] if calls_file.exists() else []
    wait(lambda: any("--add-label" in c["args"] for c in calls()), "the label call", bound=60)
    got = calls()
    comment = next(c for c in got if c["args"][:2] == ["issue", "comment"])
    label = next(c for c in got if "--add-label" in c["args"])
    assert f"landed on main {rec['pushed_sha'][:12]}" in comment["stdin"]
    assert label["args"][-1] == "ready-for-agent"
    ended = time.mktime(time.strptime(rec["ended"], "%Y-%m-%dT%H:%M:%S"))
    assert label["t"] - ended < 60 and comment["t"] - ended < 60
