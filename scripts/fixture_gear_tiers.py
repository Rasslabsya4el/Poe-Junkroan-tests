"""Match the reference builds' rare explicit lines to PoB mod ids and report the
tier distribution (tier = rank within a mod group by level, T1 = best).

Run:  python scripts/fixture_gear_tiers.py [fixture_set]
Out:  tests/fixtures/<set>/gear_tiers.json and a summary table.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

META_PREFIXES = ("Rarity:", "Unique ID:", "Item Level:", "Quality:", "Sockets:", "LevelReq:", "Implicits:", "Armour:", "Evasion:", "Energy Shield:", "ArmourBasePercentile", "EvasionBasePercentile", "EnergyShieldBasePercentile", "Ward:", "Searing Exarch", "Eater of Worlds", "Shaper Item", "Elder Item", "Crusader Item", "Hunter Item", "Warlord Item", "Redeemer Item", "Prefix:", "Suffix:", "Crafted:", "Radius:", "Limited to:", "League:", "Source:", "Variant:", "Selected Variant:", "Has Alt Variant", "Talisman Tier:", "Corrupted", "Mirrored", "Split", "Item Class:", "Has Variant")


def parse_items(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = root.find("Items")
    equipped = {s.get("itemId") for s in items.iter("Slot") if s.get("itemId") not in (None, "0")}
    out = []
    for item in items.findall("Item"):
        if item.get("id") not in equipped:
            continue
        lines = [ln.strip() for ln in (item.text or "").splitlines() if ln.strip()]
        rarity = next((ln.split(":", 1)[1].strip().upper() for ln in lines if ln.startswith("Rarity:")), "")
        if rarity != "RARE":
            continue
        name, base = lines[1], lines[2]
        n_impl = next((int(ln.split(":")[1]) for ln in lines if ln.startswith("Implicits:")), 0)
        idx = next((i for i, ln in enumerate(lines) if ln.startswith("Implicits:")), None)
        explicit = []
        if idx is not None:
            for ln in lines[idx + 1 + n_impl:]:
                if ln.startswith(META_PREFIXES):
                    continue
                explicit.append(ln)
        out.append({"name": name, "base": base, "explicit": explicit})
    return out


def range_to_regex(template: str) -> re.Pattern:
    """'+(55-69) to maximum Life' -> regex matching '+63 to maximum Life' capturing values."""

    parts = []
    pos = 0
    for m in re.finditer(r"\(-?[\d.]+--?[\d.]+\)|-?\d+(?:\.\d+)?", template):
        parts.append(re.escape(template[pos:m.start()]))
        parts.append(r"(-?\d+(?:\.\d+)?)")
        pos = m.end()
    parts.append(re.escape(template[pos:]))
    return re.compile("^" + "".join(parts) + "$")


def template_ranges(template: str) -> list[tuple[float, float]]:
    out = []
    for m in re.finditer(r"\(-?([\d.]+)-(-?[\d.]+)\)|(-?\d+(?:\.\d+)?)", template):
        if m.group(3) is not None:
            v = float(m.group(3)); out.append((v, v))
        else:
            out.append((float(m.group(1)), float(m.group(2))))
    return out


def match_line(line: str, ladders: dict[str, list[dict]]) -> tuple[str, int, int] | None:
    """Return (group, tier, ladder_len) for the mod whose template matches the fixed line."""

    clean = re.sub(r"^(\{[^}]*\})+", "", line)
    for group, ladder in ladders.items():
        for tier, mod in enumerate(ladder, start=1):
            for tmpl in mod["lines"]:
                rx = range_to_regex(tmpl)
                m = rx.match(clean)
                if not m:
                    continue
                ranges = template_ranges(tmpl)
                vals = [float(v) for v in m.groups()]
                if len(vals) == len(ranges) and all(lo - 1e-9 <= v <= hi + 1e-9 for v, (lo, hi) in zip(vals, ranges)):
                    return group, tier, len(ladder)
    return None


def main(fixture_set: str = "tuadh_329") -> int:
    fdir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / fixture_set
    sources = json.loads((fdir / "sources.json").read_text(encoding="utf-8"))
    tier_counter: Counter = Counter()
    per_item_max_t1: list[int] = []
    unmatched: Counter = Counter()
    report = []
    with PobSession(run_id="gear-tiers") as pob:
        ladder_cache: dict[str, dict[str, list[dict]]] = {}
        for build in sources["builds"]:
            xml = decode_import_code((fdir / f"{build['slug']}.pob.txt").read_text(encoding="utf-8").strip())
            for item in parse_items(xml):
                if item["base"] not in ladder_cache:
                    try:
                        mods = pob.list_item_mods(item["base"])
                    except Exception as exc:  # unknown base
                        unmatched[f"base:{item['base']}"] += 1
                        continue
                    ladders: dict[str, list[dict]] = {}
                    for m in mods["mods"]:
                        ladders.setdefault(m["group"], []).append(m)
                    ladder_cache[item["base"]] = ladders
                ladders = ladder_cache[item["base"]]
                tiers = []
                for ln in item["explicit"]:
                    crafted = ln.startswith("{crafted}")
                    hit = match_line(ln, ladders)
                    if hit:
                        tiers.append({"line": ln, "group": hit[0], "tier": hit[1], "of": hit[2], "crafted": crafted})
                        if not crafted:
                            tier_counter[hit[1]] += 1
                    else:
                        tiers.append({"line": ln, "group": None, "tier": None, "crafted": crafted})
                        unmatched[ln[:50]] += 1
                t1 = sum(1 for t in tiers if t["tier"] == 1 and not t["crafted"])
                per_item_max_t1.append(t1)
                report.append({"build": build["slug"], "name": item["name"], "base": item["base"], "mods": tiers})
                print(f"{build['slug']:22s} {item['base']:24s} " + " ".join(f"T{t['tier']}" if t["tier"] else ("C" if t["crafted"] else "?") for t in tiers))
    total = sum(tier_counter.values())
    print("\ntier distribution (non-crafted, matched):", {f"T{k}": f"{v} ({v/total:.0%})" for k, v in sorted(tier_counter.items())})
    print("T1 mods per rare: max", max(per_item_max_t1), "median", statistics.median(per_item_max_t1), "| rares:", len(per_item_max_t1))
    print("unmatched lines:", unmatched.most_common(8))
    (fdir / "gear_tiers.json").write_text(json.dumps({"tier_counts": dict(tier_counter), "t1_per_rare": per_item_max_t1, "items": report}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "tuadh_329"))
