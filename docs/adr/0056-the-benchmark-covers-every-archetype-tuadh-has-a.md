# 2026-09-15 D56. The benchmark covers every archetype Tuadh has a leaguestart run for; references are read from the channel, judged on the strongest skill group, totems on FullDPS

Status: Accepted

The 14 references covered spell hit, brands, channelling, poison, cold /
chaos / physical DoT, bleed, melee hit and minions. The user's rule (2026-09-15):
the prototype covers every archetype, and the only reference source is
Tuadh's Exarch & Eater leaguestart runs (day-1 gear, same rails); a PoB
from another author would compare unlike things. The channel's video list
and descriptions were read by script (49 of 50 candidate runs carry a
pobb.in link), every candidate was loaded in the pinned PoB, and one run per
further archetype was taken (18): totems (Shrapnel Ballista), mines
(Pyroclast, Exsanguinate), traps (Lightning Trap Saboteur), triggers
(Spellslinger Volatile Dead, Snipe Burning Arrow), archmage (Arc
Hierophant, Volatile Dead Necromancer), impale (Cyclone, ballista),
Gladiator block (Spectral Shield Throw), wands (Kinetic Bolt, Kinetic
Fusillade), chaos DoT stacking (Soulrend + Bane + Essence Drain), shockwave
Cyclone, Static Strike, bleed Perforate, poison Spark, Elemental Hit. Not
found on the channel: CI / energy shield, low life, Righteous Fire; those
stay uncovered and marked, not filled from elsewhere.

Older leagues need no patch-note accounting: the pinned PoB recomputes every
build under 3.29 (uniques at the current variant, D50). What it cannot say
is that a concept was reworked; `scripts/reference_drift.py` compares the
author's saved PlayerStat with the recompute and flags a reference below
0.7 (none of the 32; the range is 0.93-2.17).

Two things the intake measured, each a rule:

1. PoB's main socket group is the author's display choice, not the
   build's strongest skill: the Chaos DoT Occultist points at Essence Drain
   (15,782 CombinedDPS) while its Soulrend group gives 269,105 on the same
   build. A benchmark on the display group would be beaten by a Contagion
   build. The fixture points PoB at the strongest group (each group tried as
   main, `mainSocketGroup` set in the fixture XML, recorded in
   `sources.json` as `fixture_edits`); the same for the main active gem
   inside a group (Burning Arrow first, not Snipe; Volatile Dead first, not
   Spellslinger), since the skeleton's main skill is the first gem.
2. FullDPS counts instances: a totem skill's CombinedDPS is one ballista
   (95,177), FullDPS the gem count of them at ActiveTotemLimit (557,631 for
   six; count 1 / 3 / 5 measured 95k / 280k / 465k). `objective_for` now
   maximizes FullDPS for minion and totem main skills (`counts_instances`);
   `refresh_minion_counts` already sets the count from PoB's limit stat.
   Left as measured, not yet a rule: Volatile Dead (per orb 30k-63k,
   FullDPS 357k-621k), brands (x2), Winter Orb (x5), Poison Spectral Throw
   (x4) and the like carry a per-instance multiplier in FullDPS too; on
   CombinedDPS the ratio against the author is unchanged as long as the
   count is, and the optimizer does not chase the count. Whether the
   benchmark should move to FullDPS with the main group flagged is decided
   after the first-seed intake run shows which references the difference
   changes.

Intake procedure (ROADMAP "Archetype coverage"): codes into
`tests/fixtures/tuadh_329/` + `sources.json`, `scripts/fixture_stats.py`,
`scripts/reference_drift.py`, one seed per new reference in one overnight
batch, each gap a rule + fast test + audit check, then 3 seeds; the full
benchmark once a week as the regression gate.

