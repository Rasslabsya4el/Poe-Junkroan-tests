# Spec: the move ledger -- every build records what each move of the loop cost and earned (no behaviour change)

Why (`docs/research/2026-09-19-tree-search-plan.md` "What we report from now on", extended by
`2026-09-19-components-plan.md`): loop passes add +26 / +7 / +4 / +2 / +2% and half of a build's time buys the last 8%
of its value, but nothing records WHICH move earns what per second. The next full campaign (96 builds, 28 h) must
produce that table as a by-product. The gem-count fix (D83), the judge fix (D87), the castability floors (D85), the aura-level move (D86) and the replay
bench (D84) are all on main: the loop's moves today are lanes, refine, path swaps (+ swaps replay), gear slots, picks,
aura levels, kick tree, kick joint; `not_kept` / `judged_and_reverted` counters already exist (the bench added them):
build on them, do not duplicate them. `scripts/replay_bench.py` rows carry the ledger too.

## What is recorded

`BuildResult.moves`: one entry per move the improvement loop tries, in order:

    {"pass": <int>, "move": "refine" | "path swaps" | "swaps replay" | "gear <slot>" | "picks" | "lanes" |
     "kick tree" | "kick joint" | <whatever other move the loop has: use the label the log already prints>,
     "seconds": <float>, "before": <value>, "after": <value the build stands on after the judge>, "kept": <bool>,
     "reverted_by_judge": <bool>, "violation_before": <float>, "violation_after": <float>}

Construction stages are already in `stages`; do not duplicate them. Plus, per build:

- `pob_calls`: counts by kind from a counter inside `PobSession` (fast trials, full trials, `stats`, `calc`,
  `mutate_nodes`, `set_*` / `equip`, `node_power`), and the seconds spent inside each kind.
- `tree_churn`: 1 - |A and B| / |A or B| for A = allocated passive nodes at the end of construction ("tree rebuilt on
  gear"), B = at the end; the same number restricted to TRUNK nodes of A (a node whose removal drops more than 12
  allocated nodes; `TreeGraph` gives the cascade), and `trunk_share` = trunk nodes of B / all nodes of B.
- `dropped_moves` stays what the gem-count fix made it.

All of it goes into the benchmark's `results.json` row and the search's per-build JSON. `BuildResult.summary()` and
`scripts/describe_build.py` print one table:

    | move | tries | kept | seconds | gain (sum of kept after - before) | gain per 100 s | share of the loop's gain |

and `scripts/benchmark.py --rereport` prints the same table summed over a run (median per build and total).

**The accounting identity (the test number):** for a build whose loop ended feasible, construction's final value +
the sum over KEPT moves of (after - before) = the value before "config (final lanes)", to 1e-6 relative. If a move
changes the value outside these records, the ledger is missing a move: find it and record it.

No optimizer decision may read the ledger. A fake-PoB run of the loop with and without the ledger produces the same
move sequence and the same final build.

## Tests and the measurement

Fast: the identity on the fake loop of `tests/test_improvement_loop.py` (kept, reverted and dropped moves all present);
`tree_churn` on a hand-made pair of node sets (A = {1..10}, B = {1..8, 11, 12}: 1 - 8/12 = 0.3333); the summary table
for a fixed list of moves. PoB-backed (skips without the runtime): none beyond what exists.

Measurement, ONE PoB worker: `scripts/benchmark.py stormbrand --seeds 1 --no-variants --workers 1 --loop
--loop-seconds 600`: paste the table, `pob_calls`, `tree_churn`, and confirm the identity on the real build.

Check `cmd /c dir /AL` first (junctions). Focused tests, then the whole suite once, foreground. Do not edit
`docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
