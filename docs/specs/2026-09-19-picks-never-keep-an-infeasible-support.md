# Spec: the pipeline delivered poison_spark with a support that kills the character (Sacrifice), 3 seeds of 3

Campaign `new18-rules` (@63c5dab, `artifacts/benchmark/20260919-0130-new18-rules/`): poison_spark s1 / s2 / s3 are
all infeasible on one relation, the no-degen rail (D63.3):

```
[error] relation: NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond = -1552.2 < 0 x Life = 4435.0   (s1; s2 -1832.5, s3 -1768.2)
final feasibility: NetLifeRegen+NetEnergyShieldRegen+SelfCostPerSecond>=Life (viol 0.000 -> 0.350) (viol 0.350; the loop handed `_finish` a build at 0.350)
```

Our main link is `Spark + Sacrifice + Unleash + Unbound Ailments + Inspiration`. The AUTHOR's link
(`tests/fixtures/tuadh_329/poison_spark.pob.txt`) is `Spark + Faster Projectiles + Efficacy + Unbound Ailments +
Spell Echo` -- no Sacrifice. So the picks move put Sacrifice Support in (`optimizer/self_cost.py`,
`mechanics/self_cost_gems.json`: 20% of life per use; on the author's build 5.35 casts/s x 20% x 4333 = 4636
life/s, 107% of life per second, leech 0) and the build stayed infeasible to the end on every seed. The rule that
charges Sacrifice is right; keeping it is the defect. `self_cost.py`'s docstring promises "a support a pick is
trying is judged with its cost, not after it is kept" -- find out why that did not happen.

## Task

1. Reproduce from the log first (`logs/poison_spark-s1.log`): find the step that introduced Sacrifice and print the
   score (value, violation) before and after it as the move saw them, and as a full `objective.score` of the
   applied build sees them. State the cause in the report (stale self-cost context at trial time? a trial path that
   does not include the derived stat? an already-infeasible incumbent so that "better" meant value? the skeleton
   generator's support screen?).
2. Fix the cause generally. Whatever it is, this invariant must hold and get a test: a discrete pick (support,
   aura, keystone, any move of the picks family) is judged by the FULL objective including every derived stat
   (`SelfCostPerSecond`, `MoMUnreservedShare`, ...), and a candidate that raises the violation of the incumbent is
   never kept -- feasibility before value, as everywhere else. If the incumbent is already infeasible, a candidate
   may only be kept if it lowers the violation or leaves it equal with a higher value.
3. Add the symmetric repair the pipeline lacks: D72's drop move removes a reserving group while a floor is missed;
   when the missed relation is the self-cost one, the move may swap out a main-link support that carries a self
   cost (read from `self_cost_gems.json` / the derived stat's own sources, never from gem names in code) for the
   best support the picks screen offers. Inert on a feasible build.

## Acceptance (numbers in the report and the commit message)

- `junkroan.exe scripts/benchmark.py poison_spark --seeds 1 --no-variants --workers 1 --loop --loop-seconds 900
  --tag picks-fix` (the machine runs a 5-worker benchmark: one worker only): the build is feasible (violation 0),
  no Sacrifice in the main link unless the relation holds with it; report ours / author and the main link.
- No regression on a build that has no self-cost support: `stormbrand --seeds 1 --loop-seconds 300` gives the same
  number before and after your change (run both from your worktree: `git stash` is forbidden -- use a second
  checkout of the parent commit under `artifacts/` only if you must; simpler: compare with the value printed by
  the same command at the parent commit run BEFORE you edit anything).
- Unit tests with fake sessions for the invariant (a pick that adds value and violation is rejected; on an
  infeasible incumbent only a violation-lowering pick is kept) and for the repair move.
Focused tests, then the whole suite once, in the foreground. You are the worker: write the code yourself. Do not
edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
