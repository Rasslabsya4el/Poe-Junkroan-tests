# 2026-09-12 D43. Gear passes start fresh; the ramp budget follows the DPS composition

Status: Accepted

`scripts/gap_decomposition.py` crossed the authors' and our trees and gear
under our lane. Our tree on the author's gear matches or beats the author
on most references; our gear on the author's tree is 68-83% on six of ten.
Fresh loot on the same author trees (`scripts/loot_gear_experiment.py`,
N=200, two passes) is 114-155%. So the loot is fine and the pipeline was
spoiling it: pass 1 chooses items on an empty tree, so every slot buys
life and resists; later passes let the incumbent compete and never trade
down, so those items stayed after the tree had bought the life itself.
Gear passes 2 and 3 were made to start without incumbents; the next
benchmark run refuted it: Smite fell 498k -> 317k in the fresh pass 3
(the incumbents were the best of several hundred rolls, a fresh 200
rarely beats them) and Stormbrand 629k -> 503k, while Physical DoT and
Hit Penance Brand gained. Reverted to incumbents that never trade down;
pass 3 keeps two passes. The decomposition itself was confounded: "our
gear on the author's tree" is gear chosen for our tree, so it measures
the mismatch, not the loot. Our tree with the author's gear and our gear
with the author's tree are each fine; the whole build is 74-91%. The
remaining gap is the joint tree-gear optimum, which alternating stages
reach only locally. Single-seed runs move by up to 20%, so this needs a
multi-seed benchmark before the next optimizer change is judged.

Ramp: the user's play experience puts the bar at 2.5 s, but for poison the
stacks are the mechanic, so poison may take 4 s. Not "poison builds" by
name: `rails_default.json` `ramp.seconds_by_component`, and the build's
budget is each component's seconds weighted by its share of the maximized
DPS (`ramp.ramp_budget`, derived stat `RampBudget`, relation `RampBudget >=
RampSeconds` in place of the ceiling). Viper Strike at 91% poison gets
3.9 s (the author, 4.2 s, is just outside), a hit build 2.5 s, a hybrid in
between. The pipeline lines print `ramp x/y s`.

