"""Derive config lanes for a reference build and compare DPS: author's config vs
conservative vs optimistic, listing which toggles each lane enabled and why.

Run:  python scripts/config_rules_experiment.py ignite_penance_brand
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.optimizer.config_rules import derive_config  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "tuadh_329"
KEYS = ("CombinedDPS", "FullDPS", "Life", "TotalEHP")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", default="ignite_penance_brand")
    args = ap.parse_args()
    xml = decode_import_code((FIXTURES / f"{args.slug}.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id=f"config-{args.slug}") as pob:
        pob.load_xml(xml)
        author = pob.stats(KEYS)
        state = pob.read_state().get("config_state", {})
        author_on = sorted(state.get("enabled_conditions") or [])
        print(f"author config: dps={author['CombinedDPS']:,.0f} | enabled: {author_on}")
        print(f"  bandit={state.get('bandit')} pantheon={state.get('pantheon_major')}/{state.get('pantheon_minor')}")

        derived = derive_config(pob, boss="Pinnacle")
        print(f"\nPoB shows {len(derived.shown)} inputs for this build")
        print("\nconservative lane:")
        for var, val in sorted(derived.conservative.inputs.items()):
            print(f"  {var} = {val}   [{derived.conservative.reasons.get(var, '')[:110]}]")
        print("  off:", [v for v, r in derived.conservative.reasons.items() if r.startswith("off:")][:20])
        print("\noptimistic lane extra:", sorted(set(derived.optimistic.inputs) - set(derived.conservative.inputs)))

        pob.set_config(
            bandit=state.get("bandit") or "None",
            pantheon_major=state.get("pantheon_major") or "None",
            pantheon_minor=state.get("pantheon_minor") or "None",
            enemy_state={"is_boss": "Pinnacle"},
            inputs={k: v for k, v in derived.conservative.inputs.items() if k != "enemyIsBoss"},
            conditional={"inputs": {k: v for k, v in derived.optimistic.inputs.items() if k != "enemyIsBoss"}},
        )
        cons, opti = pob.calc("baseline"), pob.calc("conditional")
        print(f"\nDPS: author {author['CombinedDPS']:,.0f} | conservative {cons['CombinedDPS']:,.0f} ({cons['CombinedDPS']/author['CombinedDPS']:.0%}) "
              f"| optimistic {opti['CombinedDPS']:,.0f} ({opti['CombinedDPS']/author['CombinedDPS']:.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
