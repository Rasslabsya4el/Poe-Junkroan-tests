# Spec: D79 amendment -- the template content the user settled, and a rare mod costs two lines

Apply on top of the merged day-1 gear templates (`docs/specs/2026-09-19-day1-gear-templates.md`,
`src/junkroan/mechanics/day1_gear_templates.json`). All four points are the user's rulings of 2026-09-19.

1. **Resistance tier T3 (36-41%) on every slot, life at the authors' medians** (the user chose it from numbers).
   Measured on the 32 Tuadh authors (rares emptied, the tree's resistance subtracted; the lead's run): the rares
   must supply a median 360% (sum of the three elements, max 405%) when the tree gives none; the authors' own
   rares give 410% and their trees another 68%. One resistance line per item at the authors' per-slot median
   tiers gives 286% on nine slots -- short by a median 90 (max 159), 0 of 32 builds capped, about 3 of the 9
   third lines spent on resistance crafts. At T3 on every slot: 9 x 38.5 = 346% plus the implicits of the chosen
   bases (two Two-Stone Rings ~ +56%): before implicits 6 of 32 cap (median short 30, max 111), with the two ring implicits 22 of 32 cap and the rest need one or two resistance crafts in the third line, which
   is the fallback the solver already has (bleed_perforate: six rare slots only). Content change only: `resistance` tier 3 in every
   template; life tiers unchanged (body armour T6, helmet T3, gloves T2, boots T2, belt T3, amulet T3, ring T2,
   shield / quiver T3).
   **Up to TWO items may carry one EXTRA resistance line** (the user, for stability: "so that any PoB is sure to cap
   from gear"): a fourth line, resistance T3, added by the solver only when the fixed lines plus the implicits do
   not cap, on at most `extra_resistance_items` = 2 items (the solver picks the slots; jewellery before armour is
   NOT a rule -- any non-weapon slot). Measured on the 32 authors at T3 with the two ring implicits: 22 cap with
   no extra line, 30 with one, 32 of 32 with two (the largest gaps: bleed_perforate 55, static_strike 41,
   ignite_penance_brand 23; without ring implicits 6 / 17 / 29 of 32). Only if two extra lines still do not cap
   does a third line go to a resistance craft. The shopping list marks an extra line as such.
2. **Weapons carry three lines, not four**: `open, open, open_or_craft`.
3. **A rare mod costs two lines; a very rare one is never taken.** Shares of the prefix pool on a Void Sceptre at
   ilvl 76 from PoB's weights (total 67,160): "+1 to Level of all Spell Skill Gems" 0.07%; "+1 to Level of all
   Cold / Fire / Lightning Spell Skill Gems" 0.37% (Physical 0.30%); ordinary damage groups 2.8-4.9%. The user:
   "+1 specific must cost two affixes; +1 all spells must not be taken at all, it is giga rare". Rails:
   `open_mod_never_below_share` 0.002, `open_mod_two_lines_below_share` 0.01 (group share = the summed weight of the
   group's accepted tiers over the pool of its affix type on that base at that item level). A two-line mod takes
   the place of two template lines of the kinds `open` / `open_or_craft` / `craft`; on a slot with a single such
   line it is not available (so an armour piece never carries one; a weapon may: one two-line mod + one line).
   The fixed `life` and `resistance` lines are never displaced.
4. **Attributes**: the tree may take at most ONE +30 attribute node for a requirement; everything else comes from
   gear (implicit bases first, then one attribute affix per item -- the existing rule). Find where the tree stage
   is allowed to pay requirements today and cap it at one such node (identify "+30 to <attribute>" nodes from the
   passives corpus, not by id); report how many the six smoke references take before / after.

## The lead's review of the merged first version (7f3e3d4), read before you start

- **The rarity rule is wrong in the first version and point 3 replaces it.** `wishlist_gear.py` computes a mod's share
  as ONE TIER's weight over the pool and blocks everything under the single rail `open_mod_min_share` 0.01. On the six
  smoke references (`artifacts/runs/gear-templates/smoke.out`, 3,192 "open candidate blocked" lines) that refuses
  everyday mods: "(9-12)% increased Cast Speed" 0.89%, "(5-7)% increased Attack Speed" 0.56%, "(21-30)% increased
  Elemental Damage with Attack Skills" 0.56%, "+(21-25)% to Chaos Resistance" 0.28-0.40%, "+(24-28)% to Fire / Cold
  Damage over Time Multiplier" 0.23%, "+(9-10)% chance to Suppress Spell Damage" 0.85%, flat added damage 0.60-0.93%.
  The share that prices rarity is the GROUP's: the summed weight of every tier of that group the template would
  accept at this item level (the chosen tier and the better ones) over the pool of its affix type -- point 3's
  definition. Remove `open_mod_min_share`; the two rails of point 3 are the only ones. Test: on a ring at ilvl 72 the
  increased-cast-speed group and the chaos-resistance group are ordinary one-line candidates; on a Void Sceptre at
  ilvl 76 "+1 to Level of all Cold Spell Skill Gems" (0.37%) is a two-line candidate and "+1 to Level of all Spell
  Skill Gems" (0.07%) is refused -- the numbers of point 3.
- The templates file of the first version carries the authors' per-slot resistance tiers (3-5) and four weapon lines
  (three open + a craft): points 1 and 2 change that content.
- The first version was never measured with PoB by its worker. The lead's transplant of it on the six smoke
  references is `artifacts/runs/gear-templates/smoke-report.md` / `smoke-results.json`: your "before".
- Item level: the wishlist rail is 72 (weapons 76); the user's loadout book says "day-1 bases and item level up to 70".
  Do not change it in this task; report what changes on the six references if it were 70 everywhere (one run).

## Numbers to report and tests

- Unit: a weight-250-of-67,160 mod is offered only as a two-line candidate and refused on a ring; a weight-50 mod
  is never offered; the weapon template yields exactly three lines; the resistance solver with nine T3 lines and
  two Two-Stone implicits caps (20, -10, 35) and reports the overcap.
- PoB-backed (skips without `var/cache/pob`): rerun the lead's measurement as a test helper on three authors
  (cold_dot, bleed_perforate, stormbrand): resistance need with the tree's resistance subtracted against the
  template's supply; expected shortfalls from the lead's run at T3 are 26 / 111 / 32 before implicits (report
  yours with implicits).
- `scripts/gear_transplant.py --set smoke`: wishlist C/A, Life and TotalEHP ratios, resistances capped on gear
  alone yes / no, and how many third lines went to resistance.
- Full items of cold_dot and stormbrand printed in the report (base, implicit, every mod with its tier).
Focused tests, then the whole suite once, in the foreground; one PoB session at a time; run scripts as
`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker: write the code yourself.
Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
