"""Proof that the tree optimizer's repeated-work rules (speed audit 2026-09-18) changed no number.

Runs the `recover_tree` experiment on a reference and then the move sequence the improvement loop
runs over a tree -- greedy, refine, path swaps, the judge's revert of a pass that lost, and the next
pass's refine -- checking the recovered CombinedDPS and the allocated node set against the values
the optimizer produced before the change, and reporting the seconds and the trials PoB was asked for
per stage.

    python scripts/tree_speed_proof.py [stormbrand] [bleed_bow] [cold_dot] [--before]

`--before` turns the memo and the remembered refine verdict off (`_state_key` answers "unknown"),
which is exactly the code path of the commit before them: run it twice to compare.

Exits 1 on any mismatch. Skips (exit 0) when the pinned PoB runtime is not present.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
# slug -> (points stripped, refine rounds, CombinedDPS before the change)
CASES = {"stormbrand": (20, 5, 1_109_127.0), "bleed_bow": (20, 5, 931_969.0), "cold_dot": (20, 5, 252_955.0)}


def runtime_present() -> bool:
    lock = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
    return (PROJECT_ROOT / "var" / "cache" / "pob" / lock["tag"] / lock["extract_subdir"] / "lua51.dll").is_file()


def run(slug: str, points: int, rounds: int, expected: float, *, before: bool) -> bool:
    from junkroan.optimizer.objective import Objective
    from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
    from junkroan.optimizer.tree_optimizer import TreeOptimizer
    from junkroan.pob.session import PobSession, decode_import_code
    from recover_tree import KEYS, strip_branches

    xml = decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip())
    graph = TreeGraph.load()
    original_nodes = set(parse_allocated_from_xml(xml))
    stages: list[tuple[str, float, int]] = []  # name, seconds, trials PoB was asked for
    with PobSession(run_id=f"tree-speed-proof-{slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        remaining, _groups = strip_branches(graph, original_nodes, points, seed=1)
        removed = pob.mutate_nodes(remove=sorted(original_nodes - remaining))["removed_node_ids"]
        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
        )
        opt = TreeOptimizer(pob, objective, graph=graph, max_depth=6)
        if before:
            opt._state_key = lambda *_a, **_kw: None  # type: ignore[method-assign]

        def stage(name: str, fn) -> None:
            t0, sent = time.perf_counter(), opt.trials_measured
            fn()
            stages.append((name, time.perf_counter() - t0, opt.trials_measured - sent))

        stage("greedy", lambda: opt.allocate(len(removed), allocated=original_nodes - set(removed)))
        stage("refine", lambda: opt.refine(max_rounds=rounds))
        snapshot = pob.export_xml()  # the loop's snapshot of the build its next move starts from
        stage("path swaps", lambda: opt.swap_subtrees(max_size=4, max_seconds=30.0))
        stage("revert", lambda: pob.load_xml(snapshot))  # the judge reverting a pass that kept nothing
        stage("refine again", lambda: opt.refine(max_rounds=rounds))

        final = pob.stats(KEYS)
        nodes = sorted(set(parse_allocated_from_xml(pob.export_xml())))

    got = float(final["CombinedDPS"])
    ok = abs(got - expected) <= 1.0
    digest = hashlib.sha1(",".join(str(n) for n in nodes).encode()).hexdigest()[:12]
    print(f"{slug:12s} {got:14,.2f} (expected {expected:,.0f}) {'OK' if ok else 'MISMATCH'}  "
          f"{len(nodes)} nodes {digest}  {sum(s[1] for s in stages):5.0f}s {sum(s[2] for s in stages):6d} trials")
    for name, seconds, trials in stages:
        print(f"             {name:13s} {seconds:7.1f}s {trials:6d} trials")
    print(f"             reused {opt.trials_reused} trials, {opt.refine_skipped} refine calls answered from a remembered verdict;"
          f" hook: {opt.hook_calls} called / {opt.hook_skipped_cached} cached / {opt.hook_skipped_inert} skipped;"
          f" path swaps not re-tried: {opt.subtree_retries_skipped};"
          f" restores: {opt.restore_fast} by mutation / {opt.restore_fallback} by reload / {opt.restore_failures} failed")
    return ok


def main() -> int:
    if not runtime_present():
        print("pinned PoB runtime not present: skipped")
        return 0
    before = "--before" in sys.argv
    slugs = [s for s in sys.argv[1:] if s in CASES] or list(CASES)
    print(f"tree speed proof ({'before' if before else 'after'} the change)")
    return 0 if all(run(s, *CASES[s], before=before) for s in slugs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
