"""Measure the delivered tree leaves and mastery effect tie-breaks of PoB builds.

    python scripts/tree_hygiene_report.py artifacts/benchmark/20260919-0941-core14-rules/*-s3.pob.txt --out docs/research/2026-09-19-tree-hygiene-core14.md
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph  # noqa: E402
from junkroan.optimizer.tree_hygiene import analyze_tree_leaves, mastery_effect_tie_rows  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402


def _paths(args: list[str]) -> list[Path]:
    return [Path(path) for arg in args for path in (glob.glob(arg) or [arg])]


def _read(path: Path) -> str:
    text = path.read_text(encoding="utf-8").strip()
    return text if text.startswith("<") else decode_import_code(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="PoB XML or import-code files (glob accepted)")
    parser.add_argument("--best-results", type=Path, help="benchmark results.json: measure the best successful seed of each slug")
    parser.add_argument("--out", type=Path, help="write the markdown report here")
    parser.add_argument("--json", dest="json_out", type=Path, help="write complete measured rows here")
    args = parser.parse_args()
    paths = _paths(args.paths)
    if args.best_results:
        results = json.loads(args.best_results.read_text(encoding="utf-8"))
        best: dict[str, dict] = {}
        for row in results:
            if not row.get("ok"):
                continue
            slug = str(row["slug"])
            if slug not in best or float(row.get("ours") or 0.0) > float(best[slug].get("ours") or 0.0):
                best[slug] = row
        paths.extend(args.best_results.parent / f"{row['slug']}-s{row['seed']}.pob.txt" for row in best.values())
    if not paths:
        parser.error("provide paths or --best-results")
    rails = Rails.load()
    graph = TreeGraph.load()
    rows: list[dict] = []
    with PobSession(run_id="tree-hygiene") as pob:
        for path in paths:
            xml = _read(path)
            pob.load_xml(xml)
            initial = pob.stats(("CombinedDPS", "FullDPS"))
            objective = None
            leaves = analyze_tree_leaves(pob, objective=objective, mastery_context=True)
            masteries = mastery_effect_tie_rows(pob, objective=objective)
            dead = [leaf for leaf in leaves if leaf.status == "dead"]
            weak = [leaf for leaf in leaves if leaf.status == "weak"]
            proof = [leaf for leaf in leaves if leaf.status == "proof"]
            row = {
                "file": path.name,
                "objective": "FullDPS" if float(initial.get("FullDPS") or 0.0) > float(initial.get("CombinedDPS") or 0.0) else "CombinedDPS",
                "allocated": len([node_id for node_id in pob.tree_light().get("user_allocated_node_ids") or () if int(node_id) in graph.allocatable]),
                "dead": [{"name": leaf.name, "node_id": leaf.node_id} for leaf in dead],
                "weak": [{"name": leaf.name, "node_id": leaf.node_id, "changes": leaf.changes} for leaf in weak],
                "proof": [{"name": leaf.name, "node_id": leaf.node_id, "inputs": leaf.proof_inputs} for leaf in proof],
                "mastery_effect_ties": masteries,
            }
            rows.append(row)
            print(f"{path.name}: allocated {row['allocated']}, dead {len(dead)}, weak {len(weak)}, proof {len(proof)}, mastery effect ties {len(masteries)}", flush=True)
    if args.json_out:
        args.json_out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    report = _markdown(rows)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"report: {args.out}")
    else:
        print(report)
    return 0


def _markdown(rows: list[dict]) -> str:
    total = lambda key: sum(len(row[key]) for row in rows)
    lines = [
        "# Tree Hygiene Measurement",
        "",
        "Every removable leaf was measured in one frozen-config `trial_stats(mode=\"fast\")` batch. A tentative dead or weak leaf was then removed for real, its conservative config re-derived, and the original build restored. FullDPS percentages are `trial_stats` values; PoB's node tooltip can show a smaller FullDPS percentage because it recomputes only the main skill.",
        "",
        f"- Builds: {len(rows)}",
        f"- Allocated points: {sum(row['allocated'] for row in rows):,}",
        f"- Dead leaves: {total('dead')}",
        f"- Weak leaves: {total('weak')}",
        f"- Proof holders: {total('proof')}",
        f"- Allocated masteries with a zero-contribution effect while another effect raises life/EHP/resistance: {total('mastery_effect_ties')}",
        "- The seed selection is the highest recorded `ours` value per reference. It is not the lead's original fourteen-file selection, so totals can differ from the recorded 3 dead / 25 weak baseline; the per-file rows make that difference reviewable.",
        "",
        "| Build | Objective | Dead | Weak | Proof holder | Mastery effect ties |",
        "|---|---|---:|---:|---|---:|",
    ]
    for row in rows:
        dead = ", ".join(entry["name"] for entry in row["dead"]) or "-"
        weak = len(row["weak"])
        proof = ", ".join(f"{entry['name']} ({', '.join(entry['inputs'])})" for entry in row["proof"]) or "-"
        lines.append(f"| {row['file']} | {row['objective']} | {dead} | {weak} | {proof} | {len(row['mastery_effect_ties'])} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
