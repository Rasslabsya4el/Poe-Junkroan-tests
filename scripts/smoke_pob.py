"""Smoke test: boot pinned PoB headless, build a tiny Fireball Witch, read stats.

Run:  python scripts/smoke_pob.py
Pass: prints Life / FullDPS / resists and an import code that PoB re-imports.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession, encode_import_code  # noqa: E402

BOOTS = """Rarity: Rare
Smoke Boots
Titan Greaves
Item Level: 70
Quality: 0
Sockets: R-R-R-R
LevelReq: 68
Implicits: 0
+80 to maximum Life
30% increased Movement Speed
+35% to Fire Resistance
"""


def main() -> int:
    t0 = time.perf_counter()
    with PobSession(run_id="smoke") as pob:
        t_boot = time.perf_counter() - t0
        pob.set_identity(level=90)
        pob.set_tree(class_id="Witch", ascendancy_id="Elementalist")
        pob.set_skills(main_link=["Fireball", "Spell Echo", "Controlled Destruction", "Elemental Focus", "Fire Penetration"])
        pob.set_items({"Boots": BOOTS})
        pob.set_config(enemy_state={"is_boss": "Pinnacle"})
        t1 = time.perf_counter()
        stats = pob.calc()
        t_calc = time.perf_counter() - t1
        keep = ("Life", "Mana", "FullDPS", "TotalDPS", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "ChaosResist", "Speed", "Str", "Dex", "Int")
        print(json.dumps({k: stats.get(k) for k in keep}, indent=2))
        print(f"stat keys available: {len(stats)}")
        xml = pob.export_xml()
        code = encode_import_code(xml)
        verify = pob.verify_import_code(code)
        print(f"import code length: {len(code)}; verify status: {verify.get('status')!r}")
        print(f"boot {t_boot:.2f}s, one calc {t_calc:.3f}s")
        print(f"run artifacts: {pob.run_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
