# 2026-09-11 D27. Path-for-path: small subtrees are re-spent whole, verified by PoB

Status: Accepted

The 1-for-1 swap and random ruin-and-recreate leave marginal points behind
(a 5% curse-effect leaf, a 3-node travel path to a weak notable).
`TreeOptimizer.swap_subtrees` enumerates every hanging subtree of up to 6
nodes (what falls off when one allocated node is cut), removes it whole,
re-spends the points greedily and keeps the result only if the objective
improved. Cheapest-loss-per-point first, time budget, stop after 12
consecutive failures. Cold DoT: +5.2% in 94 s (4 swaps), 96% -> 101% of the
author. It runs as the finishing pass, after refine and reoptimize. Note the
pass bought the Witch start "Spell Damage and Mana" node the human eye
dislikes: that is the point, the tree is judged by numbers, not by looks.

