"""#179 unit 5, MEASUREMENT ONLY: does emptying Weapon 1 (as LootGear.fill does in pass 2) drop the
Weapon 2 item, so that every trial of the emptied slot is scored without it?

Loads the delivered z329_juggernaut_boneshatter s5 build, then prints (a) stats as loaded,
(b) after equip({"Weapon 1": None}) with Weapon 2 read back, (c) the incumbent Weapon 1 as a
fast trial on the emptied slot (loot_gear.py fill_slot), (d) the same trial after the partner is
put back (restore_weapon_partner). Objective: Rails.load().objective() (the pipeline's own
per-build floors are not rebuilt, so violation is against the default rails floors).

    PYTHONPATH=<checkout with vendor/ and var/>/src python scripts/diag179_partner.py [import_code_path]
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]

from junkroan.optimizer.loot_gear import restore_weapon_partner
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession

DEFAULT = Path("C:/Coding/poe-junkroan-v2/artifacts/benchmark/20260926-0200-ziz-main3-s4/z329_juggernaut_boneshatter-s5.pob.txt")


def _equipped_raws(xml: str, slots) -> dict:
    """slot -> item text PoB wears there (None = empty); same reading as loot_gear._equipped_raws."""
    items = ET.fromstring(xml).find("Items")
    by_slot: dict = {}
    if items is not None:
        by_id = {i.get("id"): (i.text or "").strip() for i in items.findall("Item")}
        item_set = next((x for x in items.findall("ItemSet") if x.get("id") == (items.get("activeItemSet") or "1")), None)
        for slot in (item_set.findall("Slot") if item_set is not None else items.findall("Slot")):
            raw = by_id.get(slot.get("itemId") or "")
            if raw:
                by_slot[slot.get("name") or ""] = raw
    return {slot: by_slot.get(slot) for slot in slots}


def name_of(raw: str | None) -> str:
    return "(empty)" if not raw else " | ".join(raw.splitlines()[:3])


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    objective = Rails.load().objective()
    keys = list(objective.stat_keys)
    pob = PobSession(run_id="diag179_partner").__enter__()
    try:
        pob.load_import_code(path.read_text(encoding="utf-8"))
        eq = _equipped_raws(pob.export_xml(), ["Weapon 1", "Weapon 2"])
        w1, w2 = eq["Weapon 1"], eq["Weapon 2"]
        print("Weapon 1:", name_of(w1))
        print("Weapon 2:", name_of(w2))
        print("objective:", objective.describe())

        def show(label: str, stats: dict) -> None:
            s = objective.score(stats)
            viol = {k: round(v, 3) for k, v in objective.violations(stats).items() if v}
            print(f"({label}) CombinedDPS {s.value:,.0f} viol {s.violation:.3f} Life {stats.get('Life')} {viol}")

        show("a loaded", pob.stats(keys))
        pob.equip({"Weapon 1": None})
        after = _equipped_raws(pob.export_xml(), ["Weapon 1", "Weapon 2"])
        print("(b) after emptying Weapon 1: Weapon 1:", name_of(after["Weapon 1"]), "| Weapon 2:", name_of(after["Weapon 2"]),
              "| Weapon 2 unchanged:", after["Weapon 2"] == w2)
        show("b emptied", pob.stats(keys))
        out = pob.trial_stats([{"item": {"slot": "Weapon 1", "raw": w1}}], keys, mode="fast")[0]
        show("c incumbent trial, partner as left by the emptying", out.get("stats") or {})
        restore_weapon_partner(pob, {"Weapon 2": w2} if w2 else {}, "Weapon 1")
        back = _equipped_raws(pob.export_xml(), ["Weapon 2"])
        print("    Weapon 2 after restore:", name_of(back["Weapon 2"]), "| equals loaded:", back["Weapon 2"] == w2)
        out = pob.trial_stats([{"item": {"slot": "Weapon 1", "raw": w1}}], keys, mode="fast")[0]
        show("d incumbent trial, partner restored", out.get("stats") or {})
    finally:
        pob.close()


if __name__ == "__main__":
    main()
