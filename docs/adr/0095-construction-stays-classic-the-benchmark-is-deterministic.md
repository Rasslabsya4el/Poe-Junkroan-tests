# 2026-09-22 D95. Construction stays classic; the benchmark is deterministic, and a path change is judged against the seed spread

Status: Accepted

Reading `docs/readings/2026-09-22-aa-and-rig-first.md`. (1) `main-smoke` (20.09) against `main-smoke-aa` (22.09): on the
four references where the loop's weapon-base move (merged between the two) kept nothing, all 12 builds came out
identical to the digit -- the benchmark on the same code and a clean machine has no run-to-run noise, the
time-budgeted loop included. Where the move kept something the build followed another path: stormbrand -24.1,
impale_ballista +11.0, median of medians -0.2. So a change that alters paths is judged like a new seed draw: per
reference against the seed spread, and on the median of medians, never on one reference. (2) `rig-smoke`
(`--construction rig-first`) against `main-smoke-aa` on the same code: median of medians 138.6 -> 140.2, per
reference +13.6 / +13.2 / -7.6 / -19.5 / +0.7 / +1.3, all inside that yardstick; burning_arrow_snipe picks up audit
errors and impale_ballista's spread goes 28 -> 88. The construction-only gain (+2.8%) does not survive the loop.
`--construction rig-first` stays a switch; the default stays classic.

