# Reading 2026-09-22: template gear against loot gear (Opus 5.5 lead)

Source: the two campaigns on each gear, seeds 1-3, same loop budget (`--loop-seconds 5400`), code of 20.09 evening
(D91 / D92 in, regions still in the loop): `new18-r3` vs `new18-tpl`, `core14-r3` vs `core14-tpl` (their
`compare_runs` tables are in `docs/handover/2026-09-20-opus.md`, "Finished runs"). The smoke pair (`main-smoke` vs
`templates-smoke`) is a subset of these 32 references and is not counted twice. Load note: the first ~14 builds of
`core14-tpl` ran beside an owner's game (CPU 76-91%) with the same time budget, so they had fewer loop passes; this can
only have lowered the template side.

## Strength and spread

| | loot | template |
|---|---:|---:|
| median of medians, new18 | 159.8 | 151.3 |
| median of medians, core14 | 154.8 | 152.1 |
| seed spread (max - min of 3 seeds), median over references | 37.3 (29 refs) | 19.7 (28 refs) |
| references with no counted seed | 2 (impale_cyclone, poison_spark) | 4 (impale_cyclone, kinetic_bolt_wander, shockwave_cyclone, spark) |

27 references are counted on both gears. Template minus loot, points of the author: median -5.0; 7 better by more than
5, 7 within 5, 13 worse by more than 5.

| worse by 30+ points | delta | better by 25+ points | delta |
|---|---:|---|---:|
| archmage_volatile_dead | -70.5 | stormbrand | +53.4 |
| regular_viper_strike | -43.6 | bleed_perforate | +45.2 |
| pyroclast_mine | -39.2 | physical_dot | +38.9 |
| smite | -38.1 | lightning_trap | +25.1 |
| burning_arrow_snipe | -37.6 | | |
| winter_orb | -34.9 | | |
| absolution_minions | -32.0 | | |
| impale_ballista | -30.0 | | |

Why the four references counted nothing (Haiku sweep of the reports):

| reference | loot | template | cause |
|---|---|---|---|
| impale_cyclone | 0 of 3 | 0 of 3 | movement floor: 1.067 (loot) / 1.027 (template) < 1.164 on every seed |
| shockwave_cyclone | 2 of 3 | 0 of 3 | movement floor: 1.027 < 1.0345 (the author's own 1.0665 x 0.97) on every template seed |
| kinetic_bolt_wander | 2 of 3 | 0 of 3 | audit "dead tree node": Minion Life 10904 + 34880 |
| spark | 3 of 3 | 0 of 3 | audit "dead tree node": Chance to Ignite, Freeze and Shock 8198 |
| poison_spark | 0 of 3 | 3 of 3 | audit "dead tree node": Chance to Poison with Spells 11984 |

## What it says

1. **About half of the seed spread is loot.** With the same code and seeds the spread over references falls from 37
   to 20 points on template gear. The other half is the search itself.
2. **The template is a few points weaker, and the loss is concentrated**: -3 to -9 on the campaign medians, eight
   references lose 30-70 points. Those eight are the template's gap list (what the best-of-200 loot finds that the
   template does not buy); archmage_volatile_dead (-70.5) is the first to read.
3. **Two of the counting holes are the template's, two are shared.** The template's boots end at 1.027 movement on
   both cyclone builds (the same number twice: the boots did not buy the movement line, or bought one too low for
   the floor). The three "dead tree node" rejections look like the D87 open item (the audit judges nodes with the
   config frozen; a node that proves a conservative-lane condition -- chance to poison, chance to ignite / shock --
   is reported dead): to be confirmed on one build before any fix.
4. **For judging code changes the template is the better yardstick** (half the noise, so a real change shows with
   fewer seeds), once its boots meet the movement floor and the audit's dead-node check is confirmed or fixed. **For the
   product** the template is what a player can actually buy on day 1 (the owner's reading of 20.09); the loot is a
   lucky best-of-200. Proposal to the owner: template gear becomes the benchmark's and the product's default after
   those two fixes, the loot stays a comparison arm. Not changed now (no new code before the owner's word).
