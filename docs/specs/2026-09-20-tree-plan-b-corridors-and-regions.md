# Spec: tree plan B -- the trunk gets moves of its own (corridor exchange, region challenge by completed replacements, a second repair)

Read first: `docs/research/2026-09-19-tree-search-plan.md` (the plan, its addenda 22:20 and 01:00), `docs/DECISIONS.md`
D84 (how a move is judged) and D87 (proof holders). Facts this task stands on, all measured:

- On the 14 best builds of `core14-rules` (1,411 points): 32% of allocated nodes are leaves (refine reconsiders them),
  38% sit in subtrees of 2-6 (path swaps), 8% in 7-12 (only the random kick), **22% are TRUNK -- a node whose removal
  drops 13 or more allocated nodes -- and no move ever reconsiders them after construction.**
- PoB's fast what-if (`PobSession.trial_stats(..., mode="fast")`, 7 ms per trial) does NOT cascade: a disconnected set
  is evaluable, so an exchange can be scored atomically as long as WE guarantee the final set is connected.
- The whole-tree additive MIP is dead (experiment A: 0 of 24 proposals improved while feasible; actual / predicted
  gain -0.48 .. -65 at ten changes). Single-node what-if numbers may RANK candidates; they are never summed into a
  prediction, and every accepted change is a real PoB mutation judged by the pipeline's judge.
- On a delivered stormbrand build the loop's whole remaining gain (+2.47%) came from ONE random tree kick; refine,
  swaps, gear and picks found nothing (replay bench, `artifacts/replay/20260920-025*-smoke-*`).

## The three moves (in `src/junkroan/optimizer/tree_optimizer.py`; PoB is the judge; no node-name lists)

1. **Corridor exchange** (`exchange_corridors`). A corridor = a maximal path of allocated nodes between two KEY nodes
   (the class start, a node with three or more allocated neighbours, a notable / keystone / jewel socket / mastery
   anchor, a proof holder of D87) whose inner nodes have exactly two allocated neighbours. For each corridor, generate
   up to `k=8` alternative connections between the same two key nodes through UNALLOCATED nodes (k shortest simple paths
   in `TreeGraph` that avoid the corridor's inner nodes; length at most the corridor's length + `slack=2`, the extra
   points paid by dropping the currently weakest leaves -- one fast what-if each to pick them), score each completed
   exchange `{remove: corridor inner, add: alternative inner (+ leaves dropped)}` with ONE fast what-if, keep the best
   if it beats the incumbent by `min_gain`, apply it for real (`mutate_nodes`), verify connectivity and point count,
   let the caller judge it. With more than two retained components the connector must join all of them; a corridor
   whose endpoints have no alternative inside the limits is recorded as "no bypass" (then only move 2 can touch it).
2. **Region challenge** (`challenge_regions`). Candidate regions = connected allocated sets that detach cleanly (a key
   node's whole downstream side), in size buckets 4-6 / 7-12 / 13-20 / 21-30. Rank regions NOT by how little their
   removal costs but by the best COMPLETED replacement found cheaply: for each region, try up to `r=12` replacements
   of the same point count grown from the region's attachment node by the repair policies below using fast what-ifs
   only, and order regions by (best replacement score - incumbent). Challenge the top regions for real: remove the
   region, regrow with its old corridor FORBIDDEN for the first half of the points (otherwise greedy rebuilds the same
   trunk and the challenge tests nothing), judge.
3. **A second repair policy** next to the greedy one (used by move 2 and by the existing `reoptimize` kick, chosen
   alternately): **target-first** -- among unallocated notables / keystones-allowed / mastery anchors within
   `radius=8` of the attachment node, score each as a disconnected single fast what-if, divide by the points its
   shortest connection costs, take the best target, allocate its connection, repeat while points remain, then let
   greedy fill the rest. (Greedy looks one node ahead and recreates the basin it came from; target-first commits to
   a destination.)

All three respect D87: a removal set containing a proof holder is judged honestly (the machinery exists:
`needs_honest_removal`). All three run inside the loop's per-move recovery wrapper (`snapshot_move` / `drop_move`) and
carry COUNT budgets (candidates, not seconds) so that the replay bench is deterministic; seconds budgets only as an
outer guard in production.

## Wiring

`BuildPipeline._improvement_loop`: two new plan entries after "swaps": `("corridors", ...)` and `("regions", ...)`,
the second only in passes where refine + swaps + corridors kept nothing (it is the expensive one). The random
`kick tree` stays as it is (it is the control). `scripts/replay_bench.py --move corridors | regions` run them alone.
Log lines in the style of the existing ones (`corridor exchange kept: -5 [names] -> +5 [names] value a -> b (3s)`,
`region challenge kept: ...`, `no bypass: ...`).

## Acceptance (D84: the bench and counts, never one seed's value)

Builds: the 96 delivered builds of `artifacts/benchmark/20260919-0130-new18-rules` and `20260919-0941-core14-rules`
(the bench flags the ones that start infeasible under today's rules; report with and without them). Runs, 5 workers:
`--move kick-tree` (control), `--move corridors`, `--move regions`, each `--seed 1`, and the paired reports against
the control. Report:
- builds improved / unchanged / worse, median and mean gain %, seconds per build, gain per 100 s -- per move;
- structural counts over the 96 builds: share of TRUNK nodes that were part of at least one evaluated candidate
  (target: above 95%; today 0%), corridors found / with a bypass / exchanged, regions challenged / kept by bucket,
  which repair policy produced each kept region;
- D87's counters (honest holder judgements, RESTORE FAILED = 0) and audit errors after the move (must not rise).
A move that pays less per second than the control on the paired report is still reported, not hidden: the lead
decides what enters the default plan.

## Tests (fast, fake PoB + small hand-made graphs)

Corridor detection on a graph with a known trunk (two key nodes joined by a 4-node corridor and a 5-node bypass: the
exchange is found, scored with one what-if, the final set is connected and the point count holds; with `slack=0` it is
"no bypass"); a corridor containing a proof holder goes through the honest path; region ranking by completed
replacement (a region that is cheap to remove but has no better replacement ranks BELOW one that is costly to remove
and has a much better replacement -- the research's example: loss 1 / recovery 1.2 against loss 100 / recovery 150);
the forbidden-corridor rule (the regrow may not re-take the old corridor in its first half); target-first picks the
destination with the best value per connection point; count budgets are honoured. Whole suite once at the end with
`-p no:faulthandler`. Do not edit `docs/ROADMAP.md`, `docs/DECISIONS.md`, `CLAUDE.md`. Commit after each move; begin
the final message with `=== FINAL REPORT ===`.
