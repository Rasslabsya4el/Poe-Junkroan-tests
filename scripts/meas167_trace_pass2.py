"""#167, second measurement: WHERE the 0.307692 comes from, given that the revert is faithful.

Job 1 (`meas167_replay_pass3.py`) showed the build at the START of `loop pass 3` already
violates `ManaCostPool >= CostedManaCost` by 0.307692 while the loop's `cur` carries 0.
This job replays the same row and, from the loop's first pass on, records a FRESH
`self.objective.score(self.pob.stats(...))` next to the loop's own `cur` at every point
that can move either of them (`_reconfigure`, `_tune_lanes`, `_restore_castability`,
`_take_picks`), so the step where the two part company is named.

MEASUREMENT ONLY: every wrapper records and delegates.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import time
import traceback

LIVE = pathlib.Path(r"C:/Coding/poe-junkroan-v2")
OUT = LIVE / "artifacts" / "meas167"
OUT.mkdir(parents=True, exist_ok=True)

ROOT = pathlib.Path(os.environ.get("MEAS167_ROOT") or os.getcwd()).resolve()
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

SLUG = "z326_berserker_volcanic_fissure"
SEED = 4
TARGET_VALUE = 215142.51653084
SOURCE_RUN = LIVE / "artifacts" / "benchmark" / "20260927-0322-ziz-tpl-main3-s4"

import benchmark  # noqa: E402
from junkroan.optimizer.improvement_loop import _LoopState  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402


class Done167(BaseException):
    pass


CTX: dict = {}
TRACE: list = []
REPORT: dict = {"slug": SLUG, "seed": SEED, "trace": TRACE, "loop_refine_calls": []}


def loop_frame():
    frame = sys._getframe()
    while frame is not None:
        if frame.f_code.co_name == "run" and isinstance(frame.f_locals.get("st"), _LoopState):  # #51 unit 5b: `st` lives in ImprovementLoop.run
            return frame
        frame = frame.f_back
    return None


def mark(what: str) -> None:
    """One trace row: the loop's carried `cur` next to a fresh score of the same build
    under the same objective."""

    pipeline = CTX.get("pipeline")
    if pipeline is None or CTX.get("fired"):
        return
    frame = loop_frame()
    if frame is None:
        return
    loop_state = frame.f_locals.get("st")  # the loop's `_LoopState` (#51): `cur` and `where` live there
    cur = None if loop_state is None else loop_state.cur
    loc = frame.f_locals
    try:
        stats = pipeline.pob.stats(pipeline.objective.stat_keys)
        fresh = pipeline.objective.score(stats)
        viol = pipeline.objective.violations(stats)
    except Exception as exc:  # noqa: BLE001
        TRACE.append({"what": what, "error": f"{type(exc).__name__}: {exc}"})
        return
    TRACE.append({
        "what": what,
        "where": None if loop_state is None else loop_state.where,
        "kind": loc.get("kind"),
        "slot": loc.get("slot"),
        "cur_value": None if cur is None else cur.value,
        "cur_violation": None if cur is None else cur.violation,
        "fresh_value": fresh.value,
        "fresh_violation": fresh.violation,
        "fresh_violations": viol,
        "CostedManaCost": pipeline.objective.derived_values(stats).get("CostedManaCost"),
        "ManaCostPool": pipeline.objective.derived_values(stats).get("ManaCostPool"),
        "ManaUnreserved": stats.get("ManaUnreserved"),
    })


def install_hooks() -> None:
    orig_loop = BuildPipeline._run_loop
    orig_refine = TreeOptimizer.refine
    wrapped = {}

    def loop(self, build, result, plan, flags):
        CTX.update(pipeline=self, skeleton=build.skeleton, tree=build.tree)
        return orig_loop(self, build, result, plan, flags)

    for name in ("_reconfigure", "_tune_lanes", "_restore_castability", "_take_picks"):
        wrapped[name] = getattr(BuildPipeline, name)

        def make(name=name, orig=wrapped[name]):
            def call(self, *a, **kw):
                mark(f"before {name}")
                out = orig(self, *a, **kw)
                mark(f"after {name}")
                return out
            return call

        setattr(BuildPipeline, name, make())

    def refine(self, *args, **kwargs):
        if kwargs.get("max_rounds") == 10 and CTX.get("tree") is self and not CTX.get("fired"):
            pipeline = CTX["pipeline"]
            score = pipeline.objective.score(pipeline.pob.stats(pipeline.objective.stat_keys))
            n = len(REPORT["loop_refine_calls"]) + 1
            REPORT["loop_refine_calls"].append({"call": n, "value": score.value, "violation": score.violation})
            mark(f"start of loop pass {n} refine")
            if abs(score.value - TARGET_VALUE) <= 0.01 or n >= 3:
                CTX["fired"] = True
                REPORT["fired_on_call"] = n
                raise Done167()
        return orig_refine(self, *args, **kwargs)

    BuildPipeline._run_loop = loop
    TreeOptimizer.refine = refine


def write_out() -> None:
    path = OUT / "meas167_trace.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    author_dir = OUT / "author"
    if not author_dir.is_dir():
        shutil.copytree(SOURCE_RUN / "author", author_dir)
    install_hooks()
    started = time.perf_counter()
    try:
        benchmark.run_one(SLUG, log_path=str(OUT / f"trace-{SLUG}-s{SEED}.log"), seed=SEED,
                          gear_mode="wishlist", loop_seconds=5400.0, author_cache=str(author_dir))
    except Done167:
        REPORT["outcome"] = "traced"
    except BaseException as exc:  # noqa: BLE001
        REPORT["outcome"] = f"{type(exc).__name__}: {exc}"
        REPORT["trace_error"] = traceback.format_exc()
    else:
        REPORT["outcome"] = "replay ended without reaching pass 3"
    REPORT["seconds"] = time.perf_counter() - started
    write_out()
    (OUT / "meas167_trace.done").write_text(str(REPORT["outcome"]), encoding="utf-8")
    print(f"meas167 trace: {REPORT['outcome']} in {REPORT['seconds'] / 60:.1f} min", flush=True)
    return 0 if REPORT["outcome"] == "traced" else 1


if __name__ == "__main__":
    raise SystemExit(main())
