"""An amulet's anoint written into its raw item text (#432).

An anoint is the enchant line `Allocates <notable name>` (PoB `Classes/ItemsTab.lua:2909-2921`). PoB writes an enchant
line into an item's raw as `{enchant}<line>` inside the Implicits block, counted by the `Implicits: N` header
(`Classes/Item.lua:1827` writes the tag, `:1973` counts enchants in N, `:1285` routes a tagged line to the enchant list).
Amulet bases flagged `cannotBeAnointed = true` in `Data/Bases/amulet.lua` (talismans) take none.
"""

from __future__ import annotations

import re
from functools import lru_cache

from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT

_AMULET_LUA = DEFAULT_SOURCE_ROOT / "src" / "Data" / "Bases" / "amulet.lua"
_BASE_BLOCK = re.compile(r'^itemBases\["([^"]+)"\]\s*=\s*\{', re.MULTILINE)
_ANOINT = re.compile(r"^\s*\{enchant\}(?:\{[^}]*\})*Allocates (.+?)\s*$")  # PoB's export writes `{enchant}{crafted}Allocates <name>`, and the XML text indents its lines
_IMPLICITS = re.compile(r"^Implicits: (\d+)\s*$")


@lru_cache(maxsize=1)
def _amulet_bases() -> tuple[frozenset[str], frozenset[str]]:
    """(every amulet base, those with cannotBeAnointed), parsed once from the vendored PoB."""

    text = _AMULET_LUA.read_text(encoding="utf-8")
    starts = list(_BASE_BLOCK.finditer(text))
    allb: set[str] = set()
    blocked: set[str] = set()
    for i, m in enumerate(starts):
        block = text[m.end() : starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        allb.add(m.group(1))
        if re.search(r"cannotBeAnointed\s*=\s*true", block):
            blocked.add(m.group(1))
    return frozenset(allb), frozenset(blocked)


def cannot_be_anointed_bases() -> frozenset[str]:
    return _amulet_bases()[1]


def can_anoint(base_name: str) -> bool:
    allb, blocked = _amulet_bases()
    return base_name in allb and base_name not in blocked


def anoint_line(notable: str) -> str:
    return f"{{enchant}}Allocates {notable}"


def _base_of(lines: list[str]) -> str:
    return lines[2].strip() if len(lines) > 2 else ""


def anoint_of(raw: str) -> str | None:
    for line in raw.splitlines():
        m = _ANOINT.match(line)
        if m:
            return m.group(1)
    return None


def apply_anoint(raw: str, notable: str | None) -> str:
    """The raw with its `Allocates` enchant replaced by `notable`'s; none when `notable` is None.

    A raw whose base is not an amulet base is returned untouched; a talisman-type amulet ends with no anoint.
    """

    lines = raw.split("\n")
    if _base_of(lines) not in _amulet_bases()[0]:
        return raw
    out: list[str] = []
    implicits_at = None
    removed = 0
    for line in lines:
        if _ANOINT.match(line):
            removed += 1
            continue
        out.append(line)
        if implicits_at is None and _IMPLICITS.match(line):
            implicits_at = len(out) - 1
    if implicits_at is None:
        if notable or removed:
            raise ValueError("an amulet raw without an Implicits: line cannot carry an enchant")
        return raw
    add = [anoint_line(notable)] if notable and can_anoint(_base_of(lines)) else []
    count = int(_IMPLICITS.match(out[implicits_at]).group(1)) - removed + len(add)
    out[implicits_at] = f"Implicits: {count}"
    out[implicits_at + 1 : implicits_at + 1] = add
    return "\n".join(out)
