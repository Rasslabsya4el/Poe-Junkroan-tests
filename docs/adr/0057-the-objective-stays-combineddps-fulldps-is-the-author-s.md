# 2026-09-15 D57. The objective stays CombinedDPS; FullDPS is the author's manual count times it, so instance counts are derived per skill family, never taken from the author

Status: Accepted

ROADMAP 7.1a asked whether the benchmark should judge every reference on
FullDPS with the main group flagged. Measured offline on all 32 fixtures in
the pinned PoB (the author's build as saved; `count` is the gem's own
attribute in the XML, `flag` the number of socket groups the author marked
"include in full DPS"):

| reference | main gem | count | flagged groups | CombinedDPS | FullDPS | FullDPS / (count x CombinedDPS) |
|---|---|---|---|---|---|---|
| stormbrand | Storm Brand | 2 | 1 | 898,678 | 1,797,356 | 1.00 |
| hit_penance_brand | Penance Brand | 2 | 1 | 822,633 | 1,645,266 | 1.00 |
| poison_spectral_throw | Spectral Throw | 4 | 1 | 142,552 | 570,209 | 1.00 |
| bleed_perforate | Perforate | 1 | 1 | 933,716 | 933,716 | 1.00 |
| vd_spellslinger | Volatile Dead | 8 | 1 | 63,057 | 356,392 | 0.71 |
| archmage_volatile_dead | Volatile Dead | 6 | 1 | 30,443 | 620,808 | 3.40 |
| impale_ballista | Shrapnel Ballista | 6 | 2 | 95,177 | 771,573 | 1.35 |
| winter_orb | Winter Orb | 5 | 2 | 128,344 | 988,919 | 1.54 |
| cold_dot | Cold Snap | - | 2 | 228,121 | 728,542 | 3.19 |
| physical_dot | Corrupting Fever | - | 2 | 84,247 | 780,467 | 9.26 |
| arc_archmage | Arc | 1 | 2 | 535,630 | 1,022,549 | 1.91 |
| soulrend_chaos_dot | Soulrend | 1 | 3 | 269,105 | 543,201 | 2.02 |
| 13 references with no group flagged | | | 0 | | 0 | |

With one group flagged, FullDPS is exactly `count` x CombinedDPS (four
references at 1.00; Volatile Dead is the one skill whose FullDPS carries
PoB's own orb accounting on top). With more groups flagged it adds every
flagged group's own number times its count: Cold DoT's 3.19 and Physical
DoT's 9.26 are the author's secondary skills, not the main skill's scaling.
The per-instance multipliers D56 saw (brands x2, Winter Orb x5, Spectral
Throw x4, VD x6-8) are therefore the author's typed-in `count`, a manual
assumption of how many instances hit a stationary boss, not a PoB
computation; minions and totems are the exception, where `count` is what
PoB's limit stat says and `refresh_minion_counts` already derives it (D49,
D56).

Decision (option ii of 7.1a): the benchmark and the search judge on
CombinedDPS, per instance, and on FullDPS only for main skills whose
instance count is derived from a PoB stat: minions and totems today, brands
next (PoB exposes `ActiveBrandLimit` / `BrandsAttachedLimit`; Storm Brand's
author count 2 is that limit). Count-scaling the per-instance objective
cannot see is added family by family as a count rule, never by taking the
author's number: brands from the limit stat (a 7.2 rule, proven on
stormbrand and hit_penance_brand: does the tree take brand-limit nodes once
the objective can see them), corpse-fed skills from a corpse-supply fact in
`mechanics/` (Volatile Dead: orbs per cast = corpses consumed, Spell Cascade
adds corpses; the first intake batch dropped Spell Cascade from the VD
Spellslinger link because per orb it is a "less damage" support, 94,279 ->
177,902 per orb, a decision no per-instance objective can get right),
projectile-overlap skills (Winter Orb, Spectral Throw) stay per instance
until a fact exists. A run of the benchmark under `--stat FullDPS` (queued
as `stat-fulldps`) was dropped: with our count at 1 and the author's at 2-8
it would have measured the author's typing, and with equal counts FullDPS
is arithmetic on CombinedDPS. `--stat` stays in `scripts/benchmark.py` for
the family rules' own proofs.

