"""From-scratch experiment: wipe a reference build's passive tree entirely and let
the optimizer allocate the same number of points from the class start, under
the build's own gear, gems and config. Compare to the author's tree.

Run:  python scripts/tree_from_scratch.py stormbrand [--depth 6] [--metric CombinedDPS]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.optimizer.tree_optimizer import TreeOptimizer  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code, encode_import_code  # noqa: E402
from recover_tree import KEYS, write_diff_report  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="stormbrand")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--metric", default="CombinedDPS")
    ap.add_argument("--rounds", type=int, default=30)
    ap.add_argument("--reopt-rounds", type=int, default=0)
    ap.add_argument("--ruin", type=int, default=20)
    ap.add_argument("--keystones", choices=("none", "author"), default="none",
                    help="'author': pre-allocate the author's keystones as skeleton input (paths count against the budget)")
    args = ap.parse_args()

    code = (FIXTURES / f"{args.slug}.pob.txt").read_text(encoding="utf-8").strip()
    xml = decode_import_code(code)
    graph = TreeGraph.load()
    original_nodes = set(parse_allocated_from_xml(xml))
    user_nodes = sorted(n for n in original_nodes if n in graph.allocatable)
    roots = original_nodes - set(user_nodes)

    with PobSession(run_id=f"scratch-{args.slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        print(f"original: {args.metric}={original[args.metric]:,.0f} life={original['Life']} ehp={original['TotalEHP']:,.0f} "
              f"res={original['FireResist']}/{original['ColdResist']}/{original['LightningResist']} points={len(user_nodes)}")

        wiped = pob.mutate_nodes(remove=user_nodes)
        empty = pob.stats(KEYS)
        print(f"wiped tree: {len(wiped['removed_node_ids'])} nodes removed, {wiped['points_used']} points left allocated; "
              f"{args.metric}={empty[args.metric]:,.0f} life={empty['Life']}")

        objective = Objective(
            maximize=args.metric,
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
        )
        print("objective:", objective.describe())
        opt = TreeOptimizer(pob, objective, graph=graph, max_depth=args.depth, log=print)
        t0 = time.perf_counter()
        budget = len(user_nodes)
        if args.keystones == "author":
            keystones = [n for n in user_nodes if graph.node(n) and graph.node(n).kind == "keystone"]
            ks = pob.mutate_nodes(add=keystones)
            budget -= len(ks["added_node_ids"])
            print(f"skeleton keystones: {[graph.node(n).name for n in keystones]} allocated with paths = {len(ks['added_node_ids'])} points; "
                  f"{args.metric}={pob.stats(KEYS)[args.metric]:,.0f}; budget left {budget}")
        alloc = opt.allocate(budget, allocated=opt.current_allocated())
        greedy = pob.stats(KEYS)
        print(f"after greedy: {args.metric}={greedy[args.metric]:,.0f} ({greedy[args.metric] / original[args.metric]:.1%}) "
              f"life={greedy['Life']} in {time.perf_counter() - t0:.0f}s; stop={alloc.stopped_reason}; skipped={opt.skipped_errors}")
        refine = opt.refine(max_rounds=args.rounds)
        print(refine.summary())
        after_refine = pob.stats(KEYS)
        print(f"after refine: {args.metric}={after_refine[args.metric]:,.0f} ({after_refine[args.metric] / original[args.metric]:.1%}) in {time.perf_counter() - t0:.0f}s")
        if args.reopt_rounds:
            reopt = opt.reoptimize(rounds=args.reopt_rounds, ruin_points=args.ruin)
            refine.steps.extend(reopt.steps)
        elapsed = time.perf_counter() - t0
        final = pob.stats(KEYS)
        ratio = final[args.metric] / original[args.metric]
        print(f"\nfrom scratch: {args.metric}={final[args.metric]:,.0f} ({ratio:.1%} of author's tree) life={final['Life']} "
              f"ehp={final['TotalEHP']:,.0f} res={final['FireResist']}/{final['ColdResist']}/{final['LightningResist']} in {elapsed:.0f}s")

        out_dir = Path(__file__).resolve().parents[1] / "artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        tag = f"scratch-{args.slug}-{args.metric}"
        final_xml = pob.export_xml()
        (out_dir / f"{tag}.final.pob.txt").write_text(encode_import_code(final_xml), encoding="utf-8")
        write_diff_report(out_dir / f"{tag}.diff.md", graph, original_nodes, set(parse_allocated_from_xml(final_xml)), xml, final_xml, original, final)
        (out_dir / f"{tag}.json").write_text(json.dumps({
            "slug": args.slug, "metric": args.metric, "original": original, "greedy": greedy, "final": final, "ratio": ratio, "seconds": elapsed,
            "steps": [{"node": s.node_id, "name": s.name, "kind": s.kind, "cost": s.cost, "gain": s.gain, "effect": s.mastery_effect} for s in alloc.steps + refine.steps],
        }, indent=2), encoding="utf-8")
        print(f"saved under {out_dir} as {tag}.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
