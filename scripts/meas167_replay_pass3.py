"""#167 measurement: replay ziz-tpl z326_berserker_volcanic_fissure seed 4 up to the
start of loop pass 3 and measure the `refine` move's revert the way `judge()` does it.

MEASUREMENT ONLY. Nothing under src/ is edited; the pipeline is wrapped (the wrappers
record and delegate, they never change what the pipeline does) and the experiment runs
inside the pass-3 `tree.refine(max_rounds=10)` call, before the original refine is
invoked, so the pipeline state is exactly the start of pass 3.

Run from the snapshot worktree of the pin (cwd = that worktree): it puts <cwd>/src and
<cwd>/scripts on sys.path, so every line of optimizer code is the pin's.

Writes into artifacts/meas167/ (absolute, the live checkout):
  start_of_pass3.xml        the PoB XML of the state at the start of pass 3
  after_revert.xml          the PoB XML exported right after the exact revert
  meas167.json              every number of items 1-4 of the ticket
  meas167.done              written last; its presence means the job ended
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
TARGET_VALUE = 215142.51653084  # recorded start of pass 3 (results.json move_rows)
SOURCE_RUN = LIVE / "artifacts" / "benchmark" / "20260927-0322-ziz-tpl-main3-s4"

import benchmark  # noqa: E402  (after sys.path)
from junkroan.optimizer.improvement_loop import _LoopState  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402


class Done167(BaseException):
    """Ends the replay as soon as the measurement is written (BaseException: run_one's
    `except Exception` must not swallow it)."""


CTX: dict = {}
REPORT: dict = {
    "pin_sys_path": str(ROOT),
    "slug": SLUG,
    "seed": SEED,
    "recorded": {"start_of_pass3_value": TARGET_VALUE, "start_of_pass3_violation": 0.0,
                 "refine_after_value": TARGET_VALUE, "refine_after_violation": 0.3076923076923077},
    "loop_refine_calls": [],
    "states": {},
    "notes": [],
}


def loop_cur() -> dict | None:
    """The `cur` Score the improvement loop is carrying right now, read (never written)
    off `ImprovementLoop.run`'s frame: `cur` is a field of that function's `_LoopState` (local `st`). The recorded `violation_before` of a move row is this number,
    so reading it tells a stale `cur` apart from a drifting build."""

    frame = sys._getframe()
    while frame is not None:
        if frame.f_code.co_name == "run" and isinstance(frame.f_locals.get("st"), _LoopState):  # #51 unit 5b: `st` lives in ImprovementLoop.run
            loop_state = frame.f_locals.get("st")  # the loop's `_LoopState` (#51)
            cur = None if loop_state is None else loop_state.cur
            if cur is None:
                return None
            return {"value": cur.value, "violation": cur.violation}
        frame = frame.f_back
    return None


def snap(pob, objective, *, heavy: bool) -> dict:
    """value / violation / violations() per key, plus (heavy) every scalar stat PoB
    outputs and every build surface, so item 3 can name what differs."""

    keys = objective.stat_keys
    stats = pob.stats(keys)
    score = objective.score(stats)
    out = {
        "value": score.value,
        "violation": score.violation,
        "violations": objective.violations(stats),
        "objective_stats": {k: stats.get(k) for k in keys},
        "derived": objective.derived_values(stats),
    }
    if heavy:
        out["all_stats"] = pob.stats(None)
        out["tree_light"] = pob.tree_light()
        out["config_inputs"] = pob.config_inputs()
        out["read_state"] = pob.read_state()
    return out


def describe_objective(objective) -> dict:
    return {
        "maximize": objective.maximize,
        "floors": dict(objective.floors),
        "ceilings": dict(objective.ceilings),
        "relations": [list(r) for r in objective.relations],
        "derived": [d.name for d in objective.derived],
        "stat_keys": list(objective.stat_keys),
    }


def experiment(pipeline, skeleton, tree, orig_refine, args, kwargs) -> None:
    pob = pipeline.pob
    obj_before = pipeline.objective
    cast_before = pipeline._castability_context

    REPORT["objective"] = describe_objective(obj_before)
    REPORT["loop_cur_at_start_of_pass3"] = loop_cur()

    # --- item 1: the state at the start of pass 3, as the pipeline holds it
    t0 = time.perf_counter()
    REPORT["states"]["A_start_of_pass3"] = snap(pob, obj_before, heavy=True)
    tree_obj = getattr(tree, "objective", None)
    if tree_obj is not None:  # the refine log prints its violation under THIS objective, not the pipeline's
        REPORT["tree_objective"] = describe_objective(tree_obj)
        REPORT["states"]["A_under_tree_objective"] = snap(pob, tree_obj, heavy=False)
    xml_a = pob.export_xml()
    (OUT / "start_of_pass3.xml").write_text(xml_a, encoding="utf-8")
    REPORT["notes"].append(f"state A captured in {time.perf_counter() - t0:.1f} s")

    # --- the move, exactly as the loop runs it, then judge's pre-score _reconfigure
    t0 = time.perf_counter()
    orig_refine(tree, *args, **kwargs)
    pipeline._reconfigure(skeleton)
    REPORT["states"]["N_after_refine"] = snap(pob, pipeline.objective, heavy=False)
    REPORT["notes"].append(f"refine + _reconfigure took {time.perf_counter() - t0:.1f} s")

    # --- item 2/3: the revert judge() does when restores_exact=True
    #     (pipeline.py:1088 at the pin skips _reconfigure; restore_move does load_xml)
    pob.load_xml(xml_a)
    pipeline.objective = obj_before
    pipeline._restore_castability(cast_before)
    REPORT["states"]["B_after_revert"] = snap(pob, obj_before, heavy=True)
    xml_b = pob.export_xml()
    (OUT / "after_revert.xml").write_text(xml_b, encoding="utf-8")
    REPORT["xml_equal_after_round_trip"] = xml_a == xml_b
    REPORT["xml_len"] = [len(xml_a), len(xml_b)]

    # --- item 4a: the same revert followed by _reconfigure
    pipeline._reconfigure(skeleton)
    REPORT["states"]["C_revert_then_reconfigure"] = snap(pob, pipeline.objective, heavy=False)
    REPORT["objective_after_reconfigure"] = describe_objective(pipeline.objective)

    # --- item 4b: the same revert done twice (and a third time) in a row
    for name in ("D_revert_1", "E_revert_2", "F_revert_3"):
        pob.load_xml(xml_a)
        pipeline.objective = obj_before
        pipeline._restore_castability(cast_before)
        REPORT["states"][name] = snap(pob, obj_before, heavy=False)


def install_hooks() -> None:
    orig_loop = BuildPipeline._run_loop
    orig_refine = TreeOptimizer.refine

    def loop(self, build, result, plan, flags):
        CTX.update(pipeline=self, skeleton=build.skeleton, loot=build.gear, tree=build.tree)
        return orig_loop(self, build, result, plan, flags)

    def refine(self, *args, **kwargs):
        is_loop_move = kwargs.get("max_rounds") == 10 and CTX.get("tree") is self
        if is_loop_move and not CTX.get("fired"):
            pipeline = CTX["pipeline"]
            stats = pipeline.pob.stats(pipeline.objective.stat_keys)
            score = pipeline.objective.score(stats)
            n = len(REPORT["loop_refine_calls"]) + 1
            REPORT["loop_refine_calls"].append({"call": n, "value": score.value, "violation": score.violation})
            if abs(score.value - TARGET_VALUE) <= 0.01 or n >= 3:
                CTX["fired"] = True
                REPORT["fired_on_call"] = n
                REPORT["fired_value_matches_record"] = abs(score.value - TARGET_VALUE) <= 0.01
                try:
                    experiment(pipeline, CTX["skeleton"], self, orig_refine, args, kwargs)
                finally:
                    write_out()
                raise Done167()
        return orig_refine(self, *args, **kwargs)

    BuildPipeline._run_loop = loop
    TreeOptimizer.refine = refine


def write_out() -> None:
    path = OUT / "meas167.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(REPORT, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    author_src = SOURCE_RUN / "author"
    author_dir = OUT / "author"
    if author_src.is_dir() and not author_dir.is_dir():
        shutil.copytree(author_src, author_dir)  # the run's own author memo: identical floors, no re-measure
    install_hooks()
    started = time.perf_counter()
    try:
        row = benchmark.run_one(
            SLUG,
            log_path=str(OUT / f"{SLUG}-s{SEED}.log"),
            seed=SEED,
            gear_mode="wishlist",       # the run: --gear wishlist
            loop_seconds=5400.0,        # the run: --loop-seconds 5400
            author_cache=str(author_dir),
        )
    except Done167:
        REPORT["outcome"] = "measured"
    except BaseException as exc:  # noqa: BLE001 - the job must leave a readable file either way
        REPORT["outcome"] = f"{type(exc).__name__}: {exc}"
        REPORT["trace"] = traceback.format_exc()
    else:
        REPORT["outcome"] = "replay ended without reaching pass 3"
        REPORT["row_ok"] = row.get("ok")
        REPORT["row_error"] = row.get("error")
    REPORT["seconds"] = time.perf_counter() - started
    write_out()
    (OUT / "meas167.done").write_text(str(REPORT["outcome"]), encoding="utf-8")
    print(f"meas167: {REPORT['outcome']} in {REPORT['seconds'] / 60:.1f} min -> {OUT / 'meas167.json'}", flush=True)
    return 0 if REPORT["outcome"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
