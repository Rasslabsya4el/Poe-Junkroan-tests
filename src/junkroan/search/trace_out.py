"""Sum the workers' trace counters (`TRACE.considered()`) over a whole search run (#510)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

Considered = dict[str, dict[str, dict[str, int]]]  # {move: {class: {"generated": n, "evaluated": n}}}


def merge_considered(parts: Iterable[Considered | None]) -> Considered:
    """Integer sums of several `considered` dicts, move x class x kind."""

    out: Considered = {}
    for part in parts:
        for move, classes in (part or {}).items():
            for cls, kinds in classes.items():
                slot = out.setdefault(move, {}).setdefault(cls, {"generated": 0, "evaluated": 0})
                for kind, n in kinds.items():
                    slot[kind] = slot.get(kind, 0) + int(n)
    return out


def with_total(merged: Considered) -> dict[str, Any]:
    """`merged` plus a top-level "total" = {class: {"generated": n, "evaluated": n}} summed over moves."""

    total: dict[str, dict[str, int]] = {}
    for classes in merged.values():
        for cls, kinds in classes.items():
            slot = total.setdefault(cls, {"generated": 0, "evaluated": 0})
            for kind, n in kinds.items():
                slot[kind] = slot.get(kind, 0) + int(n)
    return {**merged, "total": dict(sorted(total.items()))}


def write_trace_out(path: Path | str, parts: Iterable[Considered | None]) -> dict[str, Any]:
    doc = with_total(merge_considered(parts))
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    return doc
