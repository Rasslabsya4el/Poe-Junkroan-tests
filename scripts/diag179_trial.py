"""#179 unit 6: does the incumbent weapon read the same as a TRIAL as it does equipped?

Runs z329_juggernaut_boneshatter seed 5 (ziz, loot gear) up to the stage `gear pass 2 (with tree)`.
At the first LootGear.fill with passes == 2, right after internal pass 1 and before pass 2 empties
`Weapon 1` (pob.equip({"Weapon 1": None})), it reads: a) stats as equipped, b) fast trial of the
incumbent raw, c) full trial, d) trial on the emptied slot, e) re-equip and stats. Then it stops.
No product edits: LootGear.fill and the instance's pob.equip are wrapped here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

SLUG = "z329_juggernaut_boneshatter"
SEED = 5
SLOT = "Weapon 1"


class Stop(Exception):
    pass


def show(label, stats, objective):
    v = objective.violations(stats)
    sc = objective.score(stats)
    print(f"{label}: CombinedDPS={stats.get('CombinedDPS')} value({objective.maximize})={sc.value:,.0f} violation={sc.violation:.4f}")
    for k, x in v.items():
        print(f"    violated {k}: {x:.4f}  (stats: { {s: stats.get(s) for s in k.replace('<=', '').split('>=')} })")


def diagnose(loot, objective):
    pob = loot.pob
    keys = objective.stat_keys
    raw = loot.current_raw[SLOT]
    print("raw Quality line:", [ln for ln in raw.splitlines() if ln.startswith("Quality")])
    print("raw anoint/eldritch lines:", [ln for ln in raw.splitlines() if any(w in ln for w in ("nointment", "ldritch", "Searing", "Eater", "Exarch"))])
    print("raw head:", raw.splitlines()[:6])
    trial = [{"item": {"slot": SLOT, "raw": raw}}]
    show("a stats as equipped", pob.stats(keys), objective)
    for tag, mode in (("b", "fast"), ("c", "full")):
        o = pob.trial_stats(trial, keys, mode=mode)[0]
        print(f"{mode} trial ok={o.get('ok')} error={o.get('error')}")
        if o.get("stats"):
            show(f"{tag} {mode} trial, incumbent equipped", o["stats"], objective)
    loot._orig_equip({SLOT: None})
    for mode in ("fast", "full"):
        o = pob.trial_stats(trial, keys, mode=mode)[0]
        if o.get("stats"):
            show(f"d {mode} trial, slot emptied", o["stats"], objective)
    loot._orig_equip({SLOT: raw})
    show("e stats after re-equip", pob.stats(keys), objective)


def main() -> int:
    import benchmark
    from junkroan.optimizer import loot_gear
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.pob.session import PobSession

    orig_fill = loot_gear.LootGear.fill
    state = {"done": False}

    def fill(self, bases_by_slot, *, passes=2, **kw):
        if passes != 2 or state["done"]:
            return orig_fill(self, bases_by_slot, passes=passes, **kw)
        state["done"] = True
        pob = self.pob
        self._orig_equip = pob.equip

        def hook(items):
            if dict(items) == {SLOT: None} and SLOT in self.current_raw:
                pob.equip = self._orig_equip
                diagnose(self, self.objective)
                raise Stop()
            return self._orig_equip(items)

        pob.equip = hook
        return orig_fill(self, bases_by_slot, passes=passes, **kw)

    loot_gear.LootGear.fill = fill
    with PobSession(run_id=f"diag179-{os.getpid()}") as pob:
        prepared = benchmark.prepare_author(pob, SLUG, log=print)
        pipeline = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=print, construction="classic")
        try:
            pipeline.run(prepared.skeleton, tree_points=prepared.points, seed=SEED, gear_mode="loot", tree_max_depth=6, tree_max_trials=300, loop_max_seconds=2400.0, cluster_candidates=False, skip_inert=False, fulldps_shortcut=False, fixed_point_check=True, construction_only=True)
        except Stop:
            print("stopped after the diagnosis")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
