"""#956 unit 1: no wall clock decides where a build's search stops (PoB-free).

`BuildPipeline.run`'s `loop_max_seconds` and `scripts/benchmark.py`'s `--loop-seconds` default to no clock. A clock that
jumps 3 hours in the middle of the search changes nothing in the loop and in the fixed-point check; `--loop-seconds <n>`
given by hand still stops the loop (`loop_stop` = time) and the report counts the hit.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
import junkroan.optimizer.pipeline as pipeline_module  # noqa: E402
from junkroan.optimizer.improvement_loop import LoopPlan  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline, loop_stop_label  # noqa: E402
from junkroan.optimizer.stage_catalog import start_line  # noqa: E402
from loop_fakes import _Loot, _Pob, _Tree, _patch_generator, _skeleton, loop_over  # noqa: E402
from test_benchmark_durable import _patch_benchmark_main, _row  # noqa: E402
from test_improvement_loop import _pipeline, _started  # noqa: E402

THREE_HOURS = 3 * 3600.0
ALL_TREE_MOVES = frozenset({"refine", "swaps", "corridors", "regions"})
PIPELINE_DEFAULT = inspect.signature(BuildPipeline.run).parameters["loop_max_seconds"].default  # the clock a build gets with no flag


def _loop(monkeypatch, *, jump: float, max_seconds, max_passes: int = 4):
    """One loop on the fake build; the clock stands still and jumps `jump` seconds when pass 2 starts."""

    now = [0.0]
    clock = SimpleNamespace(perf_counter=lambda: now[0])
    monkeypatch.setattr("junkroan.optimizer.improvement_loop.time", clock)
    monkeypatch.setattr("junkroan.optimizer.tree_optimizer.time", clock)
    calls: list = []

    def log(line: str) -> None:
        if line == start_line("loop pass 2"):
            now[0] += jump

    pob = _Pob(1000.0, calls=calls)
    tree = _Tree(pob, [1100.0, 1150.0, 1160.0], swap_values=[1200.0], corridor_values=[1210.0], region_values=[1300.0], calls=calls)
    _patch_generator(monkeypatch, [])
    rig = loop_over(pob, tree=tree, gear=_Loot(pob, {}, calls=calls), skeleton=_skeleton({}, main_link=("Fireball",)), calls=calls, log=log)
    outcome = rig.run(LoopPlan(seed=1, max_passes=max_passes, max_seconds=max_seconds, min_gain=0.005, loot_n=5, moves=ALL_TREE_MOVES))
    return outcome, calls, pob.value


def test_a_jump_of_three_hours_between_two_passes_changes_nothing(monkeypatch) -> None:
    still = _loop(monkeypatch, jump=0.0, max_seconds=PIPELINE_DEFAULT)
    jumped = _loop(monkeypatch, jump=THREE_HOURS, max_seconds=PIPELINE_DEFAULT)

    assert still[0].passes >= 2, "the jump happens between two passes"
    assert jumped[0].stopped in ("", "max passes") and loop_stop_label(jumped[0].stopped) != "time", jumped[0].note
    assert (jumped[0].passes, jumped[0].stopped, jumped[0].counts, jumped[0].kept) == (still[0].passes, still[0].stopped, still[0].counts, still[0].kept)
    assert jumped[1] == still[1], "the same PoB calls in the same order"
    assert jumped[2] == still[2], "the same final build"


def test_no_clock_is_the_default_of_a_build() -> None:
    assert PIPELINE_DEFAULT is None
    assert benchmark.LOOP_SECONDS_DEFAULT is None


def _fixed_point(monkeypatch, *, jump: float, max_seconds):
    pob = _Pob(1000.0)
    calls: list = []
    p = _pipeline(pob, [], calls=calls)
    now = [0.0]
    monkeypatch.setattr(pipeline_module, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    plans: list = []
    real = p.improve

    def improve(build, result, plan):
        plans.append(plan.max_seconds)
        out = real(build, result, plan)
        now[0] += jump
        return out

    p.improve = improve
    tree = _Tree(pob, [1000.0 * 1.008 ** k for k in range(1, 7)], calls=calls)
    loot = _Loot(pob, {}, calls=calls)
    sk = _skeleton({"Boots": "Two-Toned Boots"}, main_link=("Fireball",))
    result = _started(p, sk)
    findings = p._fixed_point_check(result, sk, loot, tree, loot_n=5, seed=1, min_gain=0.005, max_seconds=max_seconds)
    return result.fixed_point_passes, [f.detail for f in findings], calls, pob.value, plans


def test_a_jump_of_three_hours_inside_the_fixed_point_check_changes_nothing(monkeypatch) -> None:
    still = _fixed_point(monkeypatch, jump=0.0, max_seconds=PIPELINE_DEFAULT)
    jumped = _fixed_point(monkeypatch, jump=THREE_HOURS, max_seconds=PIPELINE_DEFAULT)

    assert still[0] == 3, "a landscape that never settles gets the three extra passes"
    assert jumped[:4] == still[:4], "the passes, the finding, the PoB calls and the build are the same"
    assert jumped[4] == [None, None, None], "no extra pass is handed a clock"


def test_a_clock_given_by_hand_still_stops_the_loop_and_the_row_says_time(monkeypatch) -> None:
    outcome, _calls, _value = _loop(monkeypatch, jump=THREE_HOURS, max_seconds=60.0)

    assert outcome.stopped == "time budget" and loop_stop_label(outcome.stopped) == "time"
    assert outcome.note.startswith("stopped: time budget (60 s) after")


def _main(monkeypatch, tmp_path: Path, *flags: str, loop_stop: str) -> tuple[dict, list[dict], str]:
    out_dir, stamp = _patch_benchmark_main(monkeypatch, tmp_path)
    seen: list[dict] = []

    def fake_run_one(slug: str, **kwargs) -> dict:
        seen.append(kwargs)
        return _row(slug) | {"loop_stop": loop_stop}

    monkeypatch.setattr(benchmark, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "alpha", "--workers", "1", "--no-variants", "--gear", "loot", "--tag", "durable", *flags])
    assert benchmark.main() == 0
    args = json.loads((out_dir / "args.json").read_text(encoding="utf-8"))
    return args, seen, (out_dir / "report.md").read_text(encoding="utf-8")


def test_the_benchmark_default_has_no_clock_and_the_report_reads_zero_hits(monkeypatch, tmp_path: Path) -> None:
    args, seen, report = _main(monkeypatch, tmp_path, loop_stop="converged")

    assert args["loop_seconds"] is None
    assert [kw["loop_seconds"] for kw in seen] == [None]
    assert "Loop safety net (none given) hit: 0 of 1 rows" in report


def test_the_benchmark_given_loop_seconds_records_it_and_counts_the_hit(monkeypatch, tmp_path: Path) -> None:
    args, seen, report = _main(monkeypatch, tmp_path, "--loop-seconds", "60", loop_stop="time")

    assert args["loop_seconds"] == 60.0
    assert [kw["loop_seconds"] for kw in seen] == [60.0]
    assert "Loop safety net (60 s) hit: 1 of 1 rows: alpha s1" in report
