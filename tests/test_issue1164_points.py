"""#1164 rows 3 and 4: scripts/check_1164_points.py, PoB-free.

The script loads a stand, forces a bundle through `BuildPipeline.repair` and prints the allocated point count before and
after the repair and the forced count. Here the session and the pipeline are fakes; the graph check of
`--check-unaffected` reads the three seed-4 stands and the tree data only (no PobSession is opened in this file).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_1164_points as chk  # noqa: E402

STANDS = ROOT / "artifacts" / "stands-1124"
needs_stands = pytest.mark.skipif(
    not ((ROOT / "var" / "cache").is_dir() and all((STANDS / f"{n}-s4.pob.txt").is_file() for n in ("spark", "smite", "summon_raging_spirits"))),
    reason="var/cache or the seed-4 stand files are not present",
)


class FakePob:
    def __init__(self, points: int) -> None:
        self.points = points
        self.loaded: list[str] = []

    def load_import_code(self, code: str) -> None:
        self.loaded.append(code)

    def mutate_nodes(self) -> dict:
        return {"points_used": self.points}

    def stats(self, keys):
        return {k: 1.0 for k in keys}


def _factory(pob: FakePob, *, points_after: int, forced_choice: list):
    """A state factory whose repair moves the fake session's points to `points_after`."""

    def make(pob_, prepared, *, gear_mode, log):
        def repair(working, result, choice, *, seed):
            forced_choice.append((choice.direction, choice.bundle, choice.mastery_lines, seed))
            pob_.points = points_after
            return SimpleNamespace(start=1.0, values=[1.0], verdict="take")

        pipeline = SimpleNamespace(
            repair=repair, judging=None,
            objective=SimpleNamespace(maximize="CombinedDPS", stat_keys=("CombinedDPS",), score=lambda stats: SimpleNamespace(value=1.0)),
        )
        return pipeline, SimpleNamespace(), SimpleNamespace(), SimpleNamespace()

    return make


def _run(points_before: int, points_after: int):
    pob = FakePob(points_before)
    chosen: list = []
    lines: list[str] = []
    rc = chk.run(pob, code="IMPORT", prepared=object(), state_factory=_factory(pob, points_after=points_after, forced_choice=chosen),
                 ids=("keystone:1", "unique:x"), mastery_lines={}, gear_mode="wishlist", seed=1, out=lines.append)
    return rc, lines, pob, chosen


def test_points_before_after_and_forced_count_are_printed_in_plain_lines():
    rc, lines, pob, chosen = _run(102, 104)
    assert "points_used before the repair: 102" in lines
    assert "points_used after the repair: 104" in lines
    assert rc == 0
    assert pob.loaded == ["IMPORT"]
    assert chosen == [("force", ("keystone:1", "unique:x"), {}, 1)]


def test_a_collapse_of_the_allocation_exits_1():
    rc, lines, _, _ = _run(102, 6)  # the defect: 102 -> 6
    assert rc == 1
    assert "points_used before the repair: 102" in lines
    assert "points_used after the repair: 6" in lines
    assert any(line.startswith("COLLAPSE") for line in lines)


@pytest.mark.parametrize("before, after, rc", [(102, 102, 0), (102, 100, 0), (102, 104, 0), (102, 99, 1), (102, 105, 1), (102, 55, 1), (102, 6, 1)])
def test_the_points_must_stay_within_the_forced_count_of_the_value_before(before, after, rc):
    """The row: `points_used` after = before +/- the forced count (2 ids here), the count stated in the output."""

    code, lines, _, _ = _run(before, after)
    assert code == rc
    assert "forced count: 2 (the bundle's ids)" in lines


# -- --check-unaffected: the graph check -----------------------------------------------------------------------------

@needs_stands
def test_the_graph_check_finds_the_witch_start_next_to_the_spark_tree_and_none_beside_smite_and_summon():
    found = {name: chk.foreign_starts_next_to(STANDS / f"{name}-s4.pob.txt") for name in ("spark", "smite", "summon_raging_spirits")}
    assert [cls for cls, _ in found["spark"]] == ["Witch"]
    assert found["smite"] == []
    assert found["summon_raging_spirits"] == []


@needs_stands
def test_check_unaffected_exit_code_is_1_for_an_affected_stand_and_0_for_unaffected_ones(capsys):
    assert chk.main(["--check-unaffected", str(STANDS / "spark-s4.pob.txt")]) == 1
    assert "AFFECTED" in capsys.readouterr().out
    assert chk.main(["--check-unaffected", str(STANDS / "smite-s4.pob.txt"), str(STANDS / "summon_raging_spirits-s4.pob.txt")]) == 0
    assert "UNAFFECTED" in capsys.readouterr().out
