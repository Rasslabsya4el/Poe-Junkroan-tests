# 2026-09-16 D60. The improvement loop judges under the final lanes

Status: Accepted

Context: the loop (D58) re-derives the lanes after every move (D45), but the
list choices (stance, exposure type, aura effect: `_tune_choice_inputs`) and
the identity (bandit, pantheons, the bandit's extra passive points:
`_tune_identity`) were judged only in `_finish`. So the loop optimized one
number and the build was reported with another: on loop-smoke-3 the "config
(final lanes)" stage stood +43% above the loop's last pass on
burning_arrow_snipe s1 (exposure Fire, bandit Alira), +16-18% on the three
bleed_bow seeds (Pride at MAX), +14.5% on impale_ballista s3 (Blood stance),
+2% on stormbrand, 0% on cold_dot. A fixed point measured under one objective
and reported under another is not the definition of done's item 3, and the
floors (max hit under Sand vs Blood stance) were judged in the wrong lane.

Decision: the loop's objective is the final lanes'. `_tune_lanes` judges the
choices and the identity once before pass 1 and the choices again at the end
of every pass whose moves changed the build (a "lanes" step after the picks);
the chosen values live on the skeleton (`tuned_choices`) and every reconfigure
re-applies them, the user's own config numbers winning as before. `_finish`
keeps its tuning as the last word. A 7.1 shape change: proven on the smoke
set x 3 seeds (`smoke-frozen-2`) against `smoke-frozen`; the campaigns start
after it.

Outcome (2026-09-16 19:29): reverted by its own gate (`scripts/compare_runs.py
smoke-frozen smoke-frozen-2 --min-delta -5 --revert-commit 7aa1c08`, commit
6250168). Median of medians 148.2 against 158.4 (-10.2): bleed_bow 56.9 vs
127.7 and burning_arrow_snipe 135.2 vs 214.4 fell, cold_dot, stormbrand and
SRS held. The sanity build showed why: the choices and identity tuned before
pass 1 left the same build infeasible (viol 0.345), and the loop bought the
floor back with a gear roll that cost 40% of the damage. The defect stays
(the loop's last pass sits 14-43% under the final lanes on four of six smoke
references) and the final numbers stay honest; a redo needs the repair
`_finish` runs after its tuning, a smoke proof, and a rerun of the campaigns.
The campaigns of 2026-09-16/17 (`new18-frozen`, `core14-frozen`) ran without D60.

Redone (2026-09-18, inside the 7.1h reopening D61 opened): the same shape, with the
two defects the revert named fixed. (1) The value under trial wins over the remembered
one: `_tune_choice_inputs` drops the var it is judging (and, for Elemental Army, its
three exposure flags) from `skeleton.tuned_choices` for the length of its own trials, so
a second tuning really compares the values instead of comparing the remembered value
with itself and keeping the first of the list -- that one line is the whole of
bleed_bow 127.7 -> 56.9 and burning_arrow 214.4 -> 135.2, and it now has the test that
would have caught it (two rounds on a PoB whose number follows the input, both choosing
the best value). (2) The opening tuning ends with `_finish`'s repair: a build the tuned
lanes leave infeasible gets `refine(max_rounds=12)` and a re-derivation, logged, before
pass 1, instead of the loop buying the floor back with a gear roll (the sanity build's
40% of the damage). `_finish` keeps its tuning as the last word. 5 tests in
`tests/test_improvement_loop.py` (call order, the merge, the persistence, the second
round, the repair); the two regression tests fail on the old code exactly as the
references did (the first value of the list wins). Gate unchanged: the smoke set x 3
seeds against `smoke-frozen`, and the number to read is "config (final lanes)" against
the last loop pass -- a few % apart instead of 7-47%, with no reference falling.

