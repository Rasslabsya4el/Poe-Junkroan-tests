# Spec: day-1 gear from TEMPLATES -- D79 (the user's design, 2026-09-19; supersedes the probability-budget draft)

The user read the wishlist items (`gear-wishlist` cold_dot s2: a Void Sceptre with "+1 all spell gems / +1 cold
spell gems / top cold DoT multi / top cold damage", a Vaal Regalia with "+28 Strength" and nothing else, gloves
with one bench craft, life on 1 of 10 items) and ruled:

- "Wishlist rares must ALWAYS have a fixed number of affixes. That is the point: they must be as alike as possible
  from build to build, so that they are easy to check."
- "Make TEMPLATES for day 1. A typical day-1 ring is a Two-Stone Ring, T2 life, T2 resistance and a craft; from
  build to build the craft changes. I expect to see such a ring in every build -- there is nothing else to invent
  there. Keep the calculation only for the case where some mod gives the build an unreal boost (damage or
  defence alike)."
- "The main problem is that the system greedily looks at what gives a boost and never reasons 'resistance is worth
  more on this ring than elsewhere, I will stack it here in advance'."
- "On a life build life is on EVERY item that can have it, no exceptions; there is never too much life. Energy
  shield likewise on a pure ES build."
- "This gear must highlight what I, the player, should craft or buy: the top relevant mods for this stage." And it
  must be fast: "templates will save a lot of time per build".

The real day-1 rares agree (`docs/research/2026-09-18-author-rares.md` section 4, 299 items): life on 61-100% of the
items of every armour / jewellery slot (belt 100%, helmet 90%, boots 75%, gloves 73%, rings ~70%) at a median tier
T2-T3, one or two resistances per item at T3-T5, movement speed on 69% of boots plus 31% as a craft. The old
filler's "add a mod only while the objective improves" is the opposite of that and is why its affix counts look
random: 4 on a weapon (every damage mod helps), 1 on a body armour (nothing on it raises DPS once the floors hold).

## The design

1. **Templates are data**, `src/junkroan/mechanics/day1_gear_templates.json`, small, edited by the user without
   code changes. One template per slot class (helmet, gloves, body armour, boots, belt, shield, ring, amulet,
   quiver, one-hand weapon, two-hand weapon, caster off-hand ...; classes come from the base's item type in the
   corpus). A template is an ordered list of affix SLOTS, each one of:
   - `fixed`: a mod group and a tier, e.g. `{"group": "IncreasedLife", "tier": 3}` ("tier" = rank in the group's
     WHOLE ladder ordered by required level, T1 best -- the definition of `docs/research/2026-09-18-author-rares.md`
     and `tests/fixtures/tuadh_329/gear_tiers.json` -- clamped to the best tier legal at the slot's item level; if
     the group cannot roll on the base the slot is skipped and logged);
   - `resistance`: an elemental resistance whose ELEMENT is decided by the solver of point 2, tier from the template;
   - `open`: PoB chooses the best legal mod of that affix type (prefix / suffix / either) by the full objective,
     one batched trial; candidates exclude groups already on the item and obey point 3; this is where "a mod that
     gives an unreal boost" and an unmet attribute requirement (the existing `attribute_payments`, at most
     `attribute_affixes_max`) get in;
   - `craft`: one bench craft chosen by PoB (as today).
   - `open_or_craft`: ONE line that is either the best open mod or the best bench craft, whichever PoB scores
     higher (one batched trial over both candidate sets).
   Every rare of a slot class therefore has the same affix COUNT and the same shape in every build.
   **Content, settled with the user (2026-09-19)**: "life + ONE resistance fixed, then either an open mod or a
   bench craft and that is all -- five mods on an amulet is far too many for day 1"; "the weapon is fully open";
   "the median tiers of Tuadh's PoBs suit me"; "+1 to gems is too rare for day 1 if the item has anything else".
   - every armour and jewellery slot (helmet, gloves, body armour, belt, shield, ring, amulet, quiver):
     `life, resistance, open_or_craft` -- three lines;
   - boots: `life, resistance, movement speed` (the movement floor lives on boots, D28 / D55: the third line is
     movement speed as an affix or as the bench craft, whichever the base allows at the tier below);
   - weapons of every kind, caster weapons included: `open, open, open, craft`.
   Tiers are the authors' medians per slot (`docs/research/2026-09-18-author-rares.md` section 4; tier = rank in
   the mod group's whole ladder ordered by required level, T1 best -- the research's definition, clamped to what
   is legal at the slot's item level): life -- body armour T6, helmet T3, gloves T2, boots T2, belt T3, amulet T3,
   ring T2, shield / quiver T3; resistance -- body armour T3, helmet T4, gloves T4, boots T5, belt T4, amulet T3,
   ring T5, shield / quiver T4; movement speed on boots T3; open mods at the median of their own ladder.
   Pure ES build (the skeleton holds Chaos Inoculation, or the author's EnergyShield >= 2 x Life; one function,
   unit-tested only -- no ES reference exists): the life line becomes the base's best ES group at the same tier.
2. **Resistances are solved for the whole set, not greedily.** Given what the build already has (tree, auras,
   uniques, implicits of the chosen bases) and the number of `resistance` slots, assign an element to each so that
   fire / cold / lightning each reach the floor (75 with the campaign penalty PoB applies) with the least overcap;
   if the slots cannot cap them, say by how much in the log (the open slots and crafts then see the violation and
   may take resistance). A small exact search; no PoB call per candidate -- one readback of the three resistances
   and the mod values is enough, then ONE verifying calc.
3. **Open slots are bounded in rarity** so the sceptre above cannot come back: an open mod is legal when its spawn
   weight share among the mods of its affix type on that base is at least `open_mod_min_share` (rails, 0.01; print
   the share of "+1 to Level of all Spell Skill Gems" -- weight 50 -- and of "+1 to Level of all Cold Spell Skill
   Gems" -- weight 250 -- on a sceptre, and of the mods the six smoke references end up with). The user's ruling is
   explicit for one family: a "+N to Level of ... Skill Gems" mod is never an open mod on an item that carries
   anything else -- identify the family by PoB's mod group / `gem` mod tag, not by text. Open mods sit at the
   median tier of their own ladder; none at the top tier unless the ladder has one tier.
4. **Bases** stay chosen as today (D73: implicit first, the requirement paid), the bow fix stays (a slot the main
   skill needs is never left empty), weapons first.
5. **Speed is part of the task**: a template fill is one `craft_rare` per slot for the fixed part, one batched
   trial for each open slot and one for the craft; cache `list_item_mods` / `list_bench_mods` per (base, ilvl).
   Target: the whole gear of a build in under 3 minutes (today 16-29; loot 3-12) -- report per slot.
6. **The shopping list**: `explain` prints per slot one line per mod in the template's order -- the mod, its tier,
   and for open / craft slots the measured objective delta -- "what to craft or buy".
7. `--gear wishlist` runs this filler; the old greedy filler goes away with its rails (`useful_mods`, `tier.rule`,
   `above_median_max`). `--gear loot` is untouched and stays the default until the user switches it.

## Numbers to report and tests

- Unit (fake mod tables / fake session): the same template gives the same affix count on two different builds;
  a group that cannot roll on the base is skipped and logged; the resistance solver caps 75 / 75 / 75 from
  (20, -10, 35) with nine slots of 30 and reports the overcap; with too few slots it reports the shortfall; an
  open slot refuses a mod under `open_mod_min_share` and refuses a "+1 to Level of ... Gems" mod next to any other
  mod; `open_or_craft` takes the craft when it scores higher and the open mod otherwise; the ES variant swaps the life slot.
- PoB-backed (skips without `var/cache/pob`): cold_dot author, every rare emptied, the new fill: print EVERY item
  in full (base, implicit, every mod with its tier); life on every slot that can roll it; resistances at the
  floor; the sceptre has no "+1 to Level" mod.
- `scripts/gear_transplant.py --set smoke` (one PoB session): wishlist C/A per reference against the old filler's
  146.4 / 68.5 / 141.6 / 68.6 / 103.0 / 105.9 (median 104.4) and loot's B/A (median 96.6), with Life and TotalEHP
  ratios and whether the three resistances reach the floor on gear alone (one fixed resistance per item may not be
  enough: report the shortfall per reference and how many `open_or_craft` lines went to resistance).
- One full build: `junkroan.exe scripts/benchmark.py stormbrand --seeds 1 --no-variants --gear wishlist --workers 1
  --loop --loop-seconds 900 --tag templates-stormbrand`: % of the author, gear minutes inside the build (old: 22.2),
  the tree's life / resistance / attribute node count against the same build under the old filler
  (`artifacts/benchmark/20260918-1914-gear-wishlist/logs/stormbrand-s1.log`).
Focused tests, then the whole suite once, in the foreground; one PoB session at a time (a 5-worker benchmark is
running); run scripts as `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`. You are the worker:
write the code yourself. Do not edit docs/ROADMAP.md or docs/DECISIONS.md. Commit on your branch with the numbers.
