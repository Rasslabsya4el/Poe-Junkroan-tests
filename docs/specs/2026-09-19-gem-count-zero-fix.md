# Spec: derived zero minion counts are scored honestly and never reach the PoB payload

## Scope and evidence

Implement the incident fix from `docs/specs/2026-09-19-gem-count-zero-kills-the-build.md`. Do not edit
`docs/ROADMAP.md` or `docs/DECISIONS.md`. Do not change the worker's `count < 1` contract: it correctly protects
the PoB payload.

The lead reproduced the failure directly on this checkout, using one PoB worker and no optimizer run:

```text
Skeleton: Duelist/Slayer level 80, main link Cyclone,
  extra groups: Summon Chaos Golem, Summon Lightning Golem
PoB ActiveGolemLimit: 1
derived counts: Summon Chaos Golem = 1, Summon Lightning Golem = 0
current main result: PoBHeadlessHostContractError:
  Gem numeric fields must be positive in skill_payload.skill_sets[1].socket_groups[3].gems[1].
```

The cause is confirmed in `search/skeleton.py`: shared golem allocation intentionally assigns a zero to an excess
enabled golem (`divmod(limit, len(golems))`), `refresh_minion_counts` stores it in `Skeleton.gem_counts`, and
both skill writers serialize it. The alternative theory that a missing limit stat caused this is false: missing or
non-numeric stats are excluded today. A numeric zero, or an excess golem at a positive shared limit, causes the bug.

## Required behavior

1. `derived_counts()` remains the source of truth and may return `0`. In particular, two enabled golems under
   `ActiveGolemLimit == 1` must remain `{Chaos: 1, Lightning: 0}`. Also represent a numeric minion limit of zero
   rather than silently defaulting it to one.
2. A zero means the enabled minion gem fields no instances. It must be disabled for the next ordinary PoB score, so
   its buff or damage cannot make the pick appear valuable. Record and log the transition, for example:

   ```text
   minion count: Summon Lightning Golem fields 0 instances by PoB; disabled for scoring (payload count remains 1)
   ```

   If a later refresh sees a positive count, re-enable the gem and log that transition. Re-probing must include a
   previously unfielded candidate so a tree or gear change can make it fieldable again.
3. Every skill payload has a positive integer `count`, including main-link and extra-group gems. The only
   representation of zero fielded instances is the gem's `enabled=False`, never `count=0`. Preserve count data in
   `Skeleton.gem_counts` for reporting/refresh logic; do not replace zero with one there.
4. Eliminate the duplicate serialization drift between `Skeleton.apply_skills()` and
   `SkeletonGenerator._set_main_link_raw()`. The raw trial setter must use the exact same count clamping and
   per-gem enabled state as the skeleton writer. Also make `PobSession.set_skills()` defensively normalize any
   supplied gem count to at least one before it reaches the worker.
5. Initial skeleton application remains fail-closed. During `BuildPipeline._improvement_loop`, however, a
   `PoBHeadlessHostContractError` or `WorkerContractError` raised by a move must drop only that move:

   - cover refine, path swaps, each gear slot, picks/utility re-judge, and every tree and joint kick draw;
   - restore the whole state from immediately before that move: PoB XML, mutable skeleton data, loot raw state and
     wishlist resistance assignments, tree histories/objectives, pipeline objective/derived state, and result picks;
   - append one structured record to `BuildResult.dropped_moves` with `move`, `exception`, `failure_state`, and
     `message`;
   - log one line naming the move and error, continue with the next move, and never re-run `_reconfigure()` after
     loading the saved XML solely to recover from this exception;
   - if restoring itself fails, re-raise rather than claiming a valid build.

   Use the normal public imports:

   ```python
   from junkroan.pob.host_runtime import PoBHeadlessHostContractError
   from junkroan.pob.headless_runtime_worker import WorkerContractError
   ```

   Do not catch arbitrary exceptions. A failed opening `skeleton.apply()` is still a genuine failed skeleton.
6. Put the dropped-move count in `BuildResult.summary()`. In `_finish`, append a warning `Finding` to the result
   audit when the count is nonzero; keep warnings nonfatal. Include `dropped_moves` in the process-worker result
   dictionary so a search report and saved run can account for it.

## Minimal representation

Use the smallest serializable per-gem state that distinguishes a disabled zero-count gem from an enabled gem whose
payload count happens to be one. A `SocketGroup` may carry disabled/unfielded gem indices, and `Skeleton` may carry
the equivalent main-link indices. A name-only set is not sufficient for repeated gems. Include those fields in
`Skeleton.to_json()` / `from_json()` through the existing dataclasses.

At refresh time, derive against the intended minion candidates, not only those currently disabled for zero count.
It is acceptable to briefly write the candidates enabled before taking the derivation readback, then immediately
write the final disabled state; no objective score may be taken in between. Avoid creating a special hand-authored
golem rule: PoB's live limit is the only source of the result.

## Tests

Run focused tests with one PoB worker at a time, then the full suite in the foreground.

1. Extend `tests/test_golem_counts.py` with the exact PoB-backed Slayer/Cyclone regression:
   - Cyclone Slayer, one ordinary utility group (`Battlemage's Cry` is fine), plus Chaos and Lightning Golem groups;
   - assert PoB reports `ActiveGolemLimit == 1` and the derived values are Chaos `1`, Lightning `0`;
   - `refresh_minion_counts()` and the generator's skills writer complete without a contract error;
   - the Lightning Golem payload has `enabled is False` and `count == 1`; no payload gem has a count below one;
   - capture the zero-count log line; assert a later positive derivation re-enables a previously unfielded gem with
     a focused fake/readback test if changing the live PoB limit is impractical.
   - retain the pure derivation test that expects a zero for an excess golem; add a numeric-zero non-golem limit
     assertion if needed.
2. Extend `tests/test_improvement_loop.py` with fakes that mutate both PoB and external state before raising.
   Parameterize both contract exception types. Prove a failed gear move, picks/utility move, and kick are restored,
   recorded, logged, and followed by later moves; the completed loop result must survive. The test fakes must make
   recovery observable through the same full snapshot fields the production code restores.
3. Add a focused assertion that nonzero `dropped_moves` appears in `BuildResult.summary()` and its final audit has
   the warning. Do not write tests that run code from an earlier commit.

Commands:

```powershell
python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_golem_counts.py tests/test_improvement_loop.py tests/test_explain.py
python -m pytest -q -p no:cacheprovider -p no:faulthandler
```

## Measurement after implementation

Use one worker and one seed. A suitable product command is:

```powershell
python scripts/search.py Cyclone --ascendancies Slayer --top 1 --seeds 1 --workers 1 --no-mutation --no-unique-variants
```

Launch this long run detached, do not kill the existing five-worker run, and report the final delivered value,
whether the seed completed, and the dropped move count. Acceptance is a completed seed, never a worker rejection
for a zero gem count. If a contract-failing move is deliberately induced, completion with a nonzero warning count is
also valid; the ordinary request should normally report zero dropped moves after the derived-count fix.

## Commit

Commit the implementation and tests on the worker branch. The subject must state that zero-fielded minions are
disabled and invalid loop moves are recovered. Include focused/full test totals and the one-seed measurement if it
finishes before the worker ends. Do not amend an existing commit.

## Continuation Review (2026-09-19)

The prior worker left an uncommitted implementation in this worktree. Finish that work; do not discard it or create
another worktree. Address these review findings before committing:

1. The loop's `lanes` step is a move that calls `_tune_lanes()` / `_reconfigure()` and can issue the same invalid
   skills payload. Protect it with the exact per-move contract recovery path used for refine, gear, picks, and kicks.
   A failed lane move must restore the pre-move XML and external state, create one dropped-move record, and continue.
2. Snapshot only state whose restoration can affect the build or later optimizer decisions. Do not deep-copy static
   lookup caches (`LootGear._bench_cache`, `_mod_families`; `WishlistGear`'s ladder/bench/raw caches) for every
   ordinary move. Preserve/restore the operational loot state (`current_raw`, resistance assignment/plan, any result
   bookkeeping that affects a future fill), skeleton, objectives, and tree history. If a tree cache could have been
   populated under the failed state, clear/invalidate that dynamic cache on recovery rather than letting stale trial
   results affect the restored build. The normal no-error path must not pay an unbounded deep-copy cost per move.
3. Retain the successful live-PoB regression assertion, both contract exception types, and no arbitrary exception
   catch. Run focused tests first. Run the whole suite only when PoB capacity permits; say honestly if another active
   worker prevents it. Commit all changes, including this continuation note if it remains in the worktree.
