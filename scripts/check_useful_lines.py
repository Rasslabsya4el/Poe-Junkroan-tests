"""Rulebook `g-useful-n` checker (issue #437): a rare in a gear slot has at most N_slot lines with a
non-negative value (explicit + bench craft); at most `rails.gear.wishlist.extra_resistance_items`
items of a build have N_slot + 1, the extra being a single-element resistance line.

    python scripts/check_useful_lines.py <run dir | build.xml> ...

A run dir is searched for `*.xml` (the benchmark writes `<slug> s<seed>.xml` into PoB's Builds folder).
Every build is loaded into one PobSession; values are `useful_lines.line_values` (one fast trial_stats
per item). Objective: `objective_for(rails, main skill, mode)` as the pipeline builds it; the benchmark's
author-derived floors cannot be rebuilt from the XML alone, so the pipeline's default floors are used.
Exit 0 = no violation, 1 = a violation, 2 = the machine budget says WAIT.
"""

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))  # src first: scripts/junkroan.py would shadow the package

from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.useful_lines import classify, n_slot, resistance_element  # noqa: E402

GEAR_SLOTS = ("Weapon 1", "Weapon 2", "Helmet", "Body Armour", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2")

Item = tuple[str, str, str]  # slot, base, raw
ValueOf = Callable[[str, str], Sequence[tuple[object, tuple[float, float]]]]


def check_build(items: Sequence[Item], value_of: ValueOf, rails: Rails) -> list[str]:
    """Violations of one build's rare gear: an item over N_slot + 1, an extra without a resistance
    line, or more extra items than `extra_resistance_items`."""

    violations: list[str] = []
    extras: list[str] = []
    for slot, base, raw in items:
        n = n_slot(base, slot, rails)
        counted = [(ln, v) for ln, v in value_of(slot, raw) if classify(v) != "drawback"]
        k = len(counted)
        texts = [ln.text for ln, _v in counted]
        if k > n + 1:
            violations.append(f"[{slot}] {k} lines count, N_slot {n}: {texts}")
        elif k == n + 1:
            if any(resistance_element(t) for t in texts):
                extras.append(slot)
            else:
                violations.append(f"[{slot}] {k} lines count, N_slot {n}, no single-element resistance line for the extra: {texts}")
    allowed = rails.gear.wishlist.extra_resistance_items
    if len(extras) > allowed:
        violations.append(f"{len(extras)} items have N_slot + 1 ({extras}), at most {allowed} may")
    return violations


def rare_items(xml: str) -> list[Item]:
    """(slot, base, raw) of the active item set's rare gear slots; swap sets, jewels, flasks skipped."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return []
    by_id = {i.get("id"): i for i in items.findall("Item")}
    iset = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
    out: list[Item] = []
    for slot in (iset.findall("Slot") if iset is not None else items.findall("Slot")):
        name = slot.get("name") or ""
        item = by_id.get(slot.get("itemId") or "")
        if item is None or name not in GEAR_SLOTS:
            continue
        raw = (item.text or "").strip("\n")
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        if len(lines) < 3 or lines[0].replace(" ", "").upper() != "RARITY:RARE":
            continue
        out.append((name, lines[2], raw + "\n"))
    return out


def collect(paths: Sequence[str]) -> list[Path]:
    files: list[Path] = []
    for p in map(Path, paths):
        files.extend(sorted(p.rglob("*.xml")) if p.is_dir() else [p])
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="run dir(s) or build .xml file(s)")
    args = ap.parse_args(argv)

    from junkroan.pob import slot_budget

    go, line = slot_budget.verdict(1, slot_budget.ROLE_OTHER, directory=slot_budget.slot_dir(), budget=slot_budget.load_budget())
    if not go:
        print(f"machine budget says WAIT: {line}", file=sys.stderr)
        return 2

    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.useful_lines import line_values
    from junkroan.pob.session import PobSession

    rails = Rails.load()
    total = 0
    with PobSession(run_id=f"check-useful-lines-{os.getpid()}") as pob:
        for f in collect(args.paths):
            xml = f.read_text(encoding="utf-8")
            pob.load_xml(xml)
            skeleton = skeleton_from_xml(xml, pob, rails=rails)
            objective = objective_for(rails, skeleton.main_link[0], mode=skeleton.mode)
            found = check_build(rare_items(xml), lambda slot, raw: line_values(pob, objective, slot, raw), rails)
            print(f"{f}: {len(found)} violations")
            for v in found:
                print(f"  {v}")
            total += len(found)
    print(f"total: {total} violations")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
