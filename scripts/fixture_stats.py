"""Load every reference build under tests/fixtures/<set>/ into headless PoB and dump its stats.

Run:  python scripts/fixture_stats.py tuadh_329
      python scripts/fixture_stats.py zizaran_329/early   (the second reference set: the early-game
      loadout of each Zizaran / Maxroll league starter, cut out by scripts/extract_loadout.py)
Out:  tests/fixtures/<set>/stats.json  plus a summary table on stdout.
The set is any folder under tests/fixtures/ holding a sources.json and its <slug>.pob.txt files.

Used to derive realistic rails (what a strong day-1 build actually has) and as
the reference numbers for optimizer acceptance tests.
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

STATS = (
    "Life", "EnergyShield", "Mana", "TotalEHP", "FullDPS", "CombinedDPS", "TotalDPS", "TotalDotDPS",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "Armour", "Evasion", "SpellSuppressionChance", "BlockChance", "EffectiveSpellSuppressionChance",
    "Str", "Dex", "Int", "Speed", "HitChance", "CritChance",
)


def item_summary(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    items = root.find("Items")
    equipped_ids = {s.get("itemId") for s in (items.iter("Slot") if items is not None else []) if s.get("itemId") not in (None, "0")}
    rows = []
    for item in (items.findall("Item") if items is not None else []):
        if item.get("id") not in equipped_ids:
            continue
        lines = [ln.strip() for ln in (item.text or "").splitlines() if ln.strip()]
        rarity = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Rarity:")), "?")
        # explicit mods = lines after the "Implicits: N" marker (+N implicit lines), excluding metadata
        expl = []
        if any(ln.startswith("Implicits:") for ln in lines):
            idx = next(i for i, ln in enumerate(lines) if ln.startswith("Implicits:"))
            n_impl = int(lines[idx].split(":")[1])
            expl = [ln for ln in lines[idx + 1 + n_impl:] if not re.match(r"^(Sockets|LevelReq|Quality|Item Level|Unique ID|Selected Variant|Has Alt Variant|Prefix|Suffix|Armour|Evasion|Energy Shield|Implicits|Crafted|League|Source|Radius|Limited to|Variant|Ward)\b", ln)]
        rows.append({"rarity": rarity, "base": lines[2] if len(lines) > 2 else lines[-1], "explicit_count": len(expl)})
    uniques = [r for r in rows if r["rarity"].upper() == "UNIQUE"]
    rares = [r for r in rows if r["rarity"].upper() == "RARE"]
    return {
        "equipped": len(rows),
        "uniques": len(uniques),
        "rares": len(rares),
        "rare_explicit_counts": [r["explicit_count"] for r in rares],
        "unique_names": [r["base"] for r in uniques],
    }


def tree_summary(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    spec = root.find("Tree/Spec")
    nodes = [n for n in (spec.get("nodes") or "").split(",") if n] if spec is not None else []
    return {"tree_version": spec.get("treeVersion") if spec is not None else None, "allocated_nodes": len(nodes)}


def main(fixture_set: str) -> int:
    fdir = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / fixture_set
    sources = json.loads((fdir / "sources.json").read_text(encoding="utf-8"))
    results = []
    with PobSession(run_id=f"fixtures-{fixture_set}") as pob:
        for build in sources["builds"]:
            code = (fdir / f"{build['slug']}.pob.txt").read_text(encoding="utf-8").strip()
            xml = decode_import_code(code)
            pob.load_xml(xml)
            stats = pob.calc()
            row = {
                "slug": build["slug"],
                "level": build["level"],
                "class": f"{build['class']}/{build['ascendancy']}",
                **{k: stats.get(k) for k in STATS},
                "tree": tree_summary(xml),
                "items": item_summary(xml),
            }
            results.append(row)
            print(f"{row['slug']:24s} L{row['level']} {row['class']:22s} life={row['Life']:>6} ehp={row['TotalEHP']:>8.0f} "
                  f"full={row['FullDPS']:>9.0f} comb={row['CombinedDPS'] or 0:>9.0f} tot={row['TotalDPS'] or 0:>9.0f} dot={row['TotalDotDPS'] or 0:>8.0f} res={row['FireResist']}/{row['ColdResist']}/{row['LightningResist']}/{row['ChaosResist']} "
                  f"nodes={row['tree']['allocated_nodes']} uniq={row['items']['uniques']} rares={row['items']['rares']} mods/rare={row['items']['rare_explicit_counts']}")
    (fdir / "stats.json").write_text(json.dumps(results, indent=2), encoding="utf-8", newline="\n")

    def med(key):
        vals = [r[key] for r in results if isinstance(r.get(key), (int, float))]
        return statistics.median(vals) if vals else None

    print("\nmedians: level", med("level"), "life", med("Life"), "ehp", med("TotalEHP"), "dps", med("FullDPS"),
          "chaos", med("ChaosResist"), "nodes", statistics.median(r["tree"]["allocated_nodes"] for r in results),
          "uniques", statistics.median(r["items"]["uniques"] for r in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "tuadh_329"))
