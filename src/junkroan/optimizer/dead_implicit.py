"""Dead implicits (#1158): an equipped gear item whose implicit buys nothing in PoB.

Each gear item that carries an implicit is trialled once in PoB with the implicit lines removed (its raw
keeps every other line, and its `Implicits:` header reads 0), in full mode so PoB's own roll-up runs. The
removal value is read on the objective and on TotalEHP; under DEAD_IMPLICIT_SHARE on both, the implicit is dead.
Only the gear slots are trialled: the trial item path refuses a tree-socket jewel (its slot has a nodeId).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_hygiene import _judged_key, _signed_change, _trial_values, stat_keys

DEAD_IMPLICIT_SHARE = 0.001  # 0.1 %: under it on both the objective and TotalEHP, an implicit is dead (#1158)
IMPLICIT_SLOTS = ("Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Amulet", "Ring 1", "Ring 2", "Belt")

_IMPLICITS = re.compile(r"^Implicits:\s*(\d+)$")
_TAG_RUN = re.compile(r"^(?:\{[^}]*\})+")


def _implicit_span(raw: str) -> tuple[list[str], int, int] | None:
    """(the raw's lines with their endings, index of the `Implicits:` header, one past the last implicit line);
    None when the raw has no implicit block or its block is empty."""

    lines = raw.splitlines(keepends=True)
    at = next((i for i, ln in enumerate(lines) if _IMPLICITS.match(ln.strip())), None)
    if at is None:
        return None
    count = int(_IMPLICITS.match(lines[at].strip()).group(1))
    if count == 0:
        return None
    return lines, at, min(at + 1 + count, len(lines))


def raw_without_implicits(raw: str) -> str | None:
    """The raw with its implicit lines deleted and its `Implicits:` header set to 0; every other line is kept
    byte for byte. None when the raw has no implicit."""

    span = _implicit_span(raw)
    if span is None:
        return None
    lines, at, end = span
    newline = lines[at][len(lines[at].rstrip("\r\n")):]
    return "".join(lines[:at]) + "Implicits: 0" + newline + "".join(lines[end:])


def implicit_text(raw: str) -> str:
    """The raw's implicit lines as PoB writes them (tags stripped), joined by " / "; "" when there is none."""

    span = _implicit_span(raw)
    if span is None:
        return ""
    lines, at, end = span
    return " / ".join(_TAG_RUN.sub("", ln.strip()) for ln in lines[at + 1:end] if ln.strip())


def base_line(raw: str) -> str:
    """The item's base name: the line after the name for a rare or unique, else the first line after the rarity."""

    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    rest = lines[1:]
    if lines and lines[0].lower() in {"rarity: rare", "rarity: unique"} and len(rest) >= 2:
        return rest[1]
    return rest[0] if rest else ""


@dataclass(frozen=True, slots=True)
class ImplicitRemoval:
    """What PoB's own removal of one equipped item's implicit moves; changes are signed fractions."""

    slot: str
    base: str
    implicit: str
    judged_stat: str
    judged_change: float
    ehp_change: float

    @property
    def dead(self) -> bool:
        return abs(self.judged_change) < DEAD_IMPLICIT_SHARE and abs(self.ehp_change) < DEAD_IMPLICIT_SHARE


def implicit_removals(pob: Any, *, objective: Objective | None = None) -> list[ImplicitRemoval]:
    """Removal value of every gear item in IMPLICIT_SLOTS that carries an implicit, one full trial each (#1158)."""

    raws = pob.equipped_item_raws()
    targets: list[tuple[str, str, str, str]] = []  # slot, base, implicit text, implicit-free raw
    for slot in IMPLICIT_SLOTS:
        raw = raws.get(slot)
        free = raw_without_implicits(raw) if raw else None
        if free is not None:
            targets.append((slot, base_line(raw), implicit_text(raw), free))
    if not targets:
        return []
    keys = stat_keys(objective)
    base_stats = pob.stats(keys)
    judged = _judged_key(base_stats, objective)
    outcomes = pob.trial_stats([{"item": {"slot": slot, "raw": free}} for slot, _base, _implicit, free in targets], keys, mode="full")
    rows: list[ImplicitRemoval] = []
    for (slot, base, implicit, _free), outcome in zip(targets, outcomes):
        if isinstance(outcome, Mapping) and outcome.get("ok") is False:
            raise RuntimeError(f"PoB could not remove the implicit of {slot}: {outcome.get('error')}")
        trial = _trial_values(outcome)
        rows.append(ImplicitRemoval(
            slot=slot,
            base=base,
            implicit=implicit,
            judged_stat=judged,
            judged_change=_signed_change(base_stats.get(judged), trial.get(judged)),
            ehp_change=_signed_change(base_stats.get("TotalEHP"), trial.get("TotalEHP")),
        ))
    return rows


def dead_implicits(pob: Any, *, objective: Objective | None = None) -> list[ImplicitRemoval]:
    """The equipped gear implicits under DEAD_IMPLICIT_SHARE on both the objective and TotalEHP (#1158)."""

    return [row for row in implicit_removals(pob, objective=objective) if row.dead]


__all__ = ["DEAD_IMPLICIT_SHARE", "IMPLICIT_SLOTS", "ImplicitRemoval", "base_line", "dead_implicits", "implicit_removals",
           "implicit_text", "raw_without_implicits"]
