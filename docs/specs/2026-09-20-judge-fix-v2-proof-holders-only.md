# Spec: the judge fix, second attempt -- only a removal that takes a PROOF away is judged the expensive way

Read `docs/specs/2026-09-19-tree-moves-see-proof-holders.md` first (the problem, the logs, the campaign counts: 202
reverted path-swap moves, 11,551 s, 117 kept swaps lost over 42 builds). The first attempt, branch
`gpt-2026-09-19-tree-moves-see-proof-holders` (merged with main as 3f493e4 by the lead's foreman), is REJECTED. It
re-derives the whole config after EVERY real removal. Measured by the foreman on its own benchmark logs
(`artifacts/benchmark/20260919-1947` = parent, `...-2252` = branch):

| | parent | first attempt |
|---|---|---|
| winter_orb s2: batches the judge reverted / seconds / kept swaps lost | 5 / 501 s / 25 | 1 / 88 s / 0 |
| Minion Life (node 32024) still allocated | yes | no |
| a REJECTED swap candidate costs (winter_orb / stormbrand) | 18.1 s / 5.2 s | 27.8 s / 12.9 s |
| candidates tried per 120 s path-swaps move (winter_orb / stormbrand) | 10 / 12 | 4.75 / 7 |
| `RESTORE FAILED` lines (winter_orb s2) | 0 | 2 (the restore hook writes lanes over the snapshot it has just loaded) |
| `replay` fired | - | 0 times in every log: untested in production, and it has no time budget |

So it removes the batch reverts and halves the search. Also rejected: refine's gate `new_score > removal_score` (it
discards a swap that beats the pre-swap build whenever the removal alone helped), the reconfigure in the middle of a
kick (the rebuild then runs under lanes derived from a half-demolished build), the generation rule that forces every
later restore through a full XML reload.

## What to build (start from MAIN; you may port code from 3f493e4 where this spec says so)

1. **Proof holders.** After every `_reconfigure` the pipeline hands each `TreeOptimizer` a map
   `proof_holders: {node_id (or (node_id, mastery_effect_id)): {config inputs}}` = the allocated tree nodes / mastery
   effects that are the ONLY remaining proof of an input the CONSERVATIVE lane currently holds on. Source of truth:
   what `derive_config` already knows about why an input is on (its reasons / `charge_sources` / the D77 proof lines)
   and the node text index the add path already uses (`generator_kinds`, `_generator_text`). If `derive_config` names
   a proof only by its text line, attribute it to the allocated node or mastery effect that carries that line; a
   proof that also stands on an item, a gem or another allocated node is NOT a sole proof and its nodes are ordinary.
   No name lists. Log one line per reconfigure when the map is not empty: `proof holders: Caster Mastery [effect
   ...] -> usePowerCharges`.
2. **Only those removals are judged honestly.** In refine's leaf removal, `swap_subtrees`, the ruin step of
   `reoptimize` and the joint round: a removal set that contains NO proof holder goes exactly the way it goes on main
   (fast what-ifs under the frozen config, the fast inverse-mutation restore). A removal set that contains one is
   judged the way the ADD path judges a generator ("judged with usePowerCharges on", `enabler_hook`): really remove,
   reconfigure, score, and restore config AND tree to the snapshot if it is not kept -- and the restore must bring the
   snapshot's value back (`RESTORE FAILED` = a bug). No reconfigure for any other removal, none in the middle of a
   kick, no generation-forced XML restores for ordinary candidates.
3. **The replay is the safety net and the diagnostic** (port `Step.removed_node_ids`, `Step.added_mastery_effects`,
   `replay_path_swaps` and their tests from 3f493e4; it already sits inside main's per-move recovery wrapper): when the
   pipeline's judge rejects a multi-swap batch, replay the kept swaps one at a time from the pre-move state, each
   judged honestly; budget `max_seconds=90` and at most the swaps the move kept; every rejected step logs
   `replay: FALSE swap -N [names] -> +M [names]: <value before> -> <honest value>, config inputs that changed:
   [...]` (diff the conservative inputs before / after that step's reconfigure). That log line is how the remaining
   causes (Intelligence 18 times, flask / mark clusters, Mark Mastery) get named; do not guess them.
4. NOT in this task: refine's two-phase remove / add and its `removal_score` gate; any hook on every real removal.

## Acceptance (counts, not values: one seed's value is noise of ~15%; a before / after comparison is a measurement,
## never a test that runs another commit's code)

`scripts/benchmark.py winter_orb stormbrand --seeds 1 --seed 2 --no-variants --workers 2 --loop --loop-seconds 900`
on your tree (the parent's logs exist: `artifacts/benchmark/20260919-1947`). Report, counted from the logs:
- batches the judge reverted and their seconds: target winter_orb <= 1 (parent 5 / 501 s);
- Minion Life (32024) not allocated in winter_orb's delivered build;
- candidates tried per path-swaps move: within 10% of the parent's (10 and 12 per 120 s);
- `RESTORE FAILED` lines: 0; honest (proof-holder) removal judgements: how many, seconds each;
- `replay` lines: how often it fired, every FALSE swap with its changed config inputs;
- `proof holders:` lines: which nodes, which inputs, on both references.

Tests (fast, fake PoB): a removal set without a proof holder makes zero reconfigure calls; one with a sole proof holder
makes exactly one and is not kept when the honest value is lower, and the dead leaf next to it IS swapped; a proof
with a second source (an item) is not a holder; the replay's budget and its FALSE-swap log line; restore after a
rejected honest removal returns the snapshot's lanes and tree. Check `cmd /c dir /AL` first (junctions). Focused tests,
then the whole suite once, foreground (`-p no:faulthandler`: a PoB worker crash under load once produced a 789 MB dump).
Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit EARLY and after each numbered part; begin your final
message with the line `=== FINAL REPORT ===`.
