"""#157 (diagnosis): capture one real state for the fixture of the xfail test.

Loads a finished benchmark build and reads the PoB stats every constraint of that
run's objective needs, so a test can replay `_record`'s objective (pipeline.py:241)
and the construction tree's objective (pipeline.py:378, tree_optimizer.py:777) on
the same numbers without opening PoB.

One PobSession, one `stats` read (well under a minute). Read-only: nothing in the
optimizer is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from junkroan.pob.session import PobSession  # noqa: E402

# The objective of `z327_assassin_poison_spark` in run 20260926-0200-ziz-main3-s4,
# copied from its own log line 8 ("objective maximize CombinedDPS subject to ...").
# The two constraints on stats PoB does not output (MoMUnreservedShare, and the
# NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond relation, plus the ramp pair
# RampBudget >= RampStages) are left out: they are Python-derived (objective.derived),
# and this fixture holds PoB readings only.
FLOORS = {
    "Life": 3840.0,
    "EffectiveMovementSpeedMod": 1.164,
    "ElementalOverloadUptime": 0.9,
    "TotalEHP": 9485.37,
    "PhysicalMaximumHitTaken": 6733.6,
    "FireMaximumHitTaken": 4666.4,
    "ColdMaximumHitTaken": 5854.85,
    "LightningMaximumHitTaken": 4666.4,
}
RELATIONS = [
    ["FireResist", "FireResistMax", 1.0],
    ["ColdResist", "ColdResistMax", 1.0],
    ["LightningResist", "LightningResistMax", 1.0],
    ["Str", "ReqStr", 1.0],
    ["Dex", "ReqDex", 1.0],
    ["Int", "ReqInt", 1.0],
    ["ManaCostPool", "ManaCost", 1.0],
    ["LifeUnreserved", "LifeCost", 1.0],
    ["ManaRegenRecovery+ManaLeechGainRate+ManaRecoup", "ManaPerSecondCost", 0.85],
    ["LifeRegenRecovery+LifeLeechGainRate+LifeRecoup", "LifePerSecondCost", 0.85],
    ["EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts", "ESPerSecondCost", 0.85],
]


def stat_keys() -> list[str]:
    keys = ["CombinedDPS", *FLOORS]
    for a, b, _f in RELATIONS:
        keys.extend(a.split("+"))
        keys.append(b)
    return list(dict.fromkeys(keys))


def main() -> int:
    source = Path(sys.argv[1])
    out = Path(sys.argv[2])
    code = source.read_text(encoding="utf-8").strip()
    with PobSession(run_id="diag-157") as pob:
        pob.load_import_code(code)
        stats = pob.stats(stat_keys())
    clean = {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in stats.items()}
    # A constraint whose stats PoB does not output is derived in Python by the pipeline
    # (optimizer/ramp.py, self_cost.py, castability.py, keystone_floors.py); this fixture
    # holds PoB readings only, so those constraints are dropped and named.
    dropped = [k for k in FLOORS if k not in clean]
    relations = [r for r in RELATIONS if all(n in clean for n in r[0].split("+") + [r[1]])]
    dropped += [f"{r[0]} >= {r[2]:g}*{r[1]}" for r in RELATIONS if r not in relations]
    payload = {
        "source": f"artifacts/benchmark/{source.parent.name}/{source.name}",
        "note": "the delivered build of one benchmark row; its recorded final violation is 0.1924 "
                "and its only audit floor finding is EffectiveMovementSpeedMod = 0.940 < 1.164",
        "maximize": "CombinedDPS",
        "floors": {k: v for k, v in FLOORS.items() if k in clean},
        "relations": relations,
        "excluded": dropped,
        "stats": clean,
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: payload["stats"].get(k) for k in ("CombinedDPS", "EffectiveMovementSpeedMod", "ManaPerSecondCost", "LifePerSecondCost", "ESPerSecondCost")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
