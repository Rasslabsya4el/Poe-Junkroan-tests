"""Loot-simulation gear model: for each rare slot, roll N random rares on the
author's base with PoB spawn weights, keep the best one for the build (item
trials), equip it, move on. Compare the resulting build to the author's for
several N. The N that reproduces the author's gear quality is the "how much
loot did a day-1 player see" knob.

Run:  python scripts/gear_bestofn.py stormbrand --n 50 200 1000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from gear_fill_experiment import KEYS, equipped_rares  # noqa: E402
from junkroan.optimizer.loot_gear import ordered_slots  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"


def best_of_n(pob: PobSession, objective: Objective, slot: str, base: str, n: int, *, sockets: str | None, seed: int) -> tuple[dict, object]:
    keys = objective.stat_keys
    current = objective.score(pob.stats(keys))
    rolled = pob.random_rares(base, n=n, ilvl=70, sockets=sockets, seed=seed)
    outcomes = pob.trial_stats([{"item": {"slot": slot, "raw": r["raw"]}} for r in rolled], keys, mode="fast")
    best = None
    for r, o in zip(rolled, outcomes):
        if not o.get("ok") or not o.get("stats"):
            continue
        s = objective.score(o["stats"])
        key = (current.violation - s.violation, s.value) if not current.feasible else (1.0 if s.feasible else -s.violation, s.value)
        if best is None or key > best[0]:
            best = (key, r, s)
    return best[1], best[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="stormbrand")
    ap.add_argument("--n", type=int, nargs="+", default=[50, 200, 1000])
    ap.add_argument("--passes", type=int, default=2)
    args = ap.parse_args()

    xml = decode_import_code((FIXTURES / f"{args.slug}.pob.txt").read_text(encoding="utf-8").strip())
    rares = equipped_rares(xml)
    rails = Rails.load()
    with PobSession(run_id=f"bestofn-{args.slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
            relations=rails.objective().relations,
        )
        print(f"original dps={original['CombinedDPS']:,.0f} life={original['Life']} | {len(rares)} rare slots | objective: {objective.describe()}")
        order = ordered_slots(rares)
        for n in args.n:
            pob.load_xml(xml)
            pob.equip({slot: None for slot in rares})
            t0 = time.perf_counter()
            for p in range(args.passes):
                for i, slot in enumerate(order):
                    base, sockets = rares[slot]
                    if p > 0:
                        pob.equip({slot: None})
                    item, score = best_of_n(pob, objective, slot, base, n, sockets=sockets, seed=1000 * n + 17 * i + p)
                    pob.equip({slot: item["raw"]})
            final = pob.stats(KEYS)
            sc = objective.score(final)
            print(f"N={n:5d}: dps={final['CombinedDPS']:,.0f} ({final['CombinedDPS']/original['CombinedDPS']:.1%}) life={final['Life']} "
                  f"ehp={final['TotalEHP']:,.0f} res={final['FireResist']}/{final['ColdResist']}/{final['LightningResist']} "
                  f"viol={sc.violation:.3f} in {time.perf_counter()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
