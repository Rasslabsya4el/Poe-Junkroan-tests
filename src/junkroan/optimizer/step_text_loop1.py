"""Plain-words descriptions of build steps (#713): `TEXT[step name] = Description(...)`; a loop move is keyed `"move: <name>"`.

This module: the improvement loop's opening, its passes, the fixed-point check, and the moves refine, swaps, regions,
corridors, aura levels and lanes. Written from improvement_loop.py, pipeline.py, objective.py and tree_optimizer.py.
"""

from __future__ import annotations

from junkroan.optimizer.step_description import MOVE_PREFIX, Description

TEXT: dict[str, Description] = {
    "loop opening": Description(
        what_it_changes=(
            "It settles the build's config choices before the first pass starts. The choices are the lists PoB offers "
            "(stance, exposure type, Pride's effect) and the identity: the bandit's extra passive points and the two "
            "pantheon gods. Afterwards it fixes the socket colours the way the final step will deliver them."
        ),
        what_it_tries=(
            "Every option of each list choice, and each pantheon god the rails do not already fix. The options come from "
            "the config that the skeleton's lanes derive, not from a hand-written list. If the tuned lanes leave a build "
            "that was feasible infeasible, it also runs one tree refine of up to 12 rounds that repairs the missed floors "
            "at the cheapest damage per violation."
        ),
        how_judged=(
            "PoB scores each option under the full objective (the floors first, then the maximized stat such as "
            "FullDPS or CombinedDPS). Pantheon ties are broken by EHP. These opening choices are measured and "
            "recorded, but they are not put through the loop's keep-or-revert rule: the loop starts from whatever the "
            "tuned lanes score."
        ),
        what_it_keeps=(
            "The best-scoring choices stay on the skeleton and every later re-derivation of the config re-applies them. "
            "The repair refine, if it runs, is a transaction: a PoB contract error drops it and restores the build. "
            "The ledger records the opening as pass 0."
        ),
        when_skipped=(
            "It is skipped when the loop is the fixed-point check's extra pass, and in the replay bench's "
            "plans (only a plan of kind loop opens with lanes). Otherwise never skipped. The repair refine runs only "
            "when the build is infeasible after the tuning."
        ),
        where="improvement_loop.py:ImprovementLoop._opening_lanes",
    ),
    "loop pass <N>": Description(
        what_it_changes=(
            "One pass of the improvement loop runs its moves one after another on the build PoB holds: the tree, "
            "the rare gear slots, the weapon bases, the support and group picks, the flat-reservation aura levels and "
            "the config lanes. A move changes the build only if it is kept. The pass is named loop pass 1, loop pass "
            "2 and so on."
        ),
        what_it_tries=(
            "The plan of a pass, in this order: tree refine, tree path swaps, one gear re-roll per rare slot "
            "(weapons first), a weapon base trial per weapon slot, picks, aura levels (only when the skeleton has a "
            "flat-reservation aura), and lanes. When none of these kept anything, two kicks follow: a tree kick "
            "(3 draws by default) and a joint gear-and-tree kick (4 draws). Corridors and regions are not in the "
            "default plan; they run only when a replay names them."
        ),
        how_judged=(
            "At the start of each pass the castability is refreshed and the build is scored again under the refreshed "
            "objective. Each move is then judged by PoB under lanes re-derived after the move, by the priced score of "
            "D116: value times (1 minus the relative floor violation, capped at 1). While a floor is missed, any better "
            "priced score is kept. Once the build is feasible, the priced score must grow by min_gain, 0.5% by default. "
            "A kept move updates the Score the next move starts from."
        ),
        what_it_keeps=(
            "Every kept move stays; a rejected move is rolled back to the snapshot taken before it. The pass notes what "
            "it kept. A pass that keeps nothing is the fixed point and ends the loop. The loop also ends at the pass limit "
            "(16 by default) or at the safety-net time budget, and says so in its note. On the last pass the socket "
            "colours are judged once more, so the build leaves on colours the loop has measured."
        ),
        when_skipped=(
            "Never skipped: pass 1 always runs. Later passes run only while the previous pass kept at least one move "
            "and the pass limit and time budget are not reached. Individual moves skip themselves under their own "
            "conditions, listed under each move."
        ),
        where="improvement_loop.py:ImprovementLoop.run",
    ),
    "repair pass <N>": Description(
        what_it_changes=(
            "The repair of one keystone choice on a finished build (the keystone held on or held off, repair.py) runs at "
            "most two passes of the improvement loop's moves from that build. Each pass is named repair pass 1 and repair "
            "pass 2. The repair runs no kicks and no time limit."
        ),
        what_it_tries=(
            "The moves of one loop pass with the keystone held as chosen: tree refine, tree path swaps, one gear re-roll per "
            "rare slot, a weapon base trial, picks, aura levels when the skeleton has a flat-reservation aura, and lanes. "
            "The repair ends after the first pass that gains less than 1% over the value before it, or after pass 2."
        ),
        how_judged=(
            "Each move is judged by PoB as in a loop pass, under the objective. The verdict reads the objective value after "
            "each pass: climbing when pass 2 gained at least 1% over pass 1, take when the last value is at least the value "
            "the repair started from, drop otherwise."
        ),
        what_it_keeps=(
            "A kept move stays and a rejected move is rolled back to its snapshot, as in a loop pass. The per-pass values "
            "are the repair's record; they are not a build the search keeps by themselves."
        ),
        when_skipped=(
            "Runs only when a keystone choice is repaired on a finished build (LoopPlan.repair). It is not part of the "
            "construction and not part of the loop of a build."
        ),
        where="improvement_loop.py:LoopPlan.repair; repair.py",
    ),
    "fixed point check": Description(
        what_it_changes=(
            "After the final config lanes, it runs one more pass of the loop's local moves on the finished build, to "
            "learn whether the loop really stopped at a fixed point. Whatever that pass keeps stays in the build. "
            "How much it gained is recorded as the build's fixed-point gain."
        ),
        what_it_tries=(
            "The same local moves as a normal pass: tree refine, path swaps, one gear re-roll per rare slot, weapon "
            "base trials, picks, and aura levels where the skeleton has a flat-reservation aura. There is no lane step and "
            "no kicks. Gear rolls use a seed offset far from every pass the loop ran (1,000,003), so they roll "
            "other items."
        ),
        how_judged=(
            "Moves are judged by the same rule as in the loop, but in the floors order rather than the priced score "
            "(#553): a move may not lower feasibility, and while feasible the value must grow by min_gain. If the pass "
            "kept something, the gain is the stage's value over the value before the pass, and above 1% it is reported "
            "as an audit error, otherwise as a warning. After the check, if the build's floor violation is above the "
            "entry value from before the final tuning (by more than the feasibility tolerance), the whole final tuning "
            "including this pass is reverted to the build the loop handed over."
        ),
        what_it_keeps=(
            "Every move the extra pass kept, unless the feasibility guard above reverts the final tuning. If the extra "
            "pass itself ran out of time before judging every move and kept nothing, nothing is claimed: the note says it "
            "stopped on the time budget."
        ),
        when_skipped=(
            "Skipped when the fixed-point check is switched off in the run options (it is on by default), and when the "
            "loop itself stopped on its time budget or its pass limit; then the build is known not to be at a fixed "
            "point, a warning is recorded, and no pass runs."
        ),
        where="pipeline.py:BuildPipeline._fixed_point_check",
    ),
    MOVE_PREFIX + "refine": Description(
        what_it_changes=(
            "It rearranges the passive tree without changing the number of points spent. It drops the least valuable "
            "leaf nodes and spends the freed points on better nodes."
        ),
        what_it_tries=(
            "Per round, one trial for each removable leaf, one for each candidate node (or cluster) of cost k, "
            "and one for each swap, up to 80 top candidates. Candidates come from the passive tree graph and PoB's "
            "trial calculations. The loop calls it with up to 10 rounds. While a floor is missed the swaps are a repair: "
            "the chosen swap is the one with the most violation removed per damage lost."
        ),
        how_judged=(
            "The tree optimizer accepts each swap on PoB's numbers under its own objective, with a minimum gain of 0.2%. "
            "The whole result is then judged by the loop: lanes re-derived, the build scored, and the priced score of D116 "
            "compared against the score before the move with min_gain 0.5%. "
            "The loop's rule can overrule the tree optimizer's inner verdict."
        ),
        what_it_keeps=(
            "If the loop's rule accepts, the new tree stays and the pass records a refine note with the change. If "
            "not, the build is restored exactly from the snapshot (XML, skeleton, gear bookkeeping, tree history). "
            "A kept refine also stops the region challenge in the same pass."
        ),
        when_skipped=(
            "Never skipped from the default plan: the first move of every pass, including the fixed-point check. "
            "A round that already measured every candidate on the same build returns at once, without new trials "
            "(the tree optimizer remembers the build it found nothing on)."
        ),
        where="improvement_loop.py:ImprovementLoop._refine_or_swaps (tree_optimizer.py:TreeOptimizer.refine)",
    ),
    MOVE_PREFIX + "swaps": Description(
        what_it_changes=(
            "It replaces small hanging parts of the passive tree with other nodes. Each such subtree is removed whole, "
            "and the freed points are spent greedily wherever the tree now wants them."
        ),
        what_it_tries=(
            "Every allocated node whose removal cascades off at most 6 nodes (subtrees containing protected nodes are "
            "excluded). They are ordered by the cheapest damage loss per point, and subtrees whose removal alone breaks "
            "a floor go last. It stops after 12 non-improvements in a row. In the loop no time or candidate-count cap "
            "is set."
        ),
        how_judged=(
            "The tree optimizer keeps a swap if PoB says its objective improved, with a minimum gain of 0.2%. The batch of "
            "kept swaps is then judged by the loop like refine: lanes re-derived, priced score of D116, min_gain 0.5%. "
            "If the batch is rejected, up to 12 of its steps are replayed one at a time under fresh lanes, and each is "
            "kept on its own if the same loop rule accepts it."
        ),
        what_it_keeps=(
            "The accepted batch, or the individual replayed swaps the loop rule accepts. A rejected batch is restored "
            "exactly from the snapshot. A false verdict (a swap that really scores lower, or whose config inputs got "
            "worse) is logged with the changed config inputs."
        ),
        when_skipped=(
            "Never skipped in the default plan; it runs after refine in every pass, including the fixed-point check. "
            "It does nothing when the tree has no small subtrees."
        ),
        where="improvement_loop.py:ImprovementLoop._refine_or_swaps (tree_optimizer.py:TreeOptimizer.swap_subtrees)",
    ),
    MOVE_PREFIX + "regions": Description(
        what_it_changes=(
            "It challenges whole detachable regions of the passive tree: a region is removed and its points are "
            "regrown elsewhere, to test whether a different trunk would be better."
        ),
        what_it_tries=(
            "Regions are grouped in buckets by size (16 per bucket) and each is given up to 12 cheap completed "
            "replacements of its own point count, each priced by one fast what-if. Regions are ordered by the best "
            "replacement, and the top 4 are challenged for real. The region's own nodes are forbidden for the first "
            "half of the regrowth, and two repair policies alternate."
        ),
        how_judged=(
            "The tree optimizer's own acceptance first (minimum gain 0.2%), then the loop's: lanes re-derived and the "
            "priced score of D116 compared with min_gain 0.5%. If the move kept no step, it is not judged at all, since "
            "the build is the one it started on, and it is recorded as kept nothing."
        ),
        what_it_keeps=(
            "A challenge accepted by the loop rule stays; otherwise the exact snapshot is restored."
        ),
        when_skipped=(
            "It is not in the default plan: it runs only when a replay names it in the plan's moves, placed after the "
            "swaps. Even then it is skipped in a pass where refine or the swaps already kept something. It was taken "
            "out of the default plan on the owner's word (comment in improvement_loop.py: 0.6% of the loop's gain for "
            "5.7% of its time)."
        ),
        where="improvement_loop.py:ImprovementLoop._trunk (tree_optimizer.py:TreeOptimizer.challenge_regions)",
    ),
    MOVE_PREFIX + "corridors": Description(
        what_it_changes=(
            "It swaps a corridor, the path of nodes between two key nodes of the passive tree, for another way "
            "between the same two key nodes."
        ),
        what_it_tries=(
            "Up to 40 corridors of the current tree. For each one, up to 8 alternative connections through "
            "unallocated nodes, shortest first, at most the corridor's length plus 2 points. The extra points of a "
            "longer way are paid by dropping the weakest leaves. Up to 8 exchanges are applied for real, bypass first, "
            "and each completed exchange is first scored by one fast what-if."
        ),
        how_judged=(
            "The tree optimizer's own acceptance (minimum gain 0.2%) and then the loop's: lanes re-derived, the priced "
            "score of D116 against the score before, min_gain 0.5%. A move that kept nothing is not judged "
            "and is recorded as kept nothing."
        ),
        what_it_keeps=(
            "An exchange set accepted by the loop rule; otherwise the exact snapshot is restored. The code comment "
            "records that on 96 delivered builds a bypass was found for 79 of 2,583 corridors and 2 exchanges were kept."
        ),
        when_skipped=(
            "It is not in the default plan: it runs only when a replay names it in the plan's moves, and then it is "
            "the first move of the pass."
        ),
        where="improvement_loop.py:ImprovementLoop._trunk (tree_optimizer.py:TreeOptimizer.exchange_corridors)",
    ),
    MOVE_PREFIX + "aura levels": Description(
        what_it_changes=(
            "It sets the gem level of each enabled flat-reservation aura (a non-mine reservation skill whose mana "
            "reservation is a flat amount), so that the reservation fits the build's mana floors."
        ),
        what_it_tries=(
            "For every such aura, every legal level from 1 up to the rails' gem level. Each level is a real write "
            "of the skill and a real PoB score. An aura whose best level is the rails' gem level carries no level "
            "override."
        ),
        how_judged=(
            "Within the move, the levels are ordered by the plan's score order, the priced score of D116 in the loop "
            "(floors order in the fixed-point check), and the first equal score wins, which keeps the lowest reservation "
            "when PoB finds no difference. The chosen levels are then judged by the loop's own rule: "
            "lanes re-derived, priced score against the score before, min_gain 0.5%."
        ),
        what_it_keeps=(
            "Accepted levels stay and the pass notes them as aura levels with each aura's name and level. A rejected "
            "result is restored from the snapshot, and the move is not tried again until another move changes the build."
        ),
        when_skipped=(
            "Skipped when the skeleton has no flat-reservation aura (the move is not in the pass plan), and "
            "skipped within a pass when nothing has changed since the last aura levels judgement or since its rejection."
        ),
        where="improvement_loop.py:ImprovementLoop._aura_levels (pipeline.py:tune_flat_reservation_aura_levels)",
    ),
    MOVE_PREFIX + "lanes": Description(
        what_it_changes=(
            "It judges the list choices of the config (stance, exposure type, Pride's effect) again for the build as "
            "it now stands. The choices follow the build, so a pass that changed the tree, the gear or the link ends "
            "with this step."
        ),
        what_it_tries=(
            "Each option of each list choice, derived from the build's current config lanes. The identity (bandit, "
            "pantheons) is not re-judged here; it is judged once in the loop opening and once in the final config step."
        ),
        how_judged=(
            "PoB scores each option under the current objective. The step is not a keep-or-revert move of the loop: it "
            "records the new score as kept when the number changed, and it never reverts. Afterwards the socket colours "
            "are judged under PoB's numbers, as the final step does."
        ),
        what_it_keeps=(
            "The tuned choices stay on the skeleton and every later config derivation re-applies them. A PoB contract "
            "error drops the move and restores the build from the snapshot."
        ),
        when_skipped=(
            "Skipped when no kept move has changed the build since the last lane tuning, and never part of the "
            "fixed-point check's plan (the extra pass is local only)."
        ),
        where="improvement_loop.py:ImprovementLoop._lanes (pipeline.py:BuildPipeline._tune_lanes)",
    ),
}
