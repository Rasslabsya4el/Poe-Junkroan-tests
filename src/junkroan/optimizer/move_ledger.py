"""Small, report-only helpers for the improvement-loop move ledger.

The ledger is deliberately passive: these functions summarize measurements
already made by the optimizer and never participate in an acceptance decision.
"""

from __future__ import annotations

import statistics
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from junkroan.report_format import human_duration, human_rate_per_minute

MOVE_COLUMNS = ("move", "tries", "kept", "time", "gain", "gain per minute", "share of the loop's gain")

# `where` values the improvement loop itself writes; anything else is a re-entry with a stage name
# (`_fixed_point_check`'s extra pass), whose rows are aggregated with the rest but also counted apart.
LOOP_WHERE = ("loop pass", "loop opening", "repair pass")  # #1064: the repair's passes are the loop's own rows


def reentry_rows(moves: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Ledger rows a re-entry appended rather than the loop's own passes.

    A row persisted before the ``where`` field existed counts as the loop's own.
    """

    return [row for row in moves if not str(row.get("where") or LOOP_WHERE[0]).startswith(LOOP_WHERE)]


def reentry_line(moves: Sequence[Mapping[str, Any]]) -> list[str]:
    """One "of which <stage>: N tries, time" line, or nothing when no re-entry ran."""

    rows = reentry_rows(moves)
    if not rows:
        return []
    names = sorted({str(row.get("where") or "") for row in rows})
    seconds = sum(float(row.get("seconds") or 0.0) for row in rows)
    return [f"of which {', '.join(names)}: {len(rows)} tries, {human_duration(seconds)}"]


def tree_churn(before: Iterable[int], after: Iterable[int]) -> float:
    """Return the Jaccard distance between two allocated-node sets."""

    left, right = set(before), set(after)
    union = left | right
    return 0.0 if not union else 1.0 - len(left & right) / len(union)


def _trunk_nodes(nodes: set[int], graph: Any, threshold: int) -> set[int]:
    if graph is None:
        return set()
    return {
        node_id
        for node_id in nodes
        if len(graph.cascade_if_removed(nodes, node_id)) > threshold
    }


def tree_churn_metrics(before: Iterable[int], after: Iterable[int], *, graph: Any = None, trunk_threshold: int = 12) -> dict[str, float]:
    """Measure construction-to-final tree churn.

    ``trunk_churn`` asks what fraction of construction's trunk nodes were not
    present in the final tree.  The trunk is intentionally defined from the
    construction tree only, so the metric does not move its own baseline when
    the final optimizer tree changes shape.
    """

    left, right = set(before), set(after)
    trunk = _trunk_nodes(left, graph, trunk_threshold)
    trunk_churn = tree_churn(trunk, trunk & right)
    return {
        "all": tree_churn(left, right),
        "trunk": trunk_churn,
        "trunk_share": len(_trunk_nodes(right, graph, trunk_threshold)) / len(right) if right and graph is not None else 0.0,
    }


def summarize_moves(moves: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate ledger entries in first-seen move order."""

    groups: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
    for entry in moves:
        name = str(entry.get("move") or "unknown")
        row = groups.setdefault(name, {"move": name, "tries": 0, "kept": 0, "seconds": 0.0, "gain": 0.0})
        row["tries"] += 1
        kept = bool(entry.get("kept"))
        row["kept"] += int(kept)
        row["seconds"] += float(entry.get("seconds") or 0.0)
        if kept:
            row["gain"] += float(entry.get("after") or 0.0) - float(entry.get("before") or 0.0)
    total_gain = sum(float(row["gain"]) for row in groups.values())
    for row in groups.values():
        seconds = float(row["seconds"])
        gain = float(row["gain"])
        row["gain per minute"] = human_rate_per_minute(gain, seconds)
        row["share of the loop's gain"] = gain / total_gain if total_gain else 0.0
    return list(groups.values())


def render_move_table(moves: Sequence[Mapping[str, Any]], *, heading: str | None = None) -> list[str]:
    """Render one move table suitable for build summaries and benchmark reports."""

    rows = summarize_moves(moves)
    if not rows:
        return []
    lines = ([heading, ""] if heading else []) + [
        "| move | tries | kept | time | gain (sum of kept after - before) | gain per minute | share of the loop's gain |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        share = row["share of the loop's gain"]
        lines.append(
            f"| {row['move']} | {row['tries']} | {row['kept']} | {human_duration(float(row['seconds']))} | "
            f"{row['gain']:,.0f} | {row['gain per minute']:,.1f} | {share:.1%} |"
        )
    return lines + reentry_line(moves)


def render_move_rows(rows: Sequence[Mapping[str, Any]], *, heading: str | None = None) -> list[str]:
    """Render already-aggregated rows without changing their statistics."""

    if not rows:
        return []
    lines = ([heading, ""] if heading else []) + [
        "| move | tries | kept | time | gain (sum of kept after - before) | gain per minute | share of the loop's gain |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        share = float(row["share of the loop's gain"])
        lines.append(
            f"| {row['move']} | {row['tries']} | {row['kept']} | {human_duration(float(row['seconds']))} | "
            f"{float(row['gain']):,.0f} | {float(row['gain per minute']):,.1f} | {share:.1%} |"
        )
    return lines


def aggregate_move_tables(rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (median per build, total) move rows for persisted benchmark rows."""

    per_build = [summarize_moves(row.get("moves") or row.get("move_rows") or ()) for row in rows if row.get("ok")]
    names: list[str] = []
    for table in per_build:
        for row in table:
            if row["move"] not in names:
                names.append(row["move"])
    median_rows: list[dict[str, Any]] = []
    total_rows: list[dict[str, Any]] = []
    for name in names:
        matching = [
            next((row for row in table if row["move"] == name),
                  {"tries": 0, "kept": 0, "seconds": 0.0, "gain": 0.0, "gain per minute": 0.0, "share of the loop's gain": 0.0})
            for table in per_build
        ]
        median_rows.append({
            "move": name,
            "tries": statistics.median(row["tries"] for row in matching),
            "kept": statistics.median(row["kept"] for row in matching),
            "seconds": statistics.median(row["seconds"] for row in matching),
            "gain": statistics.median(row["gain"] for row in matching),
            "gain per minute": statistics.median(row["gain per minute"] for row in matching),
            "share of the loop's gain": statistics.median(row["share of the loop's gain"] for row in matching),
        })
        total_rows.append({
            "move": name,
            "tries": sum(row["tries"] for row in matching),
            "kept": sum(row["kept"] for row in matching),
            "seconds": sum(row["seconds"] for row in matching),
            "gain": sum(row["gain"] for row in matching),
        })
    total_gain = sum(float(row["gain"]) for row in total_rows)
    for row in total_rows:
        row["gain per minute"] = human_rate_per_minute(float(row["gain"]), float(row["seconds"]))
        row["share of the loop's gain"] = row["gain"] / total_gain if total_gain else 0.0
    return median_rows, total_rows


def render_pob_calls(pob_calls: Mapping[str, Mapping[str, float | int]], *, heading: str | None = None) -> list[str]:
    """Render PoB call counts and their accumulated time without changing raw measurements."""

    if not pob_calls:
        return []
    lines = ([heading, ""] if heading else []) + [
        "| PoB call | calls | time |",
        "|---|---:|---:|",
    ]
    for kind, data in sorted(pob_calls.items()):
        lines.append(f"| {kind} | {data.get('count', 0)} | {human_duration(float(data.get('seconds', 0.0)))} |")
    return lines


__all__ = ["aggregate_move_tables", "reentry_line", "reentry_rows", "render_move_rows", "render_move_table",
            "render_pob_calls", "summarize_moves", "tree_churn", "tree_churn_metrics"]
