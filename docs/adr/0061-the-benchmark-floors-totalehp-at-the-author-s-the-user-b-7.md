# 2026-09-17 D61. The benchmark floors TotalEHP at the author's (the user: B); 7.1 reopens once, speed first

Status: Accepted

Context: the frozen campaigns put 28 of 32 references at or above the author with
life at 100% and max hit at 95-125% of the author's, but TotalEHP at 21-23% on
spectral_shield_throw, 44-48% poison_spectral_throw, 46-53% elemental_hit, 50-52%
vd_spellslinger, 58-64% absolution and SRS, 69-75% ignite_penance_brand: the margin
is partly the author's avoidance layers (block, evasion, suppression) sold for damage,
which neither floor sees. Options put to the user: A keep, B TotalEHP at the author's,
C a fraction of it.

Decision (the user, B): TotalEHP >= the author's under the same lane, like D59 for
life; no hand weight. Measured cost: +1 ms on a 5-8 ms fast trial. It changes the
objective's shape, so 7.1 reopens once and carries everything that does: D61, D60
redone (the trial value must win over the remembered one; `_finish`'s repair after the
tuning), the author's row and ours under literally one lane (benchmark ratio vs
one-lane D/A: poison_spark 78 vs 116, bleed_bow 89 vs 104, impale_ballista 45 vs 84).

Speed comes first inside that reopening (the user: no money for a server; tests are the
bottleneck: a smoke proof is 5 h, the campaigns 28 h). Measured 2026-09-17: a fast trial
is 5-8 ms, 16-25 ms when FullDPS is among the keys; a build is ~123,000 trials, 106,000
of them in the tree stages (400 greedy steps x ~267 candidates), wall cost 12-24 ms per
candidate. Order: (1) profile the step (Lua vs IPC vs Python); (2) exact wins, same
builds: count x CombinedDPS instead of FullDPS where the count is one group's instances,
kick draws that repeat a tried ruin set at an unchanged state, batch overhead; (3) lazy
greedy (re-evaluate the stale top N plus what the last move touched, full refresh every
M steps), proven like any optimizer change: smoke set x 3 seeds through
`scripts/compare_runs.py` with the trees compared; (4) the time saved goes to restarts
(best of K seeds), which is 7.3. Then D61 + D60 + one lane, one smoke proof, one rerun
of the campaigns.

