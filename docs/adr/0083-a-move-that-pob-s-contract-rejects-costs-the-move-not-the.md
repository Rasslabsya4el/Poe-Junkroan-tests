# 2026-09-19 D83. A move that PoB's contract rejects costs the move, not the build; a gem that fields nothing is disabled, never counted 0

Status: Accepted

The first acceptance request (Cyclone Slayer, 19.09) lost 3 of 3 seeds, and SRS Necromancer 2 of 3, after ~25 minutes
each, to `Gem numeric fields must be positive`: the picks move added a second golem, `derived_counts` shares
`ActiveGolemLimit` 1 between two golems (1 and 0), and both skills writers serialised the 0. Rules:
(1) a derived count of 0 means the gem fields nothing: it is DISABLED for scoring (so its buff cannot make the pick look
valuable), its payload count stays 1 (PoB's contract), and every refresh probes it again (a tree or gear change can
make it fieldable); PoB's numeric 0 is believed for every minion limit, not only golems. (2) One serializer
(`Skeleton.skill_payload`) feeds both the skeleton's writer and the generator's raw trial setter. (3) Inside
`_improvement_loop` a `PoBHeadlessHostContractError` / `WorkerContractError` raised by a move (lanes, refine, path
swaps, a gear slot, picks, either kick) restores the state from before that move and is recorded in
`BuildResult.dropped_moves` (summary, a warning in the audit, the results row); a failed restore re-raises; the first
write of a skeleton still fails the build. Numbers: whole suite 807 passed; the 7 `test_finish_*` failures main carried
since the tree-hygiene merge are fixed with it. Branch `gpt-2026-09-19-gem-count-zero-fix`, merge 87ab8a2; the two
requests are re-queued.

