"""Option classes of #1158's base swap: the loop's base trial on any gear slot (`improvement_loop._weapon_base_move`).

The loop stamps each base-swap trial with the trace-only key `base_swap` (never in the PoB payload; `PobSession.trial_stats`
copies it beside the payload where the trial is counted, as the tree stamps of `tree_trace` are). The class function turns the
stamp into `base-swap` and `base-swap:<slot>`, so `generated(base-swap:<slot>) > 0 and evaluated(base-swap:<slot>) > 0` proves
that the swap reached that slot, and the item's own `base:<name>` class says which bases it tried (the loadout's excluded base,
Prismatic Ring on day 1, must not be among them). Importing registers the class function; PoB-free."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from junkroan.optimizer.trace import register_class

BASE_SWAP_KEY = "base_swap"  # the trial key
BASE_SWAP = "base-swap"  # the class


def stamp(trial: dict[str, Any]) -> dict[str, Any]:
    """`trial` marked as a base-swap trial (a copy)."""

    return {**trial, BASE_SWAP_KEY: True}


def stamp_of(trial: Any) -> dict[str, bool]:
    """The base-swap stamp a trial carries, to be copied beside the PoB payload where it is counted."""

    return {BASE_SWAP_KEY: True} if isinstance(trial, Mapping) and trial.get(BASE_SWAP_KEY) else {}


def base_swap_classes(trial: dict) -> Iterable[str]:
    if not isinstance(trial, dict) or not trial.get(BASE_SWAP_KEY):
        return []
    item = trial.get("item")
    slot = item.get("slot") if isinstance(item, dict) else None
    return [BASE_SWAP, f"{BASE_SWAP}:{slot}"] if isinstance(slot, str) and slot else [BASE_SWAP]


register_class(base_swap_classes)
