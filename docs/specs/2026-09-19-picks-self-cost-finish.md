# Spec: finish the picks / self-cost fix that timed out one step before its commit

Branch `gpt-2026-09-19-picks-never-keep-an-infeasible-support`, commit 4164895 (a WIP commit made by the lead from the
worker's tree after its 300 min timeout). Original spec: `docs/specs/2026-09-19-picks-never-keep-an-infeasible-support.md`.

What the first worker established (its transcript, `artifacts/runs/gpt-worker-2026-09-19-picks-never-keep-an-infeasible-support.md`):

- Cause: `SkeletonGenerator` kept the `Objective` captured before a support trial, so the "honest" score after
  `_reconfigure()` still lacked the refreshed `SelfCostPerSecond`; the log shows the pick `Faster Projectiles ->
  Sacrifice` recorded as 137,112 -> 201,220 while the applied build already carried a 0.790 violation.
- The contract that WORKED and was measured: a TEMPORARY candidate (a support or utility being tried) refreshes only
  the self-cost context (`BuildPipeline._reconfigure(full=False)` -> `_refresh_self_cost`), a COMMITTED pick gets the
  full lane / ramp reconfiguration (`full=True`). A full reconfigure during a trial is NOT trial-safe (the ramp
  context is built from the committed link): it moved the stormbrand control from 1,631,723 to 1,797,073.
- Measured with that contract: `stormbrand --seeds 1 --no-variants --workers 1 --loop --loop-seconds 300` = 1,631,723
  FullDPS on the parent commit AND on the fixed tree (bit-identical, the same two re-judged support swaps);
  `poison_spark --seeds 1 --loop-seconds 900` feasible at violation 0, main link `Spark + Added Lightning Damage +
  Elemental Focus + Unbound Ailments + Spell Echo`, no Sacrifice, 310,150 CombinedDPS, 0 audit errors.
- Then a "clean-up" of the callback signature broke that contract, the worker noticed and was restoring it when the
  timeout hit. State of 4164895: 28 focused tests pass, `tests/test_self_cost_per_candidate.py::
  test_rejudge_rejects_a_damage_pick_that_adds_self_cost` FAILS (`_PickPob` has no `read_state`, which the trial
  path `trial_score -> _refresh_self_cost` now calls).

## Task

1. In your worktree: `git merge gpt-2026-09-19-picks-never-keep-an-infeasible-support` (main has moved: D78 touched
   `pipeline.py`, D80 `config_rules.py`; resolve conflicts keeping both).
2. Restore exactly the measured contract above, nothing cleverer. Make the focused tests green WITHOUT weakening the
   failing test's assertion (a pick that adds value and a self cost is rejected): fix the fake or the seam, not the
   invariant. No further refactor of the callback protocol.
3. Re-measure, one PoB worker (a 5-worker benchmark is running): the stormbrand control must again give exactly
   1,631,723 -- run the SAME command on your tree and compare with `artifacts/benchmark/20260919-1217-picks-fix-parent`
   (the parent's run; read it, do not recreate it). Note: main now also contains D78 / D80; if the number differs,
   first check whether the parent run predates those merges and say so -- then the comparison is your tree against
   current main, run both. poison_spark s1 (`--loop-seconds 900`): feasible, no Sacrifice unless the relation holds.
4. `artifacts/parent-before-picks` is a checkout the first worker made, with `var` / `vendor` junctions inside: do
   NOT delete it or anything under `artifacts/` (CLAUDE.md "Worktrees hold junctions").
Focused tests (`tests/test_self_cost_per_candidate.py tests/test_picks_memo.py tests/test_reserving_group_drop.py
tests/test_generator_corpus.py`), then the whole suite once, in the foreground; run scripts as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker: write the code yourself.
Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit EARLY: commit as soon as the focused tests are green and
again after the measurements -- the first worker lost its commit to the timeout.
