# 2026-09-12 D44. Joint tree+gear ruin-and-recreate, directed

Status: Accepted

The alternating stages converge to a local optimum (D43): the gear holds
the life and resists the tree lacked when the gear was chosen, the tree
holds what the gear lacked, and neither side can move alone without
breaking a floor. `BuildPipeline._joint_reoptimize` (after the tree
touch-up): each round empties two random rare slots (incumbents
forgotten) and a random tree branch (~16 points) and rebuilds both; the
round is kept only if the full objective improves.

Random recreate did nothing: on Smite all four rounds landed 5-17% below
the incumbent build (a fresh best-of-200 rarely beats an incumbent that
was the best of several hundred, and the greedy re-spend under the full
objective buys the same life back). Directed moves do: on even rounds the
emptied slots are refilled under the objective with floors and relations
removed (damage alone) and the tree re-spend repairs the floors; on odd
rounds the branch is re-spent for damage and the gear repairs. Smite:
round 3 (Amulet + Weapon 1 refilled for damage) 403,997 -> 454,303, the
other rounds reverted; 114% of the author on that single run. On the
3-seed benchmark (medians per reference, baseline -> with the stage):
cold_dot 94 -> 103%, hit_penance_brand 95 -> 101%, ignite_penance_brand
107 -> 116%, physical_dot 102 -> 114%, smite 95 -> 114%, the other five
unchanged within a point; median of medians 95 -> 103%, six of ten
references at or above the author. Kept.

Slot choice made directed too (2026-09-13): the two slots emptied each
round are the two with the most damage headroom (best of a quarter-size
loot roll under the objective without floors), not random ones. Two-
reference smoke, 3 seeds, medians before -> after: Poison Spectral Throw
70 -> 74% (seeds 69/70/95 -> 69/74/88), Stormbrand 130 -> 144% (worst
seed 76 -> 102%). Kept.

