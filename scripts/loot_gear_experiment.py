"""Day-1 loot gear on a reference build: strip its rares, rebuild each slot as
best-of-N random rares (PoB spawn weights) plus one bench craft, compare.

Run:  python scripts/loot_gear_experiment.py smite [--n 300] [--passes 2] [--no-bench]
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
from junkroan.optimizer.loot_gear import LootGear  # noqa: E402
from junkroan.optimizer.objective import Objective  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code, encode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"


def run(slug: str, *, n: int | None, passes: int, bench: bool, seed: int = 1, log=print) -> dict:
    xml = decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip())
    rares = equipped_rares(xml)
    rails = Rails.load()
    with PobSession(run_id=f"loot-{slug}") as pob:
        pob.load_xml(xml)
        original = pob.stats(KEYS)
        objective = Objective(
            maximize="CombinedDPS",
            floors={"Life": original["Life"] * 0.97, "TotalEHP": original["TotalEHP"] * 0.95},
            relations=rails.objective().relations,
        )
        pob.equip({slot: None for slot in rares})
        t0 = time.perf_counter()
        gear = LootGear(pob, objective, rails, log=log)
        results = gear.fill({s: b for s, (b, _) in rares.items()}, sockets_by_slot={s: k for s, (_, k) in rares.items() if k}, passes=passes, n=n, bench=bench, seed=seed)
        elapsed = time.perf_counter() - t0
        final = pob.stats(KEYS)
        code = encode_import_code(pob.export_xml())
    score = objective.score(final)
    return {
        "slug": slug, "n": n or rails.gear.loot_best_of_n, "passes": passes, "bench": bench,
        "original": original, "final": final, "ratio": final["CombinedDPS"] / original["CombinedDPS"],
        "violation": score.violation, "seconds": elapsed, "import_code": code,
        "slots": [{"slot": r.slot, "base": r.base, "mod_ids": r.mod_ids, "bench": r.bench_line} for r in results],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="smite")
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--no-bench", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    out = run(args.slug, n=args.n, passes=args.passes, bench=not args.no_bench, seed=args.seed)
    f, o = out["final"], out["original"]
    print(f"\n{args.slug}: dps={f['CombinedDPS']:,.0f} ({out['ratio']:.1%} of original) life={f['Life']} ehp={f['TotalEHP']:,.0f} "
          f"res={f['FireResist']}/{f['ColdResist']}/{f['LightningResist']} viol={out['violation']:.3f} in {out['seconds']:.0f}s")
    out_dir = Path(__file__).resolve().parents[1] / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"loot-{args.slug}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (out_dir / f"loot-{args.slug}.final.pob.txt").write_text(out["import_code"], encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
