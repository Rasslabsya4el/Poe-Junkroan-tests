from tools.agentops.suite_candidates import LIMIT, Candidates, parse_candidates, too_many_message

MIXED = """\
___________ ERROR collecting tests/test_issue600_boots_movement.py ____________
ImportError: boom
=========================== short test summary info ============================
FAILED tests/test_a.py::test_one - assert 0
FAILED tests/test_b.py::test_two
ERROR tests/test_c.py::test_three - RuntimeError
ERROR tests/test_issue600_boots_movement.py
"""


def test_mixed_forms():
    c = parse_candidates(MIXED)
    assert c.ids == ["tests/test_a.py::test_one", "tests/test_b.py::test_two", "tests/test_c.py::test_three"]
    assert c.files == ["tests/test_issue600_boots_movement.py"]
    assert c.targets() == [*c.ids, *c.files]
    assert c.count == 4


def test_limit_boundary():
    def make(n):
        return "\n".join(f"FAILED tests/t.py::t{i}" for i in range(n))

    over = parse_candidates(make(41))
    assert over.too_many and too_many_message(over) == "41 candidates > 40"
    assert not parse_candidates(make(LIMIT)).too_many


def test_duplicates_collapse():
    c = parse_candidates("FAILED a.py::t\nFAILED a.py::t - x\nERROR a.py::t\n")
    assert c.ids == ["a.py::t"] and c.files == []


def test_message_suffix_dropped():
    c = parse_candidates("FAILED tests/x.py::t - AssertionError: 1 == 2\n")
    assert c.ids == ["tests/x.py::t"]


def test_empty():
    c = parse_candidates("")
    assert c == Candidates([], []) and c.count == 0 and c.targets() == [] and not c.too_many


def test_a_result_line_inside_captured_output_is_not_a_candidate():
    text = ("____ test_a ____\n"
            "FAILED tests/test_x.py::test_boom - assert 0\n"
            "=========== short test summary info ===========\n"
            "FAILED tests/test_real.py::test_one - x\n"
            "ERROR tests/broken.py - SyntaxError\n"
            "1 failed, 1 error in 1.0s\n")
    c = parse_candidates(text)
    assert c.ids == ["tests/test_real.py::test_one"] and c.files == ["tests/broken.py"]
