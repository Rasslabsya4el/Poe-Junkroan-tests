"""#1153 row 2: the replay bench has a `utilities` move that runs the pipeline's utility pick step (PoB-free routing)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import LEGAL_MOVES, utilities_replay, validate_move  # noqa: E402


class _Gen:
    def __init__(self, log: list) -> None:
        self.log = log

    def pick_utilities(self, skeleton, *, max_groups, reconfigure):
        self.log.append(("pick_utilities", max_groups, reconfigure))
        return [SimpleNamespace(gems=["Dash"])]


class _Pipeline:
    def __init__(self, log: list) -> None:
        self.log = log
        self.rails = SimpleNamespace(utility_max_groups=2)
        self.objective = SimpleNamespace(stat_keys=("CombinedDPS",), score=lambda stats: SimpleNamespace(value=7.0))
        self.pob = SimpleNamespace(stats=lambda keys: {})
        self.judging = SimpleNamespace(rejudger=lambda skeleton: "rejudge")

    def _generator(self):
        return _Gen(self.log)

    def _take_picks(self, result, gen, *, before):
        self.log.append(("take_picks", before))


def test_utilities_is_a_legal_move() -> None:
    assert "utilities" in LEGAL_MOVES
    assert validate_move("utilities") == "utilities"


def test_utilities_move_runs_the_pick_step_with_the_pipelines_arguments() -> None:
    log: list = []
    skeleton = SimpleNamespace(utility_groups=None, extra_groups=[], main_link=["Fireball"])

    note = utilities_replay(_Pipeline(log), SimpleNamespace(), skeleton)

    assert log == [("pick_utilities", 2, "rejudge"), ("take_picks", 7.0)]
    assert note == "Dash"
