# Spec: amendment to the castability / maximum-resistance floors (branch `gpt-2026-09-19-usable-skills-and-max-res-floors`, commit d76df84)

The lead's review of d76df84. That branch is not merged into main: your FIRST command is
`git merge gpt-2026-09-19-usable-skills-and-max-res-floors` in your worktree (a fast merge, no conflicts expected), then
work on top of it. Three defects and one rule change, all measured or sourced.

## 1. Eldritch Battery: PoB's own rule pays a mana cost from energy shield + unreserved mana

PoB already has the rule this floor implements, `vendor/pob/source/src/Modules/Calcs.lua` lines 433-456 (the source of
the warning "You do not have enough Energy Shield and Mana to use: ..."):

    totalPool = (output.EnergyShieldProtectsMana and costResource == "ManaCost" and output.EnergyShield or 0) + output[pool]

`EnergyShieldProtectsMana` is `env.modDB:Flag(nil, "EnergyShieldProtectsMana")` (the Eldritch Battery keystone and
whatever else PoB parses into that flag; never match a keystone NAME).

Measured by the lead on the raw author `tests/fixtures/tuadh_329/soulrend_chaos_dot.pob.txt` (Eldritch Battery
allocated): `Mana` 913, `ManaUnreserved` 0, `EnergyShield` 503, largest pressed cost 52 (Essence Drain). d76df84
reports 8 of its skills as "cannot be cast" and would make every Eldritch Battery build with full reservation
infeasible. PoB shows no such warning on that build.

- Expose the flag as a numeric stat `EnergyShieldProtectsMana` (1 / 0) in the same three Lua read paths where d76df84
  special-cases `FireResistMax` (fast trial `lookup`, full trial `read_keys`, the `stats` collector), read from the
  calculated env's `modDB` of THAT calculation (a trial that allocates or drops the keystone must see its own flag).
- A derived stat `ManaCostPool` = `ManaUnreserved` + `EnergyShield` x flag; both mana relations use it as the left
  side. The over-reservation scale (the 4th element, "Mana") stays.
- `audit_castability` uses the same pool and says "... costs N mana, M unreserved mana + K energy shield" when the
  flag is on.

Test numbers: the soulrend author above -> 0 castability findings, no `ManaCostPool` violation; the same stats mapping
with the flag forced to 0 -> violation of the mana relation (52 against 0). A PoB-backed test reads
`EnergyShieldProtectsMana` == 1 on that fixture and == 0 on `physical_dot.pob.txt`, through `stats` and through a fast
trial.

## 2. The main skill's cost relation stays LIVE

d76df84 removed `("ManaUnreserved", "ManaCost", 1.0, "Mana")` and `("LifeUnreserved", "LifeCost", 1.0, "Life")` from
`Rails.objective()` and froze every cost, the main skill's too, as a constant between refreshes. A tree node, a rare
or a bench craft that changes the main skill's cost ("-7 to total mana cost", reduced mana cost of skills, Archmage's
cost growing with unreserved mana) is then invisible inside a trial, and an `Objective` built without a refresh call
has no cost floor at all (`recover_tree.py`, the transplant scripts, any new caller).

- Put the two live relations back in `Rails.objective()` (left side `ManaCostPool` for mana), and keep the frozen
  largest-pressable-cost relations from `with_castability_floors` IN ADDITION (they cover the other buttons).
  `_COST_RELATIONS` no longer strips the live pair.
- `tests/test_unique_rails.py`: the assertion that the live mana relation survives `without_sustain()` comes back
  (with the new left side).

## 3. The author's resistance is not OUR fixed floor

d76df84 turned `resist_floors(author)` into "the author's maxima" and `author_floors` writes them as fixed floors of
OUR build: an author at 79% maximum fire (impale_cyclone raw: `FireResist` 79, `FireResistTotal` 155) makes our build
infeasible unless it copies the author's source of maximum resistance. The defensive worth of a raised maximum is
already floored by `max_hit_floors` (95% of the author's maximum hit per element).

- `author_floors` writes NO fixed elemental resistance floors; the own-maximum relations
  (`ELEMENTAL_RESIST_RELATIONS`) are the rail on our side. Remove `resist_floors` if nothing else uses it (grep).
- `tests/test_benchmark_sets.py`: the floors dict holds no `FireResist` / `ColdResist` / `LightningResist` key while
  the objective's relations hold the three own-maximum relations.

## 4. A triggered skill pays its cost too

The first spec said "not triggered". The wiki says otherwise (`var/cache/wiki/2026-09-19-trigger-cost-extract.md`,
poewiki "Trigger": "Their cost must be paid normally", "If a skill cannot trigger (e.g. due to cooldown or cost), the
next triggerable skill will trigger instead"), and PoB's own warning iterates every active skill of the player,
triggered ones included. A Hextouch curse that costs 47 mana on a build with 30 unreserved never lands, while PoB
still counts the curse.

- The set of skills the floor covers = PoB's: every enabled active skill of the PLAYER with a cost (triggered or not),
  minus what PoB's own clause excuses (a skill with a reservation of its own: cost against pool + its reservation,
  `Calcs.lua` 446-448). Minion skills stay out (they are not the player's). Rename `pressable_*` accordingly
  (`costed_skills`), keep the audit message "skill cannot be used: <gem> costs N mana, ...", and say "(triggered)"
  next to a triggered one.
- The trigger's cost multiplier is already in PoB's per-skill `ManaCost`; do not recompute it.

## Numbers to report

- Re-run your own 96-build + 32-author scan (the script you used for "BUILDS FILES 96 CAST 38 RESIST 15 / AUTHORS
  FILES 32 CAST 31 RESIST 8") with the pool rule: expected the soulrend author's 8 rows gone; list whatever else moves.
- Add a third column to the scan: PoB's own `ManaCostWarningList` for the same build (read it in MAIN mode), and list
  every disagreement between PoB's list and ours, by skill, with the reason (after point 4 the expected list is
  empty or percent-cost only). Do not change the rule for them; the lead decides with that table.
- The `physical_dot` before / after you already measured stays valid; rerun only the "after" half
  (`scripts/benchmark.py physical_dot --seeds 1 --no-variants --workers 1 --loop --loop-seconds 300`).

Focused tests first, then the whole suite once, foreground. Check `cmd /c dir /AL`: `var`, `vendor`, `artifacts` are
junctions. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early, commit each of the three parts apart.
