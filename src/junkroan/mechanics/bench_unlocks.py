"""Crafting-bench recipe unlock data and the day-1 legality rail."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

DATA_PATH = Path(__file__).with_name("bench_unlocks.json")

# PoB's RePoE-derived id for this row predates the current game's ``NewSuffix``
# id.  Keep the correction at the data boundary rather than adding a second
# visible recipe to the generated 829-option index.
_MOD_ID_ALIASES = {
    "EinharMasterLocalLifeLeechPermyriad1__": "EinharMasterLocalLifeLeechPermyriadNewSuffix1",
}


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def lookup(mod_id: object | None = None, name: object | None = None) -> dict[str, Any] | None:
    raw = data()
    if mod_id:
        entry = (raw.get("by_mod_id") or {}).get(str(mod_id))
        if entry is None:
            entry = (raw.get("by_mod_id") or {}).get(_MOD_ID_ALIASES.get(str(mod_id), ""))
        if entry is not None:
            return dict(entry)
    if name:
        entry = (raw.get("by_name") or {}).get(str(name))
        if entry is not None:
            return dict(entry)
    return None


def _requirement(entry: Mapping[str, Any]) -> tuple[int, int]:
    where = str(entry.get("where") or "")
    order = {"start": 0, "campaign": 1, "labyrinth": 2, "map": 3}
    if where != "map":
        return order.get(where, 4), 0
    tier = entry.get("tier")
    return 3, int(tier) if isinstance(tier, int) else 99


def lowest_requirement(entries: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Return the reachable recipe when a PoB row maps to several game ids."""

    usable = [entry for entry in entries if entry]
    return dict(min(usable, key=_requirement)) if usable else None


def legal(
    unlock: Mapping[str, Any] | None,
    *,
    max_map_tier: int | None = 10,
    unknown_tier_allowed: bool = False,
    excluded_cost_currencies: tuple[str, ...] = (),
) -> bool:
    """Whether a bench row is legal under the supplied day-1 recipe rail."""

    if max_map_tier is None or unlock is None:
        return True
    costs = " ".join(str(cost) for cost in unlock.get("cost") or ()).casefold()
    if any(currency and currency.casefold() in costs for currency in excluded_cost_currencies):
        return False
    where = str(unlock.get("where") or "")
    if where in {"start", "campaign", "labyrinth"}:
        return True
    if where != "map":
        return True
    tier = unlock.get("tier")
    return unknown_tier_allowed if tier is None else int(tier) <= max_map_tier


__all__ = ["DATA_PATH", "data", "legal", "lookup", "lowest_requirement"]
