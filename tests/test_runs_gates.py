import pytest

from junkroan.runs.gates import gates_present, needs_gate, newest_gate, record_gate


def test_newest_gate(tmp_path):
    b = tmp_path / "benchmark"
    for n in ("20261005-1220-gate-20261005", "20261012-0900-gate-20261012", "20260928-0100-gate-x"):
        (b / n).mkdir(parents=True)
    (b / "20261020-1000-adhoc").mkdir()
    (b / "20261030-1000-gate-file").write_text("x")
    assert newest_gate(tmp_path) == "20261012-0900-gate-20261012"


def test_none_and_missing(tmp_path):
    assert newest_gate(tmp_path) is None
    (tmp_path / "benchmark" / "other").mkdir(parents=True)
    assert newest_gate(tmp_path) is None


def test_record_round_trip(tmp_path):
    p = tmp_path / "sub" / "g.json"
    assert gates_present("a", p) == set()
    p.parent.mkdir()
    p.write_text("")
    assert gates_present("a", p) == set()
    record_gate("a", "g1", p)
    record_gate("a", "g1", p)
    record_gate("b", "g2", p)
    record_gate("a", "g3", p)
    assert gates_present("a", p) == {"g1", "g3"}
    assert gates_present("b", p) == {"g2"}
    assert not list(p.parent.glob("*.tmp"))


def test_record_creates_parent(tmp_path):
    p = tmp_path / "x" / "y" / "g.json"
    record_gate("a", "g1", p)
    assert gates_present("a", p) == {"g1"}


@pytest.mark.parametrize("cmd", [
    "python scripts/probe_issue632_rage.py",
    r"python scripts\probe_x.py",
    "python -m pytest tests/test_issue632_rage_candidate.py -m pob",
    ["python", "-m", "pytest", "tests/test_a.py", "-m", "pob"],
    r"python x.py artifacts\benchmark\20261005-1220-gate-20261005\smite-s4.pob.txt",
    "python x.py artifacts/benchmark/20261005-1220-gate-20261005/a.txt",
    'python -m pytest tests/test_a.py -m "pob and not slow"',
])
def test_needs_gate_true(cmd):
    assert needs_gate(cmd)


@pytest.mark.parametrize("cmd", [
    "python scripts/benchmark.py --set core14",
    "python -m pytest tests/test_runs_store.py -q",
    'python -m pytest tests/test_runs_store.py -m "not pob"',
    ["python", "-m", "pytest", "-m", "not pob"],
])
def test_needs_gate_false(cmd):
    assert not needs_gate(cmd)
