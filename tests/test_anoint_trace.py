"""#432 unit 3: the anoint step and the end re-pick count into TRACE by the highest oil of the notable's recipe.

PoB-free: the fake PoB of tests/test_anoint_pipeline.py. The rule proof of kind A (D113): `generated > 0 and evaluated > 0`
for the day-1 side, `0` and `0` for every class above Black, and the kept anoint's class in the output.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import test_anoint_pipeline as tap
from test_anoint_pipeline import A, B, C, NODES

from junkroan.optimizer.anoint_candidates import OIL_ORDER, Candidate
from junkroan.optimizer.anoint_line import apply_anoint
from junkroan.optimizer.trace import TRACE, classify, output_counts

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import replay_bench  # noqa: E402

D, E = "Elemental Equilibrium Fake", "Another Prismatic Fake"  # recipes above Black: never allowed, never measured
CANDS = [
    Candidate(A, NODES[A], ("Clear", "Clear", "Clear"), "Clear"),
    Candidate(B, NODES[B], ("Clear", "Sepia", "Black"), "Black"),
    Candidate(C, NODES[C], ("Clear", "Clear", "Amber"), "Amber"),
    Candidate(D, 104, ("Clear", "Opalescent", "Black"), "Opalescent"),
    Candidate(E, 105, ("Prismatic", "Prismatic", "Prismatic"), "Prismatic"),
]


@pytest.fixture(autouse=True)
def _reset():
    TRACE.reset()
    yield
    TRACE.reset()


def _run(monkeypatch, **kwargs):
    monkeypatch.setattr(tap, "CANDIDATES", CANDS)
    return tap._run(monkeypatch, **kwargs)


def test_the_step_counts_generated_and_evaluated_by_highest_oil(monkeypatch) -> None:
    _run(monkeypatch)
    step = TRACE.considered()["anoint"]

    day1 = {"oil:Clear": 1, "oil:Black": 1, "oil:Amber": 1}  # A, B, C: none on the tree
    for cls, n in day1.items():
        assert step[cls] == {"generated": n, "evaluated": n}
    assert sum(v["generated"] for v in step.values()) == sum(v["evaluated"] for v in step.values()) == 3
    for oil in OIL_ORDER[OIL_ORDER.index("Black") + 1:]:
        if f"oil:{oil}" in step:
            assert step[f"oil:{oil}"] == {"generated": 0, "evaluated": 0}
    assert step["oil:Opalescent"] == {"generated": 0, "evaluated": 0} and step["oil:Prismatic"] == {"generated": 0, "evaluated": 0}


def test_a_notable_on_the_tree_is_not_counted(monkeypatch) -> None:
    class _TreeWithA(tap._Pob):
        def __init__(self) -> None:
            super().__init__(tree={NODES[A]})

    monkeypatch.setattr(tap, "_Pob", _TreeWithA)
    _run(monkeypatch)
    step = TRACE.considered()["anoint"]

    assert step.get("oil:Clear", {"generated": 0, "evaluated": 0}) == {"generated": 0, "evaluated": 0}  # A is not a candidate any more
    assert sum(v["evaluated"] for v in step.values()) == 2


def test_the_end_repick_counts_under_its_own_label(monkeypatch) -> None:
    _run(monkeypatch)
    repick = TRACE.considered()["anoint-repick"]

    assert sum(v["generated"] for v in repick.values()) >= 1 and sum(v["evaluated"] for v in repick.values()) >= 1
    assert repick["oil:Opalescent"] == {"generated": 0, "evaluated": 0}
    assert repick["oil:Prismatic"] == {"generated": 0, "evaluated": 0}


def test_the_screen_counts_nothing(monkeypatch) -> None:
    _run(monkeypatch, screen=True)
    assert "anoint" not in TRACE.considered()


def test_the_output_names_the_class_of_the_kept_anoint() -> None:
    raw = apply_anoint(tap._raw(), "Heart of Oak")
    assert "anoint" in classify({"item": {"slot": "Amulet", "raw": raw}})
    # the oil class comes from the recipe corpus; a raw without an anoint adds none
    assert not any(c.startswith("oil:") for c in output_counts([tap._raw()], []))


def test_move_anoint_is_a_legal_replay_move(monkeypatch, capsys) -> None:
    assert "anoint" in replay_bench.LEGAL_MOVES and replay_bench.validate_move("anoint") == "anoint"
    monkeypatch.setattr(sys, "argv", ["replay_bench.py", "--builds", str(Path(__file__).parent / "no-such-*.pob.txt"), "--move", "anoint", "--tag", "x"])
    with pytest.raises(SystemExit) as stopped:
        replay_bench.main()
    assert stopped.value.code == 2 and "matched no files" in capsys.readouterr().err  # past the move check, stopped on the builds
