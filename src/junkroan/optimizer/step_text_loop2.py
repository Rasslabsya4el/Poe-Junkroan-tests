"""Plain-words descriptions of build steps (#713): `TEXT[step name] = Description(...)`; a loop move is keyed `"move: <name>"`."""

from __future__ import annotations

from junkroan.optimizer.step_description import MOVE_PREFIX, Description

TEXT: dict[str, Description] = {
    MOVE_PREFIX + "gear": Description(
        what_it_changes=(
            "One rare gear slot of the build is re-rolled, one slot per trial, in the order the construction fills them: "
            "Weapon 1, Weapon 2, Body Armour, Helmet, Gloves, Boots, Belt, Amulet, Ring 1, Ring 2 (the slots the build "
            "has as rares; a slot held by a unique is not in the list). The item in the slot is replaced only if the new "
            "item wins the judging below."
        ),
        what_it_tries=(
            "The slot is first emptied in PoB, then filled from scratch under the loop's priced order, and the old item "
            "still competes with the new ones, so the slot can never get worse by a pass. On a day-1 template build "
            "(WishlistGear) the candidates are the template's bases, and each open line of the template is tried with the "
            "ordinary mods and bench crafts the rail rules allow (one attribute affix per item, no line the request "
            "forbids, the boots' Movement Speed line stays pinned). A weapon's lines follow rule 2: a candidate that "
            "makes any floor worse is refused outright, a candidate that adds +0 value is refused, and among the rest the "
            "best value wins. A candidate for an armour or jewellery slot follows rule 3: it must beat the item as it "
            "stands under the priced order, and it is refused when it removes less than 0.01 of floor violation at +0 value "
            "while the build is still infeasible. On a build that already meets every floor, a template slot's open lines "
            "are re-filled by value instead of floors first, so a damage line the tree then pays the floor for gets tried. "
            "On a non-template build (LootGear) the candidates are random rolls of the slot's base (a best-of-n draw, "
            "carrying the lines the request forces and the incumbent's Sockets line), the best few get their best legal "
            "bench craft, and the useful lines are counted."
        ),
        how_judged=(
            "Candidates are first compared with PoB's fast trial_stats. Then the finished item is equipped, its own lanes "
            "are re-derived, and if it breaks a floor the tree is asked once to repair it (refine with repair rounds only) "
            "before the verdict. The verdict compares the build's Score before and after under the priced score of D116: "
            "the objective's maximized stat (FullDPS or CombinedDPS) multiplied by one minus the relative floor violation (capped at 1), so a floor "
            "is bought with damage only at a fair price; a tie of priced values is broken by the violation and then the "
            "value, and a gain on a feasible build must clear min_gain (0.005 by default). The fixed-point check's extra "
            "pass keeps the older floors-first order instead."
        ),
        what_it_keeps=(
            "A kept item stays with the repair the tree made for it. A rejected item is rolled back by loading the "
            "snapshot taken before the slot was emptied, with the old item and the resistance plan restored. If the "
            "incumbent wins its own slot, nothing is judged at all and the move is recorded as not kept. After a rejected "
            "template value re-fill, the build state is remembered so the same refill is not repeated until something changes."
        ),
        when_skipped=(
            "Never skipped as a kind: every pass runs one gear trial per rare slot. A single slot trial ends early when the "
            "incumbent wins its own slot, or when a template slot's value re-fill was rejected before and the tree, "
            "config lanes, other items and gems are unchanged since. The slot is skipped entirely if a unique holds it."
        ),
        where="improvement_loop.py:ImprovementLoop._gear (the candidates: wishlist_gear.py:WishlistGear._choose_trial and fill_slot, loot_gear.py:LootGear.fill_slot)",
    ),
    MOVE_PREFIX + "weapon-base": Description(
        what_it_changes=(
            "The base type of a rare weapon (Weapon 1 or Weapon 2) is swapped for another base of the same item class, "
            "keeping the item's prefixes and suffixes with their rolls, its crafted lines, quality and sockets. Only "
            "the base (and with it the implicit, the Critical Strike Chance, Attacks per Second and Physical Damage of the "
            "base) changes."
        ),
        what_it_tries=(
            "Every other legal base of the equipped weapon's class (Wand, Sceptre, Dagger, Claw, One Handed Sword, Axe or "
            "Mace, Staff, Two Handed Sword, Axe or Mace, Bow) up to the rails' item level. On a template build the list "
            "comes from the wishlist's base level limit instead. Each candidate is re-crafted in PoB with the same affixes "
            "(craft_rare), and a candidate PoB cannot craft with those lines is dropped and counted in "
            "weapon_base_skipped."
        ),
        how_judged=(
            "All crafted candidates go to PoB's fast trial_stats in one batch and are scored by the objective. The best one "
            "under the loop's priced order (D116, FullDPS discounted by floor violation) is equipped and judged "
            "like any move: lanes re-derived, then accepted only if the priced score beats the current build by min_gain "
            "(0.005 by default). The judge is the exact one, restoring the whole saved state on a rejection."
        ),
        what_it_keeps=(
            "A kept swap records the old and new base and their base numbers on the move. A rejected swap is fully rolled "
            "back to the snapshot (XML, item bookkeeping and the skeleton's base), and the build state is remembered as "
            "rejected so the same trial is not re-run when nothing has changed."
        ),
        when_skipped=(
            "Skipped for a slot that holds a unique, a base the request forced, or a base whose item class is not a weapon "
            "class above. Also skipped when the fingerprint (allocated nodes, mastery effects, config lanes, gems and other "
            "items, current item text, the slot's base) equals the one of the last rejected trial, and when no candidate "
            "base or no craftable candidate exists. The plan holds one entry per Weapon 1 and Weapon 2 present."
        ),
        where="improvement_loop.py:ImprovementLoop._weapon_base and _weapon_base_move",
    ),
    MOVE_PREFIX + "ascendancy-swap": Description(
        what_it_changes=(
            "One allocated ascendancy node that does nothing for the build is swapped for another ascendancy node of the "
            "same ascendancy. A node is dead when removing it moves neither the objective nor TotalEHP by 0.1 % (the audit "
            "measures this by PoB's own removal). The dead node is removed and the new pick is added in PoB, and the "
            "ascendancy points spent may not rise."
        ),
        what_it_tries=(
            "Every ascendancy pick of the same ascendancy that is not allocated yet, with its path (PoB allocates the path "
            "in the trial). The candidates go to PoB's trial_stats in one batch in full mode. A candidate that costs more "
            "ascendancy points than the swap frees, or that would remove a node the request named, is dropped. One attempt "
            "is made per dead node, each judged on its own."
        ),
        how_judged=(
            "The best candidate by the objective under the priced order of D116 (FullDPS discounted by floor violation) "
            "is applied, the lanes are re-derived, and the build's Score is compared with the current one. The swap is kept "
            "only if it gains at least 0.1 % (the same share that makes a node dead), under the priced order and the current "
            "costs, so a swap that only moves the same damage is refused."
        ),
        what_it_keeps=(
            "A kept swap rewrites the skeleton's ascendancy nodes so the tree rebuilt after it keeps the new pick, and the "
            "note records the old and new node with its gain. A rejected swap is rolled back to the snapshot taken before "
            "the attempt. After a kept swap the dead nodes are measured again, because the swap can change what the next one is worth."
        ),
        when_skipped=(
            "Only in a plan whose rails give ascendancy points: the move is absent from the pass otherwise. Every pass "
            "measures the audit again (a picks or lanes move changes the gems, which can turn a node dead or alive); a dead node the request named (forced) or one that sits "
            "in no ascendancy. The move runs right after the path swaps, before the gear."
        ),
        where="improvement_loop.py:ImprovementLoop._ascendancy_swap (candidates: tree_hygiene.py:ascendancy_swap_candidates, dead nodes: tree_hygiene.py:dead_ascendancy_nodes)",
    ),
    MOVE_PREFIX + "picks": Description(
        what_it_changes=(
            "The discrete gem picks of the finished build: each support of the main link (except the request's fixed "
            "supports and the enablers) and each utility gem group the picker chose. While a floor is missed it may also "
            "turn off one reserving socket group (for example a reserving aura) to give the mana or life back."
        ),
        what_it_tries=(
            "For each support slot, every legal support from the generator's legal_supports list that is not already in "
            "the link (the first sweep ranks all of them, a later sweep keeps the best 12 per slot). For each picked "
            "utility group, every candidate gem of its own kind (a movement skill is replaced only by a movement skill). "
            "The reserving-group drop tries each enabled group by disabling it and asking PoB whether ManaUnreserved or "
            "LifeUnreserved rose; groups that give nothing back are not candidates."
        ),
        how_judged=(
            "Each alternative is scored by PoB under freshly derived lanes, and the best one is compared with the current "
            "build under the priced score of D116 (FullDPS discounted by floor violation), then verified once more under "
            "full lane re-derivation before it is kept. A swap needs the priced score to improve by min_gain (0.005 by "
            "default). The reserving-group drop is tried only on a build that misses a floor; a feasible build tries nothing. "
            "One sweep is made per pass."
        ),
        what_it_keeps=(
            "Swaps that pass both measurements stay and are listed in the pass notes as the support or utility replaced; "
            "a swap that fails the second measurement is put back. A kept change marks the build as changed so the next pass "
            "runs picks again, and a sweep that keeps nothing is done."
        ),
        when_skipped=(
            "Skipped when the main link has one gem or fewer and no extra group is picked or enabled. Also skipped when "
            "nothing in the build (tree, gear, kicks, aura levels, lanes) has changed since the last picks re-judge, "
            "because the re-judge is deterministic on an unchanged build."
        ),
        where="improvement_loop.py:ImprovementLoop._picks (the work: search/generator.py:rejudge_picks and drop_reserving_group)",
    ),
    MOVE_PREFIX + "kick-tree": Description(
        what_it_changes=(
            "The passive tree is shaken up by ruin and recreate: whole random branches worth about 20 points are removed, "
            "the same number of points is spent again by the greedy allocator that now sees the rest of the tree, and a "
            "refine of up to 10 rounds follows. The gear and gems are not touched."
        ),
        what_it_tries=(
            "A kick is a random draw: the branches ruined are chosen by a random generator seeded from the plan's seed, "
            "the pass number and the draw number, so a draw is reproducible. A pass makes 3 tree draws by default "
            "(kick_draws), each judged on its own, and no draw is skipped because an earlier one was kept. The tree "
            "optimizer's reoptimize already keeps or restores its own round by its own objective before the loop judges it."
        ),
        how_judged=(
            "If the build after the round equals the build before (same tree, same items), the draw is skipped without "
            "measuring. Otherwise the lanes are re-derived and the loop judges the draw like any move: the priced score of "
            "D116 (FullDPS discounted by floor violation) must beat the current build by min_gain (0.005 by default)."
        ),
        what_it_keeps=(
            "A kept draw replaces the tree and is noted as kick tree with its gain and draw number; it also gives the local "
            "moves another pass. A rejected draw is rolled back by loading the XML saved before the kick."
        ),
        when_skipped=(
            "Kicks run only in a pass where no local move kept anything, the loop has not stopped, and the pass is not the "
            "fixed-point check's local-only extra pass. When the plan restricts its moves, the kick must be named in them. A draw is "
            "skipped when the safety net time budget is reached or when it changes nothing."
        ),
        where="improvement_loop.py:ImprovementLoop._kicks and _kick_tree (tree_optimizer.py:TreeOptimizer.reoptimize)",
    ),
    MOVE_PREFIX + "kick-joint": Description(
        what_it_changes=(
            "Gear and tree are ruined together: two rare slots and a random tree branch worth about 16 points are emptied, "
            "then both sides are rebuilt and a short refine (6 rounds) follows. The two slots are the ones with the most "
            "damage headroom (weapons first), or a random pair if no slot shows headroom."
        ),
        what_it_tries=(
            "Headroom of a slot is measured by rolling it for damage alone (floors removed from the objective) and "
            "comparing the best roll with the current FullDPS. On an even draw number the gear is rebuilt for damage alone "
            "and the tree re-spend repairs the floors; on an odd draw the tree is re-spent for damage alone and the gear "
            "repairs the floors. A pass makes 4 joint draws by default (kick_draws), each with its own random stream, "
            "each judged on its own."
        ),
        how_judged=(
            "The round re-derives its own lanes. If the tree and items are the same as before, the draw is skipped. "
            "Otherwise the loop judges it by the priced score of D116 (FullDPS discounted by floor violation), which must "
            "beat the current build by min_gain (0.005 by default)."
        ),
        what_it_keeps=(
            "A kept draw stays and is noted as kick joint with its gain and draw number. A rejected draw is undone by "
            "loading the saved XML, the old item texts and the old resistance plan."
        ),
        when_skipped=(
            "Same as the tree kick: only in a pass where no local move kept anything, the loop has not stopped, and the "
            "pass is not the fixed-point check's extra pass; when the plan restricts its moves, it must be named in them. It runs after the tree "
            "kick's draws. A draw ends early when the safety net is reached or when it changes nothing."
        ),
        where="improvement_loop.py:ImprovementLoop._kicks and _kick_joint (the round: _joint_round, _slots_with_damage_headroom)",
    ),
}
