"""The item bases a build may wear, read from the items corpus.

One catalogue for the two places that choose a base: the search's loot screen
(`search/generator.candidate_bases`) and the wishlist filler's own base choice (D73).
It answers three questions and nothing else: which item class a base belongs to, what
its implicit says, and which bases of a class a day-1 character can have.

"Can have" is a base that drops from the ground and is sold by vendors -- PoB's
`not_for_sale` (atlas-only, Synthesis, Necropolis and the other league-locked bases),
`experimental_base` (Heist), `demigods` and the talismans are out, and so is anything PoB
gives no item-class tag at all ("Random One Hand Sword", its own placeholders) -- and whose
drop level, which is its level requirement, is at or under the area level the rails allow
(`gear.wishlist.base_level_max`, 70, the owner's rule, #438). The
level-1 bases are in it: a Rustic Sash's 24% increased global physical damage is a day-1
implicit like any other, and its being free is the point. Nothing here judges a base: that
is PoB's.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from junkroan.optimizer.trace import register_class

CORPUS = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "items.json"
# item classes no one wears in a gear slot
NON_GEAR_TYPES = frozenset({"Jewel", "Flask", "Tincture", "Fishing Rod", "Graft"})
# PoB's own tags for bases a character does not simply find: league-locked or never dropped at all
UNOBTAINABLE_TAGS = frozenset({"experimental_base", "demigods", "not_for_sale"})


@lru_cache(maxsize=1)
def _records() -> tuple[Mapping[str, Any], ...]:
    raw = json.loads(CORPUS.read_text(encoding="utf-8"))
    return tuple(r for r in (raw.get("records") or []) if isinstance(r, Mapping))


def _is_day1_base(record: Mapping[str, Any]) -> bool:
    if record.get("item_kind") != "base" or record.get("type") in NON_GEAR_TYPES:
        return False
    if record.get("sub_type") == "Talisman":  # a league's own bases, not a map drop
        return False
    tags = set(record.get("tags") or ())
    if tags & UNOBTAINABLE_TAGS or not (tags - {"default"}):
        # a base PoB gives no class tag beyond "default" is not an item ("Random One Hand Sword")
        return False
    return True


def drop_level(record: Mapping[str, Any]) -> int:
    """The base's level requirement, which is the area level it starts dropping at."""

    return int((record.get("requirements") or {}).get("level") or 0)


@lru_cache(maxsize=1)
def bases_by_type() -> Mapping[str, tuple[Mapping[str, Any], ...]]:
    """{item class: the bases of it a day-1 character can find}, in corpus order (which is what
    the loot screen's per-attribute-profile pick has always broken its ties on)."""

    out: dict[str, list[Mapping[str, Any]]] = {}
    for record in _records():
        if _is_day1_base(record):
            out.setdefault(str(record["type"]), []).append(record)
    return {t: tuple(rows) for t, rows in sorted(out.items())}


@lru_cache(maxsize=1)
def _by_name() -> Mapping[str, Mapping[str, Any]]:
    return {str(r["name"]).lower(): r for r in _records() if r.get("item_kind") == "base"}


def base_record(base: str) -> Mapping[str, Any] | None:
    return _by_name().get(str(base).strip().lower())


def base_drop_level(base: str) -> int | None:
    """The drop level of a base by name; None when the corpus does not know the name."""

    record = base_record(base)
    return drop_level(record) if record else None


def type_of(base: str) -> str:
    """The item class of a base ("Onyx Amulet" -> "Amulet", "Harbinger Bow" -> "Bow"); "" when
    the corpus does not know the name."""

    record = base_record(base)
    return str(record.get("type") or "") if record else ""


def implicit_of(base: str) -> str:
    """The base's implicit as the corpus writes it ("+(10-16) to all Attributes"), one line."""

    record = base_record(base)
    return " / ".join(str(record.get("implicit_text") or "").splitlines()) if record else ""


def bases_of_type(item_type: str, *, max_level: int) -> list[str]:
    """Every base of the class a day-1 character can find at or under ``max_level``, name order
    (the order is the caller's tie-break, so it must not depend on the corpus file's)."""

    return sorted(str(r["name"]) for r in bases_by_type().get(item_type, ()) if drop_level(r) <= int(max_level))


def raw_base_of(raw: str) -> str:
    """The base a PoB item raw wears: the first line after the header that the corpus knows as a base (a wishlist
    placeholder can sit in the third line), else the third line; "" for a raw too short to have one."""

    lines = raw.splitlines()
    for line in lines[2:]:
        if base_record(line.strip()) is not None:
            return line.strip()
    return lines[2].strip() if len(lines) > 2 else ""


def excluded_of(rails: Any) -> frozenset[str]:
    """The case-folded base names the rails' loadout never offers (#1154); a rails stand-in without the key excludes nothing."""

    return getattr(getattr(rails, "gear", None), "excluded_bases", None) or frozenset()


def without_excluded(names: Iterable[str], rails: Any) -> list[str]:
    """``names`` minus the bases the rails' loadout excludes (`gear.bases_excluded_by_loadout`), order kept."""

    excluded = excluded_of(rails)
    return [n for n in names if str(n).strip().casefold() not in excluded]


def _trace_base_level(trial: dict) -> list[str]:
    """#438: `base-level:<=70` / `base-level:>70` of a trial's day-1 base, for the #498 counter."""

    from junkroan.optimizer.trace import _item_classes

    item = trial.get("item") if isinstance(trial, dict) else None
    if not isinstance(item, dict):
        return []
    out = []
    for c in _item_classes(item):
        record = base_record(c[5:]) if c.startswith("base:") else None
        if record is not None and record.get("item_kind") == "base" and _is_day1_base(record):
            out.append("base-level:<=70" if drop_level(record) <= 70 else "base-level:>70")
    return out


register_class(_trace_base_level)


@lru_cache(maxsize=1)
def _day1_excluded() -> frozenset[str]:
    from junkroan.optimizer.rails import Rails

    return Rails.load().gear.excluded_bases


def _trace_base_excluded(trial: dict) -> list[str]:
    """#1154: `base-excluded-by-loadout` for a trial whose base the day-1 rails exclude (must stay 0 generated, 0 evaluated and 0 in the output)."""

    from junkroan.optimizer.trace import _item_classes

    item = trial.get("item") if isinstance(trial, dict) else None
    if not isinstance(item, dict):
        return []
    excluded = _day1_excluded()
    return ["base-excluded-by-loadout"] if any(c.startswith("base:") and c[5:].strip().casefold() in excluded for c in _item_classes(item)) else []


register_class(_trace_base_excluded)

__all__ = ["bases_by_type", "bases_of_type", "base_record", "drop_level", "excluded_of", "implicit_of", "raw_base_of", "type_of", "without_excluded"]
