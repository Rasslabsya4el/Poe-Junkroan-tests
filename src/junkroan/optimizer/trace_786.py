"""Option classes of #786's day-1 loot base rule: a Rare's base drops by the `gear.wishlist.base_level_max` rail (70).

`loot-base-over-70` must stay 0 on every day-1 Rare (its base's drop level is above the rail); `loot-base-within-70`
counts the Rares whose base is within it. Jewels, flasks, non-Rares and bases the corpus does not know get no class.
The limit is the rails' own default, never a second copy. Importing registers the class function; PoB-free."""

from __future__ import annotations

from typing import Iterable

from junkroan.optimizer.item_bases import base_drop_level
from junkroan.optimizer.rails import WishlistRails
from junkroan.optimizer.trace import register_class


def loot_base_classes(trial: dict) -> Iterable[str]:
    item = trial.get("item") if isinstance(trial, dict) else None
    if not isinstance(item, dict):
        return []
    slot = str(item.get("slot") or "")
    if "Jewel" in slot or "Flask" in slot:
        return []
    raw = item.get("raw")
    if not isinstance(raw, str):
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0].lower() != "rarity: rare":
        return []
    level = base_drop_level(lines[2])
    if level is None:
        return []
    return ["loot-base-over-70" if level > WishlistRails().base_level_max else "loot-base-within-70"]


register_class(loot_base_classes)
