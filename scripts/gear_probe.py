"""Probe the gear primitives: list legal mods for a base, craft a rare through PoB,
equip it, and check that a fast item trial equals a real equip.

Run: python scripts/gear_probe.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
KEYS = ("CombinedDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist")


def main() -> int:
    xml = decode_import_code((FIXTURES / "stormbrand.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="gear-probe") as pob:
        pob.load_xml(xml)
        base = pob.stats(KEYS)
        print("base:", {k: round(v) for k, v in base.items()})

        mods = pob.list_item_mods("Titan Greaves", ilvl=70)
        print(f"Titan Greaves @70: {len(mods['mods'])} legal mods, base tags {mods['base_tags']}, implicit {mods.get('implicit')!r}")
        by_group: dict[str, list] = {}
        for m in mods["mods"]:
            by_group.setdefault(m["group"], []).append(m)
        for g in ("IncreasedLife", "FireResistance", "MovementVelocity"):
            ladder = by_group.get(g, [])
            print(f"  {g}: " + "; ".join(f"T{i+1} {m['mod_id']} L{m['level']} w{m['weight']} {m['lines'][0]}" for i, m in enumerate(ladder[:3])))

        life = by_group["IncreasedLife"][0]["mod_id"]
        fire = by_group["FireResistance"][0]["mod_id"]
        cold = by_group["ColdResistance"][0]["mod_id"]
        ms = by_group["MovementVelocity"][0]["mod_id"]
        crafted = pob.craft_rare("Titan Greaves", prefixes=[life, ms], suffixes=[fire, {"mod_id": cold, "range": 1.0}], ilvl=70, quality=20, sockets="R-R-R-R")
        print("crafted:", crafted["name"], "| level req", crafted["level_req"], "| problems", crafted["problems"], "| unsupported", crafted["unsupported_lines"])
        print("  lines:", crafted["explicit_lines"])
        print("  raw:\n" + "\n".join("    " + l for l in crafted["raw"].splitlines()))

        bad = pob.craft_rare("Titan Greaves", prefixes=[life, "IncreasedLife0"], suffixes=[fire], ilvl=60)
        print("legality check on a bad request:", bad["problems"])

        t0 = time.perf_counter()
        trial = pob.trial_stats([{"item": {"slot": "Boots", "raw": crafted["raw"]}}], KEYS, mode="fast")[0]
        t_trial = time.perf_counter() - t0
        print("equip:", pob.equip({"Boots": crafted["raw"]}))
        real = pob.stats(KEYS)
        print(f"item trial ({t_trial*1000:.0f} ms):", {k: round(v) for k, v in trial["stats"].items()})
        print("real equip:            ", {k: round(v) for k, v in real.items()})
        state = pob.read_state()
        boots = next((s for s in state.get("gear_slots", {}).get("slots", {}).items() if s[0] == "Boots"), None)
        print("readback boots present:", boots is not None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
