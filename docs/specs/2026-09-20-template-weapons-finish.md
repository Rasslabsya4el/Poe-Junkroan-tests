# Spec (finish): template weapons -- per-rank tier positions the owner approved, and weapon bases ranked by VALUE

FIRST COMMAND in your worktree: `git merge gpt-2026-09-20-template-weapons-tiers-and-bases` (the unfinished work this task
finishes: the census by value, the two rails, the payable-requirement base screen; 9 commits, clean; resolve any conflict
mechanically, keep both sides). Then read `docs/specs/2026-09-20-template-weapons-tiers-and-bases.md` (the parent spec) and
`artifacts/runs/gear-templates/weapon-lines-census.md` + `bases-report.md` (its measurements).

## What the measurements said

Census by value (37 author weapons of the 32 Tuadh sets; our loot's 37): median USEFUL lines 3 for both; relative tier position
`(tier-1)/(of-1)` of the top-1 / top-2 / top-3 line: authors 0.43 / 0.57 / 0.69 (all useful lines T5, 0.57), our loot
0.27 / 0.43 / 0.44 (T3, 0.37); today's template: 0.50 for every open line. Feeding the AUTHORS' numbers into the rails made all
six sets weaker (bleed_bow 124.5 -> 101.3% of the author, burning_arrow_snipe 69.6 -> 51.1): not adopted.
**The owner's decision (2026-09-20): the midpoint between the authors and our loot, per rank.**
And in `bases-report.md` burning_arrow_snipe's Imperial Bow is "payable", its value 389,142 is above its guard threshold
383,667, and Bone Bow (316,862) is still TAKEN: the final choice is still sorted violation first.

## 1. Per-rank tier positions

Rail `gear.wishlist.weapon_open_tier_positions = [0.35, 0.50, 0.57]` (replaces the single `weapon_open_tier_position`; keep
reading the old key as a one-element list so nothing breaks): the FIRST open line a weapon buys is offered at position 0.35,
the second at 0.50, the third at 0.57 (a longer weapon repeats the last value); the tier taken for a group = the best tier whose
relative position is >= the rail's value and that is legal at the slot's item level. `weapon_open_lines` stays 3. These are the
DEFAULTS now. The rail's source sentence in `rails_default.json`: the census table above + "midpoint of the 32 Tuadh authors and
our best-of-200 loot per rank, approved by the owner 2026-09-20". Armour and jewellery open lines stay at the ladder's middle.
The command-line / environment override the parent task added keeps working (a comma list).

## 2. Weapon bases are ranked by VALUE (D89 already ranks weapon LINES this way)

In the weapon branch of `_rank_bases`: among PAYABLE bases the order is by effective value
`value x (1 - k x open_line_share)` (k = attribute lines the set must spend on the base's requirement; `open_line_share` = the
measured rail the parent task stored), best first; the violation (the base's own attribute requirements left out) only breaks
ties. Not payable = dropped by name, as now. The "bases PoB was offered" table is sorted by that order and shows the effective
value. The after-fill check and the single refill stay as they are. Fast tests: Imperial-like base (value +23%, k = 3, share as
stored) beats a free low base even when its violation is higher by 0.08; a tie on effective value falls to the violation; an
unpayable base is still dropped.

## 3. Numbers to report (ONE PobSession at a time; `python scripts/machine_load.py --need 1 --role other` first; never next to your pytest)

`python scripts/gear_transplant.py --set smoke --seed 1 --results artifacts/runs/gear-templates/final-results.json --report artifacts/runs/gear-templates/final-report.md`
with the new defaults: the six template / author values next to D89's (cold_dot 103.2, bleed_bow 124.5, summon_raging_spirits
115.8, impale_ballista 81.6, stormbrand 148.6, burning_arrow_snipe 69.6) and the loot's; feasibility; per weapon slot the base
taken with its verdict row; refills; the three weapon lines bought on burning_arrow_snipe and bleed_bow with their tiers.

## Rules of the house

Fast test files only (`tests/test_wishlist_gear.py tests/test_gear_transplant.py` + what you add) -- NO whole suite by day.
Durations in your report: CLAUDE.md principle 7 (minutes, never big seconds). Bounded waits only, no background shell left
behind. Never `git add -A`; nothing under `var/` `vendor/` `artifacts/` into git; no recursive deletes; do not edit
`docs/ROADMAP.md`, `docs/DECISIONS.md`, `CLAUDE.md`. Commit after each part; the final message begins with `=== FINAL REPORT ===`.
