# Spec (small): the template weapon's tier position picks the NEAREST tier, not the first tier at or beyond it

FIRST COMMAND in your worktree: `git merge gpt-2026-09-20-template-weapons-finish` (12 commits, clean; this task sits on top).

Why: `WishlistGear._median_mods` (src/junkroan/optimizer/wishlist_gear.py, the `tier_position` branch) takes "the first legal
tier whose relative position `(tier-1)/(of-1)` is >= the rail's value". That rounds EVERY line toward the worse tier: on a
ten-tier ladder 0.50 becomes T6 and 0.57 becomes T7, where the census behind the rails (`gear.wishlist.weapon_open_tier_positions
= [0.35, 0.50, 0.57]`, the midpoint of the Tuadh authors and our loot, approved by the owner) means T5 and T6. Measured with the
">=" rule (final-report.md): cold_dot 103.2 -> 99.6% of the author, stormbrand 148.6 -> 145.5, impale_ballista 81.6 -> 78.1.

1. The rule: among the tiers LEGAL at the slot's item level take the one whose relative position is NEAREST to the rail's value;
   a tie goes to the BETTER tier. Compare distances rounded to 9 decimals (0.4286 and 0.5714 are equally far from 0.50 only up to
   floating-point noise). Expected picks: position 0.35 -> T3 of 8, T4 of 10, T2 of 5, T1 of 2; 0.50 -> T4 of 8, T5 of 10, T3 of 5,
   T1 of 2; 0.57 -> T5 of 8, T6 of 10, T3 of 5, T2 of 2. The legacy `0.40` / `None` path (the ladder's middle) is untouched.
2. Update the four tests that pin the old rule (`tests/test_wishlist_gear.py`:
   `test_bench_gem_level_line_cannot_share_a_weapon_with_open_mods`,
   `test_weapon_open_tier_positions_are_applied_per_rank_and_repeat_the_last`,
   `test_three_weapon_open_lines_use_their_respective_tier_positions`,
   `test_weapon_tier_position_selects_the_best_tier_at_or_beyond_the_position` -- rename the last to say "nearest"); change only
   expectations that follow from the new rule, and say in the report what each one changed from / to. Fix the rails' source
   sentence in `rails_default.json` if it describes the ">=" rounding.
3. Fast tests: `python -m pytest -q tests/test_wishlist_gear.py tests/test_gear_transplant.py`. No whole suite.
4. Measurement (ONE PobSession; `python scripts/machine_load.py --need 1 --role other` first; never next to your pytest):
   `python scripts/gear_transplant.py --set smoke --seed 1 --results artifacts/runs/gear-templates/final2-results.json --report artifacts/runs/gear-templates/final2-report.md`
   Report the six template / author values next to D89's (103.2 / 124.5 / 115.8 / 81.6 / 148.6 / 69.6) and the ">=" run's
   (99.6 / 139.4 / 114.4 / 78.1 / 145.5 / 76.6), feasibility, the base taken per weapon slot, and the three open lines with
   their tiers on bleed_bow, burning_arrow_snipe and stormbrand.

Rules of the house: durations per CLAUDE.md principle 7; bounded waits, no background shell left behind; never `git add -A`;
nothing under `var/` `vendor/` `artifacts/` into git; no recursive deletes; do not edit `docs/ROADMAP.md`, `docs/DECISIONS.md`,
`CLAUDE.md`. Commit; the final message begins with `=== FINAL REPORT ===`.
