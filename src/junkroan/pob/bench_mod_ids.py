"""Which game mod a PoB crafting-bench row is, so its family can be looked up.

PoB's bench table (`data.masterMods`, one row per craft) carries no mod id at
all -- only PoB's own `group`. The group is not the game's mod family, so
without an id the bench filter had to fall back to `pob:<group>` and could not
see that the "+(28-33) to maximum Life / Regenerate 2 Mana per second" craft
(PoB group `BaseLifeAndManaRegen`) is family `IncreasedLife` in the game and
must never be crafted onto an item that already carries a flat-life prefix.

A bench row is recognised by its mod *text*, against every mod of RePoE's
`crafted` domain (`corpus_data/bench_mods.json`, built by
`scripts/build_mod_families.py`); `mod_families.families_of` then turns the id
into families. Matching, narrowing until one survivor:

1. the crafted mods of the row's affix type whose text is the row's lines,
   compared canonically: whitespace collapsed, case folded, reversed ranges
   ``(40-31)`` rewritten ``(31-40)``, line order ignored (RePoE and PoB print
   the lines of a two-stat mod in different orders);
2. of those, the ones whose required level is the row's `level`;
3. of those, the ones whose id contains PoB's group name -- the bench holds one
   mod per crafting master / item class with identical text
   (`StrIntMasterFireResistanceCrafted1`, `DexMasterFireResistanceCrafted1`,
   `HelenaMasterFireResist1`).

One survivor is the row's mod id. Several survivors that agree on their
families still answer the only question a caller asks, so `bench_mod_families`
returns the shared families while `bench_mod_id` returns None.

On the pinned PoB (732 bench rows in `Data/ModMaster.lua`): 716 rows resolve to
a single mod id (97.8%), the remaining 16 to a single family set; all 732 rows
end up with known families, and 415 of them sit in a family that is not their
PoB group.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from itertools import permutations
from pathlib import Path
from typing import Any, Iterable, Mapping

from .mod_families import families_of

CORPUS = Path(__file__).resolve().parent / "corpus_data" / "bench_mods.json"

_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")
_NUMBER = r"(-?\d+(?:\.\d+)?)"


def corpus_path() -> Path:
    """Where the crafting-bench mod index lives."""

    return CORPUS


def _order_range(match: re.Match[str]) -> str:
    low, high = match.group(1), match.group(2)
    if float(low) > float(high):
        low, high = high, low
    return f"({low}-{high})"


def canonical_lines(lines: Iterable[Any]) -> tuple[str, ...]:
    """The mod text as a comparable key: sorted, case folded, ranges in order."""

    out = []
    for line in lines or ():
        text = " ".join(str(line).split())
        if not text:
            continue
        out.append(_RANGE.sub(_order_range, text).casefold())
    return tuple(sorted(out))


@lru_cache(maxsize=1)
def _mods() -> dict[str, dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8")).get("mods") or {}


@lru_cache(maxsize=1)
def _by_text() -> dict[tuple[str, tuple[str, ...]], tuple[str, ...]]:
    index: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for mod_id, mod in _mods().items():
        index.setdefault((str(mod["type"]), canonical_lines(mod["lines"])), []).append(mod_id)
    return {key: tuple(sorted(ids)) for key, ids in index.items()}


def _candidates(row: Mapping[str, Any]) -> tuple[str, ...]:
    """The crafted mods a bench row can be, narrowed by text, then level, then group."""

    affix = str(row.get("type") or "").lower()
    found = _by_text().get((affix, canonical_lines(row.get("lines") or ())), ())
    if len(found) < 2:
        return found
    mods = _mods()
    level = row.get("level")
    if level is not None:
        same_level = tuple(i for i in found if mods[i]["level"] == int(level))
        if same_level:
            found = same_level
    group = row.get("group")
    if len(found) > 1 and group:
        named = tuple(i for i in found if str(group) in i)
        if named:
            found = named
    return found


def bench_mod_id(row: Mapping[str, Any]) -> str | None:
    """The RePoE crafted mod id of a PoB bench row, or None when it is not unique.

    ``row`` is a row of ``PobSession.list_bench_mods``: `type` "Prefix"/"Suffix",
    `group`, `level`, `lines` (the mod text with its ranges).
    """

    found = _candidates(row)
    return found[0] if len(found) == 1 else None


def bench_mod_candidates(row: Mapping[str, Any]) -> tuple[str, ...]:
    """All crafted mod ids whose text can represent a PoB bench row."""

    return _candidates(row)


def bench_mod_families(row: Mapping[str, Any]) -> tuple[str, ...]:
    """The game mod families a bench row occupies; empty when its candidates disagree.

    An unrecognised row has no family and never conflicts (the caller falls back
    to PoB's group).
    """

    found = _candidates(row)
    if not found:
        return ()
    families = {families_of(mod_id) for mod_id in found}
    return families.pop() if len(families) == 1 else ()


@lru_cache(maxsize=1)
def _line_patterns() -> dict[str, tuple[tuple[re.Pattern[str], tuple[tuple[float, float], ...]], ...]]:
    """Per crafted mod, one (regex, ranges) per line: the regex takes a rolled number where
    the corpus text has a range, and the number must sit inside that range."""

    out: dict[str, tuple[tuple[re.Pattern[str], tuple[tuple[float, float], ...]], ...]] = {}
    for mod_id, mod in _mods().items():
        compiled = []
        for line in mod["lines"]:
            text = " ".join(str(line).split())
            parts: list[str] = []
            ranges: list[tuple[float, float]] = []
            last = 0
            for m in _RANGE.finditer(text):
                parts.append(re.escape(text[last : m.start()]))
                parts.append(_NUMBER)
                low, high = float(m.group(1)), float(m.group(2))
                ranges.append((min(low, high), max(low, high)))
                last = m.end()
            parts.append(re.escape(text[last:]))
            compiled.append((re.compile("^" + "".join(parts) + "$", re.IGNORECASE), tuple(ranges)))
        out[mod_id] = tuple(compiled)
    return out


def _line_fits(pattern: re.Pattern[str], ranges: tuple[tuple[float, float], ...], text: str) -> bool:
    m = pattern.match(text)
    return bool(m) and all(low - 1e-9 <= float(value) <= high + 1e-9 for value, (low, high) in zip(m.groups(), ranges))


def crafted_text_mods(lines: Iterable[Any]) -> tuple[str, ...]:
    """The crafted mods whose rolled text is ``lines``: every ``{crafted}`` line of one item.

    A finished item carries its bench craft as text with the numbers rolled
    ("+31 to maximum Life", "Regenerate 2 Mana per second"), no id and no
    range, so the craft is recognised by the corpus mods whose lines it fits
    number by number (line order ignored). One bench craft = one mod, so the
    lines must be exactly one mod's lines.
    """

    texts = [" ".join(str(line).split()) for line in lines or () if str(line).strip()]
    if not texts:
        return ()
    found = []
    for mod_id, compiled in _line_patterns().items():
        if len(compiled) != len(texts):
            continue
        if any(all(_line_fits(p, r, t) for (p, r), t in zip(compiled, perm)) for perm in permutations(texts)):
            found.append(mod_id)
    return tuple(sorted(found))


def crafted_text_families(lines: Iterable[Any]) -> tuple[str, ...]:
    """The game mod families of an item's bench craft given as rolled text; empty when
    the text fits no crafted mod or the fitting mods disagree on their families."""

    found = crafted_text_mods(lines)
    if not found:
        return ()
    families = {families_of(mod_id) for mod_id in found}
    return families.pop() if len(families) == 1 else ()


__all__ = ["bench_mod_candidates", "bench_mod_families", "bench_mod_id", "canonical_lines", "corpus_path", "crafted_text_families", "crafted_text_mods"]
