# Spec: template weapons -- tiers and line count from a census BY VALUE, and a base whose requirement is a cost, not a veto

Continues D79 / D89 (`--gear wishlist`, `src/junkroan/optimizer/wishlist_gear.py`, rails `gear.wishlist`,
`scripts/gear_transplant.py`). Work on a fresh branch from main (D89 is merged). Three parts, in this order; commit after each.

## Why (the user read the six template sets, 2026-09-20)

1. burning_arrow_snipe, template 69.6% of the author against the loot's 92.8% (`artifacts/runs/gear-templates/fix4-report.md`):

   | | author | loot (best of 200) | template |
   |---|---|---|---|
   | base | Imperial Bow (20% elemental damage with attacks) | Imperial Bow | **Bone Bow** (level 23, no implicit) |
   | flat | fire 110-181, cold 105-200, lightning 5-88 | fire 146-256, lightning 21-387 | lightning 11-14 to 208-242 (T5/10), fire 63-85 to 128-148 (T5/10) |
   | lines | 6 | 6 | 3 open + 1 craft |

2. The user: "T5 on a weapon is a joke. The wishlist's tiers must be about what the Tuadh sets and our own best loot on the
   same builds show." TODAY an open line (every weapon line) sits at the MIDDLE OF ITS GROUP'S LADDER (T5 of 10, T4 of 8, T3 of
   5: `_median_mods`), a rule typed in D79, not measured. The only census we have (`tests/fixtures/tuadh_329/gear_tiers.json`,
   10 builds, 15 weapons, 66 natural lines) says: median T4, relative position 0.53, **6 lines a weapon (5 natural + 1 craft)**.
   So the ladder's middle matches the authors' median over ALL lines -- junk lines included. A player buys a weapon for its two or
   three lines that carry the damage; nobody has measured the tier of THOSE.
3. The user: a weapon's BASE (crit chance, attack speed, base physical damage, implicit) is among the strongest choices of an
   attack build. Today `_rank_bases` sorts violation before value, weapons are filled first (the other rare slots are still
   empty, so Dexterity is missing), and a payment is ONE line on the weapon itself: Imperial Bow (dex 212) is not in the first
   eight of 63 rows and Bone Bow (dex 80, level 23) wins because it asks for nothing.

## Part 1 -- the census by value: `scripts/fixture_weapon_lines.py` (one PobSession, read-only)

For every reference of the 32 Tuadh fixtures (tree converted the way the benchmark does; the objective's maximized stat chosen
the way the benchmark chooses it for that reference) and for every RARE item in `Weapon 1` / `Weapon 2` that is a weapon (not a
shield, not a quiver): every explicit line -> mod group, tier / of (reuse `scripts/fixture_gear_tiers.py`'s matching), crafted
or not, and its VALUE SHARE = (value with the item as worn - value with that one line deleted from the item's text) / value with
the item as worn, by ONE fast item what-if per line (`trial_stats([{"item": {...}}], keys, mode="fast")`). The same for OUR LOOT:
the delivered builds of `artifacts/benchmark/20260919-0941-core14-rules` and `artifacts/benchmark/20260919-0130-new18-rules`,
best seed per reference (the highest `/ author` in the run's `results.json`).

Output `artifacts/runs/gear-templates/weapon-lines-census.md` + `.json`; per weapon one row (reference, source author / loot,
base, lines, USEFUL lines = share >= 1%, then the top three lines by share with `T<tier>/<of>` and share); then the summary the
rails will quote, for authors and for loot separately and split attack weapon / caster weapon: median USEFUL lines, median tier
and median relative position `(tier-1)/(of-1)` of the top-1, top-2, top-3 line, and of all useful lines. Numbers to report: that
summary table, verbatim.

## Part 2 -- the template weapon reads its shape from the census (rails, measured; default unchanged until the lead flips it)

Two rails under `gear.wishlist`, each with its source sentence like `attribute_affixes_max` has:
`weapon_open_lines` (today 3) and `weapon_open_tier_position` (a relative position 0..1 inside a group's ladder, today the
ladder's middle; the tier taken for a group = the best tier whose relative position is >= the rail's value and that is legal at
the slot's item level -- never better than the item level allows). Armour and jewellery open lines keep the ladder's middle
(their census exists in `gear_tiers.json`: median T4, 0.43 -- already about the middle). The share rail and the gem-level rule
of D89 are untouched. Defaults stay at today's behaviour; a test pins that a default run is bit-identical on the fakes.

Measurement (one PobSession at a time, `python scripts/machine_load.py --need 1 --role other` first, never next to your pytest):
`python scripts/gear_transplant.py --set smoke --seed 1 --results .../tiers-results.json --report .../tiers-report.md` with the
two rails set to the CENSUS numbers (authors' median useful lines minus the one craft, bounded 3..5; authors' median relative
position of the top-3 lines) -- give the rails a command-line / environment override so the run needs no edit of the JSON.
Numbers to report: the six C / author values next to D89's (103.2 / 124.5 / 119.4 / 81.6 / 148.6 / 69.6), feasibility, and the
weapon lines bought on burning_arrow_snipe and bleed_bow.

## Part 3 -- a weapon base's requirement is a cost the set pays, not a veto

For WEAPON slots only (`template_for` decides, as in D89), in `_rank_bases`:

1. A base's trial VALUE and violation are read with the bare base equipped and with that base's OWN attribute-requirement
   relations left out of the violation (every other floor counts as today). Level requirement and drop level stay hard limits.
2. PAYABLE? `shortfall[X] = Req_X(base) - X(build with the bare base equipped)` for Strength / Dexterity / Intelligence.
   `capacity[X]` = what the rest of the template set can still deliver under D73 / D89's budget, from PoB's own ladders:
   `attribute_affixes_max` items x the median roll of the template-tier "+X" line on the classes that can roll it, + the best
   "+X" implicit among the legal bases of each jewellery slot the filler still has to fill (amulet, rings, belt). A base with
   `shortfall > capacity` on any attribute is dropped with the verdict "requirement not payable: needs N X, the set can pay M".
3. The price of paying: a base that needs `k` attribute lines from the set must beat the best base that needs fewer by
   `(k - k_other) x open_line_share`, where `open_line_share` = the MEASURED median value share of an open-or-craft line on
   armour and jewellery over D89's six sets (compute it from `artifacts/runs/gear-templates/fix3-results.json` +
   `fix4-results.json`, store it in the rails with its source; the lead expects 1-2%). `k = ceil(shortfall / median roll)`.
   The old "one payment line on the weapon itself + 5% guard" path goes away for weapons.
4. Nothing is reserved: the armour and jewellery open-or-craft lines are already ranked violation first, so once the weapon
   is equipped they buy the attribute lines themselves, inside `attribute_affixes_max`. After the whole fill: if the weapon's
   requirement is still unmet, log it, take the next payable base and refill ONCE; report how often that happened.
5. The "bases PoB was offered" table shows, per base: value, requirement shortfall, payable yes / no, lines needed, the
   guard's threshold, verdict -- sorted the way the choice was made. Best 8 rows + the taken one, as today.

Fast tests (fakes, no PoB): a base with a payable shortfall and +12% value beats a free base (k = 3, share 1.5%: threshold
4.5%); the same base at +3% loses; an unpayable base is dropped by name; a level requirement above the rail is still a veto;
armour and jewellery base ranking is unchanged (bit-identical on the existing tests); the refill happens once.

Measurement: the same transplant over the smoke six after Part 3 (with Part 2's census rails on). Numbers to report: the base
taken per weapon slot with its verdict row (burning_arrow_snipe must now be offered Imperial Bow as payable or say why not),
the six C / author values, feasibility, refills.

## Rules of the house

One PobSession at a time; check `machine_load.py` before every PoB phase; whole suite ONCE at the very end, alone
(`-p no:cacheprovider -p no:faulthandler`). Never `git add -A`, never add anything under `var/` `vendor/` `artifacts/` to git
(a tracked file there broke the queue's snapshot junction on 2026-09-20), no recursive deletes. Do not edit `docs/ROADMAP.md`,
`docs/DECISIONS.md`, `CLAUDE.md`. Commit after every part; the final message begins with `=== FINAL REPORT ===` and carries
Part 1's summary table, Part 2's and Part 3's six-row tables, and anything that surprised you.
