# 2026-09-19 D82. The picks judge a support together with its self cost

Status: Accepted

The user's reading of `new18-rules`: poison_spark came out infeasible on all three seeds with Sacrifice Support in
the main link, a support the author does not use ("theoretically leech covers it" -- but the floor is without
leech, D63.3). Cause (the first worker's transcript): `SkeletonGenerator` kept the `Objective` captured BEFORE a
support trial, so the "honest" score after the reconfigure still lacked the refreshed `SelfCostPerSecond`; the log
shows `Faster Projectiles -> Sacrifice` recorded as 137,112 -> 201,220 while the applied build already carried a
0.790 violation.

Contract (measured, not designed): a TEMPORARY candidate (a support or a utility being tried) refreshes only the
self-cost context (`BuildPipeline._reconfigure(full=False)`); a COMMITTED, reverted or final pick gets the full lane
and ramp reconfiguration. A full reconfigure during a trial is not trial-safe -- the ramp context is built from the
committed link -- and moved the stormbrand control from 1,631,723 to 1,797,073.

Measured (one PoB worker, `--loop-seconds 300` / 900): stormbrand s1 = 1,631,723 FullDPS on the parent and with the
fix, bit-identical, the same two re-judged support swaps; poison_spark s1 feasible at violation 0, main link Spark +
Added Lightning Damage + Elemental Focus + Unbound Ailments + Spell Echo, no Sacrifice, 201,527 CombinedDPS, 0 audit
errors. The first worker hit its 300-minute limit one step before its commit; the lead committed its tree and a
second worker finished from a follow-up spec (two workers, ~8 h of wall clock for a fix of ~110 lines).

