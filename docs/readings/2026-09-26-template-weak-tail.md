# 2026-09-26 reading: the template gear's weak tail (lead, Opus 5.5)

Source: best seed per reference of `core14-tpl-main3` / `new18-tpl-main3-lap` against `core14-main3` / `new18-main3`
(same commit @42565a9, seeds 1-3; only the gear differs), the final gear summary of every template log, and the author
fixtures. Read from the PoB XML and the logs; no PoB run.

## The tail (median of 3 seeds, % of the author under our lane)

| reference | loot | templates | what the template set does |
|---|---|---|---|
| impale_ballista | 140.2 | 73.8 | jewellery open lines buy "+33 to maximum Mana / 5% of Damage taken Recouped as Mana" (x3) and a Bone Ring (a minion implicit on a totem build); the author's jewellery carries "Adds # to # Physical Damage to Attacks" |
| archmage_volatile_dead | 213.5 | 150.2 | still 1.5x the author; the loot's extra lines are the difference |
| burning_arrow_snipe | 191.6 | 146.1 | both rings "+(21-25)% to Chaos Resistance" at +0 value; the author wears flat lightning / fire to attacks there |
| spark | 284.1 | 202.6 | 2x the author on templates: a gap to the loot, not to the author; not chased |
| smite | 133.4 | 77.9 | **off-hand Corsair Sword with ONE line** (bug 1) |
| poison_spectral_throw | 112.1 | 64.4 | rings/belt/gloves open lines: +30 Intelligence, crit chance, "13% increased Damage", "21% increased Damage during any Flask Effect" |
| regular_viper_strike | 134.2 | 90.6 | **off-hand Corsair Sword with ONE line** (bug 1) |

## Causes (general, none per build)

1. **Bug: a one-handed weapon in Weapon 2 took the shield template.** `day1_gear_templates.json` keyed "One Hand
   Sword", the corpus says "One Handed Sword": no sword / axe / mace matched. Weapon 1 fell back to the weapon shape by
   slot; Weapon 2 fell back to "Shield" (life + a resistance the base cannot roll = one open line). Over every template
   run it hit exactly smite and regular_viper_strike (all 3 seeds each). Fixed 47b03b3; measured by `offhand-fix-tpl`
   (both references, templates, seeds 1-3, @47b03b3, against core14-tpl-main3).
2. **The open line of an armour / jewellery item buys a floor at +0 value, and the loop never questions it.** 192
   template builds, 1,359 flexible armour / jewellery lines, **698 (51%) at +0 `CombinedDPS`** when chosen: "+#% to
   Chaos Resistance" 195 (the `TotalEHP` floor), attribute crafts ~200, ES regen near a rare / unique enemy 31, "+28 to
   maximum Energy Shield" 28, mana regen / leech / recoup ~60. The line is chosen violation-first (D89 rule 3) while the
   slot is rebuilt from its bare base, i.e. while the build misses floors; the loop's gear move re-fills it by the same
   deterministic rule, so "a damage line here and the tree pays the floor" is never tried. Spec
   `docs/specs/2026-09-26-template-loop-lines-by-value.md` (on a feasible build the loop re-fills by value; the tree
   repair and the judge decide).
3. **Three lines per item** (life + resistance + one flexible line): Tuadh authors 5.4 explicit lines per armour /
   jewellery item (median 5, 242 items), our loot 6.0, templates 3.2 (counted from the item text; the census of 25.09
   could not count Tuadh). **The owner, 2026-09-26: three lines is the deliberate day-1 level.** Closed; template work
   changes which lines, never how many.

## Not the gear: "gear pass 2 (with tree)" losing more than 50%

z329_juggernaut_boneshatter (templates, all three seeds 1,056,242 -> 463,737): the greedy tree grew under a ramp of
4.0 s against the 2.5 s budget (Trauma stacks the build cannot reach in time); the first `_reconfigure` after it (at
the end of gear pass 2) cut the stacks to the budget (1.4 s) and the stage took the blame. Over 348 campaign builds 15
end the greedy tree over the ramp budget; the drop is large only on templates (z329 -56%, bleed_perforate -43 to
-48%, spectral_shield_throw -42%), where gear pass 2 adds little damage to hide it. The tree is regrown on the gear
afterwards ("tree rebuilt on gear"), so the final cost is unknown. A reconfigure right after the greedy tree would
change every build's path: open, not coded.
