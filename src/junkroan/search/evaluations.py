"""Durable rows and small statistics for the outer skeleton search."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

from junkroan.search.skeleton import Skeleton


def append_row(path: Path, row: dict[str, Any]) -> None:
    """Append one completed evaluation, so a later failed job cannot erase it."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def skeleton_label(skeleton: Skeleton) -> str:
    """The skeleton portion of the final report's build name."""

    name = f"{skeleton.class_name}/{skeleton.ascendancy}"
    if skeleton.uniques:
        name += f" + {', '.join(skeleton.uniques.values())}"
    if skeleton.forbid_keystones:
        name += f" (no {', '.join(skeleton.forbid_keystones)})"
    if skeleton.rare_bases.get("Weapon 1"):
        name += f" [{skeleton.rare_bases['Weapon 1']}]"
    return name


def variant_label(skeleton: Skeleton) -> str:
    """The report's variant suffix, or an empty label for an original candidate."""

    notes = skeleton.notes or ""
    if " -> " in notes:
        return notes.rsplit(" -> ", 1)[1]
    if " + uniques " in notes:
        return notes.rsplit(" + uniques ", 1)[1]
    return ""


def row_for(
    *,
    request: str,
    skeleton: Skeleton,
    rung: str,
    result: dict[str, Any],
    seed: int | None,
    commit: str | None,
) -> dict[str, Any]:
    """Make the public evaluation schema from one successful worker result."""

    keystones = result.get("keystones")
    if not isinstance(keystones, list):
        keystones = list(skeleton.keystones)
    return {
        "request": request,
        "skeleton": skeleton_label(skeleton),
        "rung": rung,
        "seed": seed,
        "value": result["value"],
        "violation": result["violation"],
        "feasible": result["feasible"],
        "seconds": result["seconds"],
        "commit": commit,
        "features": {
            "class": skeleton.class_name,
            "ascendancy": skeleton.ascendancy,
            "mode": skeleton.mode or "",
            "main_skill": skeleton.main_link[0] if skeleton.main_link else "",
            "keystones": keystones,
            "uniques": dict(skeleton.uniques),
            "variant": variant_label(skeleton),
        },
    }


def parse_full_ranks(text: str) -> list[int]:
    """Parse one-based screen ranks, retaining only their first occurrence."""

    try:
        ranks = [int(part.strip()) for part in text.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("--full-ranks must be comma-separated positive integers") from exc
    if not ranks or any(rank < 1 for rank in ranks):
        raise ValueError("--full-ranks must contain at least one positive integer")
    return list(dict.fromkeys(ranks))


def selected_screen_ranks(ranks: Iterable[int], screened_count: int) -> list[int]:
    """Deduplicate requested ranks and drop those beyond the completed screen."""

    return [rank for rank in dict.fromkeys(ranks) if rank <= screened_count]


def spearman(left: Sequence[float | int | None], right: Sequence[float | int | None]) -> float | None:
    """Spearman rho with average ranks for ties; absent pairs do not participate."""

    pairs = [(float(a), float(b)) for a, b in zip(left, right) if isinstance(a, (int, float)) and isinstance(b, (int, float))]
    if len(pairs) < 3:  # n = 2 is always +-1.0 whatever the two builds did: report it as no answer
        return None

    def ranks(values: Sequence[float]) -> list[float]:
        out = [0.0] * len(values)
        order = sorted(range(len(values)), key=values.__getitem__)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            rank = (start + 1 + end) / 2.0
            for index in order[start:end]:
                out[index] = rank
            start = end
        return out

    x, y = ranks([pair[0] for pair in pairs]), ranks([pair[1] for pair in pairs])
    x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
    numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
    denominator = math.sqrt(sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y))
    return numerator / denominator if denominator else None


def format_rho(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


__all__ = ["append_row", "format_rho", "parse_full_ranks", "row_for", "selected_screen_ranks", "skeleton_label", "spearman"]
