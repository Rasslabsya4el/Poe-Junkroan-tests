"""Plain-words descriptions of build steps (#713): `TEXT[step name] = Description(...)`; a loop move is keyed `"move: <name>"`."""

from __future__ import annotations

from junkroan.optimizer.step_description import Description

TEXT: dict[str, Description] = {
    "tree seed toward <stat>": Description(
        what_it_changes=(
            "It spends a first share of the passive points on nodes that raise one stat the request named, "
            "before the general tree is grown. By default the share is 40 percent of the points still free "
            "(`seed_points` of the skeleton's scaling, default 0.4). The nodes are allocated in the build PoB holds."
        ),
        what_it_tries=(
            "A separate tree optimizer whose objective is only that one stat (the request's scaling stat) allocates nodes "
            "greedily, using the same candidate paths from the passive tree graph as the main tree step. "
            "Keystones the skeleton forbids stay forbidden, and nodes the skeleton protects (forced nodes) are not removed."
        ),
        how_judged=(
            "PoB measures each candidate on the one named stat only, not on CombinedDPS, FullDPS, or the floors. "
            "The step records the points it spent and the value of that stat afterwards. "
            "The build is then rejudged, and the stage is recorded under the full objective of the build."
        ),
        what_it_keeps=(
            "Every node it allocated stays; nothing is rolled back at this step. "
            "Later steps (tree greedy, tree rebuilt on gear, the improvement loop) may drop or swap these nodes, "
            "and the rebuild on gear seeds again the same way."
        ),
        when_skipped=(
            "It is skipped when the skeleton carries no scaling stat (the request did not ask to scale toward a stat). "
            "The step name on the page stands for any stat: the recorded name is `tree seed toward <that stat>`."
        ),
        where="pipeline.py:run (the seed call), pipeline.py:_seed_scaling",
    ),
    "tree greedy": Description(
        what_it_changes=(
            "It grows the passive tree from the skeleton's fixed start (ascendancy, fixed keystones, any seed) with the remaining passive points. "
            "The points are the level's limit minus what is already allocated. "
            "The gear at this moment is the first gear pass, rolled on an empty tree."
        ),
        what_it_tries=(
            "In rounds, it lists every candidate from the passive tree graph: single nodes and paths up to a maximum depth (6 in a normal run) "
            "that cost no more than the points left, capped at a maximum number of trials per round (300 in a normal run). "
            "Nodes of forbidden text, nodes that would break the attribute cap, and masteries above a cost limit are left out. "
            "Cluster candidates are added when the run enables them, and candidates that PoB found inert are skipped."
        ),
        how_judged=(
            "PoB measures every candidate as a trial on the current build. "
            "While the floors of the construction view of the objective hold, it takes the candidate with the best gain of the objective value per point spent. "
            "While a floor is missed, it estimates the points the cheapest repair needs and spends on the best gain only if enough points remain beyond that estimate plus a margin, otherwise it takes the candidate that removes most of the violation per point. "
            "The construction view differs from the loop's view: per the code comments it leaves out the movement speed floor and resource sustain."
        ),
        what_it_keeps=(
            "It keeps each allocation as it is made, one per round, and stops when the points are spent, no candidate is left, or no candidate improves the objective. "
            "The reason it stopped is written into the stage record. "
            "The gear pass that follows is run on this tree."
        ),
        when_skipped="never skipped",
        where="pipeline.py:run (tree.allocate), tree_optimizer.py:TreeOptimizer.allocate",
    ),
    "gear pass 2 (with tree)": Description(
        what_it_changes=(
            "It fills the rare gear slots again, now with the greedy tree in place, and PoB then judges the build with fresh config lanes. "
            "In a normal run it makes 2 passes (a screen makes 1) over the slots of the skeleton's rare bases. "
            "Unique items the skeleton names are put back where a refill empties their slot."
        ),
        what_it_tries=(
            "In the loot mode, per slot it rolls random rares on the skeleton's base with PoB's own spawn weights, "
            "600 rolls per slot by default for construction (60 in a screen), plus the item from the earlier pass as an incumbent. "
            "The best few by Score each get their best legal crafting-bench mod. "
            "In the wishlist mode the item shape is template-driven and PoB chooses only the open and bench lines. "
            "The request's forced affix lines are carried in both."
        ),
        how_judged=(
            "Each candidate item is trialled in PoB and compared by the Score of the objective in its floors order: "
            "the floors first, then the objective value (the construction objective, CombinedDPS or FullDPS by the skeleton's mode). "
            "The priced score of D116 is not used here; it belongs to the improvement loop. "
            "In the loot mode, the useful lines of the finished item are counted and the best counted item wins."
        ),
        what_it_keeps=(
            "The incumbent competes with the new rolls and a pass never trades down, so a slot keeps its earlier item unless a candidate wins. "
            "In a fill that leaves an emptied slot with infinite violation, the pass is built twice and the better complete gear set is kept. "
            "The fill never hands back a set that the start set outranks."
        ),
        when_skipped="never skipped",
        where="pipeline.py:run (loot.fill), loot_gear.py:LootGear.fill, wishlist_gear.py:WishlistGear.fill",
    ),
    "tree rebuilt on gear": Description(
        what_it_changes=(
            "It throws the tree away down to the ascendancy and the fixed keystones, grows it again on the finished gear, and keeps the new one only if it scores higher. "
            "The greedy tree was grown before the gear existed, so with the gear in place the best tree can be a different one. "
            "The comment in the code names an example of a 95-node cascade spent differently, 477k to 970k."
        ),
        what_it_tries=(
            "It makes two regrowths, one with the optimistic 'sum' repair estimate of the greedy allocator and one with the 'cover' estimate. "
            "Each regrowth re-applies the tree seed if the skeleton has a scaling stat, spends the free points greedily, then refines the tree by swapping weak leaf nodes for better candidates for up to 8 rounds. "
            "If the regrown tree is stronger but misses a floor, it refines for up to 16 more rounds first. "
            "The growth uses the construction view of the tree objective, with sustain and without movement."
        ),
        how_judged=(
            "After each regrowth the config lanes are rejudged for the new tree, then PoB scores the build under the objective the build is delivered on, with its floors. "
            "The better of the two regrowths is compared with the previous tree by `better_score` (floors first, then the value). "
            "The priced score of D116 is not used in this step."
        ),
        what_it_keeps=(
            "If the better regrowth beats the previous tree it is loaded and kept; otherwise the snapshot of the previous tree and its lanes is restored (reverted). "
            "The note of the stage record says which, with the values of both regrowths. "
            "The tree that stands after this step is stored as the construction tree."
        ),
        when_skipped=(
            "It is skipped in a screen run (a cheap run that ranks skeletons) and when the caller turns the rebuild off (`rebuild_tree` false). "
            "Otherwise it runs on every build."
        ),
        where="pipeline.py:run, pipeline.py:_rebuild_tree",
    ),
    "anoint": Description(
        what_it_changes=(
            "It picks one passive notable to anoint on the amulet with oils, on the finished tree and gear. "
            "The anoint is written into the amulet's text, and every later amulet the gear step makes carries it. "
            "The step runs right after the tree is rebuilt on gear and before the flasks."
        ),
        what_it_tries=(
            "Every notable that the oil rail allows (the oil limit, Black by default) and that the tree does not already hold is a candidate. "
            "Each is measured on the same amulet with no anoint. "
            "The candidate list comes from the anoint candidate table (`anoint_candidates`)."
        ),
        how_judged=(
            "PoB measures the plain amulet and each anointed amulet as item trials in one fast batch (an item trial with the explicit Allocates line equals a full equip, 0.0 percent, per the test named in the code), under the objective's Score. "
            "The candidates are ranked by that score and the best is taken only if it is strictly above the plain amulet. "
            "The priced score of D116 is not named in this step's code; which score order it uses beyond `objective.score` is not established."
        ),
        what_it_keeps=(
            "The best anoint stays if it beats the plain amulet; if none does, the amulet stays plain and the note says 'none'. "
            "The pick and the candidate list are stored so the anoint re-pick after the improvement loop can judge the ten best again on the final tree. "
            "The stage record shows the score before and after, how many were measured, and the time."
        ),
        when_skipped=(
            "It is skipped in a screen run, and when the build wears no amulet. "
            "It also does nothing, with a log line, when the amulet's base cannot be anointed or the amulet text cannot take the anoint line."
        ),
        where="pipeline.py:_anoint_step, anoint_step.py:pick_anoint, anoint_candidates.py",
    ),
    "flasks": Description(
        what_it_changes=(
            "It fills the flask slots with magic flasks and tinctures, up to the number of slots the gear rails allow. "
            "Which flasks are active is derived by PoB's own flask uptime calculation, never set by this step. "
            "It runs after the anoint and before the jewels."
        ),
        what_it_tries=(
            "Per slot, the flask the build came in with is the first candidate. "
            "Every allowed base up to the wishlist base level cap is tried bare, the top 3 bases are kept, and for each the best prefix and then the best suffix is tried, at the item level of the gear rail. "
            "Tinctures are included only if the rails allow them. "
            "Unless the build is pure energy shield, the first slot is fixed to a Divine Life Flask."
        ),
        how_judged=(
            "PoB scores each candidate placed in the slot by the whole objective Score (floors, then the value); on a tie the defence gain over the empty slot decides, compared as TotalEHP, then PhysicalMaximumHitTaken, then EffectiveMovementSpeedMod. "
            "A replacement must beat the input strictly. "
            "When all candidates tie because every flask is inactive, the search is repeated with the active flag forced on for the trial only; the remaining ties go to the lower level requirement."
        ),
        what_it_keeps=(
            "The picks stay in their slots and are written to the build; no slot is left empty while a candidate can be tried. "
            "A later move that empties a flask slot has it put back by the restore step. "
            "The record shows the score before and after and how many candidates were measured."
        ),
        when_skipped=(
            "It is skipped in a screen run, when the rails give zero flask slots, and when the PoB session cannot equip items. "
            "Otherwise it runs on every build."
        ),
        where="pipeline.py:_flask_step, flask_step.py:run_flask_step",
    ),
}
