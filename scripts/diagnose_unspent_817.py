"""#817 row 2: name the mechanism that leaves one passive point unspent.

`python scripts/diagnose_unspent_817.py [slug] [--loop-seconds 60]` runs the same pipeline as
`check_bandit_785.py` on one smoke build and prints (a) every pipeline log line with a tree stage record (its
`stopped_reason` is in the line), (b) the budget at three places: the bench's `tree_points` (author's XML count),
`max_passive_points(level, ExtraPoints)`, and what PoB holds at the end (`points_used`, `CountAllocNodes` when
PoB gives it, the allocatable nodes of the exported XML), (c) the unspent difference of each pair.
Needs PoB (a PobSession): run only through `runs submit`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline  # noqa: E402
from junkroan.optimizer.rails import max_passive_points  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402

KEYWORDS = ("EXTRA-SPEND", "ALLOCATE(", "tree", "point", "spare", "spend", "stopped", "allocat", "rebuil", "top-up", "bandit")


def diagnose(slug: str, loop_seconds: float) -> dict:
    lines: list[str] = []

    def log(message: str) -> None:
        lines.append(str(message))

    from junkroan.optimizer import pipeline as _pl
    from junkroan.optimizer.tree_optimizer import TreeOptimizer

    real_spend, real_allocate = _pl.BuildPipeline._spend_extra_points, TreeOptimizer.allocate

    def spend(self, skeleton):  # records what the spend step saw and what the tree optimizer answered
        extra = int(self.pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)
        used = self._points_used()
        lines.append(f"EXTRA-SPEND call: ExtraPoints {extra}, points_used {used}, "
                     f"spare {max_passive_points(skeleton.level, extra) - used}")
        self._diag_spend = True
        try:
            got = real_spend(self, skeleton)
        finally:
            self._diag_spend = False
        lines.append(f"EXTRA-SPEND result: spent {got}, points_used now {self._points_used()}")
        return got

    def allocate(self, points, *, allocated=None):
        res = real_allocate(self, points, allocated=allocated)
        lines.append(f"ALLOCATE({points}) spent {res.points_spent}, stopped: {res.stopped_reason}")
        return res

    _pl.BuildPipeline._spend_extra_points, TreeOptimizer.allocate = spend, allocate
    with PobSession(run_id=f"unspent817-{slug}") as pob:
        prepared = benchmark.prepare_author(pob, slug, log=lambda _m: None)
        author_used = int(pob.mutate_nodes()["points_used"])
        res = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=log).run(
            prepared.skeleton, tree_points=prepared.points, seed=1, gear_mode="loot", loop_max_seconds=loop_seconds)
        stats = pob.stats(("ExtraPoints", "CountAllocNodes"))
        extra = int(stats.get("ExtraPoints") or 0)
        used = int(pob.mutate_nodes()["points_used"])
        graph = TreeGraph.load()
        xml_nodes = parse_allocated_from_xml(pob.export_xml())
        spent = len([n for n in xml_nodes if n in graph.allocatable])
        level = res.skeleton.level
    return {"slug": slug, "lines": lines, "level": level, "extra": extra,
            "bench_tree_points": prepared.points, "author_points_used": author_used,
            "max_passive_points": max_passive_points(level, extra), "points_used_end": used,
            "count_alloc_nodes": stats.get("CountAllocNodes"), "xml_allocatable": spent, "xml_all": len(xml_nodes)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="summon_raging_spirits")
    ap.add_argument("--loop-seconds", type=float, default=60.0)
    args = ap.parse_args()
    r = diagnose(args.slug, args.loop_seconds)
    print(f"== pipeline log lines of {r['slug']} ({len(r['lines'])} in all; those naming a tree / point stage):")
    for line in r["lines"]:
        if any(k in line.lower() for k in KEYWORDS):
            print("  " + line)
    print("== budget")
    for key in ("level", "extra", "bench_tree_points", "author_points_used", "max_passive_points", "points_used_end",
                "count_alloc_nodes", "xml_allocatable", "xml_all"):
        print(f"  {key} = {r[key]}")
    print(f"  max_passive_points - points_used_end = {r['max_passive_points'] - r['points_used_end']}")
    print(f"  max_passive_points - xml_allocatable = {r['max_passive_points'] - r['xml_allocatable']}")
    print(f"  bench_tree_points - points_used_end = {r['bench_tree_points'] - r['points_used_end']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
