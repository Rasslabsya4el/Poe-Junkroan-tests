# Reading 2026-09-22: the smoke's run-to-run noise, and construction rig-first (Opus 5.5 lead)

Sources: `compare_runs main-smoke main-smoke-aa` (queue, 22:23) and `compare_runs main-smoke-aa rig-smoke` (rerun by the
lead, no PoB: the queue's two compare lines wrote the same `artifacts/runs/20260922-2223-run.out` and the second
overwrote the first). Smoke six, loot gear, seeds 1-3, `--loop-seconds 5400`, clean machine for all three runs.

## main-smoke (20.09 12:41) against main-smoke-aa (22.09 18:23, @585ae29)

| reference | main-smoke | main-smoke-aa | delta | weapon-base move kept (aa) |
|---|---:|---:|---:|---|
| bleed_bow | 120.4 | 120.4 | 0.0 | 0 on all seeds |
| burning_arrow_snipe | 145.9 | 145.9 | 0.0 | 0 |
| cold_dot | 131.6 | 131.6 | 0.0 | 0 |
| impale_ballista (2 counted) | 115.2 | 126.1 | +11.0 | kept on some seeds |
| stormbrand | 169.7 | 145.6 | -24.1 | kept on all three seeds |
| summon_raging_spirits | 178.8 | 178.8 | 0.0 | 0 |
| median of medians | 138.8 | 138.6 | -0.2 | |

This is NOT a pure A/A: main-smoke predates the loop's weapon-base move (its ledger has no "weapon base" row;
main-smoke-aa's has one). What it shows is stronger:
1. **The benchmark is deterministic on a clean machine.** Wherever the weapon-base move kept nothing, all three seeds
   of the reference came out identical to the digit two days apart (12 of 12 builds), time-budgeted loop included.
   The run-to-run noise of the same code on the same machine is zero, not a band.
2. **A small change that perturbs a build's path moves a single reference by up to ~24 points** (stormbrand -24.1,
   impale_ballista +11.0) and the median of medians by 0.2. Once a move keeps something, the rest of the build (kicks'
   draws, later passes) follows another path; the result is a different draw from roughly the seed spread, not a
   verdict on the move. This is the yardstick for any change that alters paths.

## rig-smoke (`--construction rig-first`, @e2a2bbb) against main-smoke-aa (classic)

| reference | classic | rig-first | delta | note |
|---|---:|---:|---:|---|
| bleed_bow | 120.4 | 134.0 | +13.6 | |
| burning_arrow_snipe | 145.9 | 159.1 (2 counted) | +13.2 | rig side 3 audit errors, 1 build not counted |
| cold_dot | 131.6 | 124.0 | -7.6 | |
| impale_ballista | 126.1 (2 counted) | 106.6 | -19.5 | rig spread 88 (construction ended -35.7%) |
| stormbrand | 145.6 | 146.3 | +0.7 | |
| summon_raging_spirits | 178.8 | 180.1 | +1.3 | |
| median of medians | 138.6 | 140.2 | +1.6 | |

Per reference the deltas sit inside the path-change yardstick above (|delta| <= 24); the median of medians moves
+1.6; burning_arrow_snipe gains an audit problem on the rig side and impale_ballista's spread quadruples. The
construction-only advantage (+2.8% at the median, 5 of 6 above) does not survive the loop as a measurable gain.
Verdict: rig-first stays an experiment switch, classic stays the default (D95).
