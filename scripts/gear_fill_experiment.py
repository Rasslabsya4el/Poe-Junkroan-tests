"""Gear filler acceptance experiment: strip every rare from a reference build, then
let the filler rebuild rares on the same bases under the rails. Compare to the
author's gear. Tree, uniques, flasks, jewels and config stay as the author had them.

Run:  python scripts/gear_fill_experiment.py stormbrand [--passes 2]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from junkroan.optimizer.gear_filler import GearFiller  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code, encode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
KEYS = ("CombinedDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist", "Str", "Dex", "Int", "ReqStr", "ReqDex", "ReqInt", "ManaUnreserved", "ManaCost")


def equipped_rares(xml_text: str) -> dict[str, tuple[str, str | None]]:
    """slot -> (base, sockets) for every equipped RARE item in the active item set."""

    root = ET.fromstring(xml_text)
    items = root.find("Items")
    active = items.get("activeItemSet") or "1"
    by_id = {}
    for item in items.findall("Item"):
        lines = [ln.strip() for ln in (item.text or "").splitlines() if ln.strip()]
        rarity = next((ln.split(":", 1)[1].strip().upper() for ln in lines if ln.startswith("Rarity:")), "")
        sockets = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("Sockets:")), None)
        by_id[item.get("id")] = (rarity, lines[2] if len(lines) > 2 else None, sockets)
    out = {}
    item_set = next((s for s in items.findall("ItemSet") if s.get("id") == active), None)
    slots = item_set.findall("Slot") if item_set is not None else items.findall("Slot")
    for slot in slots:
        name, item_id = slot.get("name"), slot.get("itemId")
        if item_id in (None, "0") or name is None or "Swap" in name or "Abyssal" in name or name.startswith("Flask"):
            continue
        rarity, base, sockets = by_id.get(item_id, ("", None, None))
        if rarity == "RARE" and base:
            out[name] = (base, sockets)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="stormbrand")
    ap.add_argument("--passes", type=int, default=1)
    args = ap.parse_args()

    xml = decode_import_code((FIXTURES / f"{args.slug}.pob.txt").read_text(encoding="utf-8").strip())
    rares = equipped_rares(xml)
    rails = Rails.load()
    with PobSession(run_id=f"gearfill-{args.slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        print(f"original: dps={original['CombinedDPS']:,.0f} life={original['Life']} ehp={original['TotalEHP']:,.0f} "
              f"res={original['FireResist']}/{original['ColdResist']}/{original['LightningResist']}/{original['ChaosResist']}")
        print(f"rares to rebuild ({len(rares)}): " + ", ".join(f"{s}={b}" for s, (b, _) in rares.items()))

        pob.equip({slot: None for slot in rares})
        stripped = pob.stats(KEYS)
        print(f"stripped: dps={stripped['CombinedDPS']:,.0f} life={stripped['Life']} ehp={stripped['TotalEHP']:,.0f} "
              f"res={stripped['FireResist']}/{stripped['ColdResist']}/{stripped['LightningResist']}")

        # Floors: the author's own defensive numbers (slightly relaxed) + legality relations from rails.
        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
            relations=rails.objective().relations,
        )
        print("objective:", objective.describe())
        filler = GearFiller(pob, objective, rails, log=print)
        t0 = time.perf_counter()
        results = filler.fill({s: b for s, (b, _) in rares.items()}, sockets_by_slot={s: k for s, (_, k) in rares.items() if k}, passes=args.passes)
        elapsed = time.perf_counter() - t0

        final = pob.stats(KEYS)
        ratio = final["CombinedDPS"] / original["CombinedDPS"]
        print(f"\nfilled: dps={final['CombinedDPS']:,.0f} ({ratio:.1%} of original) life={final['Life']} ehp={final['TotalEHP']:,.0f} "
              f"res={final['FireResist']}/{final['ColdResist']}/{final['LightningResist']}/{final['ChaosResist']} "
              f"attr {final['Str']}/{final['Dex']}/{final['Int']} req {final['ReqStr']}/{final['ReqDex']}/{final['ReqInt']} in {elapsed:.0f}s")
        print("final objective:", objective.score(final))
        out_dir = Path(__file__).resolve().parents[1] / "artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"gearfill-{args.slug}.final.pob.txt").write_text(encode_import_code(pob.export_xml()), encoding="utf-8")
        (out_dir / f"gearfill-{args.slug}.json").write_text(json.dumps({
            "slug": args.slug, "original": original, "stripped": stripped, "final": final, "ratio": ratio, "seconds": elapsed,
            "slots": [{"slot": r.slot, "base": r.base, "affixes": [f"{a.affix_type[0]} T{a.tier} {a.line}" for a in r.affixes], "steps": r.steps, "seconds": r.seconds} for r in results],
        }, indent=2), encoding="utf-8")
        print(f"saved under {out_dir} as gearfill-{args.slug}.*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
