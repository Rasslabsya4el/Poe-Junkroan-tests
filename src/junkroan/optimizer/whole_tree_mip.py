"""Exact connected-tree proposals over an additive PoB node model.

This is deliberately an experiment helper, not a TreeOptimizer move.  PoB
measures node weights around one incumbent; HiGHS then finds the best rooted,
budgeted connected set for that frozen additive model.  The returned proposal
still has to be judged by real PoB before it means anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import perf_counter
from typing import Iterable, Mapping

from junkroan.optimizer.tree_graph import TreeGraph


@dataclass(frozen=True, slots=True)
class MipSolution:
    """One rooted connected-subgraph solution from HiGHS."""

    nodes: frozenset[int]
    mastery_effects: dict[int, int]
    predicted_weight: float
    seconds: float
    gap: float | None
    status: str
    optimal: bool


def solve_connected_tree(
    graph: TreeGraph,
    *,
    root: int,
    weights: Mapping[int, float],
    point_budget: int,
    fixed_nodes: Iterable[int] = (),
    fixed_connectors: Iterable[int] = (),
    incumbent: Iterable[int] = (),
    incumbent_mastery_effects: Mapping[int, int] | None = None,
    hamming_radius: int | None = None,
    mastery_weights: Mapping[int, Mapping[int, float]] | None = None,
    time_limit: float = 60.0,
) -> MipSolution:
    """Maximize additive node weight under a rooted connectivity constraint.

    ``point_budget`` counts selected graph vertices, including ``root``.  Jewel
    sockets are deliberately outside the decision variables: allocated sockets
    remain selected and unallocated sockets cannot be proposed.  The flow sends
    one unit to each selected paid node, so every selected node is connected to
    ``root``.  A flow arc can carry at most ``point_budget - 1`` units, the
    exact cardinality bound of the selected paid nodes.
    """

    try:
        import highspy
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised by users without the research extra
        raise RuntimeError("whole-tree MIP needs the research extra: pip install -e .[research]") from exc

    root = int(root)
    if root not in graph.adjacency:
        raise ValueError(f"root {root} is absent from the tree graph")
    if point_budget < 1:
        raise ValueError("point_budget must include the root")

    jewel_nodes = {node_id for node_id, node in graph.nodes.items() if node.kind == "jewel"}
    fixed = {int(node_id) for node_id in fixed_nodes if int(node_id) in graph.allocatable}
    fixed &= jewel_nodes
    connectors = {int(node_id) for node_id in fixed_connectors if int(node_id) in graph.adjacency and int(node_id) != root}
    selectable = sorted((graph.allocatable - jewel_nodes) - {root})
    if len(fixed) > point_budget:
        raise ValueError("fixed jewel sockets exceed the point budget")

    # All variables live on the class tree; the class start is a zero-cost,
    # always-selected root outside the passive-point budget.
    vertices = {root, *selectable, *fixed, *connectors}
    undirected = {
        (min(node_id, neighbour), max(node_id, neighbour))
        for node_id in vertices
        for neighbour in graph.neighbours(node_id)
        if neighbour in vertices and node_id != neighbour
    }
    arcs = tuple((left, right) for edge in sorted(undirected) for left, right in (edge, edge[::-1]))

    model = highspy.Highs()
    model.setOptionValue("output_flag", False)
    model.setOptionValue("time_limit", float(time_limit))
    model.setMaximize()
    x_column: dict[int, int] = {}
    effect_weights = {
        int(node_id): {int(effect_id): float(weight) for effect_id, weight in effects.items()}
        for node_id, effects in (mastery_weights or {}).items()
        if int(node_id) in selectable and effects
    }
    for node_id in selectable:
        x_column[node_id] = len(x_column)
        model.addVar(0.0, 1.0)
        # A mastery's node cost captures retaining an allocated mastery while
        # its effect variable holds the delta for the selected effect. For an
        # unallocated mastery the node cost is zero and the effect is its payoff.
        model.changeColCost(x_column[node_id], float(weights.get(node_id, 0.0)))
        model.changeColIntegrality(x_column[node_id], highspy.HighsVarType.kInteger)

    mastery_column: dict[tuple[int, int], int] = {}
    for node_id, effects in sorted(effect_weights.items()):
        for effect_id, weight in sorted(effects.items()):
            column = len(x_column) + len(mastery_column)
            mastery_column[(node_id, effect_id)] = column
            model.addVar(0.0, 1.0)
            model.changeColCost(column, weight)
            model.changeColIntegrality(column, highspy.HighsVarType.kInteger)

    flow_column: dict[tuple[int, int], int] = {}
    capacity = float(point_budget - 1)
    for arc in arcs:
        column = len(x_column) + len(mastery_column) + len(flow_column)
        flow_column[arc] = column
        model.addVar(0.0, capacity)

    def add_row(lower: float, upper: float, terms: Mapping[int, float]) -> None:
        entries = [(column, value) for column, value in terms.items() if value]
        model.addRow(
            lower,
            upper,
            len(entries),
            np.asarray([column for column, _value in entries], dtype=np.int32),
            np.asarray([value for _column, value in entries], dtype=np.float64),
        )

    # Selected nodes consume one flow unit.  At the root the outgoing supply
    # equals every selected paid node, including the fixed jewel sockets.
    for node_id in sorted(vertices - {root}):
        terms: dict[int, float] = {}
        for neighbour in graph.neighbours(node_id):
            if (neighbour, node_id) in flow_column:
                terms[flow_column[(neighbour, node_id)]] = 1.0
            if (node_id, neighbour) in flow_column:
                terms[flow_column[(node_id, neighbour)]] = -1.0
        if node_id in x_column:
            terms[x_column[node_id]] = -1.0
            add_row(0.0, 0.0, terms)
        elif node_id in fixed:
            add_row(1.0, 1.0, terms)
        else:
            # Class-start proxy ids sit between the class root and its first
            # paid passive in the corpus. They are fixed tree plumbing, not
            # a point and not a flow sink.
            add_row(0.0, 0.0, terms)

    root_terms: dict[int, float] = {}
    for neighbour in graph.neighbours(root):
        if (root, neighbour) in flow_column:
            root_terms[flow_column[(root, neighbour)]] = 1.0
        if (neighbour, root) in flow_column:
            root_terms[flow_column[(neighbour, root)]] = -1.0
    for node_id, column in x_column.items():
        root_terms[column] = -1.0
    add_row(float(len(fixed)), float(len(fixed)), root_terms)

    # Flow can use an edge only when both its ends are selected.  Fixed sockets
    # and the root have selection value one, so they need no extra coefficient.
    for (left, right), column in flow_column.items():
        if left in x_column:
            add_row(-highspy.kHighsInf, 0.0, {column: 1.0, x_column[left]: -capacity})
        if right in x_column:
            add_row(-highspy.kHighsInf, 0.0, {column: 1.0, x_column[right]: -capacity})

    add_row(
        -highspy.kHighsInf,
        float(point_budget - 1 - len(fixed)),
        {column: 1.0 for column in x_column.values()},
    )

    for node_id in effect_weights:
        add_row(
            0.0,
            0.0,
            {
                **{mastery_column[(node_id, effect_id)]: 1.0 for effect_id in effect_weights[node_id]},
                x_column[node_id]: -1.0,
            },
        )
    for effect_id in sorted({effect for effects in effect_weights.values() for effect in effects}):
        add_row(
            -highspy.kHighsInf,
            1.0,
            {column: 1.0 for (node_id, effect), column in mastery_column.items() if effect == effect_id},
        )

    if hamming_radius is not None:
        if hamming_radius < 0:
            raise ValueError("hamming_radius must not be negative")
        incumbent_set = {int(node_id) for node_id in incumbent}
        fixed_difference = len((fixed - incumbent_set) | ((incumbent_set & jewel_nodes) - fixed))
        incumbent_selectable = incumbent_set & set(x_column)
        # sum(in S) (1-x) + sum(not in S) x <= D
        # becomes sum(not in S) x - sum(in S) x <= D - |S| - fixed difference.
        terms = {
            column: (-1.0 if node_id in incumbent_selectable else 1.0)
            for node_id, column in x_column.items()
        }
        add_row(
            -highspy.kHighsInf,
            float(hamming_radius - len(incumbent_selectable) - fixed_difference),
            terms,
        )

    # Give branch-and-bound the delivered connected tree before it spends the
    # time limit finding one. HiGHS completes the continuous flow columns.
    incumbent_set = {int(node_id) for node_id in incumbent}
    incumbent_effects = {int(node_id): int(effect_id) for node_id, effect_id in (incumbent_mastery_effects or {}).items()}
    start_columns = list(x_column.values()) + list(mastery_column.values())
    start_values = [1.0 if node_id in incumbent_set else 0.0 for node_id in x_column]
    start_values.extend(
        1.0 if incumbent_effects.get(node_id) == effect_id else 0.0
        for node_id, effect_id in mastery_column
    )
    if start_columns:
        model.setSolution(
            len(start_columns),
            np.asarray(start_columns, dtype=np.int32),
            np.asarray(start_values, dtype=np.float64),
        )

    started = perf_counter()
    model.run()
    seconds = perf_counter() - started
    status_value = model.getModelStatus()
    status = str(status_value).removeprefix("HighsModelStatus.")
    solution = model.getSolution()
    if not solution.value_valid:
        raise RuntimeError(f"HiGHS returned no primal solution ({status})")
    selected = frozenset(
        node_id
        for node_id, column in x_column.items()
        if solution.col_value[column] >= 0.5
    ) | frozenset(fixed)
    info = model.getInfo()
    raw_gap = float(info.mip_gap)
    gap = raw_gap if isfinite(raw_gap) else None
    return MipSolution(
        nodes=selected,
        mastery_effects={
            node_id: effect_id
            for (node_id, effect_id), column in mastery_column.items()
            if solution.col_value[column] >= 0.5
        },
        predicted_weight=float(info.objective_function_value),
        seconds=seconds,
        gap=gap,
        status=status,
        optimal=status_value == highspy.HighsModelStatus.kOptimal,
    )


__all__ = ["MipSolution", "solve_connected_tree"]
