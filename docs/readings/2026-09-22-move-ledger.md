# Reading 2026-09-22: which loop moves pay for their time (Opus lead, economy mode)

Source: the per-build "loop moves" tables of four finished runs, 180 builds: `main-smoke` (18, before the weapon-base
move), `new18-r3` (54), `core14-r3` (42), `ziz-rules` (66 of 78; 12 failed at load). Each kept move's gain is taken as a
percentage of that build's FINAL value, so a 2.4M stormbrand and a 0.3M cold_dot weigh the same. Gains compound, so the
sums rank the moves and nothing more. Worker time is the ledger's own time per move (the "time" column), summed.
Parser: an awk over `report.md` (no PoB), reproducible from the four report files.

Loop worker time: 97 h over 180 builds = 32 min per build.

| move | builds it improved | median gain per build (4 runs) | sum of gains, % of final value | worker time | share of loop time | % per minute |
|---|---:|---|---:|---:|---:|---:|
| picks | 157/180 | 8.0-11.0% | 2,275 | 14 h 26 min | 15% | 2.6 |
| path swaps | 138/180 | 3.2-3.9% | 859 | 17 h 37 min | 18% | 0.81 |
| refine | 123/180 | 0-3.4% | 876 | 2 h 42 min | 2.8% | 5.4 |
| lanes | 97/180 | 0-1.4% | 501 | 64 min | 1.1% | 7.8 |
| gear Weapon 1 | 88/174 | 0-1.8% | 800 | 79 min | 1.4% | 10.1 |
| weapon base | 104/156 | 0.5-1.0% | 245 | 9 min | 0.2% | 27 |
| gear Weapon 2 | 40/141 | 0 | 245 | 40 min | 0.7% | 6.1 |
| swaps replay | 20/59 | 0 | 135 | 10 min | 0.2% | 13.5 |
| gear, the other 8 slots | 96/180 | 0.4-1.7% | 445 | 5 h 53 min | 6.1% | 1.3 |
| kick tree | 86/180 | 0-1.1% | 588 | 15 h 21 min | 16% | 0.64 |
| kick joint | 80/180 | 0-0.4% | 781 | 31 h 20 min | 32% | 0.42 |
| regions | 11/180 | 0 | 49 | 5 h 33 min | 5.7% | 0.15 |
| lanes tree refine | (a floor repair: trades value for feasibility) | | -234 | 33 min | 0.6% | - |

## What it says

1. **Picks are the loop's engine**: 29% of the summed gain for 15% of the time, 157 of 180 builds improved, median
   8-11% a build in every run.
2. **The kicks cost 48% of the loop's time for 17.5% of its gain, and they are NOT a cut.** The gain is concentrated:
   kick joint kept something on 80 of 180 builds, ~10% of the final value per build it hits (kick tree ~7%), and it
   lands on reference medians: on `main-smoke`, dividing the kick-joint gains out moves stormbrand's median from 170% to
   ~148% and the median of medians from 139% to ~133%. The kicks run only after a pass keeps nothing, so their gain is
   what no cheaper move found.
3. **Regions did not survive real loops**: 11 of 180 builds, 0.6% of the gain for 5.7% of the time (~1.9 min a build),
   the lowest yield per minute of any move. The plan-B bench's +0.43% came from starts where refine and path swaps had
   not harvested yet. Proposal: out of the default loop (a flag, like corridors), confirmed on a smoke A/A after the
   reset.
4. **Gear**: the weapon moves are among the best per minute (weapon base 27 %/min, Weapon 1 10 %/min); the other eight
   slots together are 6% of the time for ~6% of the gain: keep.
5. **For the owner's question "parallelism inside one build" (handover, 2 of 2)**: the kicks are 3 + 4 independent draws,
   each judged on its own, and they are 15.6 min of a build's 32-min loop. Running the draws of one kick on parallel
   workers is the natural first target: on 4 workers about a third of a build's loop wall clock goes (48% x 3/4), and
   with per-draw seeds the result can stay identical. It shortens one request's wait, not the benchmark's throughput
   (the queue already fills every worker with whole builds).
