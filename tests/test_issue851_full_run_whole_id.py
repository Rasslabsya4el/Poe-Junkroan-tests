"""#851: a failing test id matches an open red-suite ticket only as a whole test id, not as a piece of a longer one."""
from tests.test_issue690_full_run import env, sh  # noqa: F401  (fixture reuse)
from tests.test_issue849_full_run_dedupe import _run
from tools.agentops import full_run as fr

X = "tests/a.py::test_x"


def test_row2_longer_name_is_not_the_same_test(env):
    open_list = [{"number": 7, "title": "Full suite on main is red: tests/a.py::test_x_more", "body": ""}]
    creates, comments = _run(env, open_list, [X])
    assert len(creates) == 1 and comments == []


def test_row3_parametrized_case_is_not_the_same_test(env):
    open_list = [{"number": 7, "title": "Full suite on main is red: tests/a.py::test_p[ab]", "body": ""}]
    creates, comments = _run(env, open_list, ["tests/a.py::test_p[a]"])
    assert len(creates) == 1 and comments == []


def test_row4_id_at_title_end_and_body_middle(env):
    t = {"number": 7, "title": f"Full suite on main is red: {X}", "body": f"failing: `{X}` and more"}
    creates, comments = _run(env, [t], [X])
    assert creates == [] and len(comments) == 1


def test_names_id_edges():
    assert fr.names_id(X, X) and fr.names_id(f"a {X}", X) and fr.names_id(f"{X}, b", X)
    assert not fr.names_id(X + "_more", X) and not fr.names_id("x" + X, X)
    assert fr.names_id(f"{X}_more {X}", X)
