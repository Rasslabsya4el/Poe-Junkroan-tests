# Spec: the judge fix, third step -- a holder is a NECESSARY proof, not a sole one

Your FIRST command in your worktree: `git merge gpt-2026-09-20-judge-fix-v2-proof-holders-only` (163492d: v2 with main
merged in, whole suite 835 passed). Read `docs/specs/2026-09-20-judge-fix-v2-proof-holders-only.md` first. v2's
machinery is right and verified by the lead's foreman (removal sets without a holder take main's fast path unchanged;
a holder removal is judged by real removal + reconfigure + snapshot restore; no `RESTORE FAILED`; the replay sits inside
the per-move recovery wrapper with a 90 s budget). It missed its acceptance for ONE reason, proved on the delivered
build with PoB:

`derive_config` gives winter_orb's `usePowerCharges` TWO proof lines: "gain a power charge after spending a total of
200 mana" (Occultist ASCENDANCY node 62504) and "gain a power charge each second while channelling a spell" (Caster
Mastery 40196, effect 33089). The input stands on the SUM of their rates: the replay measured that removing the mastery
alone flips it (`usePowerCharges: True -> None`, `overridePowerCharges: 3 -> None`, 95,411 -> 81,692). v2's
`_set_proof_holders` (`pipeline.py` ~1378-1430) calls an input ambiguous as soon as ANY of its lines has no owner among
`TreeGraph` nodes (ascendancy nodes are not in it), so the map was EMPTY on both references: 0 honest judgements,
winter_orb still 5 reverted batches / 456 s, Minion Life (32024) still allocated.

## What to change

1. **Necessary, not sole.** A tree node / mastery effect is a proof holder of an input when the conservative lane
   would turn that input off, or lower its derived number, WITHOUT that node's proof line(s) -- with every other source
   (ascendancy, items, gems, other nodes) left in place. Compute it by re-running the rule's own derivation with the
   node's lines masked: pure Python over the evidence `derive_config` has already collected for that reconfigure (no
   PoB call; budget: under 50 ms per reconfigure, measure it). Lines owned by something that tree moves cannot remove
   are fixed evidence, never "ambiguous". Where a rule's derivation cannot be re-run without PoB, fall back to v2's
   sole-proof test for that input and log `proof holders: <input>: not decidable without PoB (<rule>)` once.
   The map keeps the before / after value of the input: `{(40196, 33089): {"usePowerCharges": (True, None),
   "overridePowerCharges": (3, None)}}`, and the log line says so.
2. **A reverted tree move keeps the optimizer's memory.** v2 routes a judge-reverted tree move through
   `restore_move` -> `invalidate_after_recovery()`, which clears `_unswappable` and `_rejected_subtrees`
   (`pipeline.py` ~795, `tree_optimizer.py` ~346): `subtrees skipped` lines fell from 3 to 0 and winter_orb's passes 4
   and 5 re-tried the identical 5 candidates (97 s). Only a CONTRACT-ERROR recovery invalidates those; a plain revert
   restores build and lanes and keeps them.
3. **The replay's labels tell the truth**: `FALSE swap` only when the honest value is lower than before the step (or a
   conservative input changed for the worse); a step that gains less than `min_gain` is `below min gain`, not FALSE; a
   step whose mutation no longer applies because an earlier step was rejected is `skipped: depends on a rejected step`.
4. Remove the dead assignment `removal_reconfigured = ...` (`tree_optimizer.py` ~1153).

## Acceptance (counts; one seed's value is noise)

`scripts/benchmark.py winter_orb stormbrand --seeds 1 --seed 2 --no-variants --workers 2 --loop --loop-seconds 900` on
your tree. v2's run for comparison (also 2 workers): `artifacts/benchmark/20260920-0145`; the parent's:
`artifacts/benchmark/20260919-1947`. Report, counted from the logs:

| count | parent | v2 | target |
|---|---|---|---|
| winter_orb: path-swap batches the judge reverted / seconds | 5 / 501 s | 5 / 456 s | <= 1 |
| Minion Life (node 32024) in winter_orb's delivered build | yes | yes | no |
| candidates per 120 s path-swaps move (winter_orb / stormbrand) | 10.0 / 12.0 | 8.2 / 13.0 | within 10% of the parent |
| `proof holders:` lines | - | 0 | >= 1 on winter_orb, naming Caster Mastery -> usePowerCharges |
| honest holder judgements: how many, seconds each | - | 0 | report |
| `RESTORE FAILED` / `restore drift` | 0 | 0 | 0 |
| replay: fired, FALSE / below min gain / skipped | - | 21 lines: 6 kept, 6 FALSE, 7 mismatches | report; every FALSE with its changed inputs |

Tests (fast, fake derivation): an input proved by two lines whose rule needs BOTH (an unowned ascendancy line + a
mastery line) -> the mastery IS a holder with the (before, after) pair; the same input where either line suffices ->
no holder; a line owned by an item -> fixed evidence, never ambiguous; `_set_proof_holders` on a fake pipeline FINDS a
holder (v2 had only hand-set maps and one `== {}` assertion); a judge-reverted tree move keeps `_rejected_subtrees`, a
contract-error recovery clears it; the three replay labels. Check `cmd /c dir /AL` first (junctions). Focused tests,
then the whole suite once, foreground, `-p no:faulthandler`. Do not edit `docs/ROADMAP.md` or `docs/DECISIONS.md`.
Commit early and after each numbered part; begin your final message with `=== FINAL REPORT ===`.
