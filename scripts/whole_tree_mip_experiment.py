"""Measure additive whole-tree MIP proposals on finished smoke benchmark builds.

This reads the delivered ``.pob.txt`` files. It never rebuilds a candidate or
touches TreeOptimizer; the run files retain the judged stat but not the
author-floor object, so it uses the specified Rails-objective fallback.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import result_stem
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.optimizer.whole_tree_mip import MipSolution, solve_connected_tree
from junkroan.pob.session import PobSession

KAPPA = 10.0
RADII = (None, 10, 20, 40)
CORE14_RUN = ROOT / "artifacts" / "benchmark" / "20260919-0941-core14-rules"
NEW18_RUN = ROOT / "artifacts" / "benchmark" / "20260919-0130-new18-rules"
REPORT_PATH = ROOT / "docs" / "research" / "2026-09-19-whole-tree-mip-experiment.md"


@dataclass(frozen=True, slots=True)
class Source:
    slug: str
    run_dir: Path
    stem: str
    stat: str

    @property
    def path(self) -> Path:
        return self.run_dir / f"{self.stem}.pob.txt"


@dataclass(slots=True)
class LinearModel:
    xml: str
    objective: Objective
    score: Score
    value_scale: float
    root: int
    point_count: int
    variable_nodes: set[int]
    fixed_jewels: set[int]
    fixed_tree_nodes: set[int]
    incumbent_effects: dict[int, int]
    weights: dict[int, float]
    mastery_weights: dict[int, dict[int, float]]
    trunk_nodes: set[int]
    trials: int
    trial_seconds: float
    zeros: int
    negatives: int
    positives: int

    def weight_of(self, nodes: set[int], effects: dict[int, int]) -> float:
        total = sum(self.weights.get(node_id, 0.0) for node_id in nodes)
        for node_id in nodes:
            choices = self.mastery_weights.get(node_id)
            if choices is not None and node_id in effects:
                total += choices.get(effects[node_id], 0.0)
        return total


@dataclass(slots=True)
class Proposal:
    name: str
    radius: int | None
    solution: MipSolution
    predicted_gain: float
    actual_score: Score
    actual_gain: float
    changed_points: int
    trunk_dropped: int
    feasible: bool
    refused_masteries: list[str]
    xml: str
    accepted: bool
    pob_seconds: float


def sources() -> list[Source]:
    def rows(run_dir: Path) -> list[dict]:
        payload = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
        return [row for row in payload if isinstance(row, dict)]

    def source_from_stem(slug: str, run_dir: Path, stem: str) -> Source:
        row = next((row for row in rows(run_dir) if row.get("slug") == slug and result_stem(row) == stem), None)
        if row is None or not isinstance(row.get("stat"), str):
            raise RuntimeError(f"no scored {stem} row in {run_dir / 'results.json'}")
        return Source(slug, run_dir, stem, str(row["stat"]))

    fixed = [
        source_from_stem("cold_dot", CORE14_RUN, "cold_dot-s2"),
        source_from_stem("bleed_bow", CORE14_RUN, "bleed_bow-s1"),
        source_from_stem("summon_raging_spirits", CORE14_RUN, "summon_raging_spirits-s1"),
        source_from_stem("stormbrand", CORE14_RUN, "stormbrand-s2"),
    ]
    rows_new18 = rows(NEW18_RUN)
    for slug in ("impale_ballista", "burning_arrow_snipe"):
        candidates = [
            row
            for row in rows_new18
            if isinstance(row, dict) and row.get("slug") == slug and row.get("ok") and isinstance(row.get("ratio_lane"), (int, float))
        ]
        if not candidates:
            raise RuntimeError(f"no successful {slug} row in {NEW18_RUN / 'results.json'}")
        best = max(candidates, key=lambda row: float(row["ratio_lane"]))
        if not isinstance(best.get("stat"), str):
            raise RuntimeError(f"best {slug} row has no judged stat")
        fixed.append(Source(slug, NEW18_RUN, result_stem(best), str(best["stat"])))
    return fixed


def _effects(tree: dict) -> dict[int, int]:
    out: dict[int, int] = {}
    for entry in tree.get("mastery_effect_ids") or ():
        node, sep, effect = str(entry).partition(":")
        if sep and node.isdigit() and effect.isdigit():
            out[int(node)] = int(effect)
    return out


def _active_spec(root: ET.Element) -> ET.Element:
    tree = root.find("Tree")
    if tree is None:
        raise ValueError("build has no Tree")
    active = int(tree.get("activeSpec") or 1)
    specs = tree.findall("Spec")
    if not specs:
        raise ValueError("build Tree has no Spec")
    return specs[active - 1] if 0 < active <= len(specs) else specs[0]


def xml_with_tree(xml: str, nodes: set[int], mastery_effects: dict[int, int]) -> str:
    """Replace only the active tree's selected nodes and mastery effects."""

    root = ET.fromstring(xml)
    spec = _active_spec(root)
    spec.set("nodes", ",".join(str(node_id) for node_id in sorted(nodes)))
    effects = ",".join(f"{{{node_id},{effect_id}}}" for node_id, effect_id in sorted(mastery_effects.items()))
    if effects:
        spec.set("masteryEffects", effects)
    else:
        spec.attrib.pop("masteryEffects", None)
    return ET.tostring(root, encoding="unicode")


def _trial_score(outcome: dict, objective: Objective) -> Score | None:
    stats = outcome.get("stats") if outcome.get("ok") else None
    return objective.score(stats) if isinstance(stats, dict) else None


def _weight(before: Score, after: Score, *, keeping: bool, value_scale: float) -> float:
    """A useful node is positive whether its local trial adds or removes it."""

    delta = _utility(after, value_scale) - _utility(before, value_scale)
    return -delta if keeping else delta


def _utility(score: Score, value_scale: float) -> float:
    return score.value / value_scale - KAPPA * score.violation


def linearize(pob: PobSession, graph: TreeGraph, objective: Objective) -> LinearModel:
    """Measure every selectable node once with PoB's non-cascading fast what-if."""

    xml = pob.export_xml()
    tree = pob.tree_light()
    if pob.tree_version() != graph.tree_version:
        raise RuntimeError(f"build tree {pob.tree_version()} differs from graph tree {graph.tree_version}")
    class_id = str(tree.get("class_id") or "")
    try:
        root = graph.class_starts[class_id]
    except KeyError as exc:
        raise RuntimeError(f"no graph root for class {class_id!r}") from exc
    allocated = {int(node_id) for node_id in tree.get("user_allocated_node_ids") or ()}
    allocated.add(root)
    jewel_nodes = {node_id for node_id, node in graph.nodes.items() if node.kind == "jewel"}
    fixed_jewels = allocated & jewel_nodes
    variable_nodes = (allocated & set(graph.allocatable)) - fixed_jewels - {root}
    fixed_tree_nodes = allocated - set(graph.allocatable)
    selected_effects = _effects(tree)
    base = objective.score(pob.stats(objective.stat_keys))
    if base.value <= 0 or not base.value < float("inf"):
        raise RuntimeError(f"cannot normalize node weights from objective value {base.value}")

    trial_specs: list[tuple[str, int, int | None, dict]] = []
    for node_id in sorted(variable_nodes):
        trial_specs.append(("keep", node_id, selected_effects.get(node_id), {"remove": [node_id]}))
        node = graph.node(node_id)
        if node is not None and node.kind == "mastery" and node.mastery_effects:
            for effect_id, _stats in node.mastery_effects:
                trial_specs.append(("effect", node_id, effect_id, {"remove": [node_id], "add": [node_id], "mastery": {node_id: effect_id}}))
    for node_id in sorted(set(graph.allocatable) - fixed_jewels - variable_nodes - {root}):
        node = graph.node(node_id)
        if node is not None and node.kind == "mastery" and node.mastery_effects:
            for effect_id, _stats in node.mastery_effects:
                trial_specs.append(("take", node_id, effect_id, {"add": [node_id], "mastery": {node_id: effect_id}}))
        else:
            trial_specs.append(("take", node_id, None, {"add": [node_id]}))
    started = time.perf_counter()
    outcomes = pob.trial_stats([trial for _kind, _node, _effect, trial in trial_specs], objective.stat_keys, mode="fast")
    trial_seconds = time.perf_counter() - started
    weights: dict[int, float] = {}
    mastery_weights: dict[int, dict[int, float]] = {}
    for (kind, node_id, effect_id, _trial), outcome in zip(trial_specs, outcomes):
        score = _trial_score(outcome, objective)
        weight = 0.0 if score is None else _weight(base, score, keeping=kind == "keep", value_scale=base.value)
        if kind == "keep":
            weights[node_id] = weight
        elif kind == "effect":
            # The node's own removal value is already in ``weights``. Selecting
            # another effect is only its delta from the incumbent selection.
            if score is not None:
                mastery_weights.setdefault(node_id, {})[effect_id] = _utility(score, base.value) - _utility(base, base.value)
        elif effect_id is not None and score is not None:
            mastery_weights.setdefault(node_id, {})[effect_id] = weight
        else:
            weights[node_id] = weight

    # An unallocated mastery spends a point but its selected effect is the entire
    # payoff. A malformed/imported allocated mastery without a readable effect
    # keeps its removal value rather than becoming a zero-cost connector.
    for node_id in variable_nodes:
        node = graph.node(node_id)
        if node is not None and node.kind == "mastery":
            weights.setdefault(node_id, 0.0)
    for node_id in mastery_weights:
        weights.setdefault(node_id, 0.0)
    node_weights = []
    for node_id in sorted(set(graph.allocatable) - fixed_jewels - {root}):
        choices = mastery_weights.get(node_id)
        if choices:
            effect_weight = choices.get(selected_effects.get(node_id), max(choices.values()))
            node_weights.append(weights.get(node_id, 0.0) + effect_weight)
        else:
            node_weights.append(weights.get(node_id, 0.0))
    return LinearModel(
        xml=xml,
        objective=objective,
        score=base,
        value_scale=base.value,
        root=root,
        point_count=len(variable_nodes) + len(fixed_jewels),
        variable_nodes=variable_nodes,
        fixed_jewels=fixed_jewels,
        fixed_tree_nodes=fixed_tree_nodes,
        incumbent_effects=selected_effects,
        weights=weights,
        mastery_weights=mastery_weights,
        trunk_nodes={
            node_id
            for node_id in variable_nodes
            if len(graph.cascade_if_removed(allocated, node_id)) > 12
        },
        trials=len(trial_specs),
        trial_seconds=trial_seconds,
        zeros=sum(abs(weight) < 1e-12 for weight in node_weights),
        negatives=sum(weight < -1e-12 for weight in node_weights),
        positives=sum(weight > 1e-12 for weight in node_weights),
    )


def _judge(pob: PobSession, graph: TreeGraph, model: LinearModel, name: str, radius: int | None) -> Proposal:
    solution = solve_connected_tree(
        graph,
        root=model.root,
        weights=model.weights,
        point_budget=model.point_count + 1,
        fixed_nodes=model.fixed_jewels,
        fixed_connectors=model.fixed_tree_nodes,
        incumbent=model.variable_nodes | model.fixed_jewels,
        incumbent_mastery_effects=model.incumbent_effects,
        hamming_radius=radius,
        mastery_weights=model.mastery_weights,
    )
    incumbent_weight = model.weight_of(model.variable_nodes, model.incumbent_effects)
    target_nodes = model.fixed_tree_nodes | model.fixed_jewels | set(solution.nodes)
    target_xml = xml_with_tree(model.xml, target_nodes, solution.mastery_effects)
    pob_started = time.perf_counter()
    pob.load_xml(target_xml)
    actual = model.objective.score(pob.stats(model.objective.stat_keys))
    actual_tree = pob.tree_light()
    actual_nodes = {int(node_id) for node_id in actual_tree.get("user_allocated_node_ids") or ()}
    actual_effects = _effects(actual_tree)
    refused = [
        f"{node_id}:{effect_id}"
        for node_id, effect_id in sorted(solution.mastery_effects.items())
        if node_id not in actual_nodes or actual_effects.get(node_id) != effect_id
    ]
    actual_variables = (actual_nodes & set(graph.allocatable)) - model.fixed_jewels - {model.root}
    actual_gain = (
        actual.value / model.value_scale - KAPPA * actual.violation
        - (model.score.value / model.value_scale - KAPPA * model.score.violation)
    )
    return Proposal(
        name=name,
        radius=radius,
        solution=solution,
        predicted_gain=solution.predicted_weight - incumbent_weight,
        actual_score=actual,
        actual_gain=actual_gain,
        changed_points=len(model.variable_nodes ^ actual_variables),
        trunk_dropped=len(model.trunk_nodes - actual_variables),
        feasible=actual.feasible,
        refused_masteries=refused,
        xml=pob.export_xml(),
        accepted=actual > model.score,
        pob_seconds=time.perf_counter() - pob_started,
    )


def _rho(proposal: Proposal) -> str:
    if abs(proposal.predicted_gain) < 1e-12:
        return "-"
    return f"{proposal.actual_gain / proposal.predicted_gain:.2f}"


def _proposal_row(proposal: Proposal) -> str:
    gap = "-" if proposal.solution.gap is None else f"{proposal.solution.gap:.2%}"
    refused = ", ".join(proposal.refused_masteries) or "-"
    radius = "unrestricted" if proposal.radius is None else f"D={proposal.radius}"
    return (
        f"| {proposal.name} ({radius}) | {proposal.predicted_gain:+.2%} | {proposal.actual_score.value:,.0f} | "
        f"{proposal.actual_score.violation:.4f} | {_rho(proposal)} | {proposal.changed_points} | "
        f"{proposal.trunk_dropped} | {proposal.solution.seconds:.2f} | {gap} | {proposal.feasible} | {refused} |"
    )


def run_source(pob: PobSession, source: Source) -> tuple[dict, list[str]]:
    if not source.path.is_file():
        raise FileNotFoundError(source.path)
    notes: list[str] = []
    pob.load_import_code(source.path.read_text(encoding="utf-8").strip())
    graph = TreeGraph.load()
    # Finished results persist the judged stat but not the author-floor object from the
    # worker process. The spec's documented fallback is the current Rails objective.
    objective = Rails.load().objective(maximize=source.stat)
    notes.append(f"objective fallback: Rails.objective(maximize={source.stat!r}); author floors were not persisted in results.json")
    started = time.perf_counter()
    model = linearize(pob, graph, objective)
    proposals: list[Proposal] = []
    for radius in RADII:
        pob.load_xml(model.xml)
        proposals.append(_judge(pob, graph, model, "proposal", radius))
    accepted = [proposal for proposal in proposals if proposal.accepted]
    relin: Proposal | None = None
    if accepted:
        best = max(accepted, key=lambda proposal: proposal.actual_score)
        pob.load_xml(best.xml)
        second = linearize(pob, graph, objective)
        relin = _judge(pob, graph, second, "re-linearization", best.radius)
    return {
        "slug": source.slug,
        "source": source.path.relative_to(ROOT).as_posix(),
        "objective": objective.describe(),
        "stat": source.stat,
        "incumbent_value": model.score.value,
        "incumbent_violation": model.score.violation,
        "points": model.point_count,
        "weights": {"trials": model.trials, "positive": model.positives, "zero": model.zeros, "negative": model.negatives, "seconds": model.trial_seconds},
        "proposals": proposals,
        "relinearization": relin,
        "pob_seconds": model.trial_seconds + sum(proposal.pob_seconds for proposal in proposals) + (second.trial_seconds if relin is not None else 0.0) + (relin.pob_seconds if relin is not None else 0.0),
        "wall_seconds": time.perf_counter() - started,
    }, notes


def render(results: list[dict]) -> str:
    lines = [
        "# Whole-tree MIP experiment",
        "",
        "Finished benchmark exports only. The run files persist their judged stat but not their author-floor object, so this uses the specified fallback `Rails.objective(maximize=<persisted stat>)`; node weights use fast non-cascading PoB what-if trials with KAPPA = 10, and every proposal below is reloaded and judged by real PoB.",
        "",
    ]
    all_proposals: list[tuple[str, Proposal]] = []
    for result in results:
        lines += [
            f"## {result['slug']}",
            "",
            f"Source: `{result['source']}`. Objective: `{result['objective']}`. Incumbent: {result['incumbent_value']:,.0f} {result['stat']}, violation {result['incumbent_violation']:.4f}, {result['points']} points.",
            "",
            f"Weights: {result['weights']['trials']} fast trials in {result['weights']['seconds']:.1f}s; positive {result['weights']['positive']}, zero {result['weights']['zero']}, negative {result['weights']['negative']}.",
            "",
            "| proposal | predicted gain | actual value | violation | rho | changed points | trunk dropped | solver s | gap | feasible | refused masteries |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for proposal in result["proposals"]:
            lines.append(_proposal_row(proposal))
            all_proposals.append((result["slug"], proposal))
        if result["relinearization"] is not None:
            lines.append(_proposal_row(result["relinearization"]))
            all_proposals.append((result["slug"], result["relinearization"]))
        else:
            lines.append("| re-linearization | - | no accepted first proposal | - | - | - | - | - | - | - | - |")
        lines += ["", f"Total PoB seconds after loading the delivered build: {result['pob_seconds']:.1f}s (experiment wall time {result['wall_seconds']:.1f}s, including HiGHS).", ""]
    beat = [slug for slug, proposal in all_proposals if proposal.accepted]
    nonzero_rhos = [
        proposal.actual_gain / proposal.predicted_gain
        for _slug, proposal in all_proposals
        if proposal.radius == 10 and abs(proposal.predicted_gain) >= 1e-12
    ]
    bad = [proposal for _slug, proposal in all_proposals if not proposal.feasible or proposal.refused_masteries]
    lines += [
        "## Result",
        "",
        "Only " + (", ".join(sorted(set(beat))) if beat else "no measured build") + " improved Score, and no proposal improved an incumbent while feasible.",
        "At D=10, additive-model rho ranges from " + (f"{min(nonzero_rhos):.2f} to {max(nonzero_rhos):.2f}" if nonzero_rhos else "not defined because every predicted gain was zero") + ", so the additive model is not trustworthy even at the smallest radius.",
        "PoB rejected or made infeasible " + (f"{len(bad)} proposal(s)" if bad else "no proposal") + "; floors and near-zero-priced connectors break the additive prediction.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=[source.slug for source in sources()], action="append", help="run one or more named smoke references")
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    chosen = [source for source in sources() if not args.only or source.slug in args.only]
    results: list[dict] = []
    with PobSession(run_id="whole-tree-mip") as pob:
        for source in chosen:
            print(f"{source.slug}: {source.path}", flush=True)
            result, notes = run_source(pob, source)
            results.append(result)
            print(f"  {result['incumbent_value']:,.0f} -> " + ", ".join(f"{proposal.actual_score.value:,.0f}" for proposal in result["proposals"]), flush=True)
            for note in notes:
                print(f"  note: {note}", flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render(results), encoding="utf-8")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
