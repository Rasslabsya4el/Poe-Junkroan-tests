"""Plain-words descriptions of build steps (#713): `TEXT[step name] = Description(...)`; a loop move is keyed `"move: <name>"`."""

from __future__ import annotations

from junkroan.optimizer.step_description import Description

TEXT: dict[str, Description] = {
    "clusters": Description(
        what_it_changes=(
            "Puts up to count_max rare cluster jewels into big jewel sockets of the passive tree, each with its own size, enchant, "
            "up to notables_max notables and the inner path to them. "
            "To pay for the new passive points it removes the least valuable leaf nodes of the tree."),
        what_it_tries=(
            "For every reachable socket that is not an inner cluster socket, it tries each enchant of each allowed size "
            "(a Large cluster goes only into a Large socket, a Medium one into a Medium or Large socket) with no notables. "
            "It keeps the best screen_keep of those, then tries each notable of the kept ones alone, "
            "and pairs made from the best five single notables when notables_max is 2 or more. "
            "The enchants and notables come from the cluster data read by the pipeline (cluster_enchants, cluster_notables), not from a hand-written list."),
        how_judged=(
            "Every trial is a PoB score of the build under the objective (floors first, then the objective stat such as CombinedDPS or FullDPS). "
            "The best trial is placed, the points it needs are freed by removing, one at a time, the leaf whose removal loses least, "
            "and the cluster counts only if the build then scores strictly above the build before it. "
            "After the whole step the lanes are derived again and the build is compared once more with the build before the step."),
        what_it_keeps=(
            "A cluster that does not beat the build stops the round and is not placed. "
            "If the score after the step is not above the score before it, the whole step is loaded back as it was and the log says reverted. "
            "Otherwise the placed clusters stay and are carried by every later tree change."),
        when_skipped=(
            "Skipped for a screen run, when the tree is not rebuilt, and when the clusters rail count_max is 0 or the PoB session cannot list socketed jewels or cluster graphs. "
            "The shipped rails file rails_default.json sets count_max to 0, so with those rails the step is skipped; "
            "whether another rails file in use sets it higher is not established."),
        where="pipeline.py:_cluster_step (search in cluster_step.py:run_cluster_step)",
    ),
    "jewels": Description(
        what_it_changes=(
            "Places up to count_max rare jewels (2 in the shipped rails), each with one useful line, into jewel sockets of the passive tree. "
            "The path to a socket is bought with passive points, and the points are freed by removing the least valuable leaf nodes."),
        what_it_tries=(
            "Every spawnable line of the Jewel mod pool is one candidate (jewel_lines.py:jewel_line_candidates, read from the game data). "
            "Each candidate is socketed into the cheapest reachable socket and measured; the best line is then tried in every reachable socket, "
            "with the points for its path freed from the tree, and the best socket wins."),
        how_judged=(
            "All of it is PoB scores under the objective (floors first, then CombinedDPS / FullDPS or the build's objective stat). "
            "A line must score above the same socket allocated empty, and a socket must score above the build before the jewel. "
            "After the step the lanes are derived again and the build must score above the build before the step."),
        what_it_keeps=(
            "A jewel that does not pay stops the round. "
            "If the build after the step does not score above the build before it, the build is loaded back exactly as it was and the log says reverted. "
            "Otherwise the jewels stay; at the end of the pipeline each jewel's line is measured again against its ten best lines (a separate re-pick, not this step)."),
        when_skipped=(
            "Skipped for a screen run, when the tree is not rebuilt, when the jewels rail count_max is 0, "
            "or when the PoB session cannot list socketed jewels."),
        where="pipeline.py:_jewel_step (search in jewel_step.py:run_jewel_step)",
    ),
    "supports re-picked": Description(
        what_it_changes=(
            "Chooses the support gems of the main skill's link again, now that the tree, the gear, the anoint, the flasks and the jewels are in place. "
            "Supports the request fixed and enabler supports stay where they are."),
        what_it_tries=(
            "The candidates are the supports PoB itself links to the main skill (read back from PoB, day-1 supports only, "
            "minus forbidden ones and delivery changers such as mines, traps, totems and triggers that the skill does not already have). "
            "It adds supports greedily, the best one each round, until the link is full; "
            "then it tries one-for-one swaps in every slot that is not fixed, up to three rounds."),
        how_judged=(
            "Each trial is a PoB score under the objective, floors first, then CombinedDPS / FullDPS or the build's objective stat, with the config lanes derived again after each pick. "
            "A support that only wins under the old lanes is rejected when the lanes are derived again. "
            "The new link replaces the link the skeleton held only at a strictly greater score."),
        what_it_keeps=(
            "The link the skeleton held before is kept when the re-pick does not score strictly above it. "
            "Otherwise the new link stays, and the picks are written into the build's pick list with their scores."),
        when_skipped=(
            "Skipped when repick_supports is off or for a screen run. "
            "scripts/search.py turns it on for a full run when the skeleton has fewer than 5 fixed supports; what other callers pass is not established."),
        where="pipeline.py:run (search in search/generator.py:pick_supports)",
    ),
    "utility links": Description(
        what_it_changes=(
            "Adds utility socket groups of one gem each (auras, curses, movement skills and the like) next to the main skill, up to the build's utility group limit. "
            "It changes only the gem groups, not the tree or the gear."),
        what_it_tries=(
            "The candidates are utility gems by family, taken from the tags of the gem corpus (no Vaal gems, none already in the build or forbidden, "
            "and buffs whose uptime is too low are left out). "
            "When the rails require a movement skill and the build has none, travel and blink gems are tried first and the best is taken. "
            "Then candidates are added one by one, the best each round, with the pool cut to the best 25 when more were measured."),
        how_judged=(
            "Each candidate is a PoB score under the objective with mana reservation, sustain and the floors inside it, and TotalEHP breaks ties. "
            "A gem is added only if it scores above the current build, and a gem that only wins under the old config lanes is rejected when the lanes are derived again. "
            "A movement gem must not lower floor satisfaction."),
        what_it_keeps=(
            "Every gem that passed both checks stays as its own group. "
            "When nothing scores above the current build, no group is added and the step records none."),
        when_skipped=(
            "Skipped when pick_utilities is off, for a screen run, or when the skeleton already holds as many extra groups as its utility group limit "
            "(the skeleton's utility_groups, else the rails' utility_max_groups)."),
        where="pipeline.py:run (search in search/generator.py:pick_utilities)",
    ),
    "fill": Description(
        what_it_changes=(
            "Adds socket groups of one gem each into the sockets the build leaves empty: the auras, guards, heralds and buffs that PoB counts. "
            "It is not held to the utility group limit and changes only the gem groups and the config choices of the gems it adds."),
        what_it_tries=(
            "The candidates come from the gem tags aura, guard and herald and from PoB's skill type buff (no Vaal gems, none already in the build or forbidden, "
            "none the movement rail refuses, and buffs whose uptime is too low are left out). "
            "Each candidate stands alone in the first slot that has a free socket its colour fits (a white socket fits any gem, an abyss socket none, and a kept gem uses its socket up); a gem with config choices of its own (Flesh and Stone: Blood and Sand stance) is measured under each of them. "
            "Once the pool a gem reserves from has nothing unreserved (ManaUnreserved or LifeUnreserved at 0 or below, as PoB's level data says Mana or Life), that gem is not measured any more."),
        how_judged=(
            "Each candidate is a PoB score under the objective. It passes when no floor gets worse, the objective falls by at most fill_max_objective_loss "
            "and TotalEHP or the objective rises by at least fill_min_gain. "
            "The best passing candidate by score, then TotalEHP, is measured again under re-derived lanes before it is kept."),
        what_it_keeps=(
            "A gem that passed both checks stays as its own group, together with the config choice it won under. "
            "A gem that failed a check is dropped for the rest of the step, and the step ends when no socket or no candidate is left."),
        when_skipped=(
            "Skipped when pick_utilities is off, for a screen run, or when the fill_step rail is off. "
            "When no candidate fits a free socket (none free, or none of a fitting colour) it makes no PoB call."),
        where="pipeline.py:_fill_step (search in search/generator.py:pick_fill)",
    ),
    "tree refine": Description(
        what_it_changes=(
            "Improves the passive tree of a screen run with one local search, as the last construction stage of a screen. "
            "A screen is the cheap version used to rank many skeletons: small gear loot, a greedy tree, one refine, and no loop."),
        what_it_tries=(
            "It frees k passive points by dropping the k least valuable leaf nodes and spends them on the best candidate of cost k, "
            "up to 8 rounds. "
            "When a floor is missed, the swaps are a repair: the swap with the most floor violation removed per DPS lost is taken."),
        how_judged=(
            "PoB is asked about every removable leaf and about the candidate swaps. "
            "A swap is accepted when the objective improved or a floor violation shrank, floors before CombinedDPS / FullDPS. "
            "After the round the config lanes are derived again and the stage is recorded; the screen's score ledger starts from that score."),
        what_it_keeps=(
            "The swaps PoB accepted stay in the tree. "
            "What happens to the rest of a round that finds no swap is not established beyond the function's own description."),
        when_skipped=(
            "Skipped for every run that is not a screen; a full run goes on to the improvement loop instead."),
        where="pipeline.py:run (search in tree_optimizer.py:TreeOptimizer.refine)",
    ),
    "anoint re-pick": Description(
        what_it_changes=(
            "Chooses the amulet's anoint again after the improvement loop, when the tree and the gear are final. "
            "The tree may by now hold the notable the amulet was anointed with, so the anoint can change."),
        what_it_tries=(
            "The candidates are the ten best notables of the first anoint pick plus the anoint worn now, "
            "minus every notable the tree already allocates. "
            "The first pick took its notables from the oil rail's list (anoint_candidates with oil_max)."),
        how_judged=(
            "The candidates are measured against the plain amulet as one fast PoB batch, under the objective, floors first, then CombinedDPS / FullDPS. "
            "The best is chosen only if it scores above no anoint. "
            "After the change PoB scores the whole build again with a full calculation."),
        what_it_keeps=(
            "If the full calculation scores lower than before the change, because the fast trials and the full calculation disagreed, the worn anoint is put back. "
            "A kept change is added to the build's move list so that the score ledger still adds up."),
        when_skipped=(
            "Skipped when the first anoint step made no pick (a screen run, no amulet on the build, an amulet base that cannot be anointed) or when no amulet is on the build. "
            "It runs after the improvement loop and before the jewel re-pick and the final config lanes."),
        where="pipeline.py:_anoint_repick (anoint_step.py:repick_anoint)",
    ),
    "config (final lanes)": Description(
        what_it_changes=(
            "Settles the build's config at the very end: the config lanes (a conservative and an optimistic set of toggles) are derived once more, "
            "the choice inputs and the identity (pantheons, and the extra passive points from killing every bandit) are tuned, "
            "and the sockets are made white with the colour step giving colour only where it pays. "
            "The finish group's fixed point check and last floor repair run inside the same function."),
        what_it_tries=(
            "The choice inputs are tuned by tune_choices (its candidates are not established here), "
            "and each pantheon major and minor is tried unless the rails fix it. "
            "If a floor is broken after that, the tree is refined again (12 rounds, then repair rounds only) and the lanes are derived again. "
            "After the record, one more pass of loop moves, the fixed point check, is run, and a last floor repair is tried if a floor is still broken."),
        how_judged=(
            "Every choice is a PoB score under the objective, floors first, then CombinedDPS / FullDPS; pantheons tie-break by defence. "
            "Each tuning step is guarded: it stays only if it did not lower feasibility. "
            "At the end the build is compared with the build the loop handed over."),
        what_it_keeps=(
            "A tuning step that lowers feasibility is loaded back. "
            "If the delivered build ends with a floor violation worse than the loop's build, the whole final tuning is reverted to the build the loop handed over, and the log says so. "
            "Otherwise the tuned config, the pantheons and the sockets stay."),
        when_skipped="Never skipped: every run that reaches the finish, including a screen run, goes through it.",
        where="pipeline.py:_finish",
    ),
}
