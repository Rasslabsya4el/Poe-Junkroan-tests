"""Optimizer acceptance experiment: strip points from a reference build, let the
optimizer re-spend them, compare to the original.

Run:  python scripts/recover_tree.py stormbrand [--points 30] [--depth 6]

Stripping removes whole branches (cascading removals of 2..12 nodes) so the
optimizer has to re-path to payoff nodes, not just re-take adjacent leaves.
Objective: maximize CombinedDPS subject to Life / EHP / resists not falling
below (slightly relaxed) original values.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code, encode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
KEYS = ("CombinedDPS", "FullDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist")


def strip_branches(graph: TreeGraph, allocated: set[int], target_points: int, *, seed: int = 1) -> tuple[set[int], list[list[int]]]:
    """Remove branches (cascade size 2..12) until >= target_points nodes are gone."""

    rng = random.Random(seed)
    removed_groups: list[list[int]] = []
    remaining = set(allocated)
    total = 0
    attempts = 0
    while total < target_points and attempts < 500:
        attempts += 1
        pool = [n for n in remaining if n in graph.allocatable and graph.node(n) and graph.node(n).kind != "mastery"]
        node = rng.choice(pool)
        cascade = graph.cascade_if_removed(remaining, node)
        if not (2 <= len(cascade) <= 12) or total + len(cascade) > target_points + 4:
            continue
        remaining -= cascade
        removed_groups.append(sorted(cascade))
        total += len(cascade)
    return remaining, removed_groups


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="stormbrand")
    ap.add_argument("--points", type=int, default=30)
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--metric", default="CombinedDPS", help="stat to maximize (CombinedDPS or FullDPS)")
    ap.add_argument("--skip-inert", action="store_true", help="do not re-send a candidate PoB scored inert until something that could wake it happens (approximate)")
    args = ap.parse_args()

    code = (FIXTURES / f"{args.slug}.pob.txt").read_text(encoding="utf-8").strip()
    xml = decode_import_code(code)
    graph = TreeGraph.load()
    original_nodes = set(parse_allocated_from_xml(xml))

    with PobSession(run_id=f"recover-{args.slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        print(f"original: dps={original['CombinedDPS']:,.0f} life={original['Life']} ehp={original['TotalEHP']:,.0f} "
              f"res={original['FireResist']}/{original['ColdResist']}/{original['LightningResist']}")

        remaining, groups = strip_branches(graph, original_nodes, args.points, seed=args.seed)
        to_remove = sorted(original_nodes - remaining)
        result = pob.mutate_nodes(remove=to_remove)
        removed = result["removed_node_ids"]
        stripped = pob.stats(KEYS)
        print(f"stripped {len(removed)} nodes in {len(groups)} branches: dps={stripped['CombinedDPS']:,.0f} life={stripped['Life']} "
              f"lost masteries={result['removed_mastery_effects']}")

        objective = Objective(
            maximize=args.metric,
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
        )
        print("objective:", objective.describe())

        allocated_now = original_nodes - set(removed)
        opt = TreeOptimizer(pob, objective, graph=graph, max_depth=args.depth, skip_inert=args.skip_inert, log=print)
        t0 = time.perf_counter()
        alloc = opt.allocate(len(removed), allocated=allocated_now)
        greedy = pob.stats(KEYS)
        print(alloc.summary())
        print(f"after greedy: {args.metric}={greedy[args.metric]:,.0f} ({greedy[args.metric] / original[args.metric]:.1%}) in {time.perf_counter() - t0:.0f}s; skipped={opt.skipped_errors}")
        refine = opt.refine(max_rounds=args.rounds)
        elapsed = time.perf_counter() - t0

        final = pob.stats(KEYS)
        print(refine.summary())
        ratio = final["CombinedDPS"] / original["CombinedDPS"]
        print(f"\nrecovered: dps={final['CombinedDPS']:,.0f} ({ratio:.1%} of original) life={final['Life']} ehp={final['TotalEHP']:,.0f} "
              f"res={final['FireResist']}/{final['ColdResist']}/{final['LightningResist']} in {elapsed:.0f}s")
        chosen = {s.node_id for s in alloc.steps}
        print(f"re-took {len(chosen & set(removed))} of the removed payoff/target nodes directly; {len(chosen - set(removed))} different choices")
        print(f"candidate evaluations: {opt.inert_sent} sent to PoB, {opt.inert_skipped} skipped as inert, {opt.inert_revived} revived (skip_inert={opt.skip_inert})")
        out = {
            "slug": args.slug, "points": len(removed), "depth": args.depth, "seed": args.seed,
            "original": original, "stripped": stripped, "final": final, "ratio": ratio, "seconds": elapsed,
            "greedy": greedy,
            "steps": [{"node": s.node_id, "name": s.name, "kind": s.kind, "cost": s.cost, "gain": s.gain, "effect": s.mastery_effect} for s in alloc.steps + refine.steps],
        }
        out_dir = Path(__file__).resolve().parents[1] / "artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = f"{args.slug}-{args.seed}" + ("" if args.metric == "CombinedDPS" else f"-{args.metric}")
        (out_dir / f"recover-{tag}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

        # Human-inspectable evidence: final build as import code, node diff, config untouched.
        final_xml = pob.export_xml()
        (out_dir / f"recover-{tag}.final.pob.txt").write_text(encode_import_code(final_xml), encoding="utf-8")
        (out_dir / f"recover-{tag}.original.pob.txt").write_text(code, encoding="utf-8")
        final_nodes = set(parse_allocated_from_xml(final_xml))
        write_diff_report(out_dir / f"recover-{tag}.diff.md", graph, original_nodes, final_nodes, xml, final_xml, original, final)
        print(f"saved import codes and diff report under {out_dir}")
    return 0


def _config_section(xml_text: str) -> dict:
    """Config inputs by (config set, name) -> value; PoB re-exports reorder attributes, so compare semantically."""
    from xml.etree import ElementTree as ET
    root = ET.fromstring(xml_text)
    out = {}
    sets = root.findall("Config/ConfigSet") or ([root.find("Config")] if root.find("Config") is not None else [])
    for cs in sets:
        for inp in cs.findall("Input"):
            out[(cs.get("id"), inp.get("name"))] = (inp.get("boolean"), inp.get("number"), inp.get("string"))
    return out


def _items_section(xml_text: str) -> list:
    from xml.etree import ElementTree as ET
    root = ET.fromstring(xml_text)
    return sorted((i.get("id"), " ".join((i.text or "").split())) for i in root.findall("Items/Item"))


def _mastery_effects(xml_text: str) -> dict[int, int]:
    from xml.etree import ElementTree as ET
    root = ET.fromstring(xml_text)
    spec = root.find("Tree/Spec")
    import re
    text = spec.get("masteryEffects") or "" if spec is not None else ""
    return {int(node): int(effect) for node, effect in re.findall(r"\{(\d+),(\d+)\}", text)}


def write_diff_report(path: Path, graph: TreeGraph, original_nodes: set[int], final_nodes: set[int], original_xml: str, final_xml: str, original_stats: dict, final_stats: dict) -> None:
    removed = sorted(original_nodes - final_nodes)
    added = sorted(final_nodes - original_nodes)
    orig_m, final_m = _mastery_effects(original_xml), _mastery_effects(final_xml)
    config_same = _config_section(original_xml) == _config_section(final_xml)
    items_same = _items_section(original_xml) == _items_section(final_xml)

    def describe(node_id: int) -> str:
        node = graph.node(node_id)
        if node is None:
            return f"- `{node_id}` (not in corpus)"
        stats = "; ".join(node.stats) if node.stats else ""
        effect = ""
        if node.kind == "mastery":
            eid = final_m.get(node_id) or orig_m.get(node_id)
            for e_id, e_stats in node.mastery_effects:
                if e_id == eid:
                    effect = " -> " + "; ".join(e_stats)
        return f"- `{node_id}` **{node.name}** ({node.kind}){(': ' + stats) if stats else ''}{effect}"

    lines = [
        f"# Tree recovery diff",
        "",
        f"Config section identical to original: **{config_same}**  ",
        f"Items section identical to original: **{items_same}**  ",
        f"Points: original {len([n for n in original_nodes if n in graph.allocatable])}, final {len([n for n in final_nodes if n in graph.allocatable])}",
        "",
        "| stat | original | final |", "|---|---|---|",
        *[f"| {k} | {original_stats.get(k):,.0f} | {final_stats.get(k):,.0f} |" for k in ("CombinedDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist")],
        "",
        f"## Removed by the optimizer's outcome ({len(removed)} nodes: stripped and not re-taken, or swapped out)",
        *[describe(n) for n in removed],
        "",
        f"## Added ({len(added)} nodes)",
        *[describe(n) for n in added],
        "",
        "## Mastery effects changed",
        *[f"- `{n}` {graph.node(n).name if graph.node(n) else n}: {orig_m.get(n)} -> {final_m.get(n)}" for n in sorted(set(orig_m) | set(final_m)) if orig_m.get(n) != final_m.get(n)],
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
