"""Where does a rebuilt reference lose against its author? Cross the author's
build with the benchmark build (PoB Builds/Junkroan/benchmark <run>/<slug> s<seed>.xml with --run,
else benchmark <slug>.xml),
everything under our conservative lane:

  A  author tree + author gear          (the reference under our lane)
  B  author tree + our gear             -> B/A is the gear gap
  C  our tree + author gear             -> C/A is the tree gap
  D  our tree + our gear                (the benchmark build)

Gems follow each side as it is (the author's gem levels stay on the author's
side; D is under the rails). Config is re-derived on every combination.

Run:  python scripts/gap_decomposition.py [slug ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.config_rules import derive_config  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
BUILDS = Path.home() / "Documents" / "Path of Building" / "Builds" / "Junkroan"
KEYS = ("CombinedDPS", "Life", "TotalEHP")


def _items_block(xml: str) -> str:
    return re.search(r"<Items.*?</Items>", xml, re.S).group(0)


def _tree_block(xml: str) -> str:
    return re.search(r"<Tree.*?</Tree>", xml, re.S).group(0)


def _swap(xml: str, block: str, kind: str) -> str:
    pat = r"<Items.*?</Items>" if kind == "items" else r"<Tree.*?</Tree>"
    return re.sub(pat, lambda _m: block, xml, count=1, flags=re.S)


def _under_our_lane(pob: PobSession, xml: str) -> dict:
    pob.load_xml(xml)
    d = derive_config(pob)
    pob.set_config(inputs={k: v for k, v in d.conservative.inputs.items() if k != "enemyIsBoss"}, conditional={"inputs": {k: v for k, v in d.optimistic.inputs.items() if k != "enemyIsBoss"}})
    return pob.stats(KEYS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", default=sorted(p.name[: -len(".pob.txt")] for p in FIXTURES.glob("*.pob.txt")))
    ap.add_argument("--run", help='a benchmark run\'s PoB folder, e.g. "2026-09-15 1654-intake" (Builds/Junkroan/benchmark <run>/<slug> s<seed>.xml); default: the flat "benchmark <slug>.xml"')
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    graph = TreeGraph.load()
    print(f"{'build':24s} {'A author':>10s} {'B our gear':>10s} {'C our tree':>10s} {'D ours':>10s}   gear B/A  tree C/A  both D/A   points A/D")
    with PobSession(run_id="gap") as pob:
        for slug in args.slugs:
            ours_path = BUILDS / f"benchmark {args.run}" / f"{slug} s{args.seed}.xml" if args.run else BUILDS / f"benchmark {slug}.xml"
            if not ours_path.is_file():
                print(f"{slug:24s} no benchmark build")
                continue
            author = decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip())
            ours = ours_path.read_text(encoding="utf-8")
            a = _under_our_lane(pob, author)
            b = _under_our_lane(pob, _swap(author, _items_block(ours), "items"))
            c = _under_our_lane(pob, _swap(author, _tree_block(ours), "tree"))
            d = _under_our_lane(pob, ours)
            pa = len([n for n in parse_allocated_from_xml(author) if n in graph.allocatable])
            pd = len([n for n in parse_allocated_from_xml(ours) if n in graph.allocatable])
            dps = lambda s: s.get("CombinedDPS") or 0.0  # noqa: E731
            print(f"{slug:24s} {dps(a):>10,.0f} {dps(b):>10,.0f} {dps(c):>10,.0f} {dps(d):>10,.0f}   {dps(b) / max(1, dps(a)):>7.0%}  {dps(c) / max(1, dps(a)):>7.0%}  {dps(d) / max(1, dps(a)):>7.0%}   {pa}/{pd}"
                  f"   life A {a.get('Life')} B {b.get('Life')} C {c.get('Life')} D {d.get('Life')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
