"""Is the weapon our weak slot? On every reference build, replace the author's
rare weapon(s) alone (tree, other gear, config untouched) with:
  loot N=200 (the rails), loot N=1000, and the greedy affix ceiling under the
  rails' tier caps (<=1 T1, <=2 T2, <=T8, 6 mods, one bench craft).
Report CombinedDPS as a share of the author's, per weapon slot.

Run:  python scripts/weapon_experiment.py [slug ...] [--n 200 1000]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from gear_fill_experiment import KEYS, equipped_rares  # noqa: E402
from junkroan.optimizer.gear_filler import GearFiller  # noqa: E402
from junkroan.optimizer.loot_gear import LootGear  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
WEAPON_SLOTS = ("Weapon 1", "Weapon 2")


def run(slug: str, *, ns: list[int], seed: int = 1, log=print) -> list[dict]:
    xml = decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip())
    rares = equipped_rares(xml)
    weapons = {s: rares[s] for s in WEAPON_SLOTS if s in rares}
    rails = Rails.load()
    rows: list[dict] = []
    if not weapons:
        return rows
    with PobSession(run_id=f"weapon-{slug}") as pob:
        pob.load_xml(xml)
        author = pob.stats(KEYS)
        objective = Objective(maximize="CombinedDPS", floors={"Life": author["Life"] * 0.97, "TotalEHP": author["TotalEHP"] * 0.95}, relations=rails.objective().relations)
        author_xml = pob.export_xml()
        for slot, (base, sockets) in weapons.items():
            row = {"slug": slug, "slot": slot, "base": base, "author": author["CombinedDPS"]}
            for n in ns:
                pob.load_xml(author_xml)
                t0 = time.perf_counter()
                loot = LootGear(pob, objective, rails, log=lambda _m: None)
                loot.fill_slot(slot, base, n=n, sockets=sockets, seed=seed)
                s = pob.stats(KEYS)
                row[f"loot{n}"] = s["CombinedDPS"] / author["CombinedDPS"]
                row[f"loot{n}_viol"] = objective.score(s).violation
                row[f"loot{n}_s"] = time.perf_counter() - t0
            pob.load_xml(author_xml)
            pob.equip({slot: None})
            t0 = time.perf_counter()
            filler = GearFiller(pob, objective, rails, log=lambda _m: None)
            res = filler.fill_slot(slot, base, sockets=sockets, keep_equipped=False)
            s = pob.stats(KEYS)
            row["ceiling"] = s["CombinedDPS"] / author["CombinedDPS"]
            row["ceiling_viol"] = objective.score(s).violation
            row["ceiling_s"] = time.perf_counter() - t0
            row["ceiling_affixes"] = [f"T{a.tier} {a.line}" for a in res.affixes]
            rows.append(row)
            log(f"{slug:24s} {slot:9s} {base:22s} author {row['author']:>10,.0f}  " + "  ".join(f"N={n} {row[f'loot{n}']:.0%}" for n in ns) + f"  ceiling {row['ceiling']:.0%} ({row['ceiling_s']:.0f}s)")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", default=sorted(p.stem.replace(".pob", "") for p in FIXTURES.glob("*.pob.txt")))
    ap.add_argument("--n", type=int, nargs="+", default=[200, 1000])
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rows: list[dict] = []
    for slug in args.slugs:
        rows.extend(run(slug, ns=args.n, seed=args.seed))
    out = Path(__file__).resolve().parents[1] / "artifacts" / "weapon_experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\n{len(rows)} weapon slots; written {out}")
    for key in [f"loot{n}" for n in args.n] + ["ceiling"]:
        vals = sorted(r[key] for r in rows)
        if vals:
            print(f"  {key:10s} median {vals[len(vals) // 2]:.0%}  min {vals[0]:.0%}  max {vals[-1]:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
