# 2026-09-20 D88. The trunk gets one move of its own (region challenge); the corridor exchange is a measured negative; a floor bought by killing the build is not bought

Status: Accepted; amended by D88 amd 1

Tree research, step B (spec `docs/specs/2026-09-20-tree-plan-b-corridors-and-regions.md`, Opus coder, merged
a259cb9..66db266). Replay bench (D84), seed 1, 96 delivered builds. **Corridor exchange** (a run of travel nodes
between two key nodes swapped for one of the k=8 shortest bypasses within slack 2): a bypass exists for 79 of 2,583
corridors (3.1%; graph-only: 1.1% at slack 0, 9.1% at slack 6 -- the passive tree is locally a tree, and a bypass
needs UNALLOCATED nodes beside the corridor), trunk share 0.6%, 1/94/1, 2 kept. It stays in the bench
(`--move corridors`), never in the default plan. **Region challenge** (a key node's downstream side of 4-30 points,
ranked by the best of 12 cheap completed replacements, removed for real and regrown with its own nodes forbidden for
half the points, greedy alternating with a target-first repair): on the 55 starts feasible under today's rules
8/47/0, mean +0.43%, best +11.26%, 42 s a build, +0.96% per 100 s against the kick's +0.41%; trunk share 34%; the two
repair policies kept 34 each; RESTORE FAILED 0. It joins the default loop plan after the path swaps, only when refine
and swaps kept nothing in the pass; a paired default loop pass on the six smoke builds through the queue gave
identical gains on 6 of 6 at 0.96x the seconds (12 challenged, 0 kept): harmless where it finds nothing. Reading of
the tree line (MIP negative, corridors negative, regions +0.43%): the greedy trunk is near its best at day 1; what is
left is step C (branch exchange between seeds) and the far-sight packages. Both verdicts are DAY-1 verdicts: the
re-test at the endgame loadout is the graph-only bypass count on endgame trees plus `--move corridors` (minutes).
**The hole the move exposed, closed in `objective.better_score`:** while a floor is missed any better Score wins,
and a build that deals NO damage meets every floor -- stormbrand-s1 was kept at FullDPS 0 (the regrow took Voracious
Flame + Bitter Frost, "cannot deal non-fire" + "cannot deal non-cold", to remove an EHP violation of 0.012). Rule: a
new score with value <= 0 never beats a current score with value > 0. Open: five keep sites inside the tree
optimizer and the lane tuning compare Scores directly (`tree_optimizer.py` refine / reoptimize / swap_subtrees,
`pipeline.py` aura levels / list options); the loop's judge stands behind the first three; moving the rule into the
Score ordering itself needs a bench A/A.


## Amendment 1 (2026-10-03, [Move the "no damage never beats damage" rule into the Score ordering](https://github.com/Rasslabsya4el/Poe-Junkroan/issues/15))

The rule moved into the type. `Score` orders by `(value > 0, neg_violation, value)`: every score with value <= 0
ranks below every score with value > 0; inside each class violation first, then value (a repair of a dead build
still progresses). Every raw comparison (`max`, `sorted`, `>`) at the ~28 sites of the tree optimizer, the
pipeline, the jewel / flask / anoint steps, the generator and the gear fillers inherits it. `better_score` keeps
its own behaviour exactly: it compares the old tuple `(neg_violation, value)` explicitly, since the type's order
would also let a live move with a larger violation replace a dead build. `keep_if_feasible`, `repair_key` and the
`_choose` keys are not Score comparisons and are untouched. Proof (kind B, D113): D84's bench on the smoke six,
`--move loop --passes 1`, seed 1, base e309d80 against head 83461a4: finals equal to the digit on 6 of 6, ties
6 of 6. `jewel_step.py` sees a `Score` only through a test fake today (the real probe returns a float).
