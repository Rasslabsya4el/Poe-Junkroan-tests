"""#785 rows 3 and 4 (needs PoB): `python scripts/check_bandit_785.py [slug ...]` (default: the six smoke builds).

Per build: the bandit values `PobSession.set_config` receives while the author's row is prepared (the yardstick:
the author's own bandit is allowed there) and while our search runs (`pipeline.run`: must be only "None" =
PoB's "Kill all"); then ExtraPoints and the allocated passive points against `max_passive_points(level, ExtraPoints)`.
Exit 0 only when evaluated(not kill all) == 0, evaluated(kill all) > 0 and 0 points are left unspent.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import benchmark  # noqa: E402
from junkroan.optimizer.pipeline import BuildPipeline  # noqa: E402
from junkroan.optimizer.rails import max_passive_points  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402


def check(slug: str, loop_seconds: float) -> dict:
    seen = {"author": Counter(), "ours": Counter()}
    phase = ["author"]
    with PobSession(run_id=f"bandit785-{slug}") as pob:
        original = pob.set_config

        def counted(*args, **kwargs):
            seen[phase[0]][kwargs.get("bandit", "None")] += 1
            return original(*args, **kwargs)

        pob.set_config = counted
        prepared = benchmark.prepare_author(pob, slug, log=lambda _m: None)
        phase[0] = "ours"
        res = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=lambda _m: None).run(
            prepared.skeleton, tree_points=prepared.points, seed=1, gear_mode="loot", loop_max_seconds=loop_seconds)
        pob.set_config = original
        extra = int(pob.stats(("ExtraPoints",)).get("ExtraPoints") or 0)
        graph = TreeGraph.load()
        spent = len([n for n in parse_allocated_from_xml(pob.export_xml()) if n in graph.allocatable])
        available = max_passive_points(res.skeleton.level, extra)
    return {"slug": slug, "author_bandit": dict(seen["author"]), "ours_bandit": dict(seen["ours"]), "extra_points": extra,
            "spent": spent, "available": available, "unspent": available - spent}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", default=benchmark.SETS["smoke"])
    ap.add_argument("--loop-seconds", type=float, default=60.0)
    args = ap.parse_args()
    bad = 0
    print(f"{'build':28} {'author set_config bandit':26} {'ours set_config bandit':24} ExtraPoints spent/available unspent")
    for slug in args.slugs:
        r = check(slug, args.loop_seconds)
        not_kill_all = sum(n for b, n in r["ours_bandit"].items() if b != "None")
        kill_all = r["ours_bandit"].get("None", 0)
        ok = not_kill_all == 0 and kill_all > 0 and r["unspent"] == 0
        bad += not ok
        print(f"{slug:28} {r['author_bandit']!s:26} {r['ours_bandit']!s:24} {r['extra_points']} {r['spent']}/{r['available']} {r['unspent']}  {'OK' if ok else 'FAIL'}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
