"""PoB-free check of coloured sockets in PoB build XMLs (replay `builds/*.xml`).

Usage: python scripts/check_coloured_sockets.py <builds dir> [--stage day1]

A build violates when it has more R/G/B sockets (over equipped items, skipping items with
"Gems Socketed always have the Quality bonus from Socket Colour") than coloured_max(stage),
or when a coloured socket does not hold a gem of its colour. Gem index rule as in PoB
`SkillsTab.lua` UpdateSocketGroups (~1210-1244): the gem at index i of a group sits in socket
gemOffset + i of the slot's item; gemOffset = gems of earlier groups in the same slot
(every gem counts, enabled or not, group enabled or not).
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# src/ BEFORE scripts/: a scripts/junkroan.py would shadow the package otherwise.
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "src"))

from junkroan.search.sockets import coloured_max, gem_colour  # noqa: E402

_ALWAYS = "Gems Socketed always have the Quality bonus from Socket Colour"


def _sockets(raw: str) -> list[str]:
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("Sockets:"):
            return [c for c in line[len("Sockets:"):] if c.isalpha()]
    return []


def _active(parent: ET.Element | None, tag: str, attr: str) -> ET.Element | None:
    if parent is None:
        return None
    sets = parent.findall(tag)
    want = parent.get(attr)
    for s in sets:
        if s.get("id") == want:
            return s
    return sets[0] if sets else parent


def check_file(path: Path, stage: str = "day1") -> list[str]:
    root = ET.parse(path).getroot()
    items = {i.get("id"): (i.text or "") for i in root.iter("Item")}
    iset = _active(root.find("Items"), "ItemSet", "activeItemSet")
    slot_items: dict[str, str] = {}
    if iset is not None:
        for s in iset.findall("Slot"):
            iid = s.get("itemId")
            name = s.get("name", "")
            if iid and iid != "0" and iid in items and "Swap" not in name:
                slot_items[name] = items[iid]
    out: list[str] = []
    sockets: dict[str, list[str]] = {}
    total = 0
    for slot, raw in slot_items.items():
        if _ALWAYS in raw:
            continue
        socks = _sockets(raw)
        sockets[slot] = socks
        total += sum(1 for c in socks if c in "RGB")
    limit = coloured_max(stage)
    if limit is not None and total > limit:
        out.append(f"{path.name}: [all] {total} coloured sockets, max {limit}")
    sskill = _active(root.find("Skills"), "SkillSet", "activeSkillSet")
    offsets: dict[str, int] = {}
    groups = sskill.findall("Skill") if sskill is not None else []
    for g in groups:
        slot = g.get("slot")
        if not slot:
            continue
        gems = g.findall("Gem")
        off = offsets.get(slot, 0)
        offsets[slot] = off + len(gems)
        socks = sockets.get(slot)
        if not socks:
            continue
        for i, gem in enumerate(gems):
            idx = off + i
            if idx >= len(socks) or socks[idx] not in "RGB":
                continue
            name = gem.get("nameSpec", "")
            if gem_colour(name) != socks[idx]:
                out.append(
                    f"{path.name}: [{slot}] socket {idx + 1} is {socks[idx]}, "
                    f"gem {name!r} is {gem_colour(name) or 'W'}"
                )
    for slot, socks in sockets.items():
        n = offsets.get(slot, 0)
        for idx, c in enumerate(socks):
            if c in "RGB" and idx >= n:
                out.append(f"{path.name}: [{slot}] socket {idx + 1} is {c}, empty")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("builds_dir")
    ap.add_argument("--stage", default="day1")
    a = ap.parse_args(argv)
    n = 0
    for f in sorted(Path(a.builds_dir).glob("*.xml")):
        for line in check_file(f, a.stage):
            print(line)
            n += 1
    print(f"total: {n} violations")
    return 1 if n else 0


if __name__ == "__main__":
    raise SystemExit(main())
