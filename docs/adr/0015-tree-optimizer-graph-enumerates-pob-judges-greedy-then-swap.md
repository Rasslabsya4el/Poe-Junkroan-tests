# 2026-09-11 D15. Tree optimizer = graph enumerates, PoB judges, greedy then swap

Status: Accepted

`optimizer/tree_graph.py` enumerates what is reachable and at what cost; PoB
evaluates every candidate through `trial_stats` (allocate, recalc, restore, in
one round trip); the optimizer picks by (violation reduction per point, then
objective gain per point), applies, repeats, then runs a swap phase. First
measurement on the Stormbrand reference: 30 stripped points recovered to
113.8% of the original CombinedDPS with life/EHP/resist floors met. This is
the fitness function the skeleton search will rank against. No node choice is
ever made from text or memory.

