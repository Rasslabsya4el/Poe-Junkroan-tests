# Spec (experiment, no optimizer change): how much does the frozen greedy topology lose? A whole-tree MIP on node values

Background: `docs/research/2026-09-19-tree-search-plan.md` (four deep-research reports + our measurements: 22% of a
delivered tree's nodes are trunk that no move reconsiders). All four reports name the same whole-solution method: give
every node a weight around the incumbent, solve "best connected set of <= B nodes containing the root" EXACTLY as a
MIP, let PoB judge the proposal, limit how far the proposal may move (local branching, Fischetti-Lodi 2003), compare
predicted with actual gain. This task MEASURES that on finished builds. It adds a script and a small module; it does
not touch `tree_optimizer.py` or the pipeline.

Dependency: `highspy` (HiGHS, MIT licence, Windows wheels; `pip install highspy` into the Python 3.12 that runs
`junkroan.exe`; this spec is launched only after the user has allowed that one install; add it to the optional
dependencies of `pyproject.toml` under an extra named `research`, never to the core requirements). No other new
dependency, no other install.

## Inputs

The best seed of each smoke reference from the finished runs (read the `.pob.txt`, never rebuild):
`artifacts/benchmark/20260919-0941-core14-rules/` -- cold_dot-s2, bleed_bow-s1, summon_raging_spirits-s1,
stormbrand-s2; `artifacts/benchmark/20260919-0130-new18-rules/` -- the best seed of impale_ballista and of
burning_arrow_snipe (take the highest `ratio_lane` in that run's `results.json`).

## Method

1. **Objective**: the benchmark's own objective for that reference (`benchmark.objective_for` + the author floors the
   run used, or, if rebuilding those floors is not possible from the run's files, `Rails.objective` with the judged
   stat; say which). `Score = (value, violation)`.
2. **Node weights around the incumbent S** with PoB's FAST what-if (`PobSession.trial_stats(..., mode="fast")`),
   which does NOT cascade (measured by the lead: removing a trunk node alone removes only that node's own stats):
   for every allocated node `v`: one trial `{"remove": [v]}`; for every unallocated allocatable node of the graph:
   one trial `{"add": [v]}` (masteries: one trial per legal effect, keep the best; jewel sockets and ascendancy
   nodes are FIXED, not variables). Weight `w_v = dValue / Value(S) - KAPPA * dViolation` with `KAPPA = 10` (a node
   whose removal breaks a floor by 0.01 weighs like 10% of the damage), sign such that keeping / taking a useful node
   is positive. About 1,300-1,600 trials, ~10-15 s. Report the distribution of weights (how many zero, negative).
3. **MIP** (HiGHS): binaries `x_v` over the class's allocatable graph (`TreeGraph`), `x_root = 1`, fixed nodes as
   they are, `sum x_v <= B` with B = the incumbent's allocated point count, connectivity by a single-commodity flow
   from the root with big-M = B - 1 on the bidirected graph, a mastery only with an allocated node of its cluster
   next to it (the graph's adjacency already says which), maximize `sum w_v x_v`. Time limit 60 s per solve; record
   the gap HiGHS reports.
4. **Proposals**, each judged by PoB for real (`mode="full"` or a real `mutate_nodes` + stats, then restore):
   unrestricted; and with the Hamming ball `sum_{v in S}(1 - x_v) + sum_{v not in S} x_v <= D` for D = 10, 20, 40.
   For each: predicted gain (sum of weights), actual Score, `rho = actual / predicted`, points changed, how many of the
   incumbent's TRUNK nodes (cascade > 12 in the incumbent) were dropped, feasible or not, mastery effects PoB refused.
5. **One re-linearization** for the best accepted proposal per build (weights recomputed around it, D as before):
   does a second step still gain?
6. Optional if time allows: the union of the three seeds of one reference (stormbrand s1-s3) as the restricted graph
   (nodes of the three trees + their connecting paths), same MIP, PoB judges.

## Report (the final message and `docs/research/2026-09-19-whole-tree-mip-experiment.md`)

Per build one table: incumbent value; for each of the four proposals the predicted gain, the actual value, rho,
changed points, trunk nodes changed, solver seconds and gap; the re-linearization step; total PoB seconds. Then three
sentences at most: does a whole-tree proposal beat the delivered tree anywhere, at which radius does the additive
model stop being trustworthy (rho), and what broke (floors, masteries, connectors priced at zero). Numbers, no
recommendations beyond that.

Tests: a unit test of the MIP on a tiny hand-made graph (a root, two arms with prizes 5 and 100 of lengths 2 and 3:
budget 3 takes the short arm, budget 4 the long one -- the no-nesting counterexample of the research), and of the
Hamming constraint. PoB-backed parts skip without the runtime. One PoB session; a 5-worker benchmark is running: PoB is
slow, not broken. Check `cmd /c dir /AL` first (junctions). Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`.
Commit early.
