"""Census Zizaran's, Tuadh's and our template rares by explicit affix lines.

For each PoB import code the script reads the ACTIVE item set and the rare items
in the worn slots (Weapon 1/2, Helmet, Body Armour, Gloves, Boots, Belt, Amulet,
Ring 1/2; uniques, magic items, flasks and jewels are skipped). An explicit affix
is a `Prefix:` / `Suffix:` line carrying a mod id; a crafted line is a text line
starting with `{crafted}`. `Prefix: None` / `Suffix: None` mark an empty affix.

Run: python scripts/item_lines_census.py
"""

from __future__ import annotations

import glob
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob.session import decode_import_code  # noqa: E402

ZIZARAN_GLOB = str(ROOT / "tests" / "fixtures" / "zizaran_*" / "early" / "*.pob.txt")
TUADH_GLOB = str(ROOT / "tests" / "fixtures" / "tuadh_329" / "*.pob.txt")
OURS_DIR = ROOT / "artifacts" / "benchmark" / "20260924-0231-ziz-tpl-main3-lap"
OURS_GLOB = str(OURS_DIR / "*-s1.pob.txt")

SLOT_CLASS = {
    "Weapon 1": "weapon",
    "Weapon 2": "quiver+shield",
    "Body Armour": "body",
    "Helmet": "helmet",
    "Gloves": "gloves",
    "Boots": "boots",
    "Belt": "belt",
    "Amulet": "amulet",
    "Ring 1": "ring",
    "Ring 2": "ring",
}
CLASS_ORDER = ("weapon", "quiver+shield", "body", "helmet", "gloves", "boots", "belt", "amulet", "ring")
TABLE_C_SLUGS = ("z329_champion_explosive_arrow", "z329_elementalist_winter_orb", "z325_gladiator_spectral_shield_throw")


def _mod_id(value: str) -> str | None:
    """The mod id on a prefix/suffix line, without its leading `{...}` tags."""

    value = value.strip()
    if value.lower() == "none":
        return None
    value = re.sub(r"^(?:\{[^}]*\})+", "", value).strip()
    return value or None


def rare_lines(item_text: str) -> dict:
    """Explicit affixes on a rare's item text: prefix ids, suffix ids, crafted lines.

    `Prefix: None` / `Suffix: None` are empty affixes and contribute nothing. A
    crafted line is a text line starting with `{crafted}` (the repo's marker; see
    `scripts/fixture_weapon_lines.py:line_tier`).
    """

    prefixes: list[str] = []
    suffixes: list[str] = []
    crafted = 0
    for raw in item_text.splitlines():
        line = raw.strip()
        if line.startswith("Prefix:"):
            mod_id = _mod_id(line.split(":", 1)[1])
            if mod_id:
                prefixes.append(mod_id)
        elif line.startswith("Suffix:"):
            mod_id = _mod_id(line.split(":", 1)[1])
            if mod_id:
                suffixes.append(mod_id)
        elif line.startswith("{crafted}"):
            crafted += 1
    return {"prefixes": prefixes, "suffixes": suffixes, "crafted": crafted}


def _is_rare(item_text: str) -> bool:
    return any(line.strip() == "Rarity: RARE" for line in item_text.splitlines())


def items_by_id(xml: str) -> dict[str, str]:
    return {match.group(1): match.group(2) for match in re.finditer(r'<Item id="(\d+)">(.*?)</Item>', xml, re.S)}


def active_slot_items(xml: str) -> dict[str, str]:
    """The worn rare text per slot of the ACTIVE item set, keyed by slot name."""

    items_tag = re.search(r"<Items\b[^>]*>", xml)
    if not items_tag:
        return {}
    active = re.search(r'activeItemSet="(\d+)"', items_tag.group(0))
    if not active:
        return {}
    item_set = re.search(r'<ItemSet id="%s"[^>]*>(.*?)</ItemSet>' % re.escape(active.group(1)), xml, re.S)
    if not item_set:
        return {}
    items = items_by_id(xml)
    worn: dict[str, str] = {}
    for tag in re.findall(r"<Slot\b[^>]*?/>", item_set.group(1)):
        name = re.search(r'name="([^"]*)"', tag)
        item_id = re.search(r'itemId="(\d+)"', tag)
        if not name or not item_id:
            continue
        slot = name.group(1)
        if slot not in SLOT_CLASS or item_id.group(1) == "0":
            continue
        text = items.get(item_id.group(1))
        if text is not None and _is_rare(text):
            worn[slot] = text
    return worn


def decode_file(path: Path) -> str | None:
    """A file's PoB XML, or None when it is not a decodable import code."""

    try:
        return decode_import_code(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def collect(patterns: Iterable[str]) -> list[dict]:
    items: list[dict] = []
    for pattern in patterns:
        for name in sorted(glob.glob(pattern)):
            xml = decode_file(Path(name))
            if xml is None:
                continue
            for slot, text in active_slot_items(xml).items():
                lines = rare_lines(text)
                items.append({"slot": slot, "class": SLOT_CLASS[slot], **lines})
    return items


def _median(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _num(value: float | None) -> str:
    return "-" if value is None else f"{value:g}"


def _families(item: Mapping[str, object]) -> list[str]:
    ids = list(item["prefixes"]) + list(item["suffixes"])  # type: ignore[arg-type]
    return [re.sub(r"\d+$", "", mod_id) for mod_id in ids]


def _affix_cell(lines: Mapping[str, object] | None) -> str:
    if lines is None:
        return "-"
    parts: list[str] = []
    if lines["prefixes"]:
        parts.append("P:" + ",".join(lines["prefixes"]))  # type: ignore[arg-type]
    if lines["suffixes"]:
        parts.append("S:" + ",".join(lines["suffixes"]))  # type: ignore[arg-type]
    if lines["crafted"]:
        parts.append(f"crafted:{lines['crafted']}")
    return " ".join(parts) or "-"


def table_a(items_by_source: Mapping[str, list[dict]]) -> list[str]:
    lines = ["Table A: worn rare items by source and slot class", "",
             "| source | slot class | items | median explicit | median prefixes | median suffixes | crafted share |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for source, items in items_by_source.items():
        for slot_class in CLASS_ORDER:
            group = [item for item in items if item["class"] == slot_class]
            if not group:
                continue
            explicit = [len(item["prefixes"]) + len(item["suffixes"]) + (1 if item["crafted"] else 0) for item in group]
            crafted_share = sum(1 for item in group if item["crafted"]) / len(group)
            lines.append(
                f"| {source} | {slot_class} | {len(group)} | {_num(_median([float(v) for v in explicit]))} | "
                f"{_num(_median([float(len(item['prefixes'])) for item in group]))} | "
                f"{_num(_median([float(len(item['suffixes'])) for item in group]))} | {crafted_share:.0%} |"
            )
    return lines


def table_b(items_by_source: Mapping[str, list[dict]]) -> list[str]:
    lines = ["", "Table B: 10 most frequent mod-id families per source", "",
             "| source | family | count |", "|---|---|---:|"]
    for source, items in items_by_source.items():
        counts: dict[str, int] = defaultdict(int)
        for item in items:
            for family in _families(item):
                counts[family] += 1
        if not counts:
            lines.append(f"| {source} | (no Prefix/Suffix mod ids) | 0 |")
            continue
        for family, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:10]:
            lines.append(f"| {source} | {family} | {count} |")
    return lines


def table_c() -> list[str]:
    lines = ["", "Table C: affix ids per worn slot, Zizaran author vs our template (seed 1)", "",
             "| reference | slot | Zizaran item affix ids | our template item affix ids |", "|---|---|---|---|"]
    for slug in TABLE_C_SLUGS:
        match = re.match(r"z(\d+)_(.+)$", slug)
        ziz_path = ROOT / "tests" / "fixtures" / f"zizaran_{match.group(1)}" / "early" / f"{match.group(2)}.pob.txt"
        our_path = OURS_DIR / f"{slug}-s1.pob.txt"
        ziz_xml = decode_file(ziz_path)
        our_xml = decode_file(our_path)
        ziz_slots = active_slot_items(ziz_xml) if ziz_xml else {}
        our_slots = active_slot_items(our_xml) if our_xml else {}
        for slot in SLOT_CLASS:
            ziz = rare_lines(ziz_slots[slot]) if slot in ziz_slots else None
            our = rare_lines(our_slots[slot]) if slot in our_slots else None
            lines.append(f"| {slug} | {slot} | {_affix_cell(ziz)} | {_affix_cell(our)} |")
    return lines


def main() -> int:
    items_by_source = {
        "Zizaran": collect([ZIZARAN_GLOB]),
        "Tuadh": collect([TUADH_GLOB]),
        "ours": collect([OURS_GLOB]),
    }
    for source, items in items_by_source.items():
        print(f"{source}: {len(items)} worn rare items")
    for line in table_a(items_by_source) + table_b(items_by_source) + table_c():
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())