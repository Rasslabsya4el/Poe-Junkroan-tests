# 2026-09-13 D45. The tree is grown again on the finished gear

Status: Accepted

A Viper Strike seed in the 3-seed baseline doubled (477k -> 970k) when a
path swap happened to cascade 95 nodes and the greedy re-spent them with
the gear in place: the greedy tree of the first pass is grown before any
gear exists, and on the finished gear a different tree is better. After
gear pass 2 the pipeline now resets the tree to ascendancy + fixed
keystones (+ the scaling seed), grows it again with the greedy allocator
and a short refine, and keeps the new tree only if it scores higher
(`rebuild_tree=True` in `BuildPipeline.run`, ~2 min).

3-seed benchmark, medians per reference (with the joint stage D44 ->
with the rebuild too; the pool-relative reservation scale is also in):
cold_dot 103 -> 97%, hit_penance_brand 101 -> 132%, ignite_penance_brand
116 -> 127%, physical_dot 114 -> 193% (one seed infeasible, two counted),
smite 114 -> 121%, stormbrand 82 -> 130%, winter_orb 90 -> 114%,
regular_viper_strike 172 -> 148%, poison_spectral_throw 83 -> 84%, spark
73 -> 89%. Median of medians 103 -> 127%, seven of ten at or above the
author. The rebuild was kept in 25 of 30 builds. Kept.

Fairness fix found on the way: list-type config choices (Plague Bearer
state, Wave of Conviction exposure type, Pride effect) are assumptions
about the fight, not the author's build decisions, and our build got the
PoB-judged best value while the author's re-score did not. The author
now gets the same choice; on the fixtures it moves Poison Spectral Throw
(+20%) and Spark (+16%) only, so their fair medians in the run above are
70% and 77%, the other eight are unchanged (Pride was already MAX in
the Physical DoT author's build).

A second rebuild on the final gear, under the full objective, was tried
and refuted on 3 seeds: median of medians 121 -> 114%, Hit Penance Brand
132 -> 98%, Stormbrand 130 -> 90%, Poison Spectral Throw 70 -> 45%, kept
in only 11 of 30 builds; removed. The comparison inside the rebuild was
also wrong: it scored the new tree before the config lanes were
re-derived, so a tree that lost the node proving a lane condition kept
the old tree's proof and could win on paper. The rebuild now re-derives
the lanes before comparing; the snapshot restores the old lanes with the
old tree.

Checked and closed: the authors' Searing Exarch / Eater of Worlds
implicits (up to 7 lines on Poison Spectral Throw, 6 on Stormbrand) are
worth at most 4% of their DPS under our lane (Smite 96%, Stormbrand 97%,
Spark 98%, the rest 99-100% without them), so the rails' no-influence
gear model is not the gap.

