"""Issue #1030, unit 2: what PoB says when ONE keystone K is flipped on a finished build B.

For every (B, K): state 1 = B as loaded; state 2 = B with K allocated directly
(`mutate_nodes(add=[K])`; PoB's AllocNode brings its own shortest path), or K removed when B already
holds it. Both states' numbers are printed by PoB, the objective is the pipeline's own
(`objective_for(rails, main skill, mode)`, as `check_useful_lines.py` builds it), and the marginal value of
every allocated passive node and every affix line of the rare gear is measured in both states. The output is
raw JSON; this script decides nothing (no class line, no table).

    python scripts/keystone_flip.py --build spark [--keystone "Chaos Inoculation" ...] [--limit N] [--out file.json]

`--build` is spark | cold_dot | smite (the finished -s4 PoBs of the core-3 benchmark run) or a path to a PoB
XML / import-code file. `--out` defaults to `artifacts/keystone_flip/<build>.json`; the per-build baseline
(numbers + baseline marginals) is cached beside it as `<out stem>.baseline.json` and reused while the build
file is unchanged. The run is resumable: a keystone already in the JSON is skipped. The JSON is rewritten after
every keystone.

Marginal value of a node or a line (one `trial_stats` batch per state, mode "fast", the node removed with its
path kept, the line removed from its item): `(R - R_without) / R`, R = the maximized stat of the state with the
thing kept. Two readings are stored: `v` on the maximized stat alone, `p` on the pipeline's priced score
(`priced_value`: the value discounted by the floors the state misses; a state that misses a floor by >= 100 %
prices every node at 0, so `p` is None there). `collapsed` = the share of the things worth something in state 1
(value != 0) whose value in state 2 fell by more than half or changed sign; a node state 2 no longer holds
counts as 0, K itself is left out. Shares are by count and by baseline value; the counts are stored too.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "src"))  # src first: scripts/junkroan.py would shadow the package

BENCH_DIR = ROOT / "artifacts" / "benchmark" / "20261013-0101-P2-core-3"
NAMED_BUILDS = {name: BENCH_DIR / f"{name}-s4.pob.txt" for name in ("spark", "cold_dot", "smite")}
OUT_DIR = ROOT / "artifacts" / "keystone_flip"

STATS = ("CombinedDPS", "Life", "EnergyShield", "Mana", "ManaUnreserved", "TotalEHP", "PhysicalMaximumHitTaken", "ChaosResist")
DELTA_KEYS = (*STATS, "objective")


# -- pure part (no PoB) -------------------------------------------------------------------------------


def delta_pct(before: Any, after: Any) -> float | None:
    """The change from `before` to `after` in percent of |before|; None when either is not a number or
    `before` is 0 (no percentage exists)."""

    if isinstance(before, bool) or isinstance(after, bool) or not isinstance(before, (int, float)) or not isinstance(after, (int, float)):
        return None
    if not (math.isfinite(before) and math.isfinite(after)) or before == 0:
        return None
    return (after - before) / abs(before) * 100.0


def deltas(state1: Mapping[str, Any], state2: Mapping[str, Any], keys: Iterable[str] = DELTA_KEYS) -> dict[str, float | None]:
    return {k: delta_pct(state1.get(k), state2.get(k)) for k in keys}


def flip_choice(allocated: Iterable[int], keystone_id: int) -> str:
    """"remove" when the build already holds the keystone, else "add"."""

    return "remove" if int(keystone_id) in {int(n) for n in allocated} else "add"


def relative_marginal(reference: float | None, without: float | None) -> float | None:
    """(reference - without) / reference; None when there is no positive reference to measure against."""

    if reference is None or without is None or not (math.isfinite(reference) and math.isfinite(without)) or reference <= 0.0:
        return None
    return (reference - without) / reference


def is_collapsed(before: float, after: float) -> bool:
    """A thing worth something in state 1 (`before` != 0) whose value in state 2 fell by more than half, or
    changed sign. A thing worth nothing in state 1 has nothing to lose."""

    if before == 0.0:
        return False
    if before * after < 0.0:
        return True
    return before > 0.0 and after < before / 2.0


def collapsed_share(base: Mapping[str, float], flipped: Mapping[str, float]) -> dict[str, Any]:
    """The share of `base`'s valued things (value != 0) that collapse under the flip, by count and by
    baseline value (sum of the positive baseline values of the collapsed ones over the sum of all positive
    baseline values). A key missing from `flipped` is worth 0 there (the node is gone). Empty -> shares None."""

    valued = {k: v for k, v in base.items() if v != 0.0}
    gone = [k for k, v in valued.items() if is_collapsed(v, float(flipped.get(k, 0.0)))]
    pos_total = sum(v for v in valued.values() if v > 0.0)
    pos_gone = sum(valued[k] for k in gone if valued[k] > 0.0)
    return {
        "n": len(valued),
        "n_collapsed": len(gone),
        "share_count": len(gone) / len(valued) if valued else None,
        "value_total": pos_total,
        "value_collapsed": pos_gone,
        "share_value": pos_gone / pos_total if pos_total > 0.0 else None,
        "collapsed": sorted(gone),
    }


def pending_keystones(keystones: Sequence[tuple[int, str]], rows: Iterable[Mapping[str, Any]], names: Sequence[str] = (), limit: int | None = None) -> list[tuple[int, str]]:
    """The keystones (node id, name) still to measure: those named in `names` (case-insensitive; all when
    empty) that no row of `rows` holds, in name order, at most `limit`. An unknown name raises."""

    ordered = sorted(keystones, key=lambda k: (k[1].lower(), k[0]))
    if names:
        wanted = {n.lower() for n in names}
        unknown = wanted - {name.lower() for _id, name in ordered}
        if unknown:
            raise ValueError(f"unknown keystone(s): {sorted(unknown)}")
        ordered = [k for k in ordered if k[1].lower() in wanted]
    done = {int(r["node_id"]) for r in rows}
    todo = [k for k in ordered if k[0] not in done]
    return todo[:limit] if limit is not None else todo


def json_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    """The scalar entries of a PoB stats dict, JSON-safe (a non-finite float becomes its name)."""

    out: dict[str, Any] = {}
    for k, v in stats.items():
        if isinstance(v, bool) or isinstance(v, int):
            out[k] = v
        elif isinstance(v, float):
            out[k] = v if math.isfinite(v) else str(v)
        elif isinstance(v, str):
            out[k] = v
    return out


def _atomic_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# -- PoB part ------------------------------------------------------------------------------------------


def load_build_xml(path: Path) -> str:
    from junkroan.pob.session import decode_import_code

    text = path.read_text(encoding="utf-8").strip()
    return text if text.startswith("<") else decode_import_code(text)


def state_numbers(pob: Any, objective: Any) -> dict[str, Any]:
    """PoB's own numbers of the live build: the report stats, the objective's keys, and the objective value
    (the maximized stat), its floor violations and the priced score."""

    from junkroan.optimizer.objective import priced_value

    keys = tuple(dict.fromkeys((*STATS, *objective.stat_keys)))
    stats = pob.stats(keys)
    score = objective.score(stats)
    out = json_stats({k: stats.get(k) for k in keys if k in stats})
    out["objective"] = score.value if math.isfinite(score.value) else str(score.value)
    out["objective_stat"] = objective.maximize
    out["violation"] = score.violation if math.isfinite(score.violation) else str(score.violation)
    out["violations"] = {k: v for k, v in objective.violations(stats).items()}
    out["priced"] = priced_value(score)
    return out


def measure_marginals(pob: Any, objective: Any, node_ids: Sequence[int], items: Sequence[tuple[str, str, str]]) -> dict[str, Any]:
    """The marginal value of each node (removed, path kept) and each affix line of `items`
    ((slot, base, raw) of the rare gear) on the live build: ONE fast `trial_stats` batch.

    -> {"nodes": {node_id: (v, p)}, "lines": {"<slot>#<index>": (v, p)}, "line_info": {key: (kind, text)},
    "failed": [keys of trials PoB did not answer], "full": {"v": R, "p": P}}. `v` / `p` as in the module doc."""

    from junkroan.optimizer.objective import priced_value
    from junkroan.optimizer.useful_lines import item_lines, trial_item

    trials: list[dict[str, Any]] = [{}]
    labels: list[tuple[str, Any]] = [("full", None)]
    for node_id in node_ids:
        trials.append({"remove": [int(node_id)]})
        labels.append(("node", int(node_id)))
    line_info: dict[str, tuple[str, str]] = {}
    for slot, _base, raw in items:
        lines = item_lines(raw)
        if not lines:
            continue
        trials.append({"item": {"slot": slot, "raw": raw}})
        labels.append(("item_full", slot))
        for ln in lines:
            key = f"{slot}#{ln.index}"
            line_info[key] = (ln.kind, ln.text)
            trials.append({"item": trial_item(slot, raw, [ln])})
            labels.append(("line", key))
    outcomes = pob.trial_stats(trials, objective.stat_keys, mode="fast")
    if len(outcomes) != len(trials):
        raise RuntimeError(f"trial_stats returned {len(outcomes)} outcomes for {len(trials)} trials")

    def readings(outcome: Mapping[str, Any]) -> tuple[float, float] | None:
        if not outcome.get("ok") or not outcome.get("stats"):
            return None
        score = objective.score(outcome["stats"])
        return (score.value, priced_value(score))

    nodes: dict[int, tuple[float | None, float | None]] = {}
    lines_out: dict[str, tuple[float | None, float | None]] = {}
    failed: list[str] = []
    full = readings(outcomes[0])
    if full is None:
        raise RuntimeError(f"PoB did not answer the state's own trial: {outcomes[0].get('error')}")
    item_ref: dict[str, tuple[float, float] | None] = {}
    for (kind, ref), outcome in zip(labels[1:], outcomes[1:]):
        got = readings(outcome)
        if kind == "item_full":
            item_ref[ref] = got
        elif kind == "node":
            if got is None:
                failed.append(f"node:{ref}")
            else:
                nodes[ref] = (relative_marginal(full[0], got[0]), relative_marginal(full[1], got[1]))
        else:  # a line: its item's own full candidate is the reference, as `useful_lines.line_values_many`
            ref_item = item_ref.get(ref.split("#", 1)[0])
            if got is None or ref_item is None:
                failed.append(f"line:{ref}")
            else:
                lines_out[ref] = (relative_marginal(ref_item[0], got[0]), relative_marginal(ref_item[1], got[1]))
    return {"nodes": nodes, "lines": lines_out, "line_info": line_info, "failed": failed, "full": {"v": full[0], "p": full[1]}}


def allocated_measurable(pob: Any) -> list[int]:
    """The allocated nodes of the live build a removal trial is run on: the user-allocatable ones (no
    ascendancy, no class start)."""

    from junkroan.optimizer.tree_graph import TreeGraph

    graph = TreeGraph.load()
    tree = pob.tree_light()
    return sorted(int(n) for n in tree.get("user_allocated_node_ids") or () if int(n) in graph.allocatable)


def keystones() -> list[tuple[int, str]]:
    from junkroan.optimizer.tree_graph import TreeGraph

    return [(n.node_id, n.name) for n in TreeGraph.load().nodes.values() if n.kind == "keystone"]


def _split(marginals: Mapping[Any, tuple[float | None, float | None]], which: int, drop: Iterable[Any] = ()) -> dict[str, float]:
    skip = {str(d) for d in drop}
    return {str(k): v[which] for k, v in marginals.items() if v[which] is not None and str(k) not in skip}


def collapsed_block(base: Mapping[str, Any], nodes2: Mapping[int, tuple[float | None, float | None]], lines2: Mapping[str, tuple[float | None, float | None]],
                    *, gone: Iterable[int], unmeasured: Iterable[str], keystone_id: int, priced_ok: bool) -> dict[str, Any]:
    """`collapsed` of one row, for the v and the p reading. `gone` = baseline nodes state 2 no longer holds
    (worth 0 there); `unmeasured` = trial keys ("node:<id>" / "line:<key>") PoB did not answer in state 2
    (left out on both sides)."""

    out: dict[str, Any] = {}
    skip_nodes = {str(keystone_id), *(u.split(":", 1)[1] for u in unmeasured if u.startswith("node:"))}
    skip_lines = {u.split(":", 1)[1] for u in unmeasured if u.startswith("line:")}
    for name, which in (("value", 0), ("priced", 1)):
        if which == 1 and not priced_ok:
            out[name] = None
            continue
        b_nodes = {k: v["vp"][which] for k, v in base["nodes"].items() if v["vp"][which] is not None and k not in skip_nodes}
        b_lines = {k: v["vp"][which] for k, v in base["lines"].items() if v["vp"][which] is not None and k not in skip_lines}
        f_nodes = _split(nodes2, which)
        f_nodes.update({str(g): 0.0 for g in gone})
        f_lines = _split(lines2, which)
        out[name] = {"nodes": collapsed_share(b_nodes, f_nodes), "lines": collapsed_share(b_lines, f_lines)}
    return out


def build_baseline(pob: Any, objective: Any, xml: str, xml_sha: str) -> dict[str, Any]:
    from check_useful_lines import rare_items
    from junkroan.optimizer.tree_graph import TreeGraph

    t0 = time.monotonic()
    graph = TreeGraph.load()
    node_ids = allocated_measurable(pob)
    items = rare_items(xml)
    numbers = state_numbers(pob, objective)
    m = measure_marginals(pob, objective, node_ids, items)
    nodes = {}
    for nid, vp in m["nodes"].items():
        node = graph.node(nid)
        nodes[str(nid)] = {"name": node.name if node else str(nid), "kind": node.kind if node else "unknown", "vp": list(vp)}
    lines = {}
    for key, vp in m["lines"].items():
        kind, text = m["line_info"][key]
        lines[key] = {"kind": kind, "text": text, "vp": list(vp)}
    return {
        "xml_sha256": xml_sha,
        "numbers": numbers,
        "full": m["full"],
        "node_ids": node_ids,
        "items": [{"slot": s, "base": b} for s, b, _r in items],
        "nodes": nodes,
        "lines": lines,
        "failed": m["failed"],
        "seconds": time.monotonic() - t0,
    }


def measure_keystone(pob: Any, objective: Any, xml: str, baseline: Mapping[str, Any], keystone_id: int, keystone_name: str) -> dict[str, Any]:
    """One row: state 2 of keystone K against `baseline` (state 1); the build is reloaded from `xml` after."""

    from check_useful_lines import rare_items

    t0 = time.monotonic()
    row: dict[str, Any] = {"keystone": keystone_name, "node_id": int(keystone_id), "state1": baseline["numbers"], "status": "ok", "reason": None}
    allocated_before = allocated_measurable(pob)
    flip = flip_choice(allocated_before, keystone_id)
    row["flip"] = flip
    try:
        try:
            result = pob.mutate_nodes(remove=[keystone_id]) if flip == "remove" else pob.mutate_nodes(add=[keystone_id])
        except Exception as exc:  # PoB (the worker) refuses: unknown id, no path, ...
            row.update(status="pob_refused", reason=f"{type(exc).__name__}: {exc}", state2=None, delta_pct=None, collapsed=None)
            return row
        allocated_after = {int(n) for n in result.get("allocated_node_ids") or ()}
        row["added_node_ids"] = [int(n) for n in result.get("added_node_ids") or ()]
        row["removed_node_ids"] = [int(n) for n in result.get("removed_node_ids") or ()]
        if (flip == "add") != (int(keystone_id) in allocated_after):
            row.update(status="not_flipped", reason=f"flip {flip}: node {keystone_id} is {'not ' if flip == 'add' else 'still '}allocated after mutate_nodes", state2=None, delta_pct=None, collapsed=None)
            return row
        state2 = state_numbers(pob, objective)
        row["state2"] = state2
        row["delta_pct"] = deltas(baseline["numbers"], state2)
        value2 = state2.get("objective")
        if not isinstance(value2, (int, float)) or value2 <= 0.0:
            row.update(status="skill_dead", reason=f"{state2.get('objective_stat')} = {value2} in state 2", collapsed=None)
            return row
        node_ids = [int(n) for n in baseline["node_ids"] if int(n) in allocated_after]
        gone = [int(n) for n in baseline["node_ids"] if int(n) not in allocated_after and int(n) != int(keystone_id)]
        m = measure_marginals(pob, objective, node_ids, rare_items(xml))
        row["marginals2"] = {
            "nodes": {str(k): list(v) for k, v in m["nodes"].items()},
            "lines": {k: list(v) for k, v in m["lines"].items()},
            "unmeasured": m["failed"],
            "gone_nodes": gone,
        }
        priced_ok = m["full"]["p"] is not None and m["full"]["p"] > 0.0 and baseline["full"]["p"] > 0.0
        row["collapsed"] = collapsed_block(baseline, m["nodes"], m["lines"], gone=gone, unmeasured=m["failed"], keystone_id=keystone_id, priced_ok=priced_ok)
        return row
    finally:
        pob.load_xml(xml)  # exact restore of state 1
        row["seconds"] = time.monotonic() - t0


def run(argv: Sequence[str] | None = None) -> int:
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession
    from junkroan.report_format import human_duration

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build", required=True, help="spark | cold_dot | smite | path to a PoB XML / import-code file")
    ap.add_argument("--keystone", action="append", default=[], help="keystone name (repeatable); default every keystone of the tree")
    ap.add_argument("--out", help="output JSON (default artifacts/keystone_flip/<build>.json)")
    ap.add_argument("--limit", type=int, help="measure at most N keystones in this run")
    args = ap.parse_args(argv)

    path = NAMED_BUILDS.get(args.build, Path(args.build))
    label = args.build if args.build in NAMED_BUILDS else path.name.removesuffix(".txt").removesuffix(".pob")
    out = Path(args.out) if args.out else OUT_DIR / f"{label}.json"
    cache = out.with_name(f"{out.stem}.baseline.json")
    xml = load_build_xml(path)
    xml_sha = hashlib.sha256(xml.encode("utf-8")).hexdigest()

    payload: dict[str, Any] = {"build": label, "path": str(path), "xml_sha256": xml_sha, "rows": []}
    if out.is_file():
        old = json.loads(out.read_text(encoding="utf-8"))
        if old.get("xml_sha256") == xml_sha:
            payload = old
        else:
            print(f"{out} belongs to another build file (hash differs): starting it again", file=sys.stderr)
    todo = pending_keystones(keystones(), payload["rows"], args.keystone, args.limit)
    print(f"{label}: {len(payload['rows'])} keystones already measured, {len(todo)} to do", file=sys.stderr)
    if not todo:
        return 0

    rails = Rails.load()
    with PobSession(run_id=f"keystone-flip-{label}") as pob:
        pob.load_xml(xml)
        skeleton = skeleton_from_xml(xml, pob, rails=rails)
        objective = objective_for(rails, skeleton.main_link[0], mode=skeleton.mode)
        pob.load_xml(xml)
        payload["main_skill"] = skeleton.main_link[0]
        payload["mode"] = skeleton.mode
        payload["objective"] = objective.describe()

        baseline = None
        if cache.is_file():
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("xml_sha256") == xml_sha:
                baseline = cached
        if baseline is None:
            baseline = build_baseline(pob, objective, xml, xml_sha)
            _atomic_write(cache, baseline)
            print(f"baseline: {len(baseline['nodes'])} nodes, {len(baseline['lines'])} lines, {human_duration(baseline['seconds'])}", file=sys.stderr)
        payload["baseline"] = {"numbers": baseline["numbers"], "n_nodes": len(baseline["nodes"]), "n_lines": len(baseline["lines"]), "cache": str(cache)}
        if not isinstance(baseline["numbers"].get("objective"), (int, float)) or baseline["numbers"]["objective"] <= 0.0:
            raise SystemExit(f"{label}: the build itself has {baseline['numbers'].get('objective_stat')} = {baseline['numbers'].get('objective')}: nothing to flip")

        for node_id, name in todo:
            row = measure_keystone(pob, objective, xml, baseline, node_id, name)
            payload["rows"].append(row)
            _atomic_write(out, payload)
            c = (row.get("collapsed") or {}).get("value") or {}
            d = (row.get("delta_pct") or {}).get("objective")
            print(f"{name}: {row['flip']} {row['status']} objective {'-' if d is None else f'{d:+.1f}%'}"
                  f" collapsed nodes {_pct((c.get('nodes') or {}).get('share_count'))} lines {_pct((c.get('lines') or {}).get('share_count'))}"
                  f" ({human_duration(row['seconds'])})", file=sys.stderr)
    return 0


def _pct(share: float | None) -> str:
    return "-" if share is None else f"{share:.0%}"


if __name__ == "__main__":
    raise SystemExit(run())
