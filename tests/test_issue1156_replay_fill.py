"""#1156 unit 3: the replay bench has a `fill` move that runs the utility pick and then the pipeline's fill step
(`BuildPipeline._fill_step`, gated by the `fill_step` rail). PoB-free: the pipeline and the generator are fakes."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import LEGAL_MOVES, fill_replay, utilities_replay, validate_move  # noqa: E402


class _Gen:
    def __init__(self, log: list) -> None:
        self.log = log

    def pick_utilities(self, skeleton, *, max_groups, reconfigure):
        self.log.append(("pick_utilities", max_groups))
        return [SimpleNamespace(gems=["Dash"])]


class _Pipeline:
    def __init__(self, log: list, *, fill_step: bool = True) -> None:
        self.log = log
        self.rails = SimpleNamespace(utility_max_groups=2, fill_step=fill_step)
        self.objective = SimpleNamespace(stat_keys=("CombinedDPS",), score=lambda stats: SimpleNamespace(value=7.0))
        self.pob = SimpleNamespace(stats=lambda keys: {})
        self.judging = SimpleNamespace(rejudger=lambda skeleton: "rejudge")

    def _generator(self):
        return _Gen(self.log)

    def _take_picks(self, result, gen, *, before):
        self.log.append(("take_picks", before))

    def _fill_step(self, result, skeleton):
        self.log.append(("fill_step",))
        result.stages.append(SimpleNamespace(name="fill", notes="Vaal Haste"))


def _skeleton():
    return SimpleNamespace(utility_groups=None, extra_groups=[], main_link=["Fireball"])


def test_fill_is_a_legal_move() -> None:
    assert "fill" in LEGAL_MOVES
    assert validate_move("fill") == "fill"


def test_fill_move_runs_the_utility_pick_then_the_fill_step_once() -> None:
    log: list = []
    result = SimpleNamespace(stages=[])

    note = fill_replay(_Pipeline(log), result, _skeleton())

    assert log == [("pick_utilities", 2), ("take_picks", 7.0), ("fill_step",)]
    assert note == "Vaal Haste"


def test_fill_move_with_the_fill_step_rail_off_skips_the_fill_step() -> None:
    log: list = []
    result = SimpleNamespace(stages=[])

    note = fill_replay(_Pipeline(log, fill_step=False), result, _skeleton())

    assert ("fill_step",) not in log
    assert ("pick_utilities", 2) in log
    assert note == "fill step off (fill_step rail)"


def test_utilities_move_alone_does_not_call_the_fill_step() -> None:
    log: list = []

    note = utilities_replay(_Pipeline(log), SimpleNamespace(stages=[]), _skeleton())

    assert ("fill_step",) not in log
    assert note == "Dash"
