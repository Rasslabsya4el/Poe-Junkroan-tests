"""Measure bench-row annotation coverage and crafted lines in a finished run."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.mechanics.bench_unlocks import legal, lookup, lowest_requirement  # noqa: E402
from junkroan.pob.bench_mod_ids import crafted_text_mods  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402


def _unlock_for(lines: list[str]) -> tuple[tuple[str, ...], dict | None]:
    ids = crafted_text_mods(lines)
    return ids, lowest_requirement([entry for mod_id in ids if (entry := lookup(mod_id=mod_id))])


def measure_rows() -> None:
    """Ask PoB once per base type and union its global master-mod indexes."""

    items = json.loads((ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "items.json").read_text(encoding="utf-8"))
    bases: dict[str, str] = {}
    for record in items.get("records") or ():
        if record.get("item_kind") == "base" and record.get("type"):
            bases.setdefault(str(record["type"]), str(record["name"]))
    with PobSession(run_id="measure-bench-rows") as pob:
        rows = {}
        for base in bases.values():
            for row in pob.list_bench_mods(base, ilvl=84)["mods"]:
                rows[int(row["index"])] = row
    counts = Counter("annotated" if row.get("unlock") is not None else "without_entry" for row in rows.values())
    print(f"base types: {len(bases)}; unique PoB rows: {len(rows)}; {dict(counts)}")
    print(f"rows with one mod id: {sum(row.get('mod_id') is not None for row in rows.values())}; rows with ambiguous/no mod id: {sum(row.get('mod_id') is None for row in rows.values())}")
    if counts["without_entry"]:
        print("without entry:")
        for row in rows.values():
            if row.get("unlock") is None:
                print(json.dumps({key: row.get(key) for key in ("index", "name", "group", "lines", "mod_id")}, ensure_ascii=False))


def measure_run(run: Path, *, max_map_tier: int = 10) -> None:
    total = legal_count = missing = 0
    tier_illegal: Counter[tuple[str, str, int]] = Counter()
    currency: Counter[tuple[str, str, str, int | None]] = Counter()
    builds: defaultdict[tuple[str, str, int], set[str]] = defaultdict(set)
    for path in sorted(run.glob("*.pob.txt")):
        root = ET.fromstring(decode_import_code(path.read_text(encoding="utf-8").strip()))
        items = root.find("Items")
        if items is None:
            continue
        active_set = int(items.get("activeItemSet") or 1)
        sets = items.findall("ItemSet")
        active_ids = {
            int(slot.get("itemId") or 0)
            for slot in (sets[active_set - 1].findall("Slot") if 0 < active_set <= len(sets) else ())
            if int(slot.get("itemId") or 0) > 0
        }
        for item in items.findall("Item"):
            if int(item.get("id") or 0) not in active_ids:
                continue
            raw = item.text or ""
            if "Rarity: RARE" not in raw:
                continue
            crafted = [line.removeprefix("{crafted}") for line in raw.splitlines() if line.startswith("{crafted}")]
            if not crafted:
                continue
            total += 1
            ids, unlock = _unlock_for(crafted)
            if unlock is None:
                missing += 1
                print(f"without entry: {path.stem}: craft={crafted!r}, candidate_ids={ids!r}")
                continue
            if legal(unlock, max_map_tier=max_map_tier):
                legal_count += 1
            elif unlock.get("where") == "map" and unlock.get("tier") is not None:
                key = (" / ".join(crafted), str(unlock.get("location") or ""), int(unlock["tier"]))
                tier_illegal[key] += 1
                builds[key].add(path.stem)
            for cost in unlock.get("cost") or ():
                if "Exalted Orb" in cost or "Divine Orb" in cost:
                    currency[(" / ".join(crafted), str(unlock.get("location") or ""), str(cost), unlock.get("tier"))] += 1
    print(f"crafts total={total}; legal={legal_count}; illegal tier/currency/unknown={total - legal_count - missing}; without entry={missing}")
    print("tier 11-16:")
    for key, count in sorted(tier_illegal.items(), key=lambda row: (row[0][2], row[0][0])):
        print(f"{count} builds={len(builds[key])}: craft={key[0]!r}, map={key[1]!r}, tier={key[2]}")
    print("Exalted/Divine costs:")
    for (craft, location, cost, tier), count in sorted(currency.items()):
        print(f"{count}: craft={craft!r}, map={location!r}, tier={tier}, cost={cost}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path)
    parser.add_argument("--rows", action="store_true")
    args = parser.parse_args()
    if args.rows:
        measure_rows()
    if args.run:
        measure_run(args.run)
    if not args.rows and not args.run:
        parser.error("choose --rows or --run")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
