# Spec 2026-09-22: template gear v4 -- the line COUNT is the only hard-code, every line is flexible

Lead: Opus 5.5. Worker: one coder in its own worktree. `--gear wishlist` only; the loot path must stay
byte-identical. Replaces the withdrawn drafts `2026-09-22-template-shape.md` and `2026-09-22-item-obtainability.md`.

## The owner's rule (2026-09-22, verbatim in substance)

"The number of lines on every item stays what it is today, and the number of bench crafts: that is the only
hard-code. Every mod is flexible and the system decides it optimally, with the floors of the rails and PoB's other
surfaces (the tree)." No threshold for life: the rails' floors (life, maximum hit, resistances, attributes) already
stop the system from trading all life for damage. A quiver follows the weapon rule (three lines + one bench craft).

## Why

Today (`src/junkroan/mechanics/day1_gear_templates.json`, `src/junkroan/optimizer/wishlist_gear.py`, rails
`gear.wishlist`, D79 / D89 / D92): armour, jewellery, shield and quiver = a FIXED `IncreasedLife` line + a FIXED
resistance line + one open-or-craft line; weapons = three open lines by value + one craft. Template against loot,
same code and seeds: -8.5 / -2.7 points on the campaign medians; archmage_volatile_dead -70.5 (MoM + Archmage: the
template's shield carries life + resistance + one double-damage craft where the author and loot wear spell damage +
mana); bleed_bow wears two Iron Rings (a resistance implicit is worth nothing when every ring has a fixed resistance
line anyway); Astral Plate on casters; items `docs/readings/2026-09-22-item-examples.md`. Plus a floor hole: every
template build of impale_cyclone and shockwave_cyclone ends at `EffectiveMovementSpeedMod` 1.027 (floors 1.164 and
1.0345) although template boots elsewhere carry +25% movement speed.

## Requirements

1. **Line count.** Every armour, jewellery and shield item keeps exactly today's number of lines (read it from the
   template JSON: today 3, one of which may be the bench craft); the set's bench craft count stays `wishlist.
   bench_crafts`. Weapons unchanged. The quiver takes the weapon shape (`weapon_open_lines` natural lines by value +
   one craft).
2. **Every line flexible.** A line may be any mod group the base can roll (prefix / suffix room respected) or a legal
   bench craft. Keep the rules that exist for other reasons: the attribute-affix budget (D73: at most one attribute
   affix per item, at most `attribute_affixes_max` items), the gem-level rule (D89), a +0 line is never bought, the
   bench unlock rail. No other per-slot rule: `IncreasedLife` and resistances are ordinary candidates.
3. **Tiers unchanged, per kind.** A line's tier follows today's rule for its kind: `IncreasedLife` at the slot's
   template life tier, an elemental resistance at the slot's template resistance tier, the fourth-resistance repair
   rule as today, any other group at today's open-line rule (median tier / the weapon tier positions). Only the KIND
   of a line becomes free.
4. **The set is solved, not the slot.** Start from today's template set (so v4 is never worse than today on the
   judge), then improve by moves judged with PoB (fast item what-ifs, `Objective` / `better_score`: violation first,
   then value), to a fixed point:
   a. line swap: one line of one item for any candidate line of that item;
   b. two-item exchange: item X gives up a floor-carrying line (resistance, attribute, life) for a value line while
      item Y replaces one of its lines with that floor line -- judged as ONE move (a single swap cannot move a floor
      between items without breaking it on the way);
   c. base re-choice on the FINISHED flexible item: a base's implicit (Two-Stone resistances, Astral Plate, a
      sceptre's elemental damage) is judged by what the whole set does with the line it frees.
   Report how many moves of each kind were tried and kept, and the time per build.
5. **Boots and the movement floor.** First read PoB's breakdown of `EffectiveMovementSpeedMod` on a template build of
   each cyclone (`C:\Coding\poe-junkroan-archive\benchmark\20260921-0929-new18-tpl\<ref>-s1.pob.txt`), on the loot's
   `...\20260920-1618-new18-r3\impale_cyclone-s1.pob.txt` and on both authors: every source and its value. If the
   boots are the cause, the movement line is an ordinary flexible candidate that the floor makes the solver buy (at
   today's boots tier or the lowest tier that meets the floor). STOP rule: if the cause is elsewhere (the floor read
   wrongly for a channelled skill, a buff our config does not prove, a penalty from another item), change nothing in
   the floor and report the chain with numbers.
6. Each of 1 (quiver), 2-4 (flexible lines) and 5 (boots) is a switch in the template rails so it is measured alone;
   the default after the merge is all on.

## Numbers to report

- A. `scripts/gear_transplant.py`, seed 1, on the smoke six + archmage_volatile_dead + impale_cyclone +
  shockwave_cyclone + every other Tuadh reference whose main weapon is a bow: template % of the author and
  feasibility -- today | quiver only | flexible only | boots only | all on; the loot % beside it.
- B. On bleed_bow, stormbrand, archmage_volatile_dead and each bow reference: every item's lines today -> all on
  (slot: lines, base), so the owner can read them; count of items per set without a life line, today and all on.
- C. Moves tried / kept per kind (4a, 4b, 4c) and template construction time per build, today -> all on.
- D. The loot path: one reference through `gear_transplant`'s loot section before / after -- byte-identical.
- E. Fast test files: pytest summary; the whole suite once at the end; your own cost (wall time, tool calls / turns
  if visible).

## Rules

- Your worktree reaches `var/`, `vendor/` and `artifacts/` through junctions: read them, write only under
  `artifacts/`, never delete anything there, never remove the worktree.
- PoB budget: `python scripts/machine_load.py --need 2 --role other` before PoB work; at most 2 PoB processes of
  yours (`gear_transplant` with at most 2 workers), never next to your own pytest; one whole-suite run. Waits bounded
  (steps of at most 10 min); stop every background shell you start before your final report.
- Commit on your branch with the numbers in the message. Do not merge into main.
- Durations for a human: seconds under ~90 s, then minutes, then hours + minutes.
- Principles (CLAUDE.md): PoB is the only judge; no game numbers from memory; no gates, ledgers or waivers. Where the
  spec leaves a choice, make the smallest one and list it.
