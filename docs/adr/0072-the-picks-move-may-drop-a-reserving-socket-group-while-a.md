# 2026-09-18 D72. The picks move may drop a reserving socket group while a floor is missed

Status: Accepted

The improvement loop had no move that could lower reservation. The tree moves allocate and
deallocate nodes, the gear moves roll items, and the picks (`SkeletonGenerator.rejudge_picks`) swap
one utility gem for another of the same family -- none of them can turn a group off. On the
rules-smoke run (`artifacts/benchmark/20260918-0723-rules-smoke`) stormbrand s3 took Mind over
Matter in loop pass 1 (viol 0.264 -> 0.136 -> 0.076), landed at `MoMUnreservedShare` 0.324 against
the rails floor of 0.40, and stayed infeasible for nine more passes with no move able to give the
mana back; D66 then correctly refused to let `_finish` hide it.

`SkeletonGenerator.drop_reserving_group` is that move, first in every sweep of `rejudge_picks` and
therefore inside the loop's "picks" plan entry. **It runs only while the build is infeasible**
(`Score.feasible` false on any floor or relation): reservation is paid back to buy a floor, never to
buy damage, so on a feasible build the move applies no trial at all and is inert. Every enabled
socket group is disabled on its own, PoB recalculates, and the group counts as **reserving** exactly
when PoB's `ManaUnreserved` or `LifeUnreserved` rises -- the witness is PoB's number, never a gem
name or an "aura" tag, so a herald a Blood Magic build pays for out of life is not a candidate and a
unique that reserves is. The best Score among the reserving drops is applied, the lanes are derived
again (D45), and it is kept by the one rule every move shares (`objective.better_score`, written
once and now used by the loop, the re-judge and this move): feasibility first, so a drop that buys
the floor wins at a lower value, and `min_gain` only once feasible. At most one group per pass --
the next pass judges the build this one left behind. A dropped group stays in the skeleton with
`enabled=False`, the way `optimizer/buff_gems.py` disables a guard skill: nothing is removed, so a
variant of the build or a later construction picks the gem again, and `rejudge_picks` no longer
wastes trials swapping gems inside a group that is off.

One supporting fix in the loop: a pass whose only kept move was the picks used to set
`changed_since_picks = False` unconditionally, so the next pass skipped the re-judge and the sweep
never ran again on the build its own last sweep produced. The flag now follows what the sweep kept
(`changed_since_picks = bool(changes)`) -- "the loop itself is the repetition rejudge_picks does with
max_sweeps", and it is how a second reserving group is dropped when one was not enough. A sweep that
keeps nothing still ends the repetition.

**Proof** (the finished stormbrand s3 of that run, reloaded, one picks move under the rails
objective with the author's floors: `scripts/benchmark.author_floors` and that run's author memo):

| | FullDPS | feasible | violation | MoMUnreservedShare | ManaUnreserved |
|---|---|---|---|---|---|
| before | 1,869,566 | no | 0.076 | 0.324 | 605 of 1865 |
| after | 1,181,691 | **yes** | 0.000 | 0.662 | 1235 of 1865 |

Dropped: the Wrath + More Duration + Smite group (-36.8%). PoB's own trials ranked the five groups:
Vitality (no mana given back, viol 0.182), Leap Slam and Flame Dash (no mana given back, viol 0.076
unchanged), Righteous Fire + Zealotry + Assassin's Mark (630 mana back, feasible, 833,605) and Wrath
(630 mana back, feasible, 1,181,691) -- two groups could buy the floor, and the cheaper one won. The
same proof showed why the trials must use the full setter on an instance-counted main skill: the raw
setter writes count 1 and judged every trial at 590,854 against an incumbent at 1,869,566 (two
brands).
