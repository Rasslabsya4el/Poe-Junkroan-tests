# Spec: gear transplant -- how strong is our generated day-1 gear against the real characters' own (measurement, no optimizer change)

Two gear models, two hand-set realism knobs: the loot simulation (D19: best of N random rares per slot by PoB
spawn weights, N = 600 in construction / 200 in the loop, one bench craft) and the deterministic wishlist (D68/D73:
`useful_mods` 3 / 4, median tier, one bench craft, numbers copied from the 299 real Tuadh rares). On `gear-loot` /
`gear-wishlist` @04bc1d6 they disagree by up to 2x: burning_arrow_snipe s1 -- final bow 1,304,946 under loot,
682,234 under wishlist; build 137-184% of the author under loot, 71% under wishlist; cold_dot 112.4% against 94%.
The research (`docs/research/2026-09-18-generated-gear.md` section 4) found loot rares equal to the authors' by tier
rank (0.55 / 0.55) with 4.98 affixes against 4.61 -- but nothing has measured what that gear is WORTH in PoB.

The user, 2026-09-18: the realism of generated gear must not be dictated by Tuadh's numbers as an input. So Tuadh
becomes the check of the output instead: put our gear on the author's own build and compare with the author's gear.

## The measurement

`scripts/gear_transplant.py` (new; reuse the benchmark's author preparation -- tree converted to 3_29, gems
normalized to the rails, our conservative lane, the objective with the author's own floors exactly as
`scripts/benchmark.py` builds it -- import, do not copy). Per reference:

- **A**: the author's build as prepared above; record the objective stat (CombinedDPS or FullDPS as the benchmark
  chooses), Life, TotalEHP, the max hits, the three resists, feasibility under the author-floors objective.
- **B (loot)**: every RARE slot of the author emptied (uniques, flasks, jewels, the tree, gems and config untouched),
  then filled by `LootGear` on the author's bases with the pipeline's own call (construction N from the rails, the
  same number of passes as gear pass 2, the bench craft on), seed 1; seeds 1-3 on the six smoke references.
- **C (wishlist)**: the same with `WishlistGear` (its own base choice on).

Report per reference: A, B, C objective values, B/A and C/A, feasible yes/no for each, Life and TotalEHP ratios,
seconds. Then medians of B/A and C/A over all references, over the smoke six, and split by attack / spell / minion /
DoT (the skeleton's damage mode). 1.00 means "our gear is worth what the real character's gear is worth".

Sets: the 32 Tuadh references (`SETS["new18"]` + `SETS["core14"]`). One PoB session at a time (the machine is
running a 5-worker benchmark; expect 3-6 h). Run as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`,
detached, log to `artifacts/runs/gear-transplant.log`, results to `artifacts/runs/gear-transplant/results.json` and
`docs/research/2026-09-19-gear-transplant.md` (tables only, no conclusions -- the analysis is the main model's).
A reference that fails is a row with the error, not a stop.

## Second table, same script (`--sweep`), smoke six only

The two knobs swept, so the lead can read where each model crosses 1.00:
- loot: construction N in {25, 50, 100, 200, 600};
- wishlist: `useful_mods` default in {3, 4, 5} (weapons +1), tier rule as today.
One row per (reference, knob value): ratio to A, feasible.

## Tests

Unit tests with a fake session for: only rare slots are emptied (a unique in a slot survives), the author's floors
reach the objective, a failing reference does not stop the run. One PoB-backed smoke test (skips without
`var/cache/pob`) on cold_dot with N = 25: B is finite and the unique slots are unchanged. Focused tests, then the
whole suite once, in the foreground. Commit on your branch; the long run itself is launched by the lead after review
(do run cold_dot and stormbrand end to end and put their rows in the report).
