# Spec (experiment behind a switch, default unchanged): the first gear is chosen against a rough tree, not an empty one

Why (`docs/research/2026-09-19-components-plan.md`, item 4): construction today is gear pass 1 (full loot fill against
an EMPTY tree, 114 s on a typical build, 182 k of a final 1.09 M) -> tree greedy -> gear pass 2 -> tree rebuilt on
gear. The literature on interdependent components calls building one part against an empty partner "a convention, not
evidence". The search already builds a cheap rig before the screen (`scripts/search.py rig_supports`: best-of-40 loot,
one pass, then half a tree with `max_trials=300`). This task lets the pipeline do the same INSIDE construction and
measures whether it changes anything. The gem-count fix and the judge fix are merged; construction now also chooses flat-reservation aura levels after the
first gear fill (D86): keep that step where it is in both arms.

## The switch

`BuildPipeline(..., construction="classic" | "rig-first")`, `scripts/benchmark.py --construction rig-first`, same on
`scripts/build_from_skeleton.py`. Default `classic`: byte-identical behaviour.

`rig-first` replaces ONLY the stage "gear pass 1 (empty tree)" by three recorded stages:
1. "rig gear" -- `LootGear.fill(passes=1, n=40)` (the rig's numbers; with `--gear wishlist` the template filler as is);
2. "rig tree" -- `TreeOptimizer.allocate(points // 2)` with `max_trials=300` under the same objective the tree greedy
   uses;
3. "gear pass 1 (rig tree)" -- the ordinary full gear pass 1, now against the rig tree.
Then the rig tree is REMOVED and "tree greedy" runs from scratch exactly as today, and everything after it is
unchanged. (Keeping the rig tree as the start of the greedy is a different experiment; not this one.)

Also `--construction-only` on `scripts/benchmark.py`: stop after "tree rebuilt on gear", write the row (value,
violation, seconds per stage) and the build; no loop, no variants.

## Measurement (the numbers to report)

`scripts/benchmark.py --set smoke --seeds 3 --construction-only --no-variants --workers 5 --tag construct-classic`
and the same with `--construction rig-first --tag construct-rig` (about 18 builds x ~9 min / 5 workers = ~35 min
each; a 5-worker benchmark may be running: then use `--workers 2` and say so). Report per reference the median value
at "tree rebuilt on gear" for both arms, the ratio, the construction seconds of both arms, and the number of
references where rig-first is higher. Verdict is the lead's (the noise of one build is ~15%: do not claim a winner).
A before / after comparison is a measurement, never a test that runs another commit's code.

## Tests

Fast, fake PoB: `classic` records exactly today's stage names in today's order; `rig-first` records the three new
stages in place of "gear pass 1 (empty tree)" and the tree is empty again when "tree greedy" starts;
`--construction-only` ends after "tree rebuilt on gear" with a row whose `stages` end there.

Check `cmd /c dir /AL` first (junctions). Focused tests, then the whole suite once, foreground. Do not edit
`docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
