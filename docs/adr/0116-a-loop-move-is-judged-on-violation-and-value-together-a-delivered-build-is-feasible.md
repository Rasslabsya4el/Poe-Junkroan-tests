# 2026-10-06 D116. A loop move is judged on violation and value together; a delivered build is feasible

Status: Accepted; amended by D116 amd 1

Why: today `Score` orders `(value > 0, neg_violation, value)` and `better_score` accepts any violation cut over any
value loss. On D84's replay bench (smoke six, 20260926-1357-tpl-byvalue-smoke-s4, seed 1) single moves gave up most
of FullDPS for a small violation cut while the floor stayed broken: the cluster move on impale_ballista went
-74.53 % FullDPS for violation 0.0195 -> 0.0024; the gear move on stormbrand went 2,588,214 -> 1,436,655
(-44.49 %); bleed_bow cluster -67.67 % for 0.1500 -> 0.1389.

Decision:

1. Inside the improvement loop only (acceptance `better_score` and the candidate choice inside every loop move), the
   order is the priced score `value x (1 - clamp(violation, 0, 1))`, `violation` being the sum of relative floor
   misses as computed today.
2. On an equal priced score, today's order `(value > 0, neg_violation, value)` breaks the tie. This is the whole
   treatment of `violation >= 1` (all such states score 0, the floor-first order chooses among them until violation
   falls under 1) and of `value <= 0`.
3. Construction before the loop and the tree optimizer keep today's violation-first order.
4. The loop's last step repairs any floor still broken with the existing floor moves under the floor-first order
   until violation = 0; a build that cannot be repaired fails the audit as today.
5. The author's build and the benchmark's reading of it do not change. No hand weight beyond the formula.

Trade-off: a hard order makes the optimizer pay any DPS for a crumb of floor; a priced order lets an intermediate
state stay infeasible, so the final repair step guarantees the floors.

Examples:

| from violation | move to violation | FullDPS change | verdict |
|---|---|---|---|
| 0.0195 | 0.0024 | -74.53 % | refused (0.2547 x 0.9976 < 0.9805) |
| 0.0195 | 0 | -1 % | kept (0.99 > 0.9805) |
| 1.469 | 0.648 | any | kept (tie at 0, floor-first) |

Consequences: every build's path changes; the next weekly core run is the new baseline. Proven by a PoB-free test of
the score and D84's replay bench before/after (D113, kind B). Hard to reverse: every number downstream follows the
new order.

## D116 amd 1 (2026-10-10, #553, #718): a weapon line is not under the priced score

A weapon line keeps its own rule at every violation: a candidate that worsens any floor is refused, among the rest
the best value wins and the violation only breaks a tie. The priced score of point 1 and the `violation >= 1` tie
rule of point 2 do not apply to it. Every other choice inside the loop stays under points 1 and 2.

Why: the weapon line's refusal already forbids trading a floor away, so value-first among the rest only decides
which DPS line to buy; under the tie rule at `violation >= 1` it bought the line with the larger floor cut instead,
a cut point 4's repair step makes anyway. Measured on D84's replay bench (gear move, seed 1, pin 29ab3b1):
summon_raging_spirits starts at violation 1.2445 and ended at 1,115,554 against 1,146,018 before the priced score
(-2.66 %), taking a Mana and Minion Damage line (1,086,027) over an Attack and Cast Speed line (1,111,066).

State of the code: the merge of #553 (4bc9bf0) still puts the weapon line under the priced score; #718 brings the
code to this amendment.
