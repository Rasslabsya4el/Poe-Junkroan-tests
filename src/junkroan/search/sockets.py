"""Item socket strings and gem colours (PoB-free; reads PoB's data files as text)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_POB_DATA = _ROOT / "vendor" / "pob" / "source" / "src" / "Data"
_RULEBOOK = _ROOT / "docs" / "rulebook" / "loadout-rulebook.json"
_COLOURS = "RGB"


def whiten(sockets: str, chosen: Mapping[int, str] | None = None) -> str:
    """Make every R/G/B/W socket W except the `chosen` positions (counted over sockets only)."""

    chosen = dict(chosen or {})
    out: list[str] = []
    pos = 0
    for ch in sockets:
        if ch in "-  " or ch.isspace():
            out.append(ch)
            continue
        if pos in chosen:
            if ch == "A":
                raise ValueError(f"socket {pos} is an abyss socket")
            out.append(chosen[pos])
        elif ch in "RGBW":
            out.append("W")
        else:
            out.append(ch)
        pos += 1
    bad = [p for p in chosen if p < 0 or p >= pos]
    if bad:
        raise ValueError(f"socket position out of range: {bad} (have {pos})")
    return "".join(out)


def linked_white(n: int) -> str:
    return "-".join("W" * n) if n > 0 else ""


@lru_cache(maxsize=1)
def _gem_colours() -> dict[str, str | None]:
    """Gem name -> R/G/B/None, from PoB: `color` of the granted effect (Data/Skills/*.lua),
    1/2/3 = R/G/B as in SkillsTab:UpdateSocketGroups; 4 (and none) = white."""

    by_effect: dict[str, int] = {}
    for f in (_POB_DATA / "Skills").glob("*.lua"):
        cur = None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r'skills\["([^"]+)"\] = \{', line)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"\tcolor = (\d+),", line)
            if m and cur:
                by_effect[cur] = int(m.group(1))
                cur = None
    out: dict[str, str | None] = {}
    name = None
    for line in (_POB_DATA / "Gems.lua").read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'\t\t(?:name|baseTypeName) = "([^"]+)"', line)
        if m:
            name = m.group(1)
            continue
        m = re.match(r'\t\tgrantedEffectId = "([^"]+)"', line)
        if m and name:
            c = by_effect.get(m.group(1), 4)
            out[name] = _COLOURS[c - 1] if 1 <= c <= 3 else None
    return out


def gem_colour(gem_name: str) -> str | None:
    return _gem_colours().get(gem_name)


def coloured_max(stage: str = "day1") -> int | None:
    """machine.coloured_max.<stage> of rulebook row `gm-sockets`; None = no limit or absent."""

    try:
        data = json.loads(_RULEBOOK.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if o.get("id") == "gm-sockets":
                v = ((o.get("machine") or {}).get("coloured_max") or {}).get(stage)
                return int(v) if v is not None else None
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)
    return None
