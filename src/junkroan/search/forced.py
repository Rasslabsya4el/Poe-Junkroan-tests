"""Forced directions of a request (#510, D114 amd 1): what every build of the search must carry.

A request's named unique, rare base, passive node and mod line is a constraint, never a hint: no
build without it is sent to PoB. This module holds the shared shape the units of #510 read:
``forced_of(skeleton)`` and the number-free comparison of a mod line against an item's text.
"""

from __future__ import annotations

import re
from typing import Any

_NUMBER = re.compile(r"[+-]?\d+(?:\.\d+)?")
_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")  # a mod record's "(10-15)"
_LINE_TAGS = re.compile(r"^(?:\{[^}]*\})+")  # PoB's "{tags:..}{prefix}", "{range:..}", "{crafted}" in front of an item line


def affix_template(line: str) -> str:
    """A mod line with every number replaced by ``#``, case-folded, spaces collapsed:
    "+1 to Level of all Fire Spell Skill Gems" and "+2 to Level of ..." share one template; a range "(1-2)" reads as one number and PoB's
    leading "{tags:..}{prefix}" groups of an item line are dropped."""

    text = _LINE_TAGS.sub("", str(line).strip())
    return " ".join(_NUMBER.sub("#", _RANGE.sub("1", text)).split()).lower()


def raw_has_affix(raw: str, line: str) -> bool:
    """Whether the item text ``raw`` (PoB's item format, one mod per line) carries ``line``."""

    want = affix_template(line)
    return any(affix_template(row) == want for row in str(raw).splitlines())


_HEADER = re.compile(r"^(?:Prefix|Suffix): (?:\{[^}]*\})*(\S+)\s*$")


def raw_header_ids(raw: str) -> frozenset[str]:
    """The mod ids of the ``Prefix:`` / ``Suffix:`` headers of a rolled item (before its ``Implicits:`` line);
    ``None`` is no mod."""

    out: set[str] = set()
    for row in str(raw).splitlines():
        if row.startswith("Implicits:"):
            break
        m = _HEADER.match(row.strip())
        if m and m.group(1) != "None":
            out.add(m.group(1))
    return frozenset(out)


def forced_of(skeleton: Any) -> dict[str, Any]:
    """The skeleton's forced directions in one mapping (the shape ``TRACE.set_forced`` takes):
    ``{"uniques": {slot: name}, "bases": {slot: base}, "nodes": [id, ...], "affixes": {slot: [line, ...]}}``."""

    return {
        "uniques": dict(getattr(skeleton, "forced_uniques", {}) or {}),
        "bases": dict(getattr(skeleton, "forced_bases", {}) or {}),
        "nodes": [int(n) for n in (getattr(skeleton, "forced_nodes", []) or [])],
        "affixes": {s: list(v) for s, v in (getattr(skeleton, "forced_affixes", {}) or {}).items()},
        "spectres": [str(s) for s in (getattr(skeleton, "forced_spectres", []) or [])],
    }


def xml_spectre_ids(xml: str) -> set[str]:
    """The ids of the `<Spectre id="..."/>` children of `<Build>` in a build XML."""

    import xml.etree.ElementTree as ET

    build = ET.fromstring(xml).find("Build")
    return {e.get("id", "") for e in (build.findall("Spectre") if build is not None else [])}


def has_forced(forced: dict[str, Any] | None) -> bool:
    return bool(forced) and any(forced.get(k) for k in ("uniques", "bases", "nodes", "affixes", "spectres"))
