# Spec: with Eldritch Battery and no damage taken from mana, energy-shield RECHARGE sustains an ES cost (D63.2 amendment)

## Why (measured 2026-09-20, the day-1 template gear reading)

`summon_raging_spirits` (Tuadh, Guardian, Eldritch Battery, no Mind over Matter): PoB reports `ESPerSecondCost` 151.62,
`EnergyShield` 721, `EnergyShieldRegenRecovery` 0 on the author's build. Our sustain floor (D63.2, `rails.py:239`)

    EnergyShieldRegenRecovery + EnergyShieldLeechGainRate + EnergyShieldRecoup >= 0.85 x ESPerSecondCost

sees no recovery at all, so the AUTHOR's build is infeasible (violation 1.13 in `artifacts/runs/gear-templates/fix3-results.json`),
the loot gear stays infeasible (1.0), and the template gear buys the bench craft "Regenerate 120 Energy Shield per second
while a Rare or Unique Enemy is Nearby" TWICE (body armour and belt) only to pass the floor.

The fact (wiki, `var/cache/wiki/2026-09-20-eldritch-battery-extract.md`, verbatim: "Energy shield recharge is not interrupted
by energy shield spent to pay costs. Unless interrupted by damage to mana or energy shield, energy shield will continually
recharge."; the user's verdict 2026-09-20 says the same and adds: with Mind over Matter any enemy hit cuts the recharge, so
it does NOT count there). With EB the energy shield protects MANA; without a "damage taken from mana before life" source
nothing ever damages it; the recharge is a permanent recovery. PoB computes it: `output.EnergyShieldRecharge` per second
(`vendor/pob/source/src/Modules/CalcDefence.lua:1353`, already carrying EB's "50% less Energy Shield Recharge Rate").

## The rule

A derived stat (the `Objective.derived` mechanism, like `keystone_floors.eo_uptime_stat` or `castability`'s cost pool):

    EnergyShieldRechargeForCosts = EnergyShieldRecharge   if EnergyShieldProtectsMana is on
                                                          and sharedMindOverMatter == 0
                                                          and every <Type>MindOverMatter == 0
                                                             (Physical, Lightning, Cold, Fire, Chaos; CalcDefence.lua:2306, 2347)
                                   0                      otherwise (a missing stat counts as "not proven": 0)

and the ES relation's left side becomes
`EnergyShieldRegenRecovery+EnergyShieldLeechGainRate+EnergyShieldRecoup+EnergyShieldRechargeForCosts`. Nothing else moves:
the factor (0.85; 1.0 for a channelling main skill), the mana and life relations, `Objective.without_sustain()`, the
no-degen floor (D63.3) are untouched. The keys the derived stat reads are added to the objective's stat keys the same way
the castability pool's are (check `EnergyShieldProtectsMana` is already requested: `castability.py:329`). If PoB's readback
does not deliver `sharedMindOverMatter` / `<Type>MindOverMatter` through `stats(keys)`, say so and read MoM from the worker
the way `EnergyShieldProtectsMana` is read -- never from a node name.

No build WITHOUT Eldritch Battery may change by one digit: assert it (test below).

## Tests (fast, fake stats; no PoB)

1. EB on, MoM outputs 0, recharge 120, cost 151.62 -> relation violation = the value the existing formula gives for
   recovery 120 (not 0); with recharge 130 -> satisfied at 0.85.
2. EB on, `sharedMindOverMatter` 30 -> the derived stat is 0, the violation is what it was before this change.
3. EB on, `LightningMindOverMatter` 10 only -> 0 as well.
4. EB off (`EnergyShieldProtectsMana` 0 or missing), recharge 500 -> 0: a plain ES build gains nothing.
5. `Objective.without_sustain()` still drops the whole relation.
One PoB-backed test (skips without the runtime): the `summon_raging_spirits` fixture, tree converted as the benchmark
does, reads `EnergyShieldRecharge` > 0 and `EnergyShieldProtectsMana` on.

## Numbers to report (one PoB session at a time; BEFORE any PoB work run
## `python scripts/machine_load.py --need 1 --role other` and wait on WAIT; never next to your own pytest; by day at most one session)

1. The author's `summon_raging_spirits` under today's objective, before / after: `EnergyShieldRecharge`, `ESPerSecondCost`,
   the ES relation's own violation, the total violation, feasible yes/no. (Lead's estimate: recharge ~ 721 x 0.333 x 0.5 =
   ~120/s against 0.85 x 151.62 = 128.9 -- about at the floor; report PoB's real number.)
2. `python scripts/gear_transplant.py summon_raging_spirits --seed 1 --results <before|after>.json --report <...>.md` on your
   branch before and after the change (two runs, ~9 min each, one after the other): C value / author, C feasible, and the
   bench crafts on Body Armour and Belt (today: the ES-regen craft on both).
3. Which of the 32 Tuadh references and the Zizaran set have Eldritch Battery on (one pass of fixture loads; a list of
   slugs with EB on / MoM share) -- those are the only builds this can move.
4. Whole suite once at the end, alone on the machine (`machine_load.py` first), `-p no:cacheprovider -p no:faulthandler`.

Do not edit `docs/ROADMAP.md`, `docs/DECISIONS.md`, `CLAUDE.md`. Commit early and often; begin the final message with
`=== FINAL REPORT ===`.
