# Spec: a derived gem count of 0 must not kill a build (the first acceptance request lost all three seeds)

## What happened

`junkroan build --skill "Cyclone" --mode hit --ascendancy Slayer --level 80 --workers 5 --no-variants` (queue run
`20260919-1721-run` @d86b8bd, output `artifacts/runs/20260919-1721-run.out`, logs
`artifacts/search-cyclone/logs/full-Slayer-0-s{1,2,3}.log`): the screen was fine (112,072), the full optimize ran
~25 min per seed and then ALL THREE seeds ended with

    full optimize failed Slayer-0 seed 1: PoBHeadlessHostContractError: Gem numeric fields must be positive in
    skill_payload.skill_sets[1].socket_groups[4].gems[1].

(seed 3: `socket_groups[5].gems[1]`). The worker's check is `level < 1 or quality < 0 or count < 1`
(`pob/headless_runtime_worker.py` ~2748). Seed 1's log: loop pass 5 kept the pick "utility Battlemage's Cry -> Summon
Lightning Golem" (301,420 -> 315,279); the build died at the next skills write (loop pass 6, after the gear slots).
The lead's reading: `SkeletonGenerator._apply_groups` (`search/generator.py` ~537) writes
`"count": int(skeleton.gem_counts.get(n, 1))`, and `Skeleton.refresh_minion_counts` -> `derived_counts` (D49 / D57 /
the golem-instances work of 2026-09-18) put a 0 there for the golem -- a minion gem in a UTILITY group whose PoB limit
stat read 0 at that moment. Confirm or refute this from the code and a reproduction; do not take it on faith.

## Task

1. Reproduce WITHOUT a 25-minute run: a Slayer Cyclone skeleton with an extra group holding Summon Lightning Golem
   (next to another utility, as in the log), `refresh_minion_counts`, then the generator's skills write. A PoB-backed
   test that fails on main and passes on your tree.
2. Root cause: why is the derived count 0 (limit stat missing until the gem is applied and recalculated? a golem
   limit read from the wrong actor? the count read while the group is disabled by a trial?). Fix it where the count
   is derived. Rule: a count is what PoB says the build can field; when PoB says 0 for an ENABLED minion gem, the gem
   fields nothing -- that is a fact to log, and the payload still carries `count` 1 (PoB's contract), never 0. If 0
   instances is the true answer, the pick that added the gem must see its real (zero) value through the ordinary
   score, not through an exception.
3. Resilience, general: a move inside the improvement loop (picks, utility links, gear slot, kicks) that raises a
   `PoBHeadlessHostContractError` / `WorkerContractError` must cost that MOVE, not the build: restore the state from
   before the move, log one line with the move and the error, continue. A build that loses a move still delivers.
   (The first write of a skeleton may still raise: a skeleton that cannot be applied is a real failure.)
   Count in the run's summary how many moves were dropped this way; the audit gets a warning when it is not 0.
4. Measure: the same request with `--seeds 1` semantics if the CLI has it, else the smallest product-path run that
   reaches the improvement loop with the golem pick (you may fix the utility list through the request's
   `utilities fixed` option to get there fast); report the final build and that no seed is lost. One PoB worker.
5. Check `cmd /c dir /AL` in your worktree first: `var`, `vendor`, `artifacts` must be junctions. Focused tests, then
   the whole suite once in the foreground (a 5-worker search is running; PoB-backed tests are slow, not broken).
   Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`. Commit early.
