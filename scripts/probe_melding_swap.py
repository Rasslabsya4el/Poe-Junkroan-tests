"""#1159 unit 1 (row 1): the Melding 2-for-2 tree swap on Contagion A1, measured once in PoB.

    python scripts/probe_melding_swap.py --out artifacts/probe-1159

Loads A1's delivered build (its own config, no search, no change to src/). The allocated passive nodes come from
the build's own import XML (`decode_import_code`, the <Spec nodes=...> attribute). From the corpus:

- the Melding group (corpus group_id 543): its non-mastery nodes, which are allocated, which are missing;
- the leaf Life node of each path: an allocated Life node whose only allocated neighbour is the path's notable
  (Cruel Preparation 21958, Blood Drinker 27788). Removing a leaf cascades nothing.

The swap: remove the two leaf Life nodes, add the two missing Melding nodes in path order (each hangs from the
allocated tree once the one before it is in). Before and after are the same PoB reads: CombinedDPS, Life,
EnergyShield, TotalEHP, every <Type>MaximumHitTaken, the resistances, and every floor of rails_default.json as
`Objective.violations` reads it (derived values added the same way). Writes <out>/row1.json and prints the table.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph, _load_records  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

A1 = ROOT / "artifacts" / "search-contagion" / "20261015-0336" / "01 witch_occultist_no_iron_will_prophecy_wand.pob.txt"
MELDING_GROUP = 543
PATH_NOTABLES = {"Cruel Preparation": 21958, "Blood Drinker": 27788}
ELEMENTS = ("Physical", "Fire", "Cold", "Lightning", "Chaos")
RESISTS = ("FireResist", "ColdResist", "LightningResist", "ChaosResist")
ELEMENTAL_RESIST_EACH = 65  # rails_default.json floors.elemental_resist_each (elemental_resist_goal 75 is read off the table: all three 75)


def allocated_from_xml(xml: str) -> set[int]:
    spec = re.search(r"<Spec\b[^>]*>", xml)
    nodes = re.search(r'\bnodes="([^"]*)"', spec.group(0)) if spec else None
    if nodes is None:
        raise ValueError("no <Spec nodes=...> in the import XML")
    return {int(x) for x in nodes.group(1).split(",") if x.strip()}


def melding_group(graph: TreeGraph) -> dict[int, str]:
    """Corpus nodes of group 543 that are not masteries: {node id: name}."""

    out: dict[int, str] = {}
    for rec in (*_load_records("passives.json"), *_load_records("keystones.json"), *_load_records("masteries.json")):
        nid = int(rec["node_id"])
        if rec.get("group_id") == MELDING_GROUP and graph.nodes[nid].kind != "mastery":
            out[nid] = graph.nodes[nid].name
    return out


def leaf_life(graph: TreeGraph, alloc: set[int], notable: int) -> int:
    """The allocated Life node whose only allocated neighbour is `notable` (the path's last Life node)."""

    found = []
    for b in sorted(graph.adjacency.get(notable, ())):
        node = graph.nodes.get(b)
        if b in alloc and node is not None and node.kind == "normal" and any("maximum Life" in s for s in node.stats):
            if [c for c in graph.adjacency.get(b, ()) if c in alloc] == [notable]:
                found.append(b)
    if len(found) != 1:
        raise ValueError(f"leaf Life node of notable {notable}: expected 1, found {found}")
    return found[0]


def ordered_missing(graph: TreeGraph, alloc: set[int], missing: list[int]) -> list[int]:
    """The missing nodes in an order where each one hangs from the allocated tree or from the one before it."""

    current, todo, order = set(alloc), list(missing), []
    while todo:
        nxt = [n for n in todo if any(b in current for b in graph.adjacency.get(n, ()))]
        if not nxt:
            raise ValueError(f"missing Melding nodes {todo} do not hang from the allocated tree")
        order.append(nxt[0])
        current.add(nxt[0])
        todo.remove(nxt[0])
    return order


def measure(pob: Any, objective: Any) -> dict[str, Any]:
    stats = pob.stats()
    full = {**stats, **objective.derived_values(stats)}
    violations = objective.violations(stats)
    keys = ("CombinedDPS", "Life", "EnergyShield", "TotalEHP", *(f"{e}MaximumHitTaken" for e in ELEMENTS), *RESISTS, "EffectiveMovementSpeedMod")
    return {
        "stats": {k: stats.get(k) for k in keys},
        "floors": {k: {"floor": v, "value": full.get(k), "ok": k not in violations} for k, v in objective.floors.items()},
        "violations": violations,
    }


def fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:.2f}"
    return str(value)


def print_table(before: dict, after: dict, nodes: dict, names: dict[int, str]) -> None:
    print("Row 1: swap table (A1, delivered config, PoB stats; floors from rails_default.json)")
    print("| stat | before | after | delta |")
    print("|---|---:|---:|---:|")
    for k in before["stats"]:
        b, a = before["stats"][k], after["stats"][k]
        delta = (a - b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None
        print(f"| {k} | {fmt(b)} | {fmt(a)} | {fmt(delta)} |")
    print()
    print("| floor (rails_default.json) | floor | before value | before | after value | after |")
    print("|---|---:|---:|---|---:|---|")
    for k, row in before["floors"].items():
        a = after["floors"][k]
        print(f"| {k} | {fmt(row['floor'])} | {fmt(row['value'])} | {'ok' if row['ok'] else 'broken'} | {fmt(a['value'])} | {'ok' if a['ok'] else 'broken'} |")
    for r in RESISTS[:3]:
        bv, av = before["stats"][r], after["stats"][r]
        print(f"| {r} (elemental_resist_each {ELEMENTAL_RESIST_EACH}) | {ELEMENTAL_RESIST_EACH} | {fmt(bv)} | "
              f"{'ok' if bv is not None and bv >= ELEMENTAL_RESIST_EACH else 'broken'} | {fmt(av)} | "
              f"{'ok' if av is not None and av >= ELEMENTAL_RESIST_EACH else 'broken'} |")
    print()
    print(f"Melding group 543 (non-mastery): " + "; ".join(f"{n} {names[n]} {'allocated' if n in nodes['melding_allocated'] else 'missing'}" for n in names))
    for name, nid in nodes["leaves"].items():
        print(f"Leaf Life on the {name} path: {nid} (notable {PATH_NOTABLES[name]})")
    print(f"Swap: remove {nodes['remove']}, add {nodes['add']} (order as applied)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "probe-1159"))
    args = parser.parse_args()
    started = time.perf_counter()

    code = A1.read_text(encoding="utf-8").strip()
    alloc = allocated_from_xml(decode_import_code(code))
    graph = TreeGraph.load()
    group = melding_group(graph)
    names = {n: group[n] for n in sorted(group)}
    melding_allocated = [n for n in group if n in alloc]
    missing = [n for n in group if n not in alloc]
    if len(missing) != 2:
        raise ValueError(f"expected 2 missing Melding nodes, found {missing}")
    leaves = {name: leaf_life(graph, alloc, nid) for name, nid in PATH_NOTABLES.items()}
    add = ordered_missing(graph, alloc, missing)
    remove = [leaves["Cruel Preparation"], leaves["Blood Drinker"]]
    nodes = {"melding_allocated": melding_allocated, "missing": missing, "leaves": leaves, "add": add, "remove": remove,
             "allocated_before": len(alloc)}

    objective = Rails.load().objective()
    with PobSession(run_id="probe1159-a1") as pob:
        pob.load_import_code(code)
        before = measure(pob, objective)
        diffs = {"remove": pob.mutate_nodes(remove=remove)}
        for i, nid in enumerate(add, start=1):
            diffs[f"add_{i}"] = pob.mutate_nodes(add=[nid])
        after = measure(pob, objective)

    nodes["allocated_after"] = len(alloc) - len(remove) + len(add)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "row1.json").write_text(json.dumps({"nodes": nodes, "before": before, "after": after, "diffs": diffs},
                                              indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print_table(before, after, nodes, names)
    print(f"(probe took {human_duration(time.perf_counter() - started)}; json: {out / 'row1.json'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
