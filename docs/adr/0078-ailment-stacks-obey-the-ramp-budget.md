# 2026-09-19 D78. Ailment stacks obey the ramp budget

Status: Accepted; amended by D78 amd 1

The user: "we have the 2.5 s ramp; it must dictate how we count DPS over time in these situations, and ailments
are exactly the same. Later perhaps a second metric with a longer ramp, 'pinnacle boss ramp', for drawn-out fights
where the build is not expected to one- or two-shot the boss." Until now ailment stacking was exempt (D62
amendment: "PoB's own steady state") and `RampSeconds > RampBudget` was an audit warning.

The conservative lane now counts the stacks applied inside the budget -- `applied per second x min(budget,
duration)`, capped by the ailment's maximum and by PoB's steady state -- and writes them INTO PoB so the delivered
file shows the optimized number: `overrideBleedStackPotential` / `overrideIgniteStackPotential` for bleed and
ignite; for poison PoB's own parsed mod "Cannot Poison Enemies with at least N Poisons on them"
(`PoisonStackLimit`, applied in `CalcOffence.lua`) as a commented custom mod -- the lead's choice over a whole-percent
"less Damage with Poison" (16% less gave 0.835 where the stacks say 0.848, and per-poison multipliers would not
follow). The optimistic lane keeps the steady state; the audit raises an error when a delivered build counts more
stacks than the budget allows; the summary prints "pinnacle boss ramp (10 s)" as a report-only line
(`assumptions.pinnacle_ramp_seconds`, a placeholder until the user sets it).

Measured on the delivered `new18-rules` builds with the branch's code (the lead's run): bleed_perforate s1
(Crimson Dance) 1,392,672 -> 489,499 -- 2 of 8 stacks inside 2.5 s at 1.08 attacks per second, bleed duration
7.39 s -- 121% of the author instead of 343%; s2 (one stack, no Crimson Dance) 762,081 -> 697,597, 172% (that
0.915 is the rest of the lane re-derived under D75-D77, not this rule).

**D78 amendment 1 (2026-09-19): poison is capped by PoB's own stack limit.** The custom-mod block now carries
`Cannot Poison Enemies with at least N Poisons on them` (`PoisonStackLimit`), N = the stacks applied inside the
budget, and the conservative `multiplierPoisonOnEnemy` never exceeds N; the audit rejects the old less-damage
surrogate. poison_spectral_throw author: 14.147 -> 12 stacks, TotalPoisonDPS 145,312 -> 123,258 (0.848 exactly; the
16% surrogate gave 0.842), hit DPS unchanged. Over the 32 authors, cap off against on in one session
(`scripts/measure_ailment_stack_caps.py`): three move -- poison_spark 330,363 -> 191,160 (0.579, 14 stacks),
poison_spectral_throw 171,272 -> 149,217 (0.871, 12), regular_viper_strike 616,500 -> 363,065 (0.589, 7) -- and the
other 29 are identical. The authors' lane numbers of those three references change with this rule, so their
ratios in earlier runs are not comparable with later ones.

