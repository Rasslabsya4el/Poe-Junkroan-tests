# 2026-09-18 D66. The delivered build is never less feasible than the fixed point the loop reached

Status: Accepted

`BuildPipeline._finish` -- config lanes, the list choices, the identity (pantheons, the bandit's
extra points), the optimistic prune -- used to run after `_improvement_loop` with nothing judging
it. Every one of those steps can move a floored number, and none of them was ever asked whether it
had. The rule now: after each step the objective's `Score` is compared with the score before it
(feasibility first, value second, `keep_if_feasible`); a step that introduced or grew a violation is
reverted to its own pre-step snapshot and logged as `reverted: <step> broke <floor> = x < floor`; a
step that keeps feasibility is kept as before, whatever it does to the value -- value is the loop's
business. Where the code already iterates per choice (`_tune_choice_inputs`) the judgement is per
choice: the values are still ranked against each other (D24), and the winner is then ranked against
the build the tuning started from, so the best of a list that is entirely worse than the incumbent
state is put back. The loop's own `_tune_lanes` does not guard: it is allowed to tune into a
violation and buy the floor back with the tree, because a whole pass judges its result (D60).

Two things the guard cannot revert, and what happens instead. The final lane derivation is what the
build honestly is, not a choice, and `with_ramp` can hand the end of the run a new floor set. So the
last act of `_finish` is a check of the full objective: feasible -> `final feasibility: ok`;
infeasible -> the repair path (`refine(max_rounds=12)` and then the repair-only
`refine(max_rounds=0, repair_rounds=60)` the loop's gear move uses, with the lanes derived again);
still less feasible than the state `_finish` was handed -> the pre-`_finish` snapshot is loaded back
byte for byte, `final tuning reverted: <reason>` is logged, and nothing else runs on the build. The
verdict line is in the log and in the `config (final lanes)` stage note, so a benchmark log says it.

The repair is judged by the same rule, which it was not before: it refines under the tree's own
objective, so a round that pays there can be flat or worse under the objective the build is
delivered on, and a repair that buys no feasibility is only a DPS bill. Kept when the full
objective's Score improves, else reverted with
`reverted: repair after the final lanes bought nothing`. On the delivered cold_dot s2, replayed with
today's objective (which carries D64's `ElementalOverloadUptime >= 0.9`, a floor the 07:23 run did
not have), the repair pays and is kept: viol 0.873 -> 0.704 -- the movement floor cleared, 1.140 ->
1.19, and the Elemental Overload uptime 0.047 -> 0.196 -- for 46% of the number, 357,694 -> 192,985.
Feasibility first is exactly what the Score ordering says, and that build was never feasible.

One real defect found on the way and fixed with it: the repair gate asked
`self._trees[1].current_score()`, whose objective is the full one
`without("EffectiveMovementSpeedMod")` (D28: the tree may not chase movement speed). A build that
ended short of the movement floor was therefore never offered the repair at all -- cold_dot s2 of
`20260918-0723-rules-smoke` finished at `EffectiveMovementSpeedMod = 1.140 < 1.164` and its
`config (final lanes)` line carries no repair note, while stormbrand s3, whose floor was
`MoMUnreservedShare` (which the tree's objective does carry), does. The gate now reads
`self.objective`.

What the run actually showed, measured, so the rule is not credited with more than it does: in all
18 builds of `20260918-0723-rules-smoke` the violation at the loop's last pass and at
`config (final lanes)` is the same number (16 x 0.000 -> 0.000, stormbrand s3 0.076 -> 0.076,
cold_dot s2 0.021 -> 0.021). `_finish` broke nothing there. Both infeasible builds were already
infeasible when the loop handed them over, and from long before: stormbrand s3 sits at viol 0.076
from the pass that took Mind over Matter onwards, cold_dot s2 at 0.021 from `tree rebuilt on gear`,
its Two-Toned Boots losing to the incumbent at 1.140 in every one of its 12 passes. The guard is an
invariant that closes the surface, not a fix for those two numbers -- those are a loot and a
keystone question.

The fixed-point check (7.3, the extra pass of local moves after the final lanes) runs inside this
guard, between the repair and the final check: its own acceptance rule is feasibility-first, so it
cannot lower feasibility, and the final check is what makes that a guarantee of the build that is
delivered rather than of one step of it. A fallback undoes that pass with everything else, so its
gain and its "not at a fixed point" finding go back with it.

