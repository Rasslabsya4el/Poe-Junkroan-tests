# 2026-09-20 D92. Template weapons: tier positions from a census BY VALUE, the nearest tier, a payable base requirement (amends D89; written 2026-09-22, owed)

Status: Accepted

`--gear wishlist` only. Merged 9a82d4f + 24df6cf. Census (`scripts/fixture_weapon_lines.py`, 37 author weapons of the
32 Tuadh sets and our loot's 37): median useful lines 3 and 3; relative tier position of the top-1 / top-2 / top-3 line,
authors 0.43 / 0.57 / 0.69, loot 0.27 / 0.43 / 0.44. Rail `gear.wishlist.weapon_open_tier_positions = [0.35, 0.50,
0.57]`, the midpoint per rank, approved by the owner (the authors' own numbers made all six sets weaker and were not
adopted). A position picks the NEAREST legal tier (a tie goes to the better one): the first '>=' rounding put every line
about half a tier low (0.50 -> T6 of 10). A weapon base's requirement is a COST the set pays, not a veto: payable =
shortfall within the attribute budget's capacity, bases ranked by effective value = value x (1 - lines x open_line_share),
violation only breaks ties (burning_arrow_snipe: Imperial Bow, 88 Dex within a capacity of 115, instead of Bone Bow
level 23). `gear_transplant`, smoke six, seed 1, template / author (D89 -> nearest): cold_dot 103.2 -> 105.2, bleed_bow
124.5 -> 151.1, summon_raging_spirits 115.8 -> 119.4, impale_ballista 81.6 -> 84.0, stormbrand 148.6 -> 152.4,
burning_arrow_snipe 69.6 -> 85.4; median 109.5 -> 112.3 against the loot's 109.3. Whether the product wears template or
loot gear is read from the full campaigns (`docs/readings/2026-09-22-templates-vs-loot.md`).

