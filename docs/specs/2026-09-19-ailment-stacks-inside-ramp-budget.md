# Spec: ailment stacks obey the ramp budget (the user's verdict, 2026-09-19) -- D78

The user: "the 2.5 s ramp must dictate how we count DPS over time in these situations; ailments are exactly the
same". Later a second metric, "pinnacle boss ramp", with a longer budget for drawn-out fights; the 2.5 s number
stays THE number.

Today (`src/junkroan/optimizer/ramp.py`, D62 amendment): every ramp-type CONFIG count is written at what the build
reaches inside the budget (`ramp_inputs`), but ailment stacking is exempt -- "PoB's own steady state" -- and
`RampSeconds > RampBudget` is an audit warning. Result, campaign `new18-rules`: bleed_perforate s1 = 1,392,672 =
343% of the author (s2 188%) on Crimson Dance, whose 8 bleed stacks need 5.1 s of attacking
(`artifacts/benchmark/20260919-0130-new18-rules/bleed_perforate-s1.pob.txt`, log line "ramp 5.1 s against a 2.5 s
budget").

## The rule

The optimized number is the DPS the build has reached after `RampBudget` seconds of attacking. `ramp.py` already
holds the model -- `DPS(t) = M(t) * sum_i dps_i * min(1, t / ramp_i)` with every ingredient a PoB output
(`<Ailment>StackPotential`, `<Ailment>StacksMax`, `<Ailment>Duration`, `PoisonStacks`, `Speed`, `HitSpeed`) -- so:

1. For each stacking ailment component (bleed, ignite when it stacks, poison, and anything else `ramp.py` models as
   a climbing component) the stacks counted are those applied inside the budget: `applied per second x min(budget,
   duration)`, capped by the ailment's maximum; never more than PoB's own steady state.
2. Write it INTO PoB, so the delivered `.pob.txt` shows the same number we optimized: PoB has
   `overrideBleedStackPotential` and `overrideIgniteStackPotential` (`Modules/ConfigOptions.lua`); set them through
   the conservative lane exactly as `ramp_inputs` sets charges (the value PoB expects is the stack count -- check
   `CalcOffence.lua` around `BleedStackPotentialOverride`: it divides by max stacks). Poison has no override input:
   use the accepted mechanism of a commented custom-mod block (as for Pride, D62 amendment 3): "N% less Damage with
   Poison" with N from the arithmetic and a comment that names the stacks inside the budget and the steady state;
   verify by readback that `PoisonDPS` moved by exactly that factor and nothing else moved.
3. The derivation runs wherever the lane is derived (it depends on attack rate and duration, which the tree and
   gear change), is idempotent, and leaves a build with no stacking ailment byte-identical.
4. The optimistic lane keeps PoB's steady state. `RampSeconds` stays in summaries; the audit warning "ramp:
   RampSeconds > RampBudget (ailment stacking ...)" disappears for ailments handled here and becomes an ERROR if a
   delivered build still counts more stacks than the budget allows.
5. A hook, not a second objective yet: `rails_default.json` gains `assumptions.pinnacle_ramp_seconds` (put 10.0,
   marked "placeholder until the user sets it") and the summary prints one extra line "pinnacle boss ramp (10 s):
   <stat> <value>" computed by the same function with that budget. Not optimized, not gated.

## Numbers to report and tests

- Unit (fake stats): Crimson Dance, 8 max stacks, bleed duration 5.1 s, 1.6 stacks applied per second, budget 2.5
  -> 4 stacks counted (floor or exact -- follow what PoB's override accepts and say which), steady state 8.
  Duration 2.0 s, budget 2.5 -> the steady state, no override written. No ailment -> nothing written.
- PoB-backed (skips without `var/cache/pob`): on `artifacts/benchmark/20260919-0130-new18-rules/bleed_perforate-s1`
  (copy the `.pob.txt` to `tests/fixtures/regressions/`): the conservative number before (1,392,672) and after,
  the stacks counted, `RampSeconds`; on one poison reference (`tests/fixtures/tuadh_329/poison_spectral_throw`) the
  author's lane number before / after and the readback proving only `PoisonDPS` scaled.
- No regression: authors of the 32 Tuadh references through the benchmark's author preparation -- the lane value
  of every reference WITHOUT a stacking ailment is identical before and after; list the ones that move with
  before / after / factor.
Focused tests, then the whole suite once, in the foreground; one PoB session at a time (a 5-worker benchmark is
running); run scripts as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker:
write the code yourself. Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
