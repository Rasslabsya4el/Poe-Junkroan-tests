"""#849: a red full run comments on the open ticket naming the same failing test instead of opening a second one."""
import json
import subprocess

from tests.test_issue690_full_run import env, sh  # noqa: F401  (fixture reuse)
from tools.agentops import full_run as fr

A = "tests/test_x.py::a"
B = "tests/test_x.py::b"


def _fake(open_list, calls, list_rc=0):
    def gh(args):
        calls.append(args)
        if args[:2] == ["issue", "list"]:
            return subprocess.CompletedProcess(args, list_rc, json.dumps(open_list), "")
        return subprocess.CompletedProcess(args, 0, "https://github.com/x/y/issues/9\n", "")
    return gh


def _run(env, open_list, fail, list_rc=0):
    calls = []
    env.behave(fail=fail, recheck_fail=fail)
    rc = fr.run_full(env.c3, root=env.repo, suite_cmd=env.cmd, suite_env=env.suite_env,
                     gh=_fake(open_list, calls, list_rc), resolve_head=lambda: env.c3)
    assert rc == 1
    return ([c for c in calls if c[:2] == ["issue", "create"]],
            [c for c in calls if c[:2] == ["issue", "comment"]])


def _t(n, ids):
    return {"number": n, "title": f"Full suite on main is red: {ids[0]}", "body": "failing: " + " ".join(ids)}


def test_row2_open_ticket_names_a_comment_only(env):
    creates, comments = _run(env, [_t(7, [A])], [A])
    assert creates == [] and len(comments) == 1
    assert comments[0][2] == "7"
    body = comments[0][comments[0].index("--body") + 1]
    assert env.c3 in body and ".out" in body and A in body


def test_row3_other_test_opens_ticket(env):
    creates, comments = _run(env, [_t(7, [A])], [B])
    assert len(creates) == 1 and comments == []


def test_row4_closed_ticket_names_nothing(env):
    creates, comments = _run(env, [], [A])
    assert len(creates) == 1 and comments == []


def test_row5_split_between_comment_and_new_ticket(env):
    creates, comments = _run(env, [_t(7, [A])], [A, B])
    assert len(comments) == 1 and comments[0][2] == "7"
    assert len(creates) == 1
    c = creates[0]
    assert c[c.index("--title") + 1].endswith(B) and A not in c[c.index("--body") + 1]


def test_listing_failure_still_opens_ticket(env):
    creates, comments = _run(env, [_t(7, [A])], [A], list_rc=1)
    assert len(creates) == 1 and comments == []
