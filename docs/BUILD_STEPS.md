# How a build is made

A build starts as a skeleton: a class, an ascendancy, a main skill, supports and a few chosen items. The construction steps give it a first config, gear and passive tree, one after the other, each judged by the numbers Path of Building (PoB) computes for the build after the change.

Then the improvement loop tries moves (tree, gear, supports picks, kicks) again and again until no move improves the build any more (a fixed point), and the finish steps re-pick the anoint, derive the final config lanes and export the build. Every change is kept only when PoB's numbers say it is better.

Times are medians over the builds of the run `20261005-1220-gate-20261005` (61 builds).

## Construction

### skeleton applied

Step name: `skeleton applied`

**What it changes.** This step puts the skeleton into a blank PoB build: the level, the class and ascendancy with its ascendancy nodes, the keystones, the request's forced passive nodes, the gem groups, the unique items, the flasks and the jewels the skeleton already names. It leaves rare gear and the rest of the passive tree empty for later steps.

**What it tries.** When the skeleton has no fixed skill part, it tries every part of the main skill (up to 8, until PoB clamps the index) and keeps the part with the best objective score; parts that are only an assumption (such as Maximum Hits) are skipped. A random-element skill is scored as the mean over its element parts instead. For minion skills it derives the instance counts PoB multiplies by (for example zombies, sentinels, brands) and tries minion skill 1 to 4 of each minion gem, keeping the best score.

**How it is judged.** The part choice and the minion skill choice are judged by the objective score read from PoB (the maximized stat such as FullDPS or CombinedDPS, with the floors ranked first). The instance counts are derived from PoB's own gem data, not scored. Applying the skeleton itself is not judged.

**What it keeps.** It keeps the skeleton's own choices and the best skill part or minion skill that PoB measured. The castability context is refreshed whenever the gem counts changed. Nothing is rolled back, because this is the first record of the build.

**When it is skipped.** never skipped; the pipeline always starts here. The part search runs only when the skeleton has no main part, and the minion tuning only when the skeleton carries a minion gem.

Where: `pipeline.py:run`

Median time: 3 s; share of the build time: 0.1 % (ran in 61 builds).

### first config

Step name: `config (conservative lane)`

**What it changes.** This step writes the first config into PoB so that every later evaluation sees a defensible set of config inputs. It derives two lanes, a conservative one and an optimistic one, and writes both. It also sets up the objective's contexts: the ramp, the main skill's tags, the main gem group and its self-cost.

**What it tries.** It does not try alternatives. It derives the lanes from the build PoB holds, using the config rules with the rules preferred, and it does so twice, because a cap can depend on an ordinary conservative input such as bleed chance, attack rate or duration. The second derivation is written with the first one's inputs already in place.

**How it is judged.** No PoB judging happens here; the lanes come from rules over PoB's parsed data, not from a score. The record that follows reads the build's stats, and its note counts the inputs switched on in the conservative lane.

**What it keeps.** It keeps the conservative lane as the config PoB scores under, with the optimistic lane stored beside it. The user's own config numbers win over the lane, a poison count is capped by the lane's counted poison stacks, and a config var PoB does not know is dropped and logged. The skeleton's tuned choices are re-applied on every write.

**When it is skipped.** never skipped.

Where: `judging.py:Judging.open (called from pipeline.py:run)`

Median time: 0.8 s; share of the build time: 0.0 % (ran in 61 builds).

### rig gear (rig-first only)

Step name: `rig gear`

**What it changes.** This step fills the gear slots with a quick, small set of rolled rares before any real tree exists, so that the tree built next has a gear partner to be judged against. It exists only in the rig-first construction order. The gear it leaves is a starting point: gear pass 1 (rig tree) fills the slots again, and the incumbents compete.

**What it tries.** For each slot of the skeleton's rare bases it rolls 40 random rares (n=40, one pass) with the gear filler of the chosen gear mode (loot or wishlist), using a seed derived for this purpose. The filler also tries bench crafts for the best rolls and counts useful lines. The skeleton's unique items are put back if a refill dropped a weapon's pair.

**How it is judged.** Every rolled rare is trialled in PoB and ranked by the objective score under the floors order: the build having a number first, then the fewest floor violations, then the maximized stat. The best one per slot is kept. The filler also keeps the best gear set it held across its own passes.

**What it keeps.** It keeps the best-scoring item per slot, with a slot that finds no candidate staying as it was. A slot's incumbent competes and is never traded down.

**When it is skipped.** Skipped in the classic construction order, which is the default; it runs only when the run is started with construction rig-first (the --construction option of scripts/benchmark.py and scripts/build_from_skeleton.py). The log then reads step skipped.

Where: `pipeline.py:run (loot.fill, loot_gear.py:LootGear.fill / wishlist_gear.py:WishlistGear.fill)`

Runs only when: the request asks for the rig-first construction.
Median time: none: no build of this set (61 builds) met the condition.

### rig tree (rig-first only)

Step name: `rig tree`

**What it changes.** This step grows a temporary passive tree on top of the rig gear, using half of the build's passive points. Its purpose is to give the real first gear fill a tree to be judged with instead of an empty one. The tree is removed again right after gear pass 1 (rig tree).

**What it tries.** The greedy tree optimizer looks at the allocatable nodes within its reach (candidates with a path cost within the remaining points, from the tree graph) and tries at most 300 trial nodes per round. It adds the best node, then repeats until half the points are spent or it runs out of candidates.

**How it is judged.** Each trial is measured in PoB and scored by the objective under the construction view: floors first, then the maximized stat. A node is added only when it improves the score, or when a floor is violated and the node reduces the violation. The record's note is the optimizer's stop reason, for example no candidates, no candidate improves the objective, or budget spent.

**What it keeps.** Nothing of the rig tree itself survives: the tree is reset to the skeleton's fixed tree choices (class, ascendancy, keystones, forced nodes, jewels) before the normal greedy tree starts. What survives is the rig gear's effect on gear pass 1.

**When it is skipped.** Skipped in the classic construction order (the default); it runs only with construction rig-first.

Where: `pipeline.py:run (tree.allocate, tree_optimizer.py:TreeOptimizer.allocate)`

Runs only when: the request asks for the rig-first construction.
Median time: none: no build of this set (61 builds) met the condition.

### first gear pass on the rig tree

Step name: `gear pass 1 (rig tree)`

**What it changes.** This step is the first full gear fill of a rig-first build, made against the temporary rig tree. After it the rig tree is removed and the config lanes are derived again, so the gear stays and the tree starts again from the skeleton's fixed choices.

**What it tries.** For every slot of the skeleton's rare bases it rolls a full batch of random rares: the rails' construction_best_of_n (600 by default) unless the caller gave loot_n, and a small roll for a screen run. Each slot's incumbent competes with the new rolls. The best rolls also get their best legal bench craft, and the useful-line count drops lines that give nothing. The wishlist gear mode fills fixed day-1 templates instead of free rolls.

**How it is judged.** Every roll is trialled in PoB and ranked under the floors order: has a number, then fewest floor violations, then the maximized stat. After the fill the lanes are re-derived (a rejudge) so the record carries the lane of the new gear. The fill keeps the best gear set it saw.

**What it keeps.** It keeps the gear set. A slot never trades down because the previous item competes. The rig tree is thrown away and the construction tree optimizer's history is cleared.

**When it is skipped.** Skipped in the classic construction order (the default), where gear pass 1 (empty tree) runs instead; it runs only with construction rig-first.

Where: `pipeline.py:run (loot.fill, _reset_construction_tree)`

Runs only when: the request asks for the rig-first construction.
Median time: none: no build of this set (61 builds) met the condition.

### first gear pass on an empty tree

Step name: `gear pass 1 (empty tree)`

**What it changes.** This step is the first full gear fill of a classic build. It puts rolled rare items on every slot of the skeleton's rare bases while the passive tree holds only the skeleton's fixed nodes. The gear is later refilled in gear pass 2 once the tree exists.

**What it tries.** For each slot it rolls the rails' construction_best_of_n random rares (600 by default; a caller's loot_n wins, a screen run uses a small roll) in the gear mode chosen, loot or wishlist. The best rolls also try their best legal bench craft, and the useful-line count removes lines that give nothing. The wishlist mode fills fixed day-1 templates instead of free rolls.

**How it is judged.** Every roll is trialled in PoB and ranked under the floors order: has a number, then fewest floor violations, then the maximized stat. The lanes are re-derived after the fill, so the record carries the config of the new gear; when the build has a flat-reservation aura, the record is written after the aura-level step's own rejudge.

**What it keeps.** It keeps the best-scoring item per slot and the best gear set across the fill's internal passes. When an emptied slot leaves the build with no number at all, the pass is built twice and the better set is kept.

**When it is skipped.** Skipped when the run uses the rig-first construction order; with the default classic order it always runs.

Where: `pipeline.py:run (loot.fill, loot_gear.py:LootGear.fill, wishlist_gear.py:WishlistGear.fill)`

Median time: 1.9 min; share of the build time: 3.0 % (ran in 61 builds).

### config re-derived after the first gear pass

Step name: `config re-derived (after gear pass 1)`

**What it changes.** This step is a correction line, not a move: the config lanes are derived again after the first gear fill, and when any config input changed the line records the change as pairs of old and new values. The first gear fill's own record keeps the value from before the rejudge, and this line carries the effect of the rejudge.

**What it tries.** It tries nothing. It compares the config inputs PoB held before the rejudge with those after, key by key. The new lanes are derived from the build as it now stands, including the gear that was just filled.

**How it is judged.** No PoB judging happens; the step only reads the config inputs before and after a rejudge. The record that follows reads the build's stats like any stage.

**What it keeps.** It keeps the re-derived lanes as the config of the build. Its effect is charged to this line and to nothing else (#176), so no move gets credit for what the config change did.

**When it is skipped.** Runs only when the build carries a flat-reservation aura and a config input actually changed in the rejudge; otherwise it is logged as skipped. A build with no flat-reservation aura never reaches it.

Where: `pipeline.py:_flat_reservation_stage`

Runs only when: the build has a flat-reservation aura and a config input changed when the first gear pass was judged again.
Median time: none: no build of this set (61 builds) met the condition.

### flat-reservation aura levels

Step name: `flat-reservation aura levels`

**What it changes.** This step chooses the gem level of each enabled aura whose reservation is flat, such as an aura that reserves a fixed amount of mana, because a lower level reserves less and can free mana or sustain. A level is written into the skeleton's aura_levels and applied to the gem groups in PoB.

**What it tries.** The auras come from PoB's own level data (a flat manaReservationFlat reservation on a non-mine skill, among the gems the build carries). For each aura it tries every level from 1 up to the rails' gem level, one real skills write and one score per level.

**How it is judged.** Each level is scored with the complete current objective under the floors order: a level that makes a mana, sustain or defensive floor fail loses. The first of equal scores wins, which keeps the lowest reservation when PoB sees no difference. In the improvement loop the same choice is made again under the priced score of D116; this construction run uses floors.

**What it keeps.** It keeps the best level per aura, and an aura whose best level is the rail level carries no override. The lanes are re-derived afterwards. The record's note lists each aura with its level, or says rail.

**When it is skipped.** Runs only when the skeleton has an enabled aura with a flat reservation; otherwise it is logged as skipped.

Where: `pipeline.py:tune_flat_reservation_aura_levels (called from pipeline.py:_flat_reservation_stage)`

Median time: 3.1 s; share of the build time: 0.1 % (ran in 31 builds).

### supports re-picked (no number)

Step name: `supports re-picked (no number)`

**What it changes.** This is a repair of the main link's supports, run right after gear pass 1 when the build has no number at all (the maximized stat is not above 0). A weapon variant can inherit supports another weapon chose, for example a sword finalist's Close Combat, which zeroes Smite on a staff or a sceptre, so the supports are chosen again on the rig as it stands.

**What it tries.** The generator's greedy support pick adds the best support one at a time until the link holds as many supports as before (at least 1, at most the rails' main link maximum minus one). Fixed supports the request named and the enablers stay in place. The candidate supports come from the generator's legal support list for the skeleton.

**How it is judged.** Every candidate support is scored in PoB with the config lanes re-derived after each pick, so a support that only wins under a stale assumption is rejected. A candidate is added only when its score is strictly greater than the link's score so far. The note records the supports before and after.

**What it keeps.** It keeps the picked supports. If the build still has no number after this step the run raises an error saying the skill cannot be used with this skeleton, so a build that cannot be scored never gets ranked.

**When it is skipped.** Skipped when gear pass 1 already left a number above 0, or when the main link carries no support that is neither fixed by the request nor an enabler. In the normal case it is logged as skipped.

Where: `pipeline.py:_revive_supports (condition in pipeline.py:run and _revivable_supports)`

Runs only when: the build has no score after the first gear pass and some of its supports can be swapped.
Median time: none: no build of this set (61 builds) met the condition.

### tree seed toward the scaling stat

Step name: `tree seed toward <stat>`

**What it changes.** It spends a first share of the passive points on nodes that raise one stat the request named, before the general tree is grown. By default the share is 40 percent of the points still free (`seed_points` of the skeleton's scaling, default 0.4). The nodes are allocated in the build PoB holds.

**What it tries.** A separate tree optimizer whose objective is only that one stat (the request's scaling stat) allocates nodes greedily, using the same candidate paths from the passive tree graph as the main tree step. Keystones the skeleton forbids stay forbidden, and nodes the skeleton protects (forced nodes) are not removed.

**How it is judged.** PoB measures each candidate on the one named stat only, not on CombinedDPS, FullDPS, or the floors. The step records the points it spent and the value of that stat afterwards. The build is then rejudged, and the stage is recorded under the full objective of the build.

**What it keeps.** Every node it allocated stays; nothing is rolled back at this step. Later steps (tree greedy, tree rebuilt on gear, the improvement loop) may drop or swap these nodes, and the rebuild on gear seeds again the same way.

**When it is skipped.** It is skipped when the skeleton carries no scaling stat (the request did not ask to scale toward a stat). The step name on the page stands for any stat: the recorded name is `tree seed toward <that stat>`.

Where: `pipeline.py:run (the seed call), pipeline.py:_seed_scaling`

Runs only when: the skeleton names a stat to scale toward.
Median time: none: no build of this set (61 builds) met the condition.

### tree greedy

Step name: `tree greedy`

**What it changes.** It grows the passive tree from the skeleton's fixed start (ascendancy, fixed keystones, any seed) with the remaining passive points. The points are the level's limit minus what is already allocated. The gear at this moment is the first gear pass, rolled on an empty tree.

**What it tries.** In rounds, it lists every candidate from the passive tree graph: single nodes and paths up to a maximum depth (6 in a normal run) that cost no more than the points left, capped at a maximum number of trials per round (300 in a normal run). Nodes of forbidden text, nodes that would break the attribute cap, and masteries above a cost limit are left out. Cluster candidates are added when the run enables them, and candidates that PoB found inert are skipped.

**How it is judged.** PoB measures every candidate as a trial on the current build. While the floors of the construction view of the objective hold, it takes the candidate with the best gain of the objective value per point spent. While a floor is missed, it estimates the points the cheapest repair needs and spends on the best gain only if enough points remain beyond that estimate plus a margin, otherwise it takes the candidate that removes most of the violation per point. The construction view differs from the loop's view: per the code comments it leaves out the movement speed floor and resource sustain.

**What it keeps.** It keeps each allocation as it is made, one per round, and stops when the points are spent, no candidate is left, or no candidate improves the objective. The reason it stopped is written into the stage record. The gear pass that follows is run on this tree.

**When it is skipped.** never skipped

Where: `pipeline.py:run (tree.allocate), tree_optimizer.py:TreeOptimizer.allocate`

Median time: 72 s; share of the build time: 2.1 % (ran in 61 builds).

### second gear pass with the tree

Step name: `gear pass 2 (with tree)`

**What it changes.** It fills the rare gear slots again, now with the greedy tree in place, and PoB then judges the build with fresh config lanes. In a normal run it makes 2 passes (a screen makes 1) over the slots of the skeleton's rare bases. Unique items the skeleton names are put back where a refill empties their slot.

**What it tries.** In the loot mode, per slot it rolls random rares on the skeleton's base with PoB's own spawn weights, 600 rolls per slot by default for construction (60 in a screen), plus the item from the earlier pass as an incumbent. The best few by Score each get their best legal crafting-bench mod. In the wishlist mode the item shape is template-driven and PoB chooses only the open and bench lines. The request's forced affix lines are carried in both.

**How it is judged.** Each candidate item is trialled in PoB and compared by the Score of the objective in its floors order: the floors first, then the objective value (the construction objective, CombinedDPS or FullDPS by the skeleton's mode). The priced score of D116 is not used here; it belongs to the improvement loop. In the loot mode, the useful lines of the finished item are counted and the best counted item wins.

**What it keeps.** The incumbent competes with the new rolls and a pass never trades down, so a slot keeps its earlier item unless a candidate wins. In a fill that leaves an emptied slot with infinite violation, the pass is built twice and the better complete gear set is kept. The fill never hands back a set that the start set outranks.

**When it is skipped.** never skipped

Where: `pipeline.py:run (loot.fill), loot_gear.py:LootGear.fill, wishlist_gear.py:WishlistGear.fill`

Median time: 2.5 min; share of the build time: 3.8 % (ran in 61 builds).

### tree rebuilt on gear

Step name: `tree rebuilt on gear`

**What it changes.** It throws the tree away down to the ascendancy and the fixed keystones, grows it again on the finished gear, and keeps the new one only if it scores higher. The greedy tree was grown before the gear existed, so with the gear in place the best tree can be a different one. The comment in the code names an example of a 95-node cascade spent differently, 477k to 970k.

**What it tries.** It makes two regrowths, one with the optimistic 'sum' repair estimate of the greedy allocator and one with the 'cover' estimate. Each regrowth re-applies the tree seed if the skeleton has a scaling stat, spends the free points greedily, then refines the tree by swapping weak leaf nodes for better candidates for up to 8 rounds. If the regrown tree is stronger but misses a floor, it refines for up to 16 more rounds first. The growth uses the construction view of the tree objective, with sustain and without movement.

**How it is judged.** After each regrowth the config lanes are rejudged for the new tree, then PoB scores the build under the objective the build is delivered on, with its floors. The better of the two regrowths is compared with the previous tree by `better_score` (floors first, then the value). The priced score of D116 is not used in this step.

**What it keeps.** If the better regrowth beats the previous tree it is loaded and kept; otherwise the snapshot of the previous tree and its lanes is restored (reverted). The note of the stage record says which, with the values of both regrowths. The tree that stands after this step is stored as the construction tree.

**When it is skipped.** It is skipped in a screen run (a cheap run that ranks skeletons) and when the caller turns the rebuild off (`rebuild_tree` false). Otherwise it runs on every build.

Where: `pipeline.py:run, pipeline.py:_rebuild_tree`

Median time: 3.2 min; share of the build time: 5.3 % (ran in 61 builds).

### amulet anoint

Step name: `anoint`

**What it changes.** It picks one passive notable to anoint on the amulet with oils, on the finished tree and gear. The anoint is written into the amulet's text, and every later amulet the gear step makes carries it. The step runs right after the tree is rebuilt on gear and before the flasks.

**What it tries.** Every notable that the oil rail allows (the oil limit, Black by default) and that the tree does not already hold is a candidate. Each is measured on the same amulet with no anoint. The candidate list comes from the anoint candidate table (`anoint_candidates`).

**How it is judged.** PoB measures the plain amulet and each anointed amulet as item trials in one fast batch (an item trial with the explicit Allocates line equals a full equip, 0.0 percent, per the test named in the code), under the objective's Score. The candidates are ranked by that score and the best is taken only if it is strictly above the plain amulet. The priced score of D116 is not named in this step's code; which score order it uses beyond `objective.score` is not established.

**What it keeps.** The best anoint stays if it beats the plain amulet; if none does, the amulet stays plain and the note says 'none'. The pick and the candidate list are stored so the anoint re-pick after the improvement loop can judge the ten best again on the final tree. The stage record shows the score before and after, how many were measured, and the time.

**When it is skipped.** It is skipped in a screen run, and when the build wears no amulet. It also does nothing, with a log line, when the amulet's base cannot be anointed or the amulet text cannot take the anoint line.

Where: `pipeline.py:_anoint_step, anoint_step.py:pick_anoint, anoint_candidates.py`

Median time: 3.7 s; share of the build time: 0.1 % (ran in 57 builds).

### flasks

Step name: `flasks`

**What it changes.** It fills the flask slots with magic flasks and tinctures, up to the number of slots the gear rails allow. Which flasks are active is derived by PoB's own flask uptime calculation, never set by this step. It runs after the anoint and before the jewels.

**What it tries.** Per slot, the flask the build came in with is the first candidate. Every allowed base up to the wishlist base level cap is tried bare, the top 3 bases are kept, and for each the best prefix and then the best suffix is tried, at the item level of the gear rail. Tinctures are included only if the rails allow them. Unless the build is pure energy shield, the first slot is fixed to a Divine Life Flask.

**How it is judged.** PoB scores each candidate placed in the slot by the whole objective Score (floors, then the value); on a tie the defence gain over the empty slot decides, compared as TotalEHP, then PhysicalMaximumHitTaken, then EffectiveMovementSpeedMod. A replacement must beat the input strictly. When all candidates tie because every flask is inactive, the search is repeated with the active flag forced on for the trial only; the remaining ties go to the lower level requirement.

**What it keeps.** The picks stay in their slots and are written to the build; no slot is left empty while a candidate can be tried. A later move that empties a flask slot has it put back by the restore step. The record shows the score before and after and how many candidates were measured.

**When it is skipped.** It is skipped in a screen run, when the rails give zero flask slots, and when the PoB session cannot equip items. Otherwise it runs on every build.

Where: `pipeline.py:_flask_step, flask_step.py:run_flask_step`

Median time: 8 min; share of the build time: 11.7 % (ran in 61 builds).

### cluster jewels

Step name: `clusters`

**What it changes.** Puts up to count_max rare cluster jewels into big jewel sockets of the passive tree, each with its own size, enchant, up to notables_max notables and the inner path to them. To pay for the new passive points it removes the least valuable leaf nodes of the tree.

**What it tries.** For every reachable socket that is not an inner cluster socket, it tries each enchant of each allowed size (a Large cluster goes only into a Large socket, a Medium one into a Medium or Large socket) with no notables. It keeps the best screen_keep of those, then tries each notable of the kept ones alone, and pairs made from the best five single notables when notables_max is 2 or more. The enchants and notables come from the cluster data read by the pipeline (cluster_enchants, cluster_notables), not from a hand-written list.

**How it is judged.** Every trial is a PoB score of the build under the objective (floors first, then the objective stat such as CombinedDPS or FullDPS). The best trial is placed, the points it needs are freed by removing, one at a time, the leaf whose removal loses least, and the cluster counts only if the build then scores strictly above the build before it. After the whole step the lanes are derived again and the build is compared once more with the build before the step.

**What it keeps.** A cluster that does not beat the build stops the round and is not placed. If the score after the step is not above the score before it, the whole step is loaded back as it was and the log says reverted. Otherwise the placed clusters stay and are carried by every later tree change.

**When it is skipped.** Skipped for a screen run, when the tree is not rebuilt, and when the clusters rail count_max is 0 or the PoB session cannot list socketed jewels or cluster graphs. The shipped rails file rails_default.json sets count_max to 0, so with those rails the step is skipped; whether another rails file in use sets it higher is not established.

Where: `pipeline.py:_cluster_step (search in cluster_step.py:run_cluster_step)`

Median time: 9 min; share of the build time: 13.2 % (ran in 61 builds).

### jewels

Step name: `jewels`

**What it changes.** Places up to count_max rare jewels (2 in the shipped rails), each with one useful line, into jewel sockets of the passive tree. The path to a socket is bought with passive points, and the points are freed by removing the least valuable leaf nodes.

**What it tries.** Every spawnable line of the Jewel mod pool is one candidate (jewel_lines.py:jewel_line_candidates, read from the game data). Each candidate is socketed into the cheapest reachable socket and measured; the best line is then tried in every reachable socket, with the points for its path freed from the tree, and the best socket wins.

**How it is judged.** All of it is PoB scores under the objective (floors first, then CombinedDPS / FullDPS or the build's objective stat). A line must score above the same socket allocated empty, and a socket must score above the build before the jewel. After the step the lanes are derived again and the build must score above the build before the step.

**What it keeps.** A jewel that does not pay stops the round. If the build after the step does not score above the build before it, the build is loaded back exactly as it was and the log says reverted. Otherwise the jewels stay; at the end of the pipeline each jewel's line is measured again against its ten best lines (a separate re-pick, not this step).

**When it is skipped.** Skipped for a screen run, when the tree is not rebuilt, when the jewels rail count_max is 0, or when the PoB session cannot list socketed jewels.

Where: `pipeline.py:_jewel_step (search in jewel_step.py:run_jewel_step)`

Median time: 4.8 min; share of the build time: 6.6 % (ran in 61 builds).

### supports re-picked

Step name: `supports re-picked`

**What it changes.** Chooses the support gems of the main skill's link again, now that the tree, the gear, the anoint, the flasks and the jewels are in place. Supports the request fixed and enabler supports stay where they are.

**What it tries.** The candidates are the supports PoB itself links to the main skill (read back from PoB, day-1 supports only, minus forbidden ones and delivery changers such as mines, traps, totems and triggers that the skill does not already have). It adds supports greedily, the best one each round, until the link is full; then it tries one-for-one swaps in every slot that is not fixed, up to three rounds.

**How it is judged.** Each trial is a PoB score under the objective, floors first, then CombinedDPS / FullDPS or the build's objective stat, with the config lanes derived again after each pick. A support that only wins under the old lanes is rejected when the lanes are derived again. The new link replaces the link the skeleton held only at a strictly greater score.

**What it keeps.** The link the skeleton held before is kept when the re-pick does not score strictly above it. Otherwise the new link stays, and the picks are written into the build's pick list with their scores.

**When it is skipped.** Skipped when repick_supports is off or for a screen run. scripts/search.py turns it on for a full run when the skeleton has fewer than 5 fixed supports; what other callers pass is not established.

Where: `pipeline.py:run (search in search/generator.py:pick_supports)`

Runs only when: the request switches the supports re-pick on.
Median time: none: no build of this set (61 builds) met the condition.

### utility links

Step name: `utility links`

**What it changes.** Adds utility socket groups of one gem each (auras, curses, movement skills and the like) next to the main skill, up to the build's utility group limit. It changes only the gem groups, not the tree or the gear.

**What it tries.** The candidates are utility gems by family, taken from the tags of the gem corpus (no Vaal gems, none already in the build or forbidden, and buffs whose uptime is too low are left out). When the rails require a movement skill and the build has none, travel and blink gems are tried first and the best is taken. Then candidates are added one by one, the best each round, with the pool cut to the best 25 when more were measured.

**How it is judged.** Each candidate is a PoB score under the objective with mana reservation, sustain and the floors inside it, and TotalEHP breaks ties. A gem is added only if it scores above the current build, and a gem that only wins under the old config lanes is rejected when the lanes are derived again. A movement gem must not lower floor satisfaction.

**What it keeps.** Every gem that passed both checks stays as its own group. When nothing scores above the current build, no group is added and the step records none.

**When it is skipped.** Skipped when pick_utilities is off, for a screen run, or when the skeleton already holds as many extra groups as its utility group limit (the skeleton's utility_groups, else the rails' utility_max_groups).

Where: `pipeline.py:run (search in search/generator.py:pick_utilities)`

Runs only when: the utility link picking is on and the build has fewer link groups than the limit.
Median time: none: no build of this set (61 builds) met the condition.

### fill free sockets

Step name: `fill`

**What it changes.** Adds socket groups of one gem each into the sockets the build leaves empty: the auras, guards, heralds and buffs that PoB counts. It is not held to the utility group limit and changes only the gem groups and the config choices of the gems it adds.

**What it tries.** The candidates come from the gem tags aura, guard and herald and from PoB's skill type buff (no Vaal gems, none already in the build or forbidden, none the movement rail refuses, and buffs whose uptime is too low are left out). Each candidate stands alone in the first slot that has a free socket its colour fits (a white socket fits any gem, an abyss socket none, and a kept gem uses its socket up); a gem with config choices of its own (Flesh and Stone: Blood and Sand stance) is measured under each of them. Once the pool a gem reserves from has nothing unreserved (ManaUnreserved or LifeUnreserved at 0 or below, as PoB's level data says Mana or Life), that gem is not measured any more.

**How it is judged.** Each candidate is a PoB score under the objective. It passes when no floor gets worse, the objective falls by at most fill_max_objective_loss and TotalEHP or the objective rises by at least fill_min_gain. The best passing candidate by score, then TotalEHP, is measured again under re-derived lanes before it is kept.

**What it keeps.** A gem that passed both checks stays as its own group, together with the config choice it won under. A gem that failed a check is dropped for the rest of the step, and the step ends when no socket or no candidate is left.

**When it is skipped.** Skipped when pick_utilities is off, for a screen run, or when the fill_step rail is off. When no candidate fits a free socket (none free, or none of a fitting colour) it makes no PoB call.

Where: `pipeline.py:_fill_step (search in search/generator.py:pick_fill)`

Runs only when: the utility link picking is on, the run is not a screen, the fill_step rail is on.
Median time: none: no build of this set (61 builds) met the condition.

### tree refine (screen run)

Step name: `tree refine`

**What it changes.** Improves the passive tree of a screen run with one local search, as the last construction stage of a screen. A screen is the cheap version used to rank many skeletons: small gear loot, a greedy tree, one refine, and no loop.

**What it tries.** It frees k passive points by dropping the k least valuable leaf nodes and spends them on the best candidate of cost k, up to 8 rounds. When a floor is missed, the swaps are a repair: the swap with the most floor violation removed per DPS lost is taken.

**How it is judged.** PoB is asked about every removable leaf and about the candidate swaps. A swap is accepted when the objective improved or a floor violation shrank, floors before CombinedDPS / FullDPS. After the round the config lanes are derived again and the stage is recorded; the screen's score ledger starts from that score.

**What it keeps.** The swaps PoB accepted stay in the tree. What happens to the rest of a round that finds no swap is not established beyond the function's own description.

**When it is skipped.** Skipped for every run that is not a screen; a full run goes on to the improvement loop instead.

Where: `pipeline.py:run (search in tree_optimizer.py:TreeOptimizer.refine)`

Runs only when: the screen runs are on.
Median time: none: no build of this set (61 builds) met the condition.

## Improvement loop

### improvement loop opening

Step name: `loop opening`

**What it changes.** It settles the build's config choices before the first pass starts. The choices are the lists PoB offers (stance, exposure type, Pride's effect) and the identity: the bandit's extra passive points and the two pantheon gods. Afterwards it fixes the socket colours the way the final step will deliver them.

**What it tries.** Every option of each list choice, and each pantheon god the rails do not already fix. The options come from the config that the skeleton's lanes derive, not from a hand-written list. If the tuned lanes leave a build that was feasible infeasible, it also runs one tree refine of up to 12 rounds that repairs the missed floors at the cheapest damage per violation.

**How it is judged.** PoB scores each option under the full objective (the floors first, then the maximized stat such as FullDPS or CombinedDPS). Pantheon ties are broken by EHP. These opening choices are measured and recorded, but they are not put through the loop's keep-or-revert rule: the loop starts from whatever the tuned lanes score.

**What it keeps.** The best-scoring choices stay on the skeleton and every later re-derivation of the config re-applies them. The repair refine, if it runs, is a transaction: a PoB contract error drops it and restores the build. The ledger records the opening as pass 0.

**When it is skipped.** It is skipped when the loop is the fixed-point check's extra pass, and in the replay bench's plans (only a plan of kind loop opens with lanes). Otherwise never skipped. The repair refine runs only when the build is infeasible after the tuning.

Where: `improvement_loop.py:ImprovementLoop._opening_lanes`

Median time: 21 s (the sum of the opening's move rows, per build).

### improvement loop pass

Step name: `loop pass <N>`

**What it changes.** One pass of the improvement loop runs its moves one after another on the build PoB holds: the tree, the rare gear slots, the weapon bases, the support and group picks, the flat-reservation aura levels and the config lanes. A move changes the build only if it is kept. The pass is named loop pass 1, loop pass 2 and so on.

**What it tries.** The plan of a pass, in this order: tree refine, tree path swaps, one gear re-roll per rare slot (weapons first), a weapon base trial per weapon slot, picks, aura levels (only when the skeleton has a flat-reservation aura), and lanes. When none of these kept anything, two kicks follow: a tree kick (3 draws by default) and a joint gear-and-tree kick (4 draws). Corridors and regions are not in the default plan; they run only when a replay names them.

**How it is judged.** At the start of each pass the castability is refreshed and the build is scored again under the refreshed objective. Each move is then judged by PoB under lanes re-derived after the move, by the priced score of D116: value times (1 minus the relative floor violation, capped at 1). While a floor is missed, any better priced score is kept. Once the build is feasible, the priced score must grow by min_gain, 0.5% by default. A kept move updates the Score the next move starts from.

**What it keeps.** Every kept move stays; a rejected move is rolled back to the snapshot taken before it. The pass notes what it kept. A pass that keeps nothing is the fixed point and ends the loop. The loop also ends at the pass limit (16 by default) or at the safety-net time budget, and says so in its note. On the last pass the socket colours are judged once more, so the build leaves on colours the loop has measured.

**When it is skipped.** Never skipped: pass 1 always runs. Later passes run only while the previous pass kept at least one move and the pass limit and time budget are not reached. Individual moves skip themselves under their own conditions, listed under each move.

Where: `improvement_loop.py:ImprovementLoop.run`

Median time: 35 min; share of the build time: 46.1 % (ran in 61 builds).

### improvement loop repair pass

Step name: `repair pass <N>`

**What it changes.** The repair of one keystone choice on a finished build (the keystone held on or held off, repair.py) runs at most two passes of the improvement loop's moves from that build. Each pass is named repair pass 1 and repair pass 2. The repair runs no kicks and no time limit.

**What it tries.** The moves of one loop pass with the keystone held as chosen: tree refine, tree path swaps, one gear re-roll per rare slot, a weapon base trial, picks, aura levels when the skeleton has a flat-reservation aura, and lanes. The repair ends after the first pass that gains less than 1% over the value before it, or after pass 2.

**How it is judged.** Each move is judged by PoB as in a loop pass, under the objective. The verdict reads the objective value after each pass: climbing when pass 2 gained at least 1% over pass 1, take when the last value is at least the value the repair started from, drop otherwise.

**What it keeps.** A kept move stays and a rejected move is rolled back to its snapshot, as in a loop pass. The per-pass values are the repair's record; they are not a build the search keeps by themselves.

**When it is skipped.** Runs only when a keystone choice is repaired on a finished build (LoopPlan.repair). It is not part of the construction and not part of the loop of a build.

Where: `improvement_loop.py:LoopPlan.repair; repair.py`

Runs only when: a keystone choice is repaired on a finished build (the repair rule of #1064).
Median time: none: no build of this set (61 builds) met the condition.

### fixed point check

Step name: `fixed point check`

**What it changes.** After the final config lanes, it runs one more pass of the loop's local moves on the finished build, to learn whether the loop really stopped at a fixed point. Whatever that pass keeps stays in the build. How much it gained is recorded as the build's fixed-point gain.

**What it tries.** The same local moves as a normal pass: tree refine, path swaps, one gear re-roll per rare slot, weapon base trials, picks, and aura levels where the skeleton has a flat-reservation aura. There is no lane step and no kicks. Gear rolls use a seed offset far from every pass the loop ran (1,000,003), so they roll other items.

**How it is judged.** Moves are judged by the same rule as in the loop, but in the floors order rather than the priced score (#553): a move may not lower feasibility, and while feasible the value must grow by min_gain. If the pass kept something, the gain is the stage's value over the value before the pass, and above 1% it is reported as an audit error, otherwise as a warning. After the check, if the build's floor violation is above the entry value from before the final tuning (by more than the feasibility tolerance), the whole final tuning including this pass is reverted to the build the loop handed over.

**What it keeps.** Every move the extra pass kept, unless the feasibility guard above reverts the final tuning. If the extra pass itself ran out of time before judging every move and kept nothing, nothing is claimed: the note says it stopped on the time budget.

**When it is skipped.** Skipped when the fixed-point check is switched off in the run options (it is on by default), and when the loop itself stopped on its time budget or its pass limit; then the build is known not to be at a fixed point, a warning is recorded, and no pass runs.

Where: `pipeline.py:BuildPipeline._fixed_point_check`

Median time: 4.5 min; share of the build time: 7.7 % (ran in 35 builds).

### Loop moves

The moves of one pass of the improvement loop, in the order they are tried.

#### refine

**What it changes.** It rearranges the passive tree without changing the number of points spent. It drops the least valuable leaf nodes and spends the freed points on better nodes.

**What it tries.** Per round, one trial for each removable leaf, one for each candidate node (or cluster) of cost k, and one for each swap, up to 80 top candidates. Candidates come from the passive tree graph and PoB's trial calculations. The loop calls it with up to 10 rounds. While a floor is missed the swaps are a repair: the chosen swap is the one with the most violation removed per damage lost.

**How it is judged.** The tree optimizer accepts each swap on PoB's numbers under its own objective, with a minimum gain of 0.2%. The whole result is then judged by the loop: lanes re-derived, the build scored, and the priced score of D116 compared against the score before the move with min_gain 0.5%. The loop's rule can overrule the tree optimizer's inner verdict.

**What it keeps.** If the loop's rule accepts, the new tree stays and the pass records a refine note with the change. If not, the build is restored exactly from the snapshot (XML, skeleton, gear bookkeeping, tree history). A kept refine also stops the region challenge in the same pass.

**When it is skipped.** Never skipped from the default plan: the first move of every pass, including the fixed-point check. A round that already measured every candidate on the same build returns at once, without new trials (the tree optimizer remembers the build it found nothing on).

Where: `improvement_loop.py:ImprovementLoop._refine_or_swaps (tree_optimizer.py:TreeOptimizer.refine)`

Median time per build: 39 s.

#### swaps

**What it changes.** It replaces small hanging parts of the passive tree with other nodes. Each such subtree is removed whole, and the freed points are spent greedily wherever the tree now wants them.

**What it tries.** Every allocated node whose removal cascades off at most 6 nodes (subtrees containing protected nodes are excluded). They are ordered by the cheapest damage loss per point, and subtrees whose removal alone breaks a floor go last. It stops after 12 non-improvements in a row. In the loop no time or candidate-count cap is set.

**How it is judged.** The tree optimizer keeps a swap if PoB says its objective improved, with a minimum gain of 0.2%. The batch of kept swaps is then judged by the loop like refine: lanes re-derived, priced score of D116, min_gain 0.5%. If the batch is rejected, up to 12 of its steps are replayed one at a time under fresh lanes, and each is kept on its own if the same loop rule accepts it.

**What it keeps.** The accepted batch, or the individual replayed swaps the loop rule accepts. A rejected batch is restored exactly from the snapshot. A false verdict (a swap that really scores lower, or whose config inputs got worse) is logged with the changed config inputs.

**When it is skipped.** Never skipped in the default plan; it runs after refine in every pass, including the fixed-point check. It does nothing when the tree has no small subtrees.

Where: `improvement_loop.py:ImprovementLoop._refine_or_swaps (tree_optimizer.py:TreeOptimizer.swap_subtrees)`

Median time per build: 5 min.

#### regions

**What it changes.** It challenges whole detachable regions of the passive tree: a region is removed and its points are regrown elsewhere, to test whether a different trunk would be better.

**What it tries.** Regions are grouped in buckets by size (16 per bucket) and each is given up to 12 cheap completed replacements of its own point count, each priced by one fast what-if. Regions are ordered by the best replacement, and the top 4 are challenged for real. The region's own nodes are forbidden for the first half of the regrowth, and two repair policies alternate.

**How it is judged.** The tree optimizer's own acceptance first (minimum gain 0.2%), then the loop's: lanes re-derived and the priced score of D116 compared with min_gain 0.5%. If the move kept no step, it is not judged at all, since the build is the one it started on, and it is recorded as kept nothing.

**What it keeps.** A challenge accepted by the loop rule stays; otherwise the exact snapshot is restored.

**When it is skipped.** It is not in the default plan: it runs only when a replay names it in the plan's moves, placed after the swaps. Even then it is skipped in a pass where refine or the swaps already kept something. It was taken out of the default plan on the owner's word (comment in improvement_loop.py: 0.6% of the loop's gain for 5.7% of its time).

Where: `improvement_loop.py:ImprovementLoop._trunk (tree_optimizer.py:TreeOptimizer.challenge_regions)`

Runs only when: the plan of the pass names the regions move.
Median time: none: no build of this set (61 builds) met the condition.

#### corridors

**What it changes.** It swaps a corridor, the path of nodes between two key nodes of the passive tree, for another way between the same two key nodes.

**What it tries.** Up to 40 corridors of the current tree. For each one, up to 8 alternative connections through unallocated nodes, shortest first, at most the corridor's length plus 2 points. The extra points of a longer way are paid by dropping the weakest leaves. Up to 8 exchanges are applied for real, bypass first, and each completed exchange is first scored by one fast what-if.

**How it is judged.** The tree optimizer's own acceptance (minimum gain 0.2%) and then the loop's: lanes re-derived, the priced score of D116 against the score before, min_gain 0.5%. A move that kept nothing is not judged and is recorded as kept nothing.

**What it keeps.** An exchange set accepted by the loop rule; otherwise the exact snapshot is restored. The code comment records that on 96 delivered builds a bypass was found for 79 of 2,583 corridors and 2 exchanges were kept.

**When it is skipped.** It is not in the default plan: it runs only when a replay names it in the plan's moves, and then it is the first move of the pass.

Where: `improvement_loop.py:ImprovementLoop._trunk (tree_optimizer.py:TreeOptimizer.exchange_corridors)`

Runs only when: the plan of the pass names the corridors move.
Median time: none: no build of this set (61 builds) met the condition.

#### ascendancy-swap

**What it changes.** One allocated ascendancy node that does nothing for the build is swapped for another ascendancy node of the same ascendancy. A node is dead when removing it moves neither the objective nor TotalEHP by 0.1 % (the audit measures this by PoB's own removal). The dead node is removed and the new pick is added in PoB, and the ascendancy points spent may not rise.

**What it tries.** Every ascendancy pick of the same ascendancy that is not allocated yet, with its path (PoB allocates the path in the trial). The candidates go to PoB's trial_stats in one batch in full mode. A candidate that costs more ascendancy points than the swap frees, or that would remove a node the request named, is dropped. One attempt is made per dead node, each judged on its own.

**How it is judged.** The best candidate by the objective under the priced order of D116 (FullDPS discounted by floor violation) is applied, the lanes are re-derived, and the build's Score is compared with the current one. The swap is kept only if it gains at least 0.1 % (the same share that makes a node dead), under the priced order and the current costs, so a swap that only moves the same damage is refused.

**What it keeps.** A kept swap rewrites the skeleton's ascendancy nodes so the tree rebuilt after it keeps the new pick, and the note records the old and new node with its gain. A rejected swap is rolled back to the snapshot taken before the attempt. After a kept swap the dead nodes are measured again, because the swap can change what the next one is worth.

**When it is skipped.** Only in a plan whose rails give ascendancy points: the move is absent from the pass otherwise. Every pass measures the audit again (a picks or lanes move changes the gems, which can turn a node dead or alive); a dead node the request named (forced) or one that sits in no ascendancy. The move runs right after the path swaps, before the gear.

Where: `improvement_loop.py:ImprovementLoop._ascendancy_swap (candidates: tree_hygiene.py:ascendancy_swap_candidates, dead nodes: tree_hygiene.py:dead_ascendancy_nodes)`

Runs only when: the rails give ascendancy points.
Median time: none: no build of this set (61 builds) met the condition.

#### gear

**What it changes.** One rare gear slot of the build is re-rolled, one slot per trial, in the order the construction fills them: Weapon 1, Weapon 2, Body Armour, Helmet, Gloves, Boots, Belt, Amulet, Ring 1, Ring 2 (the slots the build has as rares; a slot held by a unique is not in the list). The item in the slot is replaced only if the new item wins the judging below.

**What it tries.** The slot is first emptied in PoB, then filled from scratch under the loop's priced order, and the old item still competes with the new ones, so the slot can never get worse by a pass. On a day-1 template build (WishlistGear) the candidates are the template's bases, and each open line of the template is tried with the ordinary mods and bench crafts the rail rules allow (one attribute affix per item, no line the request forbids, the boots' Movement Speed line stays pinned). A weapon's lines follow rule 2: a candidate that makes any floor worse is refused outright, a candidate that adds +0 value is refused, and among the rest the best value wins. A candidate for an armour or jewellery slot follows rule 3: it must beat the item as it stands under the priced order, and it is refused when it removes less than 0.01 of floor violation at +0 value while the build is still infeasible. On a build that already meets every floor, a template slot's open lines are re-filled by value instead of floors first, so a damage line the tree then pays the floor for gets tried. On a non-template build (LootGear) the candidates are random rolls of the slot's base (a best-of-n draw, carrying the lines the request forces and the incumbent's Sockets line), the best few get their best legal bench craft, and the useful lines are counted.

**How it is judged.** Candidates are first compared with PoB's fast trial_stats. Then the finished item is equipped, its own lanes are re-derived, and if it breaks a floor the tree is asked once to repair it (refine with repair rounds only) before the verdict. The verdict compares the build's Score before and after under the priced score of D116: the objective's maximized stat (FullDPS or CombinedDPS) multiplied by one minus the relative floor violation (capped at 1), so a floor is bought with damage only at a fair price; a tie of priced values is broken by the violation and then the value, and a gain on a feasible build must clear min_gain (0.005 by default). The fixed-point check's extra pass keeps the older floors-first order instead.

**What it keeps.** A kept item stays with the repair the tree made for it. A rejected item is rolled back by loading the snapshot taken before the slot was emptied, with the old item and the resistance plan restored. If the incumbent wins its own slot, nothing is judged at all and the move is recorded as not kept. After a rejected template value re-fill, the build state is remembered so the same refill is not repeated until something changes.

**When it is skipped.** Never skipped as a kind: every pass runs one gear trial per rare slot. A single slot trial ends early when the incumbent wins its own slot, or when a template slot's value re-fill was rejected before and the tree, config lanes, other items and gems are unchanged since. The slot is skipped entirely if a unique holds it.

Where: `improvement_loop.py:ImprovementLoop._gear (the candidates: wishlist_gear.py:WishlistGear._choose_trial and fill_slot, loot_gear.py:LootGear.fill_slot)`

Median time per build: 10 min.

#### weapon-base

**What it changes.** The base type of a rare weapon (Weapon 1 or Weapon 2) is swapped for another base of the same item class, keeping the item's prefixes and suffixes with their rolls, its crafted lines, quality and sockets. Only the base (and with it the implicit, the Critical Strike Chance, Attacks per Second and Physical Damage of the base) changes.

**What it tries.** Every other legal base of the equipped weapon's class (Wand, Sceptre, Dagger, Claw, One Handed Sword, Axe or Mace, Staff, Two Handed Sword, Axe or Mace, Bow) up to the rails' item level. On a template build the list comes from the wishlist's base level limit instead. Each candidate is re-crafted in PoB with the same affixes (craft_rare), and a candidate PoB cannot craft with those lines is dropped and counted in weapon_base_skipped.

**How it is judged.** All crafted candidates go to PoB's fast trial_stats in one batch and are scored by the objective. The best one under the loop's priced order (D116, FullDPS discounted by floor violation) is equipped and judged like any move: lanes re-derived, then accepted only if the priced score beats the current build by min_gain (0.005 by default). The judge is the exact one, restoring the whole saved state on a rejection.

**What it keeps.** A kept swap records the old and new base and their base numbers on the move. A rejected swap is fully rolled back to the snapshot (XML, item bookkeeping and the skeleton's base), and the build state is remembered as rejected so the same trial is not re-run when nothing has changed.

**When it is skipped.** Skipped for a slot that holds a unique, a base the request forced, or a base whose item class is not a weapon class above. Also skipped when the fingerprint (allocated nodes, mastery effects, config lanes, gems and other items, current item text, the slot's base) equals the one of the last rejected trial, and when no candidate base or no craftable candidate exists. The plan holds one entry per Weapon 1 and Weapon 2 present.

Where: `improvement_loop.py:ImprovementLoop._weapon_base and _weapon_base_move`

Median time per build: 3.2 s.

#### picks

**What it changes.** The discrete gem picks of the finished build: each support of the main link (except the request's fixed supports and the enablers) and each utility gem group the picker chose. While a floor is missed it may also turn off one reserving socket group (for example a reserving aura) to give the mana or life back.

**What it tries.** For each support slot, every legal support from the generator's legal_supports list that is not already in the link (the first sweep ranks all of them, a later sweep keeps the best 12 per slot). For each picked utility group, every candidate gem of its own kind (a movement skill is replaced only by a movement skill). The reserving-group drop tries each enabled group by disabling it and asking PoB whether ManaUnreserved or LifeUnreserved rose; groups that give nothing back are not candidates.

**How it is judged.** Each alternative is scored by PoB under freshly derived lanes, and the best one is compared with the current build under the priced score of D116 (FullDPS discounted by floor violation), then verified once more under full lane re-derivation before it is kept. A swap needs the priced score to improve by min_gain (0.005 by default). The reserving-group drop is tried only on a build that misses a floor; a feasible build tries nothing. One sweep is made per pass.

**What it keeps.** Swaps that pass both measurements stay and are listed in the pass notes as the support or utility replaced; a swap that fails the second measurement is put back. A kept change marks the build as changed so the next pass runs picks again, and a sweep that keeps nothing is done.

**When it is skipped.** Skipped when the main link has one gem or fewer and no extra group is picked or enabled. Also skipped when nothing in the build (tree, gear, kicks, aura levels, lanes) has changed since the last picks re-judge, because the re-judge is deterministic on an unchanged build.

Where: `improvement_loop.py:ImprovementLoop._picks (the work: search/generator.py:rejudge_picks and drop_reserving_group)`

Median time per build: 7.7 min.

#### aura levels

**What it changes.** It sets the gem level of each enabled flat-reservation aura (a non-mine reservation skill whose mana reservation is a flat amount), so that the reservation fits the build's mana floors.

**What it tries.** For every such aura, every legal level from 1 up to the rails' gem level. Each level is a real write of the skill and a real PoB score. An aura whose best level is the rails' gem level carries no level override.

**How it is judged.** Within the move, the levels are ordered by the plan's score order, the priced score of D116 in the loop (floors order in the fixed-point check), and the first equal score wins, which keeps the lowest reservation when PoB finds no difference. The chosen levels are then judged by the loop's own rule: lanes re-derived, priced score against the score before, min_gain 0.5%.

**What it keeps.** Accepted levels stay and the pass notes them as aura levels with each aura's name and level. A rejected result is restored from the snapshot, and the move is not tried again until another move changes the build.

**When it is skipped.** Skipped when the skeleton has no flat-reservation aura (the move is not in the pass plan), and skipped within a pass when nothing has changed since the last aura levels judgement or since its rejection.

Where: `improvement_loop.py:ImprovementLoop._aura_levels (pipeline.py:tune_flat_reservation_aura_levels)`

Median time per build: 10 s.

#### lanes

**What it changes.** It judges the list choices of the config (stance, exposure type, Pride's effect) again for the build as it now stands. The choices follow the build, so a pass that changed the tree, the gear or the link ends with this step.

**What it tries.** Each option of each list choice, derived from the build's current config lanes. The identity (bandit, pantheons) is not re-judged here; it is judged once in the loop opening and once in the final config step.

**How it is judged.** PoB scores each option under the current objective. The step is not a keep-or-revert move of the loop: it records the new score as kept when the number changed, and it never reverts. Afterwards the socket colours are judged under PoB's numbers, as the final step does.

**What it keeps.** The tuned choices stay on the skeleton and every later config derivation re-applies them. A PoB contract error drops the move and restores the build from the snapshot.

**When it is skipped.** Skipped when no kept move has changed the build since the last lane tuning, and never part of the fixed-point check's plan (the extra pass is local only).

Where: `improvement_loop.py:ImprovementLoop._lanes (pipeline.py:BuildPipeline._tune_lanes)`

Median time per build: 16 s.

#### kick-tree

**What it changes.** The passive tree is shaken up by ruin and recreate: whole random branches worth about 20 points are removed, the same number of points is spent again by the greedy allocator that now sees the rest of the tree, and a refine of up to 10 rounds follows. The gear and gems are not touched.

**What it tries.** A kick is a random draw: the branches ruined are chosen by a random generator seeded from the plan's seed, the pass number and the draw number, so a draw is reproducible. A pass makes 3 tree draws by default (kick_draws), each judged on its own, and no draw is skipped because an earlier one was kept. The tree optimizer's reoptimize already keeps or restores its own round by its own objective before the loop judges it.

**How it is judged.** If the build after the round equals the build before (same tree, same items), the draw is skipped without measuring. Otherwise the lanes are re-derived and the loop judges the draw like any move: the priced score of D116 (FullDPS discounted by floor violation) must beat the current build by min_gain (0.005 by default).

**What it keeps.** A kept draw replaces the tree and is noted as kick tree with its gain and draw number; it also gives the local moves another pass. A rejected draw is rolled back by loading the XML saved before the kick.

**When it is skipped.** Kicks run only in a pass where no local move kept anything, the loop has not stopped, and the pass is not the fixed-point check's local-only extra pass. When the plan restricts its moves, the kick must be named in them. A draw is skipped when the safety net time budget is reached or when it changes nothing.

Where: `improvement_loop.py:ImprovementLoop._kicks and _kick_tree (tree_optimizer.py:TreeOptimizer.reoptimize)`

Median time per build: 3.6 min.

#### kick-joint

**What it changes.** Gear and tree are ruined together: two rare slots and a random tree branch worth about 16 points are emptied, then both sides are rebuilt and a short refine (6 rounds) follows. The two slots are the ones with the most damage headroom (weapons first), or a random pair if no slot shows headroom.

**What it tries.** Headroom of a slot is measured by rolling it for damage alone (floors removed from the objective) and comparing the best roll with the current FullDPS. On an even draw number the gear is rebuilt for damage alone and the tree re-spend repairs the floors; on an odd draw the tree is re-spent for damage alone and the gear repairs the floors. A pass makes 4 joint draws by default (kick_draws), each with its own random stream, each judged on its own.

**How it is judged.** The round re-derives its own lanes. If the tree and items are the same as before, the draw is skipped. Otherwise the loop judges it by the priced score of D116 (FullDPS discounted by floor violation), which must beat the current build by min_gain (0.005 by default).

**What it keeps.** A kept draw stays and is noted as kick joint with its gain and draw number. A rejected draw is undone by loading the saved XML, the old item texts and the old resistance plan.

**When it is skipped.** Same as the tree kick: only in a pass where no local move kept anything, the loop has not stopped, and the pass is not the fixed-point check's extra pass; when the plan restricts its moves, it must be named in them. It runs after the tree kick's draws. A draw ends early when the safety net is reached or when it changes nothing.

Where: `improvement_loop.py:ImprovementLoop._kicks and _kick_joint (the round: _joint_round, _slots_with_damage_headroom)`

Median time per build: 6.7 min.

## Finish

### anoint re-pick on the final tree

Step name: `anoint re-pick`

**What it changes.** Chooses the amulet's anoint again after the improvement loop, when the tree and the gear are final. The tree may by now hold the notable the amulet was anointed with, so the anoint can change.

**What it tries.** The candidates are the ten best notables of the first anoint pick plus the anoint worn now, minus every notable the tree already allocates. The first pick took its notables from the oil rail's list (anoint_candidates with oil_max).

**How it is judged.** The candidates are measured against the plain amulet as one fast PoB batch, under the objective, floors first, then CombinedDPS / FullDPS. The best is chosen only if it scores above no anoint. After the change PoB scores the whole build again with a full calculation.

**What it keeps.** If the full calculation scores lower than before the change, because the fast trials and the full calculation disagreed, the worn anoint is put back. A kept change is added to the build's move list so that the score ledger still adds up.

**When it is skipped.** Skipped when the first anoint step made no pick (a screen run, no amulet on the build, an amulet base that cannot be anointed) or when no amulet is on the build. It runs after the improvement loop and before the jewel re-pick and the final config lanes.

Where: `pipeline.py:_anoint_repick (anoint_step.py:repick_anoint)`

Median time: 0.6 s; share of the build time: 0.0 % (ran in 57 builds).

### final config lanes

Step name: `config (final lanes)`

**What it changes.** Settles the build's config at the very end: the config lanes (a conservative and an optimistic set of toggles) are derived once more, the choice inputs and the identity (pantheons, and the extra passive points from killing every bandit) are tuned, and the sockets are made white with the colour step giving colour only where it pays. The finish group's fixed point check and last floor repair run inside the same function.

**What it tries.** The choice inputs are tuned by tune_choices (its candidates are not established here), and each pantheon major and minor is tried unless the rails fix it. If a floor is broken after that, the tree is refined again (12 rounds, then repair rounds only) and the lanes are derived again. After the record, one more pass of loop moves, the fixed point check, is run, and a last floor repair is tried if a floor is still broken.

**How it is judged.** Every choice is a PoB score under the objective, floors first, then CombinedDPS / FullDPS; pantheons tie-break by defence. Each tuning step is guarded: it stays only if it did not lower feasibility. At the end the build is compared with the build the loop handed over.

**What it keeps.** A tuning step that lowers feasibility is loaded back. If the delivered build ends with a floor violation worse than the loop's build, the whole final tuning is reverted to the build the loop handed over, and the log says so. Otherwise the tuned config, the pantheons and the sockets stay.

**When it is skipped.** Never skipped: every run that reaches the finish, including a screen run, goes through it.

Where: `pipeline.py:_finish`

Median time: 5.2 s; share of the build time: 0.1 % (ran in 61 builds).

## Worked example

The stages of one recorded build (`absolution_minions-s4-no-eldritch_battery`), in the order they ran.

- skeleton applied: 5.5 s (minions {'Absolution': 3, 'Raise Zombie': 6, 'Summon Carrion Golem': 1} minion skills {'Absolution': 2, 'Raise Zombie': 3, 'Summon Carrion Golem': 1})
- config (conservative lane): 1.4 s (2 inputs on)
- gear pass 1 (empty tree): 3 min
- flat-reservation aura levels: 3.4 s (Clarity 1)
- tree greedy: 2.6 min (budget spent)
- gear pass 2 (with tree): 4.4 min
- tree rebuilt on gear: 7.1 min (638,783 (viol 1.274) -> 399,240 (viol 0.597) kept [sum 399,240 (viol 0.597); cover 352,217 (viol 0.746)])
- anoint: 4.9 s (anoint: Dreamer, score 399,240 -> 399,240, 196 measured, 4.9 s)
- flasks: 9.4 min (reverted (399,240 -> 399,240); 1467 measured)
- clusters: 13 min (cluster: socket 21984 large 'affliction_damage_with_two_handed_melee_weapons' + Graceful Execution, score -1.46522 -> -1.44182, 484 measured, 10 points, removed 12189, 12143, 7688, 15081, 22062, 54694, 44799, 52714, 59606, 59252, 6.8 min; 1 placed (cluster 2: best option does not beat the build (best trial -1.42536, -1.54816 after paying its points, build -1.44182)); Score -1.46522 -> -1.44182, 994 trials, 13 min)
- jewels: 6.4 min (socket 26196 '13% increased Mana Cost Efficiency'; socket 64583 '13% increased Mana Cost Efficiency'; 1880 measured)
- loop pass 1: 8.4 min (refine -5.3% (viol 0.066 -> 0.054); swaps +0.0%; Weapon 2 +0.4%; Body Armour +2.9%; Helmet +4.5%; Ring 1 +11.2%; Ring 2 +3.6%; picks: support Controlled Destruction -> Lightning Penetration (+1.9%); support Minion Damage -> Concentrated Effect (+10.6%))
- loop pass 2: 9.1 min (refine +12.6%; swaps +3.6%)
- loop pass 3: 20 min (kick tree +5.1% (draw 1); kick tree +26.9% (draw 2); kick tree +25.3% (draw 3))
- loop pass 4: 2.1 min (no change; stopped: time budget)
- anoint re-pick: 0.7 s (anoint re-pick: kept Dreamer, score 709,550 -> 709,550, 8 measured, 0.7 s)
- config (final lanes): 5.5 s (8 conservative / 40 optimistic; choices {'elementalArmyExposureType': '0', 'pantheon_major': 'None', 'pantheon_minor': 'None'}; final feasibility: ok)
