"""Calibrate a gear "findability" measure on reference rares vs filler output.

For each explicit (non-crafted) mod on a rare, p = spawn weight of that mod id
divided by the total weight of all mods of the same affix type legal on the base
at the item's level (PoB's own weights). Item cost = sum(-ln p) over its mods:
how surprising this exact rare is. Compare the reference rares' distribution to
the filler's items.

Run:  python scripts/gear_rarity_calibration.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fixture_gear_tiers import match_line, parse_items  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"


def item_costs(pob: PobSession, xml: str, cache: dict) -> list[dict]:
    out = []
    for item in parse_items(xml):
        base = item["base"]
        if base not in cache:
            try:
                mods = pob.list_item_mods(base)
            except Exception:
                continue
            ladders: dict[str, list[dict]] = {}
            for m in mods["mods"]:
                ladders.setdefault(m["group"], []).append(m)
            cache[base] = (mods["mods"], ladders)
        mods, ladders = cache[base]
        total_by_type = {}
        for m in mods:
            total_by_type[m["type"]] = total_by_type.get(m["type"], 0) + m["weight"]
        cost, n, tiers = 0.0, 0, []
        for ln in item["explicit"]:
            if ln.startswith("{crafted}"):
                continue
            hit = match_line(ln, ladders)
            if not hit:
                continue
            group, tier, _ = hit
            mod = ladders[group][tier - 1]
            p = mod["weight"] / total_by_type[mod["type"]]
            cost += -math.log(p)
            n += 1
            tiers.append(tier)
        out.append({"name": item["name"], "base": base, "mods": n, "cost": cost, "cost_per_mod": cost / n if n else 0.0, "tiers": tiers})
    return out


def main() -> int:
    sources = json.loads((FIXTURES / "sources.json").read_text(encoding="utf-8"))
    cache: dict = {}
    ref: list[dict] = []
    with PobSession(run_id="rarity-calib") as pob:
        for build in sources["builds"]:
            xml = decode_import_code((FIXTURES / f"{build['slug']}.pob.txt").read_text(encoding="utf-8").strip())
            ref.extend(item_costs(pob, xml, cache))
        filler_path = ARTIFACTS / "gearfill-stormbrand.final.pob.txt"
        filled = item_costs(pob, decode_import_code(filler_path.read_text(encoding="utf-8").strip()), cache) if filler_path.is_file() else []

    def summary(rows: list[dict], label: str) -> None:
        costs = [r["cost"] for r in rows if r["mods"]]
        per = [r["cost_per_mod"] for r in rows if r["mods"]]
        q = statistics.quantiles(costs, n=4) if len(costs) >= 4 else costs
        print(f"{label}: items={len(costs)} cost/item p25={q[0]:.1f} med={q[1]:.1f} p75={q[2]:.1f} max={max(costs):.1f} | cost/mod med={statistics.median(per):.2f}")

    summary(ref, "reference rares")
    if filled:
        summary(filled, "filler items  ")
        for r in filled:
            print(f"   {r['base']:22s} mods={r['mods']} cost={r['cost']:.1f} tiers={r['tiers']}")
    (FIXTURES / "gear_rarity.json").write_text(json.dumps({"reference": ref, "filler": filled}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
