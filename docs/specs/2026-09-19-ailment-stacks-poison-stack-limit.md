# Spec: D78 follow-up -- poison is capped by PoB's own stack limit, and the acceptance the first worker left

D78 is merged (38a12be): the conservative lane counts the ailment stacks applied inside the ramp budget. Bleed and
ignite go through PoB's `overrideBleedStackPotential` / `overrideIgniteStackPotential`. Poison was given a
whole-percent custom mod "N% less Damage with Poison"; the first worker measured the problem itself on
poison_spectral_throw: target 12 of 14.147 stacks = 0.848, the 16% mod reads back 9,406.3 -> 7,850.9 = 0.835, and a
damage penalty does not move effects that count poisons on the enemy.

## Change (the lead's decision)

Use PoB's own parsed mod: `Cannot Poison Enemies with at least N Poisons on them` -> `PoisonStackLimit MIN N`
(`Modules/ModParser.lua:3938`; applied to `PoisonStacks` in `Modules/CalcOffence.lua` around line 4602; verified
with `PobSession.parse_mods`: ok, not unsupported). N = the stacks applied inside the budget (the same arithmetic
as today), written into the commented custom-mod block in place of the less-damage line; the conservative
`multiplierPoisonOnEnemy` (if the lane sets it) must not exceed N. Keep everything else of D78 as merged: the
idempotence, the optimistic lane on the steady state, the audit error, the report-only pinnacle line.

## Acceptance the first worker did not finish (numbers in the report and the commit message)

1. poison_spectral_throw author under the lane: `PoisonStacks`, `PoisonDPS`, `TotalPoisonDPS`, `CombinedDPS` before
   the cap, with the old less-damage surrogate, and with the stack limit; the readback must show the stacks at N and
   nothing else moved (hit DPS identical).
2. `artifacts/benchmark/20260919-0130-new18-rules/bleed_perforate-s1.pob.txt`: the lead measured 1,392,672 ->
   489,499 with `overrideBleedStackPotential` 2 (1.08 attacks/s, bleed duration 7.39 s) -- reproduce it as a
   PoB-backed test on a copy under `tests/fixtures/regressions/` (assert the override value 2 and BleedDPS scaling
   by 2/8 within 1%, not the absolute CombinedDPS).
3. The 32 Tuadh authors through the benchmark's `prepare_author` (one PoB session): the lane value of every
   reference WITHOUT a stacking ailment is identical with the cap logic on and off (switch it off by a parameter in
   your measurement script, NOT by executing another commit's code -- preamble rule 4a); list the references that
   move with before / after / factor / stacks counted.
4. The pinnacle line: print it for bleed_perforate s1 and poison_spectral_throw (10 s placeholder).
Focused tests (`tests/test_ramp.py tests/test_ramp_inputs.py tests/test_audit_and_config_limits.py` plus yours), then
the whole suite once, in the foreground; one PoB session at a time (a 5-worker benchmark is running); run scripts as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker: write the code yourself.
Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
