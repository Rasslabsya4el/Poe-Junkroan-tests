"""Option classes of #600's day-1 boots rule: the movement line is exactly `30% increased Movement Speed`.

`boots-without-30-movement` must stay 0 on every finished day-1 boots item (the template's three lines are
life, resistance, movement, so an item that carries all three line counts but no 30% line broke the rule; a
boots still being filled has fewer lines and is not counted). `boots-with-30-movement` counts the boots that carry it.
Importing this module registers the class function with `trace.register_class`; PoB-free."""

from __future__ import annotations

import re
from typing import Iterable

from junkroan.optimizer.trace import register_class
from junkroan.optimizer.trace_429 import _IMPLICITS, _NOT_A_MOD, _affix_count, _strip

MOVEMENT_30 = re.compile(r"^30% increased Movement Speed$")
FINISHED_LINES = 3  # day1_gear_templates.json "Boots": life, resistance, movement


def boots_movement_classes(trial: dict) -> Iterable[str]:
    item = trial.get("item") if isinstance(trial, dict) else None
    if not isinstance(item, dict) or item.get("slot") != "Boots":
        return []
    raw = item.get("raw")
    if not isinstance(raw, str):
        return []
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not any(ln.lower() == "rarity: rare" for ln in lines):
        return []
    idx = next((i for i, ln in enumerate(lines) if _IMPLICITS.match(ln)), None)
    if idx is None:
        return []
    mods = [ln for ln in lines[idx + 1 + int(_IMPLICITS.match(lines[idx]).group(1)) :] if _strip(ln) not in _NOT_A_MOD]
    if any(MOVEMENT_30.match(_strip(ln)) for ln in mods):
        return ["boots-with-30-movement"]
    return ["boots-without-30-movement"] if _affix_count(lines, mods) >= FINISHED_LINES else []


register_class(boots_movement_classes)
