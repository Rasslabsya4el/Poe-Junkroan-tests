# Spec: the tree moves and the pipeline's judge disagree about proof-holding nodes, and a whole batch of swaps pays for it

## What the logs show (found from the user's "how did a useless Minion Life node survive?")

`artifacts/benchmark/20260919-0941-core14-rules/logs/winter_orb-s2.log`, every loop pass and the fixed-point check:

    path swap kept: -1 [Caster Mastery] -> +1 [Spell Damage]  value 241,402 -> 244,195 (1s)
    path swap kept: -1 [Minion Life] -> +1 [Attack and Cast Speed]  value 244,195 -> 246,885 (1s)
    ...
    fixed point check tree path swaps: 207,552 (viol 0.000) vs 241,402 (viol 0.000), reverted (94s)

`TreeOptimizer.swap_subtrees` judges a swap with the config frozen. Caster Mastery's effect is the PROOF the
conservative lane stands `usePowerCharges` on (the add path knows it: "generator Caster Mastery: judged with
usePowerCharges on"). Removing it looks like +1.2% inside the move; then the pipeline re-derives the config, the
proof is gone, power charges switch off, the honest value is 207,552, and the pipeline reverts the WHOLE move --
including the real improvement next to it (Minion Life is dead weight: removing it moves nothing PoB computes; the
lead's dead-node measurement, `docs/research/scripts/2026-09-19-dead-nodes.py`). The same two swaps are found and
thrown away again in every pass; the delivered build keeps the dead node.

Campaign-wide (the lead's count over the 42 logs of that run): 202 path-swap moves were reverted by the pipeline's
judge, 11,551 s spent in them (about 275 s per build, ~10% of the median build), 117 swaps that the move itself had
kept were thrown away with their batch. Most often involved: Intelligence (18), Caster Mastery (17), Minion Life (8),
flask / mark clusters, Mark Mastery (3).

## Task

1. **Removal sees what the add path sees.** When a tree move (refine's leaf removal, `swap_subtrees`, the ruin step
   of `reoptimize` / the kicks where they judge removals) removes a node or mastery effect that the conservative lane
   currently uses as the proof of an enabled input (the optimizer already indexes such text: `generator_kinds`,
   `_generator_text`; the pipeline knows which inputs stand on which sources through `derive_config`'s reasons /
   `charge_sources`), the trial is judged with that input as it would be AFTER the removal (off, or at the count
   the remaining sources support) -- the mirror of "judged with usePowerCharges on". No name lists: derive it from the
   same data the add path uses. If another source still proves the input, nothing changes.
   Find out what the other frequent cases are (Intelligence 18 times: an attribute requirement the move's objective
   does not carry? a mana / Archmage dependency?) and report each cause; fix the ones that are the same kind of
   disagreement (the move's objective must carry every relation the pipeline's judge uses), list the rest.
2. **A failed batch is replayed, not thrown away.** When the pipeline's honest judge rejects a multi-swap move, replay
   the move's kept swaps one at a time from the pre-move state, judging each honestly, and keep the ones that hold
   (bounded: at most the swaps the move kept; a swap costs one reconfigure + one stats read). Log which swap was the
   false one. With fix 1 this should become rare; it is the safety net.
3. **Measure** (one PoB worker; a 5-worker search may be running -- PoB is slow, not broken):
   - `scripts/benchmark.py winter_orb --seeds 1 --seed 2 --no-variants --workers 1 --loop --loop-seconds 900` on the
     parent and on your tree (if `--seed 2` is not how a single seed is chosen, use the benchmark's own way): the final
     value, whether Minion Life is still allocated, how many path-swap moves the judge reverted and the seconds in them.
   - the same for `stormbrand` (the usual control).
   - From the two runs' logs: reverted path-swap moves and seconds, before / after.
   A before / after comparison is a measurement, never a test that runs another commit's code.
4. Tests: a fake-PoB unit test where removing a proof-holding mastery is judged with the input off and is NOT kept,
   while a dead leaf next to it IS swapped; a test of the replay (batch of two swaps, one false: the true one
   survives). PoB-backed tests skip without the runtime.
5. Check `cmd /c dir /AL` first (`var`, `vendor`, `artifacts` junctions). Focused tests, then the whole suite once,
   foreground. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early. Other workers are editing
   `pipeline.py` (gem count / dropped moves), `config_rules.py` and `audit.py`: keep edits local.
