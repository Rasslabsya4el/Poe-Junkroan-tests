"""#865 unit 3 (needs PoB): `python scripts/check_spare_865.py [slug ...] [--loop-seconds N]` (default: the six smoke builds).

A reader, not a gate (exit 0 always). Per build it runs the pipeline as `check_bandit_785.check` does (no bandit counters),
then prints one line: ExtraPoints, passive points spent/available, unspent, and the objective's value and violation of the
final build (`objective.score(pob.stats(objective.stat_keys))`, the number `stage_record` writes for every stage).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402


def format_line(result: dict) -> str:
    return (f"{result['slug']} ExtraPoints {result['extra_points']} spent/available {result['spent']}/{result['available']} "
            f"unspent {result['unspent']} value {result['value']:.3f} violation {result['violation']:.6f}")


def check(slug: str, loop_seconds: float) -> dict:
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import max_passive_points
    from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
    from junkroan.pob.session import PobSession

    with PobSession(run_id=f"spare865-{slug}") as pob:
        prepared = benchmark.prepare_author(pob, slug, log=lambda _m: None)
        res = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=lambda _m: None).run(
            prepared.skeleton, tree_points=prepared.points, seed=1, gear_mode="loot", loop_max_seconds=loop_seconds)
        extra = int(pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)
        graph = TreeGraph.load()
        spent = len([n for n in parse_allocated_from_xml(pob.export_xml()) if n in graph.allocatable])
        available = max_passive_points(res.skeleton.level, extra)
        score = prepared.objective.score(pob.stats(prepared.objective.stat_keys))
    return {"slug": slug, "extra_points": extra, "spent": spent, "available": available, "unspent": available - spent,
            "value": score.value, "violation": -score.neg_violation}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("slugs", nargs="*", default=benchmark.SETS["smoke"])
    ap.add_argument("--loop-seconds", type=float, default=60.0)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for slug in args.slugs:
        print(format_line(check(slug, args.loop_seconds)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
