"""Replay one optimizer move from delivered benchmark builds.

Unlike a rebuild campaign, this starts every measurement from the same exported
build. The only random work is therefore inside the named move, where the seed
and every move budget are fixed counts rather than wall-clock limits.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import random
import re
import statistics
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import fixture_path, prepare_author, result_stem  # noqa: E402
from build_from_skeleton import skeleton_from_xml  # noqa: E402
from gear_transplant import active_items  # noqa: E402
from junkroan.optimizer.audit import audit_build  # noqa: E402
from junkroan.optimizer.improvement_loop import LoopPlan, WorkingBuild  # noqa: E402
from junkroan.optimizer.judging import TREE, Mark  # noqa: E402
from junkroan.optimizer.config_rules import clear_parse_mods_cache  # noqa: E402
from junkroan.optimizer.loot_gear import LootGear  # noqa: E402
from junkroan.optimizer.objective import better_score  # noqa: E402
from junkroan.optimizer.socket_step import colour_step  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline, BuildResult  # noqa: E402
from junkroan.optimizer.self_cost import tree_patterns as self_cost_tree_patterns  # noqa: E402
from junkroan.optimizer.trace import TRACE  # noqa: E402
import junkroan.optimizer.trace_429  # noqa: E402,F401  (#429 classes: res-line, res-lines, weapon-lines)
import junkroan.optimizer.trace_600  # noqa: E402,F401  (#600 classes: boots-with/without-30-movement)
import junkroan.optimizer.trace_786  # noqa: E402,F401  (#786 classes: loot-base-over-70, loot-base-within-70)
import junkroan.optimizer.trace_1158  # noqa: E402,F401  (#1158 classes: base-swap, base-swap:<slot>)
from junkroan.optimizer.trace_output import trace_output_from_xml  # noqa: E402
from junkroan.optimizer.objective_select import forced_keystones_of, objective_for  # noqa: E402
from junkroan.optimizer.rails import Rails, max_passive_points  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402
from junkroan.optimizer.wishlist_gear import WishlistGear, is_pure_es  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.recording_pob import RecordingPob  # noqa: E402
from junkroan.report_format import human_duration, human_rate_per_minute  # noqa: E402
from junkroan.search.hypothesis import active_gems  # noqa: E402
from junkroan.runs.yield_plan import limited_completions  # noqa: E402


LEGAL_MOVES = ("loop", "refine", "swaps", "corridors", "regions", "ascendancy-swap", "gear", "weapon-base", "base-swap", "picks", "kick-tree", "kick-joint", "anoint", "sockets", "jewel", "cluster", "flask", "utilities", "fill", "fixed-point")
JEWEL_TREE_MAX_DEPTH = 6  # `BuildPipeline.run`'s default `tree_max_depth`
_SOURCE_STEM = re.compile(r"^(?P<slug>.+)-s\d+(?:-no-.+)?$")
_PREPARED_AUTHORS: dict[tuple[str, str], object] = {}


def loop_move_of(move: str) -> str:
    """The loop move a bench move runs: `base-swap` (#1158, every slot) is the loop's `weapon-base` move; the rest are their own."""

    return "weapon-base" if move == "base-swap" else move


def validate_move(move: str) -> str:
    """Return a supported replay move or name every legal alternative."""

    if move not in LEGAL_MOVES:
        raise ValueError(f"unknown replay move {move!r}; legal moves: {', '.join(LEGAL_MOVES)}")
    return move


def _finite(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def _source_name(path: Path) -> str:
    name = path.name
    if not name.endswith(".pob.txt"):
        raise ValueError(f"delivered build must end in .pob.txt: {path}")
    return name[: -len(".pob.txt")]


def _fallback_slug(path: Path) -> str:
    stem = _source_name(path)
    match = _SOURCE_STEM.match(stem)
    return match.group("slug") if match else stem


def _result_rows(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw.get("rows") if isinstance(raw, dict) else raw
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def source_info(path: Path) -> dict[str, Any]:
    """Find the benchmark row that produced a delivered export, when it remains nearby."""

    stem = _source_name(path)
    for folder in (path.parent, *path.parents):
        rows_path = folder / "results.json"
        if not rows_path.is_file():
            continue
        row = next((entry for entry in _result_rows(rows_path) if entry.get("ok") and result_stem(entry) == stem), None)
        if row is not None:
            return {
                "slug": str(row.get("slug") or _fallback_slug(path)),
                "stat": str(row.get("stat") or "CombinedDPS"),
                "gear_mode": str(row.get("gear_mode") or "loot"),
                # what the run that produced this export recorded for it. The replay rebuilds the author
                # floors and the lanes from TODAY's rules, so this is not always what the replay measures:
                # the report prints both and their ratio rather than hiding the difference.
                "recorded_value": _finite(row.get("ours")),
                "result_row": row,
            }
    return {"slug": _fallback_slug(path), "stat": "CombinedDPS", "gear_mode": "loot", "recorded_value": None, "result_row": {}}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def damage_kind(skeleton) -> str:
    """The main skill's game-data tag class for a replay summary."""

    tags = set(active_gems().get(skeleton.main_link[0].lower(), {}).get("tag_keys") or ())
    if "minion" in tags:
        return "minion"
    if "attack" in tags:
        return "attack"
    if "spell" in tags:
        return "spell"
    return "other"


def _prepared_author(pob: PobSession, slug: str, stat: str, log) -> object:
    """The benchmark author row, rebuilt at most once per reference per worker.

    The campaign's own author memo is deliberately NOT read: the bench judges today's
    code, so the floors and the lanes are today's. The memo here only keeps two builds
    of the same reference in one worker process from paying for the rebuild twice.
    """

    key = (slug, stat)
    prepared = _PREPARED_AUTHORS.get(key)
    if prepared is None:
        prepared = prepare_author(pob, slug, stat_override=stat, log=log)
        _PREPARED_AUTHORS[key] = prepared
    return prepared


NO_FIXTURE_PREPARATION = "no fixture: objective from the build"


def prepared_reference(pob: PobSession, slug: str, stat: str, log) -> object | None:
    """The benchmark author row when the slug has a fixture, else None (#1153: a search-output build has none).

    Only a missing fixture falls back: the fixture check is the one that raises FileNotFoundError here, so any
    other error from the preparation propagates. A fixture, when present, is prepared exactly as before."""

    try:
        fixture_path(slug)
    except FileNotFoundError:
        return None
    return _prepared_author(pob, slug, stat, log)


def objective_from_build(pob: Any, log) -> SimpleNamespace:
    """#1153: the rails and the objective of a build with no fixture, derived from the build itself the way
    `BuildPipeline.run` derives them (`objective_for(rails, main skill, mode)`, the request's forced keystones)."""

    skeleton = skeleton_from_xml(pob.export_xml(), pob=pob, log=log)
    rails = Rails.load()
    objective = objective_for(rails, skeleton.main_link[0], rails.objective(), mode=skeleton.mode, forced_keystones=forced_keystones_of(skeleton))
    return SimpleNamespace(rails=rails, objective=objective)


def mark_picked_utilities(skeleton, active: Mapping[str, object] | None = None) -> int:
    """#427: a skeleton rebuilt from an export carries `picked=False` on every group, so the utility
    move never judges one. Mark the enabled extra groups the live picker could have created (one
    active gem alone: no supports, never the main link) as picked. Returns how many were marked."""

    if active is None:
        active = active_gems()
    marked = 0
    for group in skeleton.extra_groups:
        if group.enabled and len(group.gems) == 1 and group.gems[0].lower() in active:
            group.picked = True
            marked += 1
    return marked


def _pipeline_state(pob: PobSession, prepared, *, gear_mode: str, log, mark_picked: bool = False) -> tuple[BuildPipeline, object, object, TreeOptimizer]:
    """Reconstruct only the state the improvement loop needs from the delivered build."""

    xml = pob.export_xml()
    skeleton = skeleton_from_xml(xml, pob=pob, log=log)
    if mark_picked:
        mark_picked_utilities(skeleton)
    graph = TreeGraph.load()
    if pob.tree_version() != graph.tree_version:
        raise RuntimeError(
            f"delivered tree {pob.tree_version()} differs from active optimizer tree {graph.tree_version}; replay keeps exports on their own tree version"
        )
    pipeline = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=log)
    judging = pipeline.judging
    # the delivered lanes, derived and written ONCE where `run`'s opening does it twice (#35 Q13), then
    # the opening's contexts on the full objective: the ramp, the main tags, the main group, the self-cost
    lanes = judging.relane(skeleton)
    triggered = judging.open_contexts(skeleton, lanes)
    pure_es = bool(skeleton.pure_es) or is_pure_es(pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
    unique_gear = {slot: pob.unique_item(name)["raw"] for slot, name in skeleton.uniques.items()}
    if gear_mode == "wishlist":
        gear = WishlistGear(pob, judging.cut("gear"), prepared.rails, log=log, pure_es=pure_es, uniques=unique_gear)
    elif gear_mode == "loot":
        gear = LootGear(pob, judging.cut("gear"), prepared.rails, log=log, uniques=unique_gear)
    else:
        raise ValueError(f"unsupported delivered gear mode {gear_mode!r}")
    equipped = active_items(xml)
    gear.current_raw = {slot: equipped[slot] for slot in skeleton.rare_bases if slot in equipped}
    judging.attach("gear", gear)
    tree = TreeOptimizer(pob, judging.cut("tree"), attribute_requirement_nodes_max=prepared.rails.attribute_plus30_nodes_max, log=log)
    judging.attach("tree", tree)  # the loop's tree: the bench has no construction tree
    self_cost_text = () if triggered else self_cost_tree_patterns(tree.graph, judging.main_tags)
    # the same wiring `BuildPipeline.run` gives its trees: a removal that withdraws a proof the conservative
    # lane needs is judged under re-derived lanes, and a tree restore puts those lanes back. Without
    # them the bench measured a move production does not make (winter_orb's Caster Mastery swap was
    # kept at +1.2% under frozen lanes and only the replay caught it, 241,402 -> 205,290).
    pipeline.wire_tree(tree, skeleton, forbidden_text=(*prepared.rails.forbidden_node_text, *self_cost_text))
    # The delivered config is re-derived before its score is recorded. Do not tune choices or
    # identity here: those are part of the finished build being replayed, not the requested move.
    judging.rejudge(skeleton)
    judging.recut()  # the views re-cut from the full objective after the last re-judge (#35 Q8, the bench only)
    return pipeline, skeleton, gear, tree


def compact_raw(raw: str) -> str:
    """A delivered item's raw in the shape the generators write: no leading blank line, no indentation.

    The export XML stores an item as a blank line, then each line indented by three tabs; the anoint code reads the base as
    line 3 and `Implicits: N` at a line start, as the filler's raws have them (#432 unit 5: on the XML shape the
    step logged "the amulet base 'Random 4' cannot be anointed" and measured nothing)."""

    return "\n".join(line.strip() for line in raw.splitlines() if line.strip())


def _uptimes(raw_pob: Any) -> Any:
    """#575: the raw session's `flask_uptimes()`, None when the session has none."""

    fn = getattr(raw_pob, "flask_uptimes", None)
    return fn() if fn is not None else None


def input_output(raw_pob: Any) -> dict[str, int]:
    """#511: `trace_output_from_xml` over the build a move starts from, read through the raw session
    (never the recorder), so a recorded transcript and `pob_calls` stay as they were."""

    return trace_output_from_xml(raw_pob.export_xml(), flask_uptimes=_uptimes(raw_pob))


def begin_recording(pob: Any, target: Path) -> RecordingPob:
    """#534: start a build's transcript from an empty `parse_mods` cache. The cache is per process, so a
    pool worker that replays a second build would otherwise skip lines the first one parsed and record
    fewer `parse_mods` calls. Only under `--record-calls`: a normal replay keeps its cache (fewer PoB calls)."""

    clear_parse_mods_cache()
    return RecordingPob(pob, target)


FIXED_POINT_MAX_SECONDS = 7200.0  # `Pipeline.run`'s own default loop_max_seconds, which `_finish` hands the check
FIXED_POINT_MIN_GAIN = 0.005  # `Pipeline.run`'s own default loop_min_gain


def fixed_point_replay(pipeline: Any, result: Any, skeleton: Any, gear: Any, tree: Any, *, seed: int) -> dict[str, Any]:
    """#800: `Pipeline._fixed_point_check` on the replayed (already delivered) build, called with the argument shape `_finish`
    gets from `run`. The table is one row per finishing step the check made (stages named "fixed point check"): the objective
    value after it and what it kept ("kept nothing" when its notes are empty); the first row is the replayed build itself."""

    before = pipeline._delivered_score().value
    # a saved build has no loop outcome: the loop did not stop on a limit, so the check runs its pass
    findings = pipeline._fixed_point_check(result, skeleton, gear, tree, loot_n=None, seed=seed, min_gain=FIXED_POINT_MIN_GAIN,
                                           max_seconds=FIXED_POINT_MAX_SECONDS, enabled=True, loop_outcome=None)
    steps = [{"step": "replayed build", "value": before, "kept": ""}]
    for stage in result.stages:
        if stage.name == "fixed point check":
            steps.append({"step": f"extra pass {len(steps)}", "value": stage.score_value, "kept": stage.notes or "kept nothing"})
    gain = float(getattr(result, "fixed_point_gain", 0.0) or 0.0)
    return {"steps": steps, "passes": len(steps) - 1, "findings": [str(finding) for finding in findings],
            "gain": gain, "note": getattr(result, "fixed_point_note", "") or "",
            "reading": f"{gain:+.1%}" if gain > 0 else "kept nothing"}


def fixed_point_lines(row: Mapping[str, object]) -> list[str]:
    fixed = row.get("fixed_point")
    if not isinstance(fixed, Mapping):
        return []
    lines = [f"### {row.get('reference')} fixed point: {fixed.get('reading')}; {fixed.get('passes')} extra pass(es), "
             f"{human_duration(float(row.get('seconds') or 0.0))}", "",
             "| step | value after | kept |", "|---|---:|---|"]
    for step in fixed.get("steps") or ():
        lines.append(f"| {step['step']} | {float(step['value']):,.0f} | {step['kept'] or '-'} |")
    lines += [f"- {text}" for text in fixed.get("findings") or ()]
    return lines


def final_repair_after_loop(pipeline: Any, result: Any, skeleton: Any, log: Any = None) -> dict[str, Any]:
    """#553 rule 3: what `_finish` does after the loop, so the replay delivers what the pipeline delivers. The score
    right after the loop is kept (`value_after_loop`, `violation_after_loop`); the floor repair runs only on an
    infeasible build with a tree view, and a non-empty note is followed by `relane`, as in `_finish`."""

    score = pipeline._delivered_score()
    out: dict[str, Any] = {"value_after_loop": score.value, "violation_after_loop": score.violation, "note": "", "ran": False}
    if score.feasible or pipeline.judging.view("tree") is None:
        return out
    out["ran"] = True
    out["note"] = pipeline._final_floor_repair(result, skeleton)
    if out["note"]:
        pipeline.judging.relane(skeleton)
    final = pipeline._delivered_score()
    out["value_final"], out["violation_final"] = final.value, final.violation
    return out


def utilities_replay(pipeline: BuildPipeline, result: BuildResult, skeleton: Any) -> str:
    """#1153: the utility pick step on the delivered build, gated and called as `pipeline.py` runs it
    (movement pair outside `max_groups`); returns the gems added, or the gate's refusal."""

    from junkroan.search.generator import movement_pair_missing, utility_groups_used

    max_groups = skeleton.utility_groups if skeleton.utility_groups is not None else pipeline.rails.utility_max_groups
    if not (utility_groups_used(skeleton.extra_groups, pipeline.rails) < max_groups or movement_pair_missing(skeleton.extra_groups, skeleton.main_link, pipeline.rails)):
        return "gate closed: at max_groups and the movement pair is complete"
    value_before = pipeline.objective.score(pipeline.pob.stats(pipeline.objective.stat_keys)).value
    gen = pipeline._generator()
    with TRACE.move("utilities"):
        added = gen.pick_utilities(skeleton, max_groups=max_groups, reconfigure=pipeline.judging.rejudger(skeleton))
        pipeline._take_picks(result, gen, before=value_before)
    return ", ".join(g.gems[0] for g in added) or "none"


def fill_replay(pipeline: BuildPipeline, result: BuildResult, skeleton: Any) -> str:
    """#1156: the utility pick, then the fill step on the delivered build, called as `pipeline.py` runs them (the fill
    step gated by the `fill_step` rail, outside the utility gate); returns the gems the fill step added."""

    utilities_replay(pipeline, result, skeleton)
    if not getattr(pipeline.rails, "fill_step", False):
        return "fill step off (fill_step rail)"
    pipeline._fill_step(result, skeleton)
    return "; ".join(stage.notes for stage in result.stages if stage.name == "fill") or "none"


def replay_one(path_text: str, *, move: str, passes: int, seed: int, record_calls: str | None = None, mark_picked: bool = False) -> dict[str, Any]:
    """Run a named move once from one delivered build; failures become report rows.

    `record_calls`: a directory; every PoB call from loading the delivered build on is recorded to
    `<dir>/<source>.calls.jsonl` (the refactor proof of #35). The author is prepared before the
    recording starts: a worker that replays a second build of the same reference reuses it, so the
    preparation would make a transcript depend on which worker drew which build."""

    path = Path(path_text)
    info = source_info(path)
    started = time.perf_counter()
    logs: list[str] = []
    recorder: RecordingPob | None = None
    TRACE.reset()  # #498: this process runs one build at a time; the counters are this build's alone
    try:
        with PobSession(run_id=f"replay-{info['slug']}-{os.getpid()}") as pob:
            raw_pob = pob
            author_started = time.perf_counter()
            prepared = prepared_reference(pob, info["slug"], info["stat"], logs.append)
            preparation = "fixture" if prepared is not None else NO_FIXTURE_PREPARATION
            author_seconds = time.perf_counter() - author_started
            if record_calls:
                recorder = begin_recording(pob, Path(record_calls) / f"{_source_name(path)}.calls.jsonl")
                pob = recorder
            pob.load_import_code(path.read_text(encoding="utf-8").strip())
            if prepared is None:  # #1153: no fixture; the objective is derived from the loaded build, read through the raw session
                fallback_started = time.perf_counter()
                prepared = objective_from_build(raw_pob, logs.append)
                author_seconds = time.perf_counter() - fallback_started
            pipeline, skeleton, gear, tree = _pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append, mark_picked=mark_picked)
            # #511: the input's option classes, read from the raw session before the report interval
            # restarts: the tree and items the move starts from, and no recorded call
            input_block = input_output(raw_pob)
            pob.reset_pob_calls()
            stats_before = pob.stats(pipeline.objective.stat_keys)
            before = pipeline.objective.score(stats_before)
            # which constraints the delivered build misses under today's rules: a move measured from an
            # infeasible start is judged on violation first, so those rows do not compare with the rest
            start_violated = sorted(pipeline.objective.violations(stats_before))
            result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=info["gear_mode"])
            # the trunk share is a statement about the DELIVERED tree: which of its own
            # never-reconsidered nodes this move put inside a candidate PoB was asked about
            start_allocated = tree.current_allocated()
            move_started = time.perf_counter()
            counts: dict[str, int] = {}
            loop_stopped = ""
            repair: dict[str, Any] = {}
            fixed_point: dict[str, Any] | None = None
            if move == "anoint":  # #432: the amulet's anoint step, then the end re-pick, on the delivered build; no other move
                if gear.current_raw.get("Amulet"):  # the delivered raw as the filler writes it, for this move only: other moves keep their transcripts
                    gear.current_raw["Amulet"] = compact_raw(gear.current_raw["Amulet"])
                pipeline._anoint_step(result, skeleton, gear)
                pipeline._anoint_repick(result, skeleton, gear)
                note = "; ".join(stage.notes for stage in result.stages if stage.name in ("anoint", "anoint re-pick"))
            elif move == "jewel":  # #434: the day-1 rare jewel step, then the end re-pick, on the delivered build; no other move
                jewel_points = max_passive_points(skeleton.level)  # `run`'s own default (tree_points None)
                pipeline._jewel_step(result, skeleton, tree, jewel_points, JEWEL_TREE_MAX_DEPTH)
                pipeline._jewel_repick(result, skeleton, tree, jewel_points, JEWEL_TREE_MAX_DEPTH)
                note = "; ".join(stage.notes for stage in result.stages if stage.name in ("jewels", "jewel re-pick"))
            elif move == "cluster":  # #433: the day-1 rare cluster jewel step on the delivered build; no other move, no end re-pick
                cluster_points = max_passive_points(skeleton.level)  # `run`'s own default (tree_points None)
                pipeline._cluster_step(result, skeleton, gear, tree, cluster_points, JEWEL_TREE_MAX_DEPTH)
                note = "; ".join(stage.notes for stage in result.stages if stage.name == "clusters")
            elif move == "flask":  # #436: the day-1 flask step on the delivered build; no other move
                pipeline._flask_step(result, skeleton)
                note = "; ".join(stage.notes for stage in result.stages if stage.name == "flasks")
            elif move == "utilities":  # #1153: the utility pick step (movement pair) on the delivered build; no other move
                note = utilities_replay(pipeline, result, skeleton)
            elif move == "fill":  # #1156: the utility pick then the fill step on the delivered build; no other move
                note = fill_replay(pipeline, result, skeleton)
            elif move == "fixed-point":  # #800: the finishing check on the delivered build; no other move
                fixed_point = fixed_point_replay(pipeline, result, skeleton, gear, tree, seed=seed)
                note = f"fixed point {fixed_point['reading']}: {fixed_point['note']}"
            elif move == "sockets":
                # #435: whitening and the colour step on the replayed build, not the improvement loop
                with TRACE.move("sockets"):
                    picked = colour_step(pob, pipeline.objective, lambda new, cur: better_score(new, cur), logs.append)
                note = f"sockets coloured: {len(picked.picks)} of {picked.trials} trials"
                result.moves.append({"pass": 1, "where": "replay", "move": "sockets", "seconds": time.perf_counter() - move_started,
                                     "before": picked.score_before.value, "after": picked.score_after.value, "kept": bool(picked.picks)})
                counts = {"kept": len(picked.picks), "not_kept": picked.trials - len(picked.picks), "judged_and_reverted": 0}
            else:
                outcome = pipeline.improve(WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree), result,
                                           LoopPlan.replay(loop_move_of(move), seed=seed, passes=passes))
                note, counts, loop_stopped = outcome.note, dict(outcome.counts), outcome.stopped
                repair = final_repair_after_loop(pipeline, result, skeleton, logs.append)  # #553 rule 3: the pipeline's own last step
                if repair["note"]:
                    note = f"{note}; {repair['note']}" if note else repair["note"]
                if move == "loop" and hasattr(pipeline, "_deliver_vaal_twins"):
                    pipeline._deliver_vaal_twins()  # #802: `_finish`'s gem step, so the replayed delivery is the delivered form
                if move == "loop" and hasattr(pipeline, "_enforce_charge_proof"):
                    pipeline._enforce_charge_proof()  # #908: `_finish`'s step after the gems, so the replayed delivery obeys the audit's proof as the delivered one does
            move_seconds = time.perf_counter() - move_started
            after = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys))
            findings = audit_build(pob, rails=prepared.rails, objective=pipeline.objective, skeleton=skeleton)
            move_rows = list(getattr(result, "move_rows", ()))
            # plan B's acceptance counts: what the move reached structurally, not only what it paid
            tree_counts = dict(tree.structural_counts(start_allocated))
            tree_counts["restore_failures"] = int(tree.restore_failures)
            pob_call_count = raw_pob.pob_calls()  # the raw session: reading it through the recorder would log one more call
            considered = TRACE.considered()
            final_xml = raw_pob.export_xml()  # the raw session: a recorded transcript stays unchanged
            output = trace_output_from_xml(final_xml, flask_uptimes=_uptimes(raw_pob))
        if recorder is not None:
            recorder.close_recording()
        gain_percent = (after.value / before.value - 1.0) * 100.0 if before.value else None
        recorded = _finite(info.get("recorded_value"))
        return {
            "ok": True,
            "reference": info["slug"],
            "source": _relative(path),
            "move": move,
            "seed": seed,
            "stat": pipeline.objective.maximize,
            "damage_kind": damage_kind(skeleton),
            "value_before": before.value,
            "value_after": after.value,
            "gain_percent": gain_percent,
            # the producing run's own number for this export against what today's rules score it at
            "recorded_value": recorded,
            "replayed_value": before.value,
            "replayed_over_recorded": before.value / recorded if recorded else None,
            "start_infeasible": bool(start_violated),
            "start_violated": start_violated,
            "seconds": move_seconds,
            "prepare_seconds": author_seconds,
            "preparation": preparation,  # "fixture", or NO_FIXTURE_PREPARATION for a search-output build
            "kept": int(counts.get("kept", 0)),
            "not_kept": int(counts.get("not_kept", 0)),
            "judged_and_reverted": int(counts.get("judged_and_reverted", 0)),
            "weapon_base_skipped": dict(result.weapon_base_skipped),
            "move_note": note,
            "loop_stop": (loop_stopped or "converged") if move == "loop" else None,  # #555: how the loop ended, read from the loop itself
            "violation_before": before.violation,
            "violation_after": after.violation,
            "value_after_loop": repair.get("value_after_loop", after.value),
            "violation_after_loop": repair.get("violation_after_loop", after.violation),
            "final_repair_ran": bool(repair.get("ran")),
            "fixed_point": fixed_point,  # #800: the table of finishing steps, the pass count and the reading; None for other moves
            "moves": move_rows,
            "pob_calls": pob_call_count,
            "considered": considered,
            "output": output,
            "input": input_block,
            "final_xml": final_xml,  # #437: written to <replay dir>/builds/ by save_final_builds, dropped from results.json
            # A replay starts at the delivered final tree, so it cannot recreate
            # construction-to-final churn. Keep the source build's measurement.
            "tree_churn": dict(info["result_row"].get("tree_churn") or {}),
            "audit_errors": sum(1 for finding in findings if finding.severity == "error"),
            "audit": [str(finding) for finding in findings],
            "tree_counts": tree_counts,
            "move_rows": move_rows,
            "logs": logs,
            "total_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        if recorder is not None:
            recorder.close_recording()
        return {
            "ok": False,
            "reference": info["slug"],
            "source": _relative(path),
            "move": move,
            "seed": seed,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(),
            "seconds": time.perf_counter() - started,
            "logs": logs,
        }


def save_final_builds(rows: Iterable[dict[str, Any]], out_dir: Path) -> list[Path]:
    """#437: write each ok row's final build to `<out_dir>/builds/<reference>.xml` (a second row of the
    same reference gets `-<k>`) and drop the XML from the row, so `check_useful_lines.py` reads the
    builds the move delivered while results.json stays small."""

    written: list[Path] = []
    for row in rows:
        xml = row.pop("final_xml", None)
        if not row.get("ok") or not xml:
            continue
        folder = out_dir / "builds"
        folder.mkdir(parents=True, exist_ok=True)
        name = str(row["reference"])
        path = folder / f"{name}.xml"
        k = 2
        while path.exists():
            path = folder / f"{name}-{k}.xml"
            k += 1
        path.write_text(str(xml), encoding="utf-8")
        row["final_build"] = _relative(path)
        written.append(path)
    return written


def paired_summary(rows: Iterable[Mapping[str, object]], against_rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Compare ``against`` minus this run on the builds both runs replayed.

    Positive differences are wins for ``against``. That direction makes the
    report read naturally as "this run against <other run>" and keeps its sign
    explicit in the returned field name.
    """

    ours = {str(row.get("source")): row for row in rows if row.get("ok") and _finite(row.get("gain_percent")) is not None}
    theirs = {str(row.get("source")): row for row in against_rows if row.get("ok") and _finite(row.get("gain_percent")) is not None}
    differences: list[float] = []
    ratios: list[float] = []
    for source in sorted(ours.keys() & theirs.keys()):
        difference = float(theirs[source]["gain_percent"]) - float(ours[source]["gain_percent"])
        differences.append(difference)
        ours_seconds, theirs_seconds = _finite(ours[source].get("seconds")), _finite(theirs[source].get("seconds"))
        if ours_seconds is not None and theirs_seconds not in (None, 0.0):
            ratios.append(ours_seconds / theirs_seconds)
    if not differences:
        return {"builds": 0, "median_gain_difference": None, "mean_gain_difference": None, "bootstrap_90": None,
                "wins": 0, "ties": 0, "losses": 0, "seconds_ratio": None}
    rng = random.Random(1)
    bootstrap = sorted(statistics.median([rng.choice(differences) for _ in differences]) for _ in range(2_000))
    return {
        "builds": len(differences),
        "median_gain_difference": statistics.median(differences),
        "mean_gain_difference": statistics.fmean(differences),
        "bootstrap_90": (bootstrap[99], bootstrap[1899]),
        "wins": sum(difference > 1e-12 for difference in differences),
        "ties": sum(abs(difference) <= 1e-12 for difference in differences),
        "losses": sum(difference < -1e-12 for difference in differences),
        "seconds_ratio": statistics.fmean(ratios) if ratios else None,
    }


def structural_lines(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """Plan B's structural counts summed over the builds that replayed (D84: a move is accepted on
    counts as well as on gain). The trunk share is the point of the whole exercise: before plan B
    no move ever reconsidered a node whose removal drops 13 or more allocated nodes."""

    counts = [row.get("tree_counts") for row in rows if row.get("ok") and isinstance(row.get("tree_counts"), Mapping)]
    if not counts:
        return []

    def total(key: str) -> int:
        return sum(int(entry.get(key) or 0) for entry in counts)

    buckets: dict[str, int] = {}
    policies: dict[str, int] = {}
    for entry in counts:
        for name, value in (entry.get("region_bucket_kept") or {}).items():
            buckets[str(name)] = buckets.get(str(name), 0) + int(value)
        for name, value in (entry.get("region_policy_kept") or {}).items():
            policies[str(name)] = policies.get(str(name), 0) + int(value)
    trunk, reached = total("trunk_nodes"), total("trunk_considered")
    lines = [
        "",
        "## Structural counts",
        "",
        f"Builds counted: {len(counts)}; allocated nodes {total('allocated')}; "
        f"TRUNK nodes (removal drops 13+) {trunk}, inside at least one evaluated candidate {reached} "
        + (f"({reached / trunk:.1%})." if trunk else "(no trunk nodes)."),
        f"Corridors found / with a bypass / no bypass: {total('corridors')} / {total('corridors_with_bypass')} / "
        f"{total('corridors_no_bypass')}; priced candidates {total('corridor_candidates')} "
        f"(unpriceable {total('corridor_unpriceable')}); applied {total('corridor_applied')}, kept {total('corridor_kept')}.",
        f"Regions found / candidates priced / challenged / kept: {total('regions')} / {total('region_candidates')} / "
        f"{total('regions_challenged')} / {total('regions_kept')}.",
        f"Regions kept by bucket: {buckets or 'none'}; by repair policy: {policies or 'none'}.",
        f"D87 honest holder judgements: {total('honest_removals')}; RESTORE FAILED: {total('restore_failures')}.",
    ]
    return lines


def weapon_base_lines(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """The base swaps and illegal-affix exclusions behind a weapon-base replay."""

    successful = [row for row in rows if row.get("ok")]
    changed = [
        (row, move)
        for row in successful
        for move in (row.get("moves") or ())
        if move.get("move") == "weapon base" and move.get("kept")
    ]
    skipped: dict[str, int] = {}
    for row in successful:
        for item_type, count in (row.get("weapon_base_skipped") or {}).items():
            skipped[str(item_type)] = skipped.get(str(item_type), 0) + int(count or 0)
    if not changed and not skipped:
        return []
    lines = ["", "## Weapon Bases", ""]
    if changed:
        lines += [
            "| reference | slot | old base | new base | changed readbacks |",
            "|---|---|---|---|---|",
        ]
        for row, move in changed:
            before = move.get("base_numbers_before") or {}
            after = move.get("base_numbers_after") or {}
            metrics = ", ".join(
                f"{key} {before.get(key)} -> {after.get(key)}"
                for key in ("Critical Strike Chance", "Attacks per Second", "Physical Damage")
                if before.get(key) != after.get(key)
            )
            implicit_before, implicit_after = move.get("implicit_before"), move.get("implicit_after")
            if implicit_before != implicit_after:
                metrics += ("; " if metrics else "") + f"implicit {implicit_before or '-'} -> {implicit_after or '-'}"
            lines.append(
                f"| {row['reference']} | {move.get('slot', '-')} | {move.get('base_before', '-')} | "
                f"{move.get('base_after', '-')} | {metrics or '-'} |"
            )
    if skipped:
        lines += ["", "Illegal candidate bases skipped by item class: " + ", ".join(f"{item_type} {count}" for item_type, count in sorted(skipped.items())) + "."]
    return lines


def _fmt_percent(value: object) -> str:
    return f"{float(value):+.2f}%" if _finite(value) is not None else "-"


def _fmt_value(value: object) -> str:
    return f"{float(value):,.0f}" if _finite(value) is not None else "-"


def _not_kept(row: Mapping[str, object]) -> int:
    """`not_kept` was called `reverted` before the count was split; read both."""

    value = row.get("not_kept", row.get("reverted"))
    return int(value) if isinstance(value, (int, float)) else 0


def _starts_feasible(row: Mapping[str, object]) -> bool:
    """A row from before the flag existed is not claimed to be infeasible."""

    return not bool(row.get("start_infeasible"))


def _start_broken(row: Mapping[str, object]) -> bool:
    """#816: the start is broken by today's rules (a delivered build older than a rule); its gain and ratio
    against the start are the price of the repair, so only base against head (the paired block) reads it."""

    return bool(row.get("ok") and row.get("start_violated"))


def _paired_lines(title: str, rows: Iterable[Mapping[str, object]], against_rows: Iterable[Mapping[str, object]]) -> list[str]:
    paired = paired_summary(rows, against_rows)
    if not paired["builds"]:
        return [f"{title}: no matching successful builds in the two runs."]
    low, high = paired["bootstrap_90"]
    ratio = paired["seconds_ratio"]
    seconds = f" Seconds ratio (this / against): {ratio:.3f}." if ratio is not None else " Seconds ratio: unavailable."
    return [
        f"**{title}** ({paired['builds']} builds)",
        f"Median difference: {paired['median_gain_difference']:+.2f}%; mean difference: {paired['mean_gain_difference']:+.2f}%.",
        f"Bootstrap 90% interval over builds (2,000 resamples, seed 1): [{low:+.2f}%, {high:+.2f}%].",
        f"Wins / ties / losses for against: {paired['wins']} / {paired['ties']} / {paired['losses']}." + seconds,
    ]


def trace_table_lines(considered: Mapping[str, Mapping[str, Mapping[str, int]]]) -> list[str]:
    """Rows = move, columns = class, cells `generated/evaluated`."""

    classes = sorted({c for per_class in considered.values() for c in per_class})
    if not classes:
        return ["(nothing counted)"]
    lines = ["| move | " + " | ".join(classes) + " |", "|---|" + "---:|" * len(classes)]
    for move in sorted(considered):
        cells = []
        for c in classes:
            cell = considered[move].get(c)
            cells.append(f"{cell.get('generated', 0)}/{cell.get('evaluated', 0)}" if cell else "-")
        lines.append(f"| {move} | " + " | ".join(cells) + " |")
    return lines


def loop_exit_cell(row: Mapping[str, object]) -> str:
    """#555: the loop's exit of one build: "max passes", "time budget" or "converged"; "-" for a row without one."""

    return str(row.get("loop_stop") or "-")


def output_class_lines(rows: list[Mapping[str, object]]) -> list[str]:
    """`## Trace: output classes by build`: one row per build with an `output` dict, one column per class key
    (sorted); a cell is `in -> out` when the row's `input` value differs, `-` when the key is missing."""

    chosen = [row for row in rows if isinstance(row.get("output"), Mapping)]
    def _kept(key: str) -> bool:
        if key.startswith("flask-"):
            return True
        if key.startswith("node") or key.rsplit(":", 1)[-1].isdigit():
            return False
        for row in chosen:
            for side in (row["output"], row.get("input")):
                if isinstance(side, Mapping) and side.get(key) not in (None, 0):
                    return True
        return False

    keys = sorted(key for key in {str(key) for row in chosen for key in row["output"]} if _kept(key))  # type: ignore[union-attr]
    lines = ["", "## Trace: output classes by build", ""]
    if not chosen or not keys:
        return lines + ["No output classes recorded."]
    lines += ["| class | " + " | ".join(str(row.get("reference")) for row in chosen) + " |", "|---|" + "---:|" * len(chosen)]
    for key in keys:
        cells = []
        for row in chosen:
            out = row["output"]
            inp = row.get("input") if isinstance(row.get("input"), Mapping) else {}
            if key not in out:  # type: ignore[operator]
                cells.append("-")
                continue
            value = out[key]  # type: ignore[index]
            before = inp.get(key)  # type: ignore[union-attr]
            cells.append(f"{before} -> {value}" if before is not None and before != value else f"{value}")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    return lines


def kick_counts(row: Mapping[str, object]) -> tuple[int, int]:
    """#619: (tried, kept) over the row's `kick tree` / `kick joint` moves."""

    kicks = [m for m in (row.get("moves") or row.get("move_rows") or ()) if isinstance(m, Mapping) and str(m.get("move")) in ("kick tree", "kick joint")]
    return len(kicks), sum(1 for m in kicks if m.get("kept"))


def kick_lines(rows: Iterable[Mapping[str, object]]) -> list[str]:
    """#619: one `kicks tried N / kept K` line per successful build."""

    return [f"- {row.get('reference')}: kicks tried {tried} / kept {kept}"
            for row in rows if row.get("ok") for tried, kept in [kick_counts(row)]]


def _move_list(row: Mapping[str, object]) -> tuple:
    return tuple((str(m.get("where")), str(m.get("move")), round(float(m.get("after") or 0.0), 6))
                 for m in (row.get("moves") or ()) if isinstance(m, Mapping))


def seed_spread(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """#619: per build (by `source`) over its seeds: spread of `value_after` = (max-min) / median in percent,
    the number of distinct move lists and of distinct finals, and the seeds."""

    groups: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        if row.get("ok"):
            groups.setdefault(str(row.get("source")), []).append(row)
    out = []
    for source, group in groups.items():
        values = [float(row["value_after"]) for row in group]
        median = statistics.median(values)
        out.append({
            "source": source,
            "reference": str(group[0].get("reference")),
            "seeds": [row.get("seed") for row in group],
            "spread_percent": (max(values) - min(values)) / median * 100.0 if median else 0.0,
            "distinct_move_lists": len({_move_list(row) for row in group}),
            "distinct_finals": len({round(v, 6) for v in values}),
        })
    return out


def seed_spread_lines(rows: Iterable[Mapping[str, object]]) -> list[str]:
    lines = ["", "## Seed spread", ""]
    for item in seed_spread(rows):
        lines.append(f"- {item['reference']} (`{item['source']}`), seeds {', '.join(str(x) for x in item['seeds'])}: "
                     f"spread {item['spread_percent']:.2f}% of median after; "
                     f"{item['distinct_move_lists']} distinct move list(s), {item['distinct_finals']} distinct final(s)")
    return lines


def render_report(rows: list[Mapping[str, object]], *, stamp: str, move: str, passes: int, workers: int,
                  seconds: float, against: tuple[Path, list[dict[str, Any]]] | None = None, trace: bool = False, seeds: int = 1) -> str:
    lines = [
        "# Replay bench",
        "",
        f"{stamp}; move `{move}`" + (f", {passes} pass(es)" if move == "loop" else "")
        + f"; {len(rows)} delivered builds; {human_duration(seconds)} on {workers} workers.",
        "",
    ]
    for row in rows:
        if _start_broken(row):
            lines.append(f"Start broken: {row.get('reference')}: violation {float(row.get('violation_before') or 0.0):.4f}, "
                         f"floors: {', '.join(str(name) for name in row['start_violated'])}")
    if len(lines) > 4:
        lines.append("")
    lines += [
        "| reference | source | recorded | replayed | replayed / recorded | after | gain | time | "
        "kept / judged+reverted / not kept | violation before / after | starts infeasible | audit errors |" + (" loop exit |" if move == "loop" else ""),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|" + ("---|" if move == "loop" else ""),
    ]
    successes = []
    for row in rows:
        if not row.get("ok"):
            lines.append(f"| {row.get('reference')} | `{row.get('source')}` | FAILED: {row.get('error')} | | | | | | | | | |" + (" |" if move == "loop" else ""))
            continue
        successes.append(row)
        broken = _start_broken(row)
        ratio = None if broken else _finite(row.get("replayed_over_recorded"))
        infeasible = ", ".join(str(name) for name in (row.get("start_violated") or ())) if row.get("start_infeasible") else "no"
        # the preparation is named only where it is not the fixture (the default), so a benchmark row reads as before
        source_cell = f"`{row['source']}`" + (f" ({row['preparation']})" if row.get("preparation") not in (None, "fixture") else "")
        lines.append(
            f"| {row['reference']} | {source_cell} | {_fmt_value(row.get('recorded_value'))} | "
            f"{_fmt_value(row.get('replayed_value', row['value_before']))} | {f'{ratio:.3f}x' if ratio is not None else '-'} | "
            f"{float(row['value_after']):,.0f} | "
            f"{'-' if broken else _fmt_percent(row.get('gain_percent'))} | {human_duration(float(row['seconds']))} | "
            f"{row['kept']} / {row.get('judged_and_reverted', '-')} / {_not_kept(row)} | "
            f"{float(row['violation_before']):.4f} / {float(row['violation_after']):.4f} | {infeasible} | {row['audit_errors']} |" + (f" {loop_exit_cell(row)} |" if move == "loop" else "")
        )
    def summary_block(title: str, chosen: list[Mapping[str, object]]) -> list[str]:
        """The acceptance table of one set of builds: what the move paid, and what it paid per
        minute (D84 judges a move on the paired report, so the pace belongs beside the gain)."""

        gains = [gain for gain in (_finite(row.get("gain_percent")) for row in chosen) if gain is not None]
        spent = [value for value in (_finite(row.get("seconds")) for row in chosen) if value is not None]
        if not gains:
            return [f"{title}: no successful replay rows."]
        block = [
            f"**{title}** ({len(gains)} builds)",
            f"Median gain: {statistics.median(gains):+.2f}%. Mean gain: {statistics.fmean(gains):+.2f}%.",
            f"Improved / unchanged / worse: {sum(gain > 1e-12 for gain in gains)} / "
            f"{sum(abs(gain) <= 1e-12 for gain in gains)} / {sum(gain < -1e-12 for gain in gains)}.",
        ]
        if spent:
            pace = human_rate_per_minute(statistics.fmean(gains), statistics.fmean(spent))
            block.append(f"Time per build: median {human_duration(statistics.median(spent))}, mean {human_duration(statistics.fmean(spent))}; "
                         f"gain per minute (mean gain / mean time): {pace:+.3f}%.")
        return block

    if move == "fixed-point":
        lines += ["", "## Fixed point per build", ""]
        for row in successes:
            lines += fixed_point_lines(row) + [""]
    lines += ["", "## Kicks per build", ""] + (kick_lines(rows) or ["No successful replay rows."])
    if seeds > 1:
        lines += seed_spread_lines(rows)
    lines += ["", "## Summary", ""]
    for row in successes:
        if row.get("final_repair_ran") and row.get("violation_after_loop") is not None:
            lines += [f"final floor repair: {row['reference']} violation {float(row['violation_after_loop']):.4f} -> {float(row['violation_after']):.4f}, "
                      f"value {float(row['value_after_loop']):,.0f} -> {float(row['value_after']):,.0f}", ""]
    gain_rows = [row for row in successes if not _start_broken(row)]
    lines += summary_block("over all builds", gain_rows)
    for kind in ("attack", "spell", "minion", "other"):
        grouped = [row for row in gain_rows if row.get("damage_kind") == kind]
        if grouped:
            lines += [""] + summary_block(f"{kind} builds", grouped)
    feasible_rows = [row for row in successes if _starts_feasible(row) and not _start_broken(row)]
    if len(feasible_rows) != len(successes):
        lines += [""] + summary_block(f"over builds that start feasible ({len(successes) - len(feasible_rows)} dropped)", feasible_rows)
    lines.append(f"Total time: {human_duration(sum(float(row.get('seconds') or 0.0) for row in successes))} (wall {human_duration(seconds)}).")

    # The consequence of judging a delivered build under today's rules, on its own line per build:
    # a replayed value below the recorded one, or a build whose start already misses a constraint.
    flagged: list[str] = []
    for row in successes:
        notes = []
        ratio = None if _start_broken(row) else _finite(row.get("replayed_over_recorded"))
        if ratio is not None and abs(ratio - 1.0) > 0.005:
            notes.append(f"recorded {float(row['recorded_value']):,.0f}, replayed {float(row['replayed_value']):,.0f} "
                         f"under today's rules ({ratio:.3f}x)")
        if row.get("start_infeasible"):
            notes.append("starts infeasible: " + (", ".join(str(name) for name in (row.get("start_violated") or ())) or "unnamed constraint"))
        if notes:
            flagged.append(f"{row['reference']}: " + "; ".join(notes))
    if flagged:
        lines += ["", "Builds the replay does not reproduce as delivered:"] + [f"- {line}" for line in flagged]
    elif successes:
        lines.append("Every build replays its recorded value and starts feasible.")
    lines += structural_lines(rows)
    lines += weapon_base_lines(rows)

    if against is not None:
        path, other_rows = against
        lines += ["", "## Paired Comparison", "", f"Against `{path}`; difference = against gain minus this run's gain.", ""]
        lines += _paired_lines("over all builds", rows, other_rows)
        feasible = [row for row in rows if not row.get("ok") or _starts_feasible(row)]
        dropped = len(successes) - sum(1 for row in successes if _starts_feasible(row))
        lines += [""] + _paired_lines(f"over builds that start feasible ({dropped} dropped)", feasible, other_rows)
    if trace:
        lines += ["", "## Trace: generated/evaluated by move and class"]
        for row in successes:
            lines += ["", f"### {row['reference']} (`{row['source']}`)", ""] + trace_table_lines(row.get("considered") or {})
        lines += output_class_lines(rows)
    return "\n".join(lines) + "\n"


def _against_rows(argument: str) -> tuple[Path, list[dict[str, Any]]]:
    path = Path(argument)
    if not path.exists():
        matches = sorted((ROOT / "artifacts" / "replay").glob(f"*-{argument}"))
        path = matches[-1] if matches else path
    results = path / "results.json" if path.is_dir() else path
    rows = _result_rows(results)
    if not rows:
        raise ValueError(f"no replay rows in {results}")
    return results, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--builds", required=True, help="glob of delivered .pob.txt builds")
    parser.add_argument("--move", required=True, help="one of: " + ", ".join(LEGAL_MOVES))
    parser.add_argument("--passes", type=int, default=1, help="whole-loop passes (only used by --move loop)")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=1, help="#619: run seeds seed..seed+N-1 of every build, each its own row; the report prints the spread per build")
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--against", help="another replay directory, results.json, or output tag")
    parser.add_argument("--trace", action="store_true", help="#498: print a move x class table (generated/evaluated) per build in the report")
    parser.add_argument("--mark-picked", action="store_true",
                        help="#427: mark the delivered build's single-gem utility groups as picked, so the utility move judges them (default off)")
    parser.add_argument("--record-calls", metavar="DIR",
                        help="record every PoB call of each replay to DIR/<source>.calls.jsonl (the refactor proof of #35)")
    args = parser.parse_args()
    move = validate_move(args.move)
    if args.passes < 1:
        parser.error("--passes must be at least 1")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.seeds < 1:
        parser.error("--seeds must be at least 1")
    patterns = [part.strip() for part in args.builds.split(";") if part.strip()]
    builds = sorted({Path(path) for pattern in patterns for path in glob.glob(pattern, recursive=True) if Path(path).is_file()})
    if not builds:
        parser.error(f"--builds matched no files: {args.builds}")
    stamp = time.strftime("%Y%m%d-%H%M") + f"-{args.tag}"
    out_dir = ROOT / "artifacts" / "replay" / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        record_calls = str(Path(args.record_calls).resolve()) if args.record_calls else None

        def submit_replay(job: tuple[Path, int]) -> Any:
            path, seed = job
            return pool.submit(replay_one, str(path), move=move, passes=args.passes, seed=seed, record_calls=record_calls, mark_picked=args.mark_picked)

        # #958: at most workers - yield replays in flight, the yield re-read before each one (a daemon yield file)
        jobs = [(path, seed) for path in builds for seed in range(args.seed, args.seed + args.seeds)]
        for future, _job in limited_completions(submit_replay, jobs, args.workers):
            row = future.result()
            if args.seeds > 1:
                row["reference"] = f"{row.get('reference')}@seed{row.get('seed')}"
            rows.append(row)
            if row["ok"]:
                print(f"  {row['reference']:30s} {row['value_before']:,.0f} -> {row['value_after']:,.0f} {_fmt_percent(row['gain_percent'])} {human_duration(row['seconds'])}", flush=True)
                for text in fixed_point_lines(row):
                    print("  " + text, flush=True)
            else:
                print(f"  {row['reference']:30s} FAILED {row['error']}", flush=True)
    rows.sort(key=lambda row: (str(row.get("reference")), str(row.get("source"))) + ((row.get("seed") or 0,) if args.seeds > 1 else ()))
    save_final_builds(rows, out_dir)
    against = _against_rows(args.against) if args.against else None
    elapsed = time.perf_counter() - started
    payload = {
        "stamp": stamp,
        "move": move,
        "passes": args.passes,
        "seed": args.seed,
        **({"seeds": args.seeds} if args.seeds > 1 else {}),
        "workers": args.workers,
        "seconds": elapsed,
        "rows": rows,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    report = render_report(rows, stamp=stamp, move=move, passes=args.passes, workers=args.workers, seconds=elapsed, against=against, trace=args.trace, seeds=args.seeds)
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    print(f"report: {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
