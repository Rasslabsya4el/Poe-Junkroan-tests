"""#1159 unit 2 (refine-trace): does one `refine` pass generate and evaluate a candidate that holds BOTH missing
Melding nodes on the finished Contagion build A1?

A1 = the delivered `01 witch_occultist_no_iron_will_prophecy_wand` build of `artifacts/search-contagion/20261015-0336`
(seed 1). The probe loads it into one PobSession exactly as `scripts/replay_bench.py` loads a delivered build (the
same `_pipeline_state`), runs the loop's own `refine` move for ONE pass (`LoopPlan.replay("refine", passes=1)`, the
tree optimizer's defaults: max_depth 6, max_trials 300, skip_inert off), and counts at the PoB boundary:

* trace classes `melding:both` (a trial whose `add` + `path` hold every node still missing of the target notable),
  split into `melding:both+add-only` (the candidate's own probe) and `melding:both+swap` (the swap trial that pairs
  it with `cost` cheapest leaves): `generated` = trials that reached `TreeOptimizer._measure`, `evaluated` = trials
  `PobSession.trial_stats` sent to PoB (`trace.py`, the same counter a kind-A test reads);
* per refine round: where the candidate stood before it was cut or kept (index in `_trials_for`'s list against
  `max_trials`, its rank among the add batch against `top_candidates`, the leaves the swap would remove, the swap's
  objective against the build's, and the acceptance rule of `refine`).

Nothing in src/ is changed or patched for good: the probe wraps `TreeOptimizer._measure` and `_trials_for` for the
run and restores them. A deadline (default 5 min for the move) stops the pass and prints what was collected.

    python scripts/machine_load.py --need 1 --role other        # wait for GO first
    python scripts/probe_melding_refine.py [--build FILE] [--seed 1] [--out artifacts/probe-1159] [--max-seconds 300]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))  # src first: scripts/junkroan.py would shadow the package

from junkroan.optimizer.trace import TRACE, register_class  # noqa: E402
import junkroan.optimizer.trace as _trace  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

A1 = ROOT / "artifacts" / "search-contagion" / "20261015-0336" / "01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
TARGET = "Melding"
FORBID = ("Iron Will",)  # the skeleton of A1 says `forbid_keystones: ['Iron Will']`; an XML cannot carry it
CLASS_BOTH = "melding:both"
CLASS_ADD = "melding:both+add-only"
CLASS_SWAP = "melding:both+swap"
STATS = ("CombinedDPS", "FullDPS", "Life", "EnergyShield", "TotalEHP")


class Deadline(BaseException):
    """Raised inside the measure wrapper when the move ran past its time; a BaseException so no `except Exception` of the loop eats it."""


# -- pure parts (no PoB) -------------------------------------------------------------------------------------------


def trial_nodes(trial: Mapping[str, Any]) -> set[int]:
    """The nodes a tree trial allocates: its `add` and the `path` the candidate walks on the way (trace-only key)."""

    return {int(n) for key in ("add", "path") for n in (trial.get(key) or ())}


def holds_all(trial: Mapping[str, Any], nodes: Iterable[int]) -> bool:
    need = {int(n) for n in nodes}
    return bool(need) and need <= trial_nodes(trial)


def candidate_classes(nodes: Iterable[int]):
    """The trace class function: `melding:both` for a trial holding every node of `nodes`, plus add-only / swap."""

    need = frozenset(int(n) for n in nodes)

    def classes(trial: dict) -> Iterable[str]:
        if not isinstance(trial, dict) or not need or not need <= trial_nodes(trial):
            return ()
        return (CLASS_BOTH, CLASS_SWAP if trial.get("remove") else CLASS_ADD)

    return classes


def batch_kind(trials: Sequence[Mapping[str, Any]]) -> str:
    """Which `refine` batch a `_measure` call is: the leaf removals, the candidate adds, or the swaps."""

    if not trials:
        return "empty"
    if all(t.get("remove") and not t.get("add") for t in trials):
        return "leaf"
    if all(t.get("add") and t.get("remove") for t in trials):
        return "swap"
    if all(t.get("add") and not t.get("remove") for t in trials):
        return "add"
    return "other"


def counter(considered: Mapping[str, Mapping[str, Mapping[str, int]]], cls: str) -> tuple[int, int]:
    """(generated, evaluated) of one trace class summed over every move of `TRACE.considered()`."""

    generated = evaluated = 0
    for classes in considered.values():
        entry = classes.get(cls)
        if entry:
            generated += int(entry.get("generated", 0))
            evaluated += int(entry.get("evaluated", 0))
    return generated, evaluated


def delta_percent(before: float, after: float) -> float | None:
    return (after / before - 1.0) * 100.0 if before else None


def rank_among(rows: Sequence[tuple[Any, tuple, int]], key: Any) -> tuple[int | None, int]:
    """Place of the row `key` in `rows` = [(id, rank key, cost)] sorted best first (1 = best); (None, total) when absent."""

    ordered = sorted(rows, key=lambda r: r[1], reverse=True)
    for place, (rid, _k, _c) in enumerate(ordered, 1):
        if rid == key:
            return place, len(ordered)
    return None, len(ordered)


# -- PoB part ------------------------------------------------------------------------------------------------------


def _stat_row(stats: Mapping[str, Any]) -> dict[str, Any]:
    return {k: stats.get(k) for k in STATS if k in stats}


def run(args: argparse.Namespace) -> dict[str, Any]:
    import replay_bench as rb  # imports the whole optimizer; only the PoB part needs it
    from junkroan.optimizer.improvement_loop import LoopPlan, WorkingBuild
    from junkroan.optimizer.objective_select import forced_keystones_of, objective_for
    from junkroan.optimizer.pipeline import BuildResult
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.tree_graph import TreeGraph
    from junkroan.optimizer.tree_optimizer import TreeOptimizer
    from junkroan.pob.session import PobSession

    path = Path(args.build)
    logs: list[str] = []
    graph = TreeGraph.load()
    started = time.perf_counter()
    out: dict[str, Any] = {"build": str(path), "seed": args.seed, "rounds": [], "trials_for": [], "leaf_order": []}
    state: dict[str, Any] = {"round": 0, "t0": None, "aborted": False}

    original_skeleton_from_xml = rb.skeleton_from_xml

    def skeleton_with_forbid(xml, *a, **k):
        skeleton = original_skeleton_from_xml(xml, *a, **k)
        skeleton.forbid_keystones = list(args.forbid)
        return skeleton

    rb.skeleton_from_xml = skeleton_with_forbid
    original_measure, original_trials_for = TreeOptimizer._measure, TreeOptimizer._trials_for
    registered = None
    try:
        with PobSession(run_id=f"probe1159-{path.stem[:20]}") as pob:
            pob.load_import_code(path.read_text(encoding="utf-8").strip())
            rails = Rails.load()
            sk0 = skeleton_with_forbid(pob.export_xml(), pob=pob, log=logs.append)
            objective = objective_for(rails, sk0.main_link[0], mode=sk0.mode, forced_keystones=forced_keystones_of(sk0))
            prepared = SimpleNamespace(rails=rails, objective=objective)
            pipeline, skeleton, gear, tree = rb._pipeline_state(pob, prepared, gear_mode="loot", log=logs.append)
            keys = tuple(dict.fromkeys((*STATS, *pipeline.objective.stat_keys)))
            start_stats = pob.stats(keys)
            start_score = pipeline.objective.score(start_stats)
            out["main_skill"], out["mode"], out["objective_stat"] = skeleton.main_link[0], skeleton.mode, pipeline.objective.maximize
            out["start"] = {**_stat_row(start_stats), "value": start_score.value, "violation": -start_score.neg_violation,
                            "violated": sorted(pipeline.objective.violations(start_stats))}

            # -- the build's tree, decoded
            allocated = tree.current_allocated()
            targets = [n for n, node in graph.nodes.items() if node.name == args.target]
            costs = graph.bfs_costs(allocated, max_depth=tree.max_depth)
            reach = [(n, costs[n]) for n in targets if n in costs]
            if not reach:
                raise SystemExit(f"{args.target}: no node of that name is reachable from the build within {tree.max_depth} points")
            target_id, (target_cost, target_path) = min(reach, key=lambda r: r[1][0])
            missing = [int(n) for n in target_path]
            out["target"] = {"id": target_id, "name": args.target, "cost": target_cost, "missing": missing,
                             "missing_nodes": {str(n): {"name": graph.nodes[n].name, "kind": graph.nodes[n].kind, "stats": list(graph.nodes[n].stats)} for n in missing}}
            near = {n for n in allocated if n in graph.allocatable and any(n in graph.neighbours(m) or n in graph.neighbours(t) for m in missing for t in graph.neighbours(m))}
            out["target"]["allocated_next_to_missing"] = {str(n): graph.nodes[n].name for n in sorted(near)}
            leaves = [n for n in graph.removable_leaves(allocated, protected=tree.protected, links=tree._links()) if n in graph.allocatable]

            def notables_near(leaf: int) -> list[str]:
                seen, frontier, found = {leaf}, [leaf], []
                for _ in range(5):
                    nxt = []
                    for f in frontier:
                        for nb in graph.neighbours(f):
                            if nb in allocated and nb not in seen:
                                seen.add(nb)
                                nxt.append(nb)
                                node = graph.nodes.get(nb)
                                if node is not None and node.kind in ("notable", "keystone"):
                                    found.append(node.name)
                    frontier = nxt
                return found

            out["removable_leaves"] = {str(n): {"name": graph.nodes[n].name, "stats": list(graph.nodes[n].stats), "notables_within_5": notables_near(n)} for n in leaves}

            # -- the instruments
            registered = candidate_classes(missing)
            register_class(registered)
            TRACE.reset()

            def current_round() -> dict[str, Any]:
                while len(out["rounds"]) < state["round"]:
                    out["rounds"].append({"round": len(out["rounds"]) + 1})
                return out["rounds"][state["round"] - 1]

            def trials_for(self, candidates):
                trials = original_trials_for(self, candidates)
                place = next((i for i, t in enumerate(trials) if holds_all(t["trial"], missing)), None)
                out["trials_for"].append({"round": state["round"], "candidates": len(candidates), "trials": len(trials), "max_trials": self.max_trials,
                                          "index_of_target": place, "inside_max_trials": place is not None and place < self.max_trials,
                                          "cost_ge_target": sum(1 for t in trials if t["candidate"].cost <= target_cost),
                                          "target_in_candidates": any(c.node_id == target_id for c in candidates)})
                return trials

            def measuring(self, trials, keys_, stats):
                kind = batch_kind(trials)
                if state["t0"] is not None and time.perf_counter() - state["t0"] > args.max_seconds:
                    state["aborted"] = True
                    raise Deadline()
                if kind == "leaf":
                    state["round"] += 1
                outcomes = original_measure(self, trials, keys_, stats)
                try:
                    note(self, kind, trials, outcomes, stats)
                except Exception:  # noqa: BLE001 - the instrument must never change the search
                    current_round()[f"{kind}_note_error"] = traceback.format_exc()
                return outcomes

            def note(self, kind, trials, outcomes, stats):
                row = current_round()
                current = self.objective.score(stats) if stats else None
                if current is not None:
                    row.setdefault("score_before", {"value": current.value, "violation": -current.neg_violation})
                if kind == "leaf":
                    scored = [(self.objective.score(o["stats"]), t["remove"][0]) for t, o in zip(trials, outcomes)
                              if o.get("ok") and o.get("stats") and len(o.get("removed_node_ids") or ()) == 1]
                    scored.sort(key=lambda item: (item[0].neg_violation, item[0].value), reverse=True)  # refine's own order, cheapest first
                    cheap = [leaf for _s, leaf in scored]
                    row["leaves"] = {"measured": len(trials), "usable": len(scored), "cheapest_first": [
                        {"id": leaf, "name": graph.nodes[leaf].name, "stats": list(graph.nodes[leaf].stats), "value": s.value, "violation": -s.neg_violation} for s, leaf in scored[:12]]}
                    row["_cheap"] = cheap
                    out["leaf_order"] = [{"round": state["round"], "order": cheap}] if state["round"] == 1 else out["leaf_order"]
                elif kind == "add":
                    rows, hit = [], None
                    for i, (t, o) in enumerate(zip(trials, outcomes)):
                        if not (o.get("ok") and o.get("stats")):
                            continue
                        cost = len(o.get("added_node_ids") or ()) or len(t.get("path") or ()) or 1
                        sc = self.objective.score(o["stats"])
                        rows.append((i, self._rank_key(current, sc, cost), cost))
                        if holds_all(t, missing) and hit is None:
                            hit = (i, sc, cost, o)
                    place, total = rank_among([r for r in rows if r[2] <= 6 and r[2] <= len(row.get("_cheap", ()))], hit[0] if hit else None)
                    row["add_batch"] = {"trials": len(trials), "ranked": total, "top_candidates": 80, "target_probe_sent": hit is not None}
                    if hit is not None:
                        i, sc, cost, o = hit
                        row["add_batch"]["target"] = {"place_in_rank": place, "inside_top_candidates": place is not None and place <= 80, "cost": cost,
                                                      "value": sc.value, "delta_percent": delta_percent(current.value, sc.value), "violation": -sc.neg_violation,
                                                      "stats": _stat_row(o["stats"]), "rank_key": list(self._rank_key(current, sc, cost)),
                                                      "note": "rank replicated from the raw trial scores (refine ranks them after _judge_with_enablers)"}
                elif kind == "swap":
                    hits = []
                    for t, o in zip(trials, outcomes):
                        if holds_all(t, missing):
                            sc = self.objective.score(o["stats"]) if o.get("ok") and o.get("stats") else None
                            net = len(o.get("added_node_ids") or ()) - len(o.get("removed_node_ids") or ())
                            better = bool(sc is not None and sc > current and (not current.feasible or sc.value >= current.value * 1.002))
                            hits.append({"remove": [int(n) for n in t["remove"]], "remove_names": [graph.nodes[int(n)].name for n in t["remove"]],
                                         "ok": bool(o.get("ok")), "net_points": net, "value": sc.value if sc else None, "violation": -sc.neg_violation if sc else None,
                                         "delta_percent": delta_percent(current.value, sc.value) if sc else None, "stats": _stat_row(o.get("stats") or {}),
                                         "refine_accepts": better, "cheap_leaves_head": row.get("_cheap", [])[:4]})
                    row["swap_batch"] = {"trials": len(trials), "target_swaps": hits}

            TreeOptimizer._measure, TreeOptimizer._trials_for = measuring, trials_for
            result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode="loot")
            start_alloc = set(tree.current_allocated())
            state["t0"] = time.perf_counter()
            try:
                pipeline.improve(WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree), result,
                                 LoopPlan.replay("refine", seed=args.seed, passes=1))
            except Deadline:
                pass
            out["move_seconds"] = time.perf_counter() - state["t0"]
            end_alloc = set(tree.current_allocated())
            out["tree_diff"] = {"added": sorted(end_alloc - start_alloc), "removed": sorted(start_alloc - end_alloc)}
            considered = TRACE.considered()
            out["trace"] = {cls: dict(zip(("generated", "evaluated"), counter(considered, cls))) for cls in (CLASS_BOTH, CLASS_ADD, CLASS_SWAP, *(f"node:{n}" for n in missing))}
            out["aborted_at_deadline"] = state["aborted"]
            out["end"] = _stat_row(pob.stats(keys))
            out["log_tail"] = logs[-10:]
    finally:
        TreeOptimizer._measure, TreeOptimizer._trials_for = original_measure, original_trials_for
        rb.skeleton_from_xml = original_skeleton_from_xml
        if registered is not None and registered in _trace._REGISTRY:
            _trace._REGISTRY.remove(registered)
    for row in out["rounds"]:
        row.pop("_cheap", None)
    out["total_seconds"] = time.perf_counter() - started
    return out


def report_lines(out: Mapping[str, Any]) -> list[str]:
    t = out["target"]
    lines = [f"A1 {out['build']}",
             f"main skill {out['main_skill']} ({out['mode']}), objective {out['objective_stat']}, start {out['start']}",
             f"target {t['name']} id {t['id']}: cost {t['cost']}, missing nodes {t['missing']} "
             + ", ".join(f"{n} {v['name']} [{v['kind']}] {v['stats']}" for n, v in t["missing_nodes"].items()),
             f"allocated next to them: {t['allocated_next_to_missing']}"]
    for cls, c in out["trace"].items():
        lines.append(f"trace {cls}: generated {c['generated']}, evaluated {c['evaluated']}")
    for call in out["trials_for"]:
        lines.append(f"_trials_for round {call['round']}: {call['candidates']} candidates, {call['trials']} trials, max_trials {call['max_trials']}, "
                     f"target index {call['index_of_target']} (inside max_trials: {call['inside_max_trials']}; target is a candidate: {call['target_in_candidates']})")
    for r in out["rounds"]:
        lines.append(f"round {r['round']}: before {r.get('score_before')}")
        if "leaves" in r:
            lines.append(f"  leaves measured {r['leaves']['measured']}, usable {r['leaves']['usable']}; cheapest to lose: "
                         + "; ".join(f"{x['id']} {x['name']} {x['stats']} -> {x['value']:,.0f}" for x in r["leaves"]["cheapest_first"][:6]))
        if "add_batch" in r:
            lines.append(f"  add batch {r['add_batch']}")
        if "swap_batch" in r:
            lines.append(f"  swap batch trials {r['swap_batch']['trials']}, swaps holding the target: {r['swap_batch']['target_swaps']}")
    lines.append(f"tree diff: {out['tree_diff']}; end {out['end']}")
    lines.append(f"move {human_duration(out['move_seconds'])}, whole probe {human_duration(out['total_seconds'])}"
                 + ("; STOPPED AT THE DEADLINE" if out["aborted_at_deadline"] else ""))
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build", default=str(A1), help="a delivered .pob.txt (default: A1)")
    parser.add_argument("--target", default=TARGET, help="the notable whose missing nodes the candidate must hold")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--forbid", action="append", default=list(FORBID), help="forbidden keystone (A1's skeleton forbids Iron Will)")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "probe-1159"))
    parser.add_argument("--max-seconds", type=float, default=300.0, help="stop the refine pass after this many seconds and report")
    args = parser.parse_args()
    out = run(args)
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "melding-refine.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("\n".join(report_lines(out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
