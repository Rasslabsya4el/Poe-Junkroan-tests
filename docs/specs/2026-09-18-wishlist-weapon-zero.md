# Spec: wishlist gear leaves the bow slot empty and the quiver kills the build (bleed_bow, impale_ballista)

Run `gear-wishlist` @04bc1d6 (2026-09-18 19:14, `artifacts/benchmark/20260918-1914-gear-wishlist/logs/`):
two of six smoke references FAILED within 35 s, every seed will (the filler is deterministic):

```
bleed_bow s1        FAILED PoBHeadlessHostContractError: ...:16: item is not valid for slot Weapon 2
impale_ballista s1  FAILED PoBHeadlessHostContractError: ...:16: item is not valid for slot Weapon 2
```

The log lines before the failure (gear pass 1, empty tree, right after `config (conservative lane)`):

```
bleed_bow:        [Weapon 1] wishlist: Citadel Bow | 0 mods (ilvl 76): 56,277 -> 0 (viol 5.691 -> inf) [3/22 bases, 11.6s]
impale_ballista:  [Weapon 1] wishlist: Imperial Bow (22% increased Elemental Damage with Attack Skills) | 0 mods (ilvl 76): 15,570 -> 0 (viol 7.058 -> inf) [3/22 bases, 14.8s]
```

The same code on the third bow reference works:

```
burning_arrow_snipe: [Weapon 1] wishlist: Imperial Bow (...) | 4 mods (ilvl 76): 182,220 -> 145,805 (viol 8.387 -> 8.375) [3/22 bases, 13.6s]
```

What the lines say: on the two failing references every bow of the class, bare or filled, scores value 0 with
an infinite violation; `WishlistGear._drop_if_worse_than_empty` then leaves Weapon 1 EMPTY (`result.before >
score`); the next slot is the quiver, and PoB refuses a quiver without a bow with a hard contract error that
nothing catches, so the whole build dies. `--gear loot` on the same pin builds both references (bleed_bow
141.4%, impale_ballista 92.4% of the author by 3-seed median), so the defect is in the wishlist path
(`src/junkroan/optimizer/wishlist_gear.py`, possibly what `pipeline.py` hands it). 79759c4 measured bleed_bow's
weapon slot at `0 -> 453,499` through the loot filler; whether the wishlist filler ever built these two
references is unknown -- check `git diff 79759c4 04bc1d6 -- src/junkroan/optimizer/wishlist_gear.py` (the
attribute payment and `empty_stats`) but do not assume the regression is there.

## Task

1. Reproduce first (must fail before the fix, ~35 s each; run as `junkroan.exe`, the copy of the interpreter
   at `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`, because another project on this
   machine kills `python.exe`): `junkroan.exe scripts/benchmark.py bleed_bow --seeds 1 --no-variants --gear
   wishlist --workers 1 --tag wl-repro`.
2. Diagnose with PoB readbacks, not by reasoning: for bleed_bow and impale_ballista at the state the filler
   sees (skeleton applied + conservative config, empty tree), report `CombinedDPS` and every violated
   objective term (name, value, floor) for: Weapon 1 empty; the author's bare base; the bare Citadel /
   Imperial Bow; and say which term is infinite and why the value is 0 on these two and not on
   burning_arrow_snipe. Put the table in the report.
3. Fix the cause generally (never a rule for one build or one base name). Whatever the cause, these two
   invariants must hold afterwards and get a test each:
   - a slot the skeleton fills and the main skill needs (PoB gives the main skill no number with the slot
     empty: `CombinedDPS` 0) is never left empty by the wishlist filler: an item that restores a number beats
     an empty slot even when it is "worse than before" by violation;
   - an item PoB refuses for a slot (the hard `item is not valid for slot` error, or a trial that comes back
     `ok: false`) never kills the build: the filler leaves the slot as it was, logs one line, goes on.
4. No behaviour change where the filler works today: burning_arrow_snipe's first weapon line must stay
   exactly `Imperial Bow (...) | 4 mods (ilvl 76): 182,220 -> 145,805 (viol 8.387 -> 8.375)`.

## Acceptance (numbers in the report and in the commit message)

- `junkroan.exe scripts/benchmark.py bleed_bow impale_ballista --seeds 1 --no-variants --gear wishlist
  --workers 2 --loop-seconds 600 --tag wl-fix`: both `ok`, neither FAILED; report each build's % of the
  author, the `[Weapon 1]` and `[Weapon 2]` lines of gear pass 1 (mods >= 1 on the bow, value after > 0), and
  the audit's error count. The machine is running a 5-worker benchmark: use at most 2 workers and expect
  ~2x wall clock.
- burning_arrow_snipe: the weapon line above unchanged (stop the run after gear pass 1; a short
  `--loop-seconds 60` run is enough).
- Tests: fake-session unit tests for the two invariants; one PoB-backed test (skips without `var/cache/pob`)
  that fills Weapon 1 then Weapon 2 on bleed_bow with the wishlist filler from the pipeline's gear-pass-1
  state and asserts both slots non-empty and `CombinedDPS > 0`. Run `python -m pytest -q -p no:cacheprovider
  -p no:faulthandler tests/test_wishlist_gear*.py tests/test_gear_slot_order.py` plus your tests, then the
  whole suite once, in the foreground.
- Commit on your branch with the before/after numbers in the message.
