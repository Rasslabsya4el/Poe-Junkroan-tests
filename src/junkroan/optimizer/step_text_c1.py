"""Plain-words descriptions of build steps (#713): `TEXT[step name] = Description(...)`; a loop move is keyed `"move: <name>"`.

Unit c1: the opening of the construction (skeleton, first config, the two gear-first routes, the flat-reservation
aura levels and the no-number support repair). Every claim was read in `pipeline.py` `run()` and the functions it calls."""

from __future__ import annotations

from junkroan.optimizer.step_description import Description

TEXT: dict[str, Description] = {
    "skeleton applied": Description(
        what_it_changes=(
            "This step puts the skeleton into a blank PoB build: the level, the class and ascendancy with its ascendancy nodes, "
            "the keystones, the request's forced passive nodes, the gem groups, the unique items, the flasks and the jewels the skeleton already names. "
            "It leaves rare gear and the rest of the passive tree empty for later steps."
        ),
        what_it_tries=(
            "When the skeleton has no fixed skill part, it tries every part of the main skill (up to 8, until PoB clamps the index) and keeps the part with the best objective score; "
            "parts that are only an assumption (such as Maximum Hits) are skipped. "
            "A random-element skill is scored as the mean over its element parts instead. "
            "For minion skills it derives the instance counts PoB multiplies by (for example zombies, sentinels, brands) and tries minion skill 1 to 4 of each minion gem, keeping the best score."
        ),
        how_judged=(
            "The part choice and the minion skill choice are judged by the objective score read from PoB (the maximized stat such as FullDPS or CombinedDPS, with the floors ranked first). "
            "The instance counts are derived from PoB's own gem data, not scored. "
            "Applying the skeleton itself is not judged."
        ),
        what_it_keeps=(
            "It keeps the skeleton's own choices and the best skill part or minion skill that PoB measured. "
            "The castability context is refreshed whenever the gem counts changed. "
            "Nothing is rolled back, because this is the first record of the build."
        ),
        when_skipped="never skipped; the pipeline always starts here. The part search runs only when the skeleton has no main part, and the minion tuning only when the skeleton carries a minion gem.",
        where="pipeline.py:run",
    ),
    "config (conservative lane)": Description(
        what_it_changes=(
            "This step writes the first config into PoB so that every later evaluation sees a defensible set of config inputs. "
            "It derives two lanes, a conservative one and an optimistic one, and writes both. "
            "It also sets up the objective's contexts: the ramp, the main skill's tags, the main gem group and its self-cost."
        ),
        what_it_tries=(
            "It does not try alternatives. "
            "It derives the lanes from the build PoB holds, using the config rules with the rules preferred, and it does so twice, because a cap can depend on an ordinary conservative input such as bleed chance, attack rate or duration. "
            "The second derivation is written with the first one's inputs already in place."
        ),
        how_judged=(
            "No PoB judging happens here; the lanes come from rules over PoB's parsed data, not from a score. "
            "The record that follows reads the build's stats, and its note counts the inputs switched on in the conservative lane."
        ),
        what_it_keeps=(
            "It keeps the conservative lane as the config PoB scores under, with the optimistic lane stored beside it. "
            "The user's own config numbers win over the lane, a poison count is capped by the lane's counted poison stacks, and a config var PoB does not know is dropped and logged. "
            "The skeleton's tuned choices are re-applied on every write."
        ),
        when_skipped="never skipped.",
        where="judging.py:Judging.open (called from pipeline.py:run)",
    ),
    "rig gear": Description(
        what_it_changes=(
            "This step fills the gear slots with a quick, small set of rolled rares before any real tree exists, so that the tree built next has a gear partner to be judged against. "
            "It exists only in the rig-first construction order. "
            "The gear it leaves is a starting point: gear pass 1 (rig tree) fills the slots again, and the incumbents compete."
        ),
        what_it_tries=(
            "For each slot of the skeleton's rare bases it rolls 40 random rares (n=40, one pass) with the gear filler of the chosen gear mode (loot or wishlist), "
            "using a seed derived for this purpose. "
            "The filler also tries bench crafts for the best rolls and counts useful lines. "
            "The skeleton's unique items are put back if a refill dropped a weapon's pair."
        ),
        how_judged=(
            "Every rolled rare is trialled in PoB and ranked by the objective score under the floors order: the build having a number first, then the fewest floor violations, then the maximized stat. "
            "The best one per slot is kept. "
            "The filler also keeps the best gear set it held across its own passes."
        ),
        what_it_keeps=(
            "It keeps the best-scoring item per slot, with a slot that finds no candidate staying as it was. "
            "A slot's incumbent competes and is never traded down."
        ),
        when_skipped=(
            "Skipped in the classic construction order, which is the default; it runs only when the run is started with construction rig-first "
            "(the --construction option of scripts/benchmark.py and scripts/build_from_skeleton.py). The log then reads step skipped."
        ),
        where="pipeline.py:run (loot.fill, loot_gear.py:LootGear.fill / wishlist_gear.py:WishlistGear.fill)",
    ),
    "rig tree": Description(
        what_it_changes=(
            "This step grows a temporary passive tree on top of the rig gear, using half of the build's passive points. "
            "Its purpose is to give the real first gear fill a tree to be judged with instead of an empty one. "
            "The tree is removed again right after gear pass 1 (rig tree)."
        ),
        what_it_tries=(
            "The greedy tree optimizer looks at the allocatable nodes within its reach (candidates with a path cost within the remaining points, from the tree graph) "
            "and tries at most 300 trial nodes per round. "
            "It adds the best node, then repeats until half the points are spent or it runs out of candidates."
        ),
        how_judged=(
            "Each trial is measured in PoB and scored by the objective under the construction view: floors first, then the maximized stat. "
            "A node is added only when it improves the score, or when a floor is violated and the node reduces the violation. "
            "The record's note is the optimizer's stop reason, for example no candidates, no candidate improves the objective, or budget spent."
        ),
        what_it_keeps=(
            "Nothing of the rig tree itself survives: the tree is reset to the skeleton's fixed tree choices (class, ascendancy, keystones, forced nodes, jewels) before the normal greedy tree starts. "
            "What survives is the rig gear's effect on gear pass 1."
        ),
        when_skipped="Skipped in the classic construction order (the default); it runs only with construction rig-first.",
        where="pipeline.py:run (tree.allocate, tree_optimizer.py:TreeOptimizer.allocate)",
    ),
    "gear pass 1 (rig tree)": Description(
        what_it_changes=(
            "This step is the first full gear fill of a rig-first build, made against the temporary rig tree. "
            "After it the rig tree is removed and the config lanes are derived again, so the gear stays and the tree starts again from the skeleton's fixed choices."
        ),
        what_it_tries=(
            "For every slot of the skeleton's rare bases it rolls a full batch of random rares: the rails' construction_best_of_n (600 by default) unless the caller gave loot_n, and a small roll for a screen run. "
            "Each slot's incumbent competes with the new rolls. "
            "The best rolls also get their best legal bench craft, and the useful-line count drops lines that give nothing. "
            "The wishlist gear mode fills fixed day-1 templates instead of free rolls."
        ),
        how_judged=(
            "Every roll is trialled in PoB and ranked under the floors order: has a number, then fewest floor violations, then the maximized stat. "
            "After the fill the lanes are re-derived (a rejudge) so the record carries the lane of the new gear. "
            "The fill keeps the best gear set it saw."
        ),
        what_it_keeps=(
            "It keeps the gear set. A slot never trades down because the previous item competes. "
            "The rig tree is thrown away and the construction tree optimizer's history is cleared."
        ),
        when_skipped="Skipped in the classic construction order (the default), where gear pass 1 (empty tree) runs instead; it runs only with construction rig-first.",
        where="pipeline.py:run (loot.fill, _reset_construction_tree)",
    ),
    "gear pass 1 (empty tree)": Description(
        what_it_changes=(
            "This step is the first full gear fill of a classic build. "
            "It puts rolled rare items on every slot of the skeleton's rare bases while the passive tree holds only the skeleton's fixed nodes. "
            "The gear is later refilled in gear pass 2 once the tree exists."
        ),
        what_it_tries=(
            "For each slot it rolls the rails' construction_best_of_n random rares (600 by default; a caller's loot_n wins, a screen run uses a small roll) in the gear mode chosen, loot or wishlist. "
            "The best rolls also try their best legal bench craft, and the useful-line count removes lines that give nothing. "
            "The wishlist mode fills fixed day-1 templates instead of free rolls."
        ),
        how_judged=(
            "Every roll is trialled in PoB and ranked under the floors order: has a number, then fewest floor violations, then the maximized stat. "
            "The lanes are re-derived after the fill, so the record carries the config of the new gear; "
            "when the build has a flat-reservation aura, the record is written after the aura-level step's own rejudge."
        ),
        what_it_keeps=(
            "It keeps the best-scoring item per slot and the best gear set across the fill's internal passes. "
            "When an emptied slot leaves the build with no number at all, the pass is built twice and the better set is kept."
        ),
        when_skipped="Skipped when the run uses the rig-first construction order; with the default classic order it always runs.",
        where="pipeline.py:run (loot.fill, loot_gear.py:LootGear.fill, wishlist_gear.py:WishlistGear.fill)",
    ),
    "config re-derived (after gear pass 1)": Description(
        what_it_changes=(
            "This step is a correction line, not a move: the config lanes are derived again after the first gear fill, "
            "and when any config input changed the line records the change as pairs of old and new values. "
            "The first gear fill's own record keeps the value from before the rejudge, and this line carries the effect of the rejudge."
        ),
        what_it_tries=(
            "It tries nothing. It compares the config inputs PoB held before the rejudge with those after, key by key. "
            "The new lanes are derived from the build as it now stands, including the gear that was just filled."
        ),
        how_judged=(
            "No PoB judging happens; the step only reads the config inputs before and after a rejudge. "
            "The record that follows reads the build's stats like any stage."
        ),
        what_it_keeps=(
            "It keeps the re-derived lanes as the config of the build. "
            "Its effect is charged to this line and to nothing else (#176), so no move gets credit for what the config change did."
        ),
        when_skipped=(
            "Runs only when the build carries a flat-reservation aura and a config input actually changed in the rejudge; "
            "otherwise it is logged as skipped. A build with no flat-reservation aura never reaches it."
        ),
        where="pipeline.py:_flat_reservation_stage",
    ),
    "flat-reservation aura levels": Description(
        what_it_changes=(
            "This step chooses the gem level of each enabled aura whose reservation is flat, such as an aura that reserves a fixed amount of mana, "
            "because a lower level reserves less and can free mana or sustain. "
            "A level is written into the skeleton's aura_levels and applied to the gem groups in PoB."
        ),
        what_it_tries=(
            "The auras come from PoB's own level data (a flat manaReservationFlat reservation on a non-mine skill, among the gems the build carries). "
            "For each aura it tries every level from 1 up to the rails' gem level, one real skills write and one score per level."
        ),
        how_judged=(
            "Each level is scored with the complete current objective under the floors order: a level that makes a mana, sustain or defensive floor fail loses. "
            "The first of equal scores wins, which keeps the lowest reservation when PoB sees no difference. "
            "In the improvement loop the same choice is made again under the priced score of D116; this construction run uses floors."
        ),
        what_it_keeps=(
            "It keeps the best level per aura, and an aura whose best level is the rail level carries no override. "
            "The lanes are re-derived afterwards. "
            "The record's note lists each aura with its level, or says rail."
        ),
        when_skipped="Runs only when the skeleton has an enabled aura with a flat reservation; otherwise it is logged as skipped.",
        where="pipeline.py:tune_flat_reservation_aura_levels (called from pipeline.py:_flat_reservation_stage)",
    ),
    "supports re-picked (no number)": Description(
        what_it_changes=(
            "This is a repair of the main link's supports, run right after gear pass 1 when the build has no number at all (the maximized stat is not above 0). "
            "A weapon variant can inherit supports another weapon chose, for example a sword finalist's Close Combat, which zeroes Smite on a staff or a sceptre, "
            "so the supports are chosen again on the rig as it stands."
        ),
        what_it_tries=(
            "The generator's greedy support pick adds the best support one at a time until the link holds as many supports as before (at least 1, at most the rails' main link maximum minus one). "
            "Fixed supports the request named and the enablers stay in place. "
            "The candidate supports come from the generator's legal support list for the skeleton."
        ),
        how_judged=(
            "Every candidate support is scored in PoB with the config lanes re-derived after each pick, so a support that only wins under a stale assumption is rejected. "
            "A candidate is added only when its score is strictly greater than the link's score so far. "
            "The note records the supports before and after."
        ),
        what_it_keeps=(
            "It keeps the picked supports. "
            "If the build still has no number after this step the run raises an error saying the skill cannot be used with this skeleton, so a build that cannot be scored never gets ranked."
        ),
        when_skipped=(
            "Skipped when gear pass 1 already left a number above 0, or when the main link carries no support that is neither fixed by the request nor an enabler. "
            "In the normal case it is logged as skipped."
        ),
        where="pipeline.py:_revive_supports (condition in pipeline.py:run and _revivable_supports)",
    ),
}
