"""Overleech sources (#610): a build whose leech is not removed at full Life / Energy Shield is leeching all fight.

The source list is read from PoB's own parsed data (`ModCache.lua` lines whose mod is one of the "leech
not removed on full pool" FLAGs), never typed here. PoB's `CalcPerform` already turns `Condition:Leeching` on
from `CanLeechLifeOnFullLife` / `CanLeechEnergyShieldOnFullEnergyShield` (except Life under `GhostReaver`);
the config rule makes the same fact explicit in the derived config, with a proof line and a trace count.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path

from junkroan.optimizer.trace import TRACE

_REPO = Path(__file__).resolve().parents[3]
MODCACHE = _REPO / "vendor" / "pob" / "source" / "src" / "Data" / "ModCache.lua"
LEGION = _REPO / "vendor" / "pob" / "source" / "src" / "Data" / "TimelessJewelData" / "LegionPassives.lua"
MODPARSER = _REPO / "vendor" / "pob" / "source" / "src" / "Modules" / "ModParser.lua"

FLAG_NAME = re.compile(r'^CanLeech\w*OnFull\w*$')
_FLAG_IN_PARSER = re.compile(r'flag\("(CanLeech\w*OnFull\w*)"')
_CACHE_ROW = re.compile(r'^c\["((?:[^"\\]|\\.)*)"\]=\{\{(.*?)\},(?:nil|".*")\}\s*$')
_PARSER_ROW = re.compile(r'^\t*\["([^"]+)"\]\s*=\s*{ flag\("(CanLeech\w*OnFull\w*)"\)\s*}')
_CACHE_NAME = re.compile(r'name="([^"]+)"')

OFF_CLASS = "overleech-leeching-off"
SET_CLASS = "overleech-leeching-set"


@lru_cache(maxsize=1)
def overleech_flag_names() -> frozenset[str]:
    """The mod names PoB's parser gives to 'leech not removed at full pool' lines."""

    return frozenset(_FLAG_IN_PARSER.findall(MODPARSER.read_text(encoding="utf-8", errors="replace")))


@lru_cache(maxsize=1)
def overleech_source_lines() -> dict[str, str]:
    """{lowercase mod line: flag name} for every ModParser / ModCache line that parses to an overleech flag alone."""

    flags = overleech_flag_names()
    out: dict[str, str] = {}
    for raw in MODPARSER.read_text(encoding="utf-8", errors="replace").splitlines():
        pm = _PARSER_ROW.match(raw)
        if pm and pm.group(2) in flags:
            out[pm.group(1).lower()] = pm.group(2)
    for raw in MODCACHE.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.startswith("c["):
            continue
        m = _CACHE_ROW.match(raw)
        if not m:
            continue
        names = set(_CACHE_NAME.findall(m.group(2)))
        hit = names & flags
        if hit and names <= flags:
            out[m.group(1).lower()] = sorted(hit)[0]
    return out


_KS_NAME = re.compile(r'"dn"\]\s*=\s*"([^"]+)"')
_KS_LINE = re.compile(r'^\s*\[\d+\]\s*=\s*"([^"]*)"')


@lru_cache(maxsize=1)
def overleech_keystones() -> dict[str, str]:
    """{lowercase keystone name: flag} for each keystone of PoB's legion keystone data whose own lines hold an overleech source.

    An item that grants such a keystone writes only its name (Soul Tether, Mahuxotl's Machination: the line "Immortal
    Ambition"), so the build text never holds the keystone's own lines; PoB resolves the name to them."""

    table = overleech_source_lines()
    out: dict[str, str] = {}
    name: str | None = None
    in_sd = False
    for raw in LEGION.read_text(encoding="utf-8", errors="replace").splitlines():
        nm = _KS_NAME.search(raw)
        if nm:
            name, in_sd = nm.group(1), False
        elif '"sd"]' in raw:
            in_sd = True
        elif in_sd and raw.strip().startswith("}"):
            in_sd = False
        elif in_sd and name:
            lm = _KS_LINE.match(raw)
            if lm and lm.group(1).lower() in table:
                out[name.lower()] = table[lm.group(1).lower()]
    return out


_PREFIX = re.compile(r'^(?:\{[^}]*\}\s*)+')


def overleech_sources_in(text: str) -> list[tuple[str, str]]:
    """(line, flag) for each build-text line that is an overleech source."""

    table = {**overleech_keystones(), **overleech_source_lines()}
    found: list[tuple[str, str]] = []
    for line in text.splitlines():
        key = _PREFIX.sub("", line.strip()).strip().lower()
        if key in table and (line.strip(), table[key]) not in found:
            found.append((line.strip(), table[key]))
    return found


def overleech_leeching(text: str, stats: Mapping[str, object]) -> tuple[bool, str | None]:
    """(set the toggle, proof line): an overleech source in the build AND any leech rate above zero in PoB."""

    sources = overleech_sources_in(text)
    if not sources:
        return False, None
    rates = [k for k in ("LifeLeechGainRate", "ManaLeechGainRate", "EnergyShieldLeechGainRate")
             if isinstance(stats.get(k), (int, float)) and not isinstance(stats.get(k), bool) and stats[k] > 0]
    if not rates:
        return False, None
    line, flag = sources[0]
    return True, f'overleech source "{line}" (PoB flag {flag}) with a positive {", ".join(rates)}: leeching all fight'


def count_overleech(is_overleech_build: bool, leeching_on: bool, was_set: bool) -> None:
    """Trace counter at derive time: the toggles this rule set, and overleech builds left with Leeching off (must be 0)."""

    TRACE.add_generated([OFF_CLASS, SET_CLASS], 0)
    TRACE.add_evaluated([OFF_CLASS, SET_CLASS], 0)
    if is_overleech_build and not leeching_on:
        TRACE.add_evaluated([OFF_CLASS])
    if was_set:
        TRACE.add_evaluated([SET_CLASS])
