# Spec: day-1 template gear, third pass -- a weapon buys damage, a floor is bought by the line that owns it

CONTINUATION (2026-09-20 02:30): a first session on this spec ran 42 minutes and was cut by a vendor outage; the
harness committed its tree as WIP a6ddd5a on branch `gpt-2026-09-20-day1-gear-templates-weapons-buy-damage`. Your FIRST
command in your worktree: `git merge gpt-2026-09-20-day1-gear-templates-weapons-buy-damage` (it already contains the
finish branch 21abf86). Then `git log --oneline -8` and `git diff 5945380 HEAD --stat` show what exists: do NOT start
over, finish the rules that are missing, then the measurement. Background: D79 is the USER's design -- every armour / jewellery slot = life + ONE resistance
+ one open-or-craft line, boots' third line movement speed, **weapons fully open: 3 open lines + a craft**, tiers = the
authors' medians per slot, a line is bought only when PoB says it helps, and "+1 to gem levels" never next to anything
else. Earlier specs: `docs/specs/2026-09-19-day1-gear-templates*.md`.

Where it stands (gear transplant, seed 1, `artifacts/runs/gear-templates/finish-report.md`): median C / A 76.0% against
the loot's 96.6%; the three bow references are the three worst (68.3 / 40.2 / 30.5%). The lead's foreman instrumented
the fill (one PoB session per reference) and found the causes; every number below is measured on 21abf86:

| what | measured |
|---|---|
| bleed_bow's bow | ONE damage line: "(110-134)% increased Physical Damage" costs TWO lines (its spawn share is 0.66% < the 1% rail), the third line goes to a crafted "+28 to Intelligence" (+0 DPS, violation -0.193) while "Adds 21 to 39 Physical Damage" (+142,099 DPS, 403,127 -> 545,226) is refused |
| stormbrand's sceptre 1 | refused on line 1: spell damage +166,729, cast speed +155,386, spell crit +138,258, crit multi +133,371; taken: "+(28-32) to Strength" (violation -0.116), then "+(90-99) maximum Mana" (+0 DPS, violation -0.0046), then the mana hybrid (violation -0.0016): ~234 k DPS (19% of the build) for 0.12 of a violation that still ends at 0.375 |
| burning_arrow's bow | the PAID base won the base screen by 0.3%; line 1 is the forced "+(43-50) Dexterity", line 2 "(25-29)% crit chance" (+0 DPS, an uptime relation), line 3 attack speed |
| elemental DAMAGE | never offered on ANY item: `_is_elemental_resistance_group` (`wishlist_gear.py` ~316) is a substring test and swallows `LocalLightningDamage`, `SpellAddedLightningDamage`, `IncreasedWeaponElementalDamagePercent`, `Fire/ColdDamageOverTimeMultiplier`, ... |
| C infeasible where the loot is feasible | cold_dot `Dex >= ReqDex` 4.9% short; bleed_bow `Int` 23.3% + `Dex` 5.5%: ONE attribute affix for the whole set cannot pay what random rares carry for free |
| the item lists | a hybrid mod prints only its first line (`WishlistMod.line`, ~399 / 434 / 452; renderers `gear_transplant.py` ~248 / 462, `explain.py` ~123): "Spell Damage + Mana" reads as a second pure spell-damage mod |
| seconds | C alone is 82-171 s per build (the report's 306-571 s is prepare + loot + C); `pob.equip` at ~150 ms a call is 30-55% of it |

## Rules (general; no per-build logic, no mod-name lists)

1. **The weapon template is D79's again**: three `open` lines + one `craft` line (the amendment WIP cut it to
   `[open, open, open_or_craft]`). The craft line reserves its affix type as it did before.
2. **Weapon lines buy the objective's VALUE.** On a weapon slot a candidate line is ranked by value; a candidate that
   makes the violation WORSE is refused; among the rest the best value wins (violation only breaks ties). A weapon's
   attribute requirement is paid under rule 4, never by a line that PoB measures at +0.
3. **Armour / jewellery open-or-craft lines keep violation first** (that is where floors are bought), but a line that
   removes less than 0.01 of violation and adds no value is not a purchase: leave the line free ("free line: anything")
   rather than buy +0.0016.
4. **Attribute payments**: at most ONE attribute affix or craft per ITEM (D73, the user's rule; the finish spec's "one
   for the whole set" was the lead's mistake and is withdrawn), and across the set at most N items may carry one, N =
   the median number of rare items with an attribute affix (rolled or crafted) over the 32 authors' day-1 sets in
   `tests/fixtures/tuadh_329/` -- compute it with a small script, report the distribution, write the number into
   `rails_default.json` with its source. Payments go to jewellery / armour open-or-craft lines first; a weapon line
   only when nothing else can pay and the base screen found no unpaid base within 5% of the paid one's finished value.
5. **Rarity**: drop the share-based two-line price (`open_mod_two_lines_below_share`) and its pair check. The user's
   rule is about GEM LEVELS: a mod that PoB parses as a gem-level property ("+N to Level of ... Skill Gems": all spell,
   per element, per tag, socketed -- derive it from PoB's parsed mod, not from the words "all spell") takes the item's
   WHOLE open budget: no other open line on that item, and it is taken only when it beats the best filling of the
   same lines with ordinary mods (measured). Everything else at the authors' median tier is an ordinary one-line mod.
6. **Resistance tiers** go back to the authors' medians per slot (the amendment WIP moved them to T3 everywhere;
   the finished sets overcap by 17-178 points). The fixed resistance line per item stays the user's design.
7. **Bugs**: `_is_elemental_resistance_group` matches resistance groups only (test: `SpellAddedLightningDamage`,
   `LocalFireDamage`, `ColdDamageOverTimeMultiplier` are NOT resistance; `FireResistance`, `FireAndColdResistance`,
   `AllResistances` are); every list, report and shopping entry prints ALL lines of a multi-line mod on one row
   ("(25-30)% increased Spell Damage / +(x-y) to maximum Mana"); `attribute_requirement_nodes_max` (the tree
   optimizer's cap of one +30 attribute node, from the amendment WIP, never specified, never measured) defaults to NO
   cap -- leave the knob, document it as unmeasured.

## Measurement (one detached run, ~40 min; no output meanwhile is normal)

`C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe scripts/gear_transplant.py --set smoke --seed 1
--results artifacts/runs/gear-templates/fix3-results.json --report artifacts/runs/gear-templates/fix3-report.md`.
In the final message: the C / A table with this column added (targets, not gates: every reference at or above 21abf86
-- 83.8 / 68.3 / 94.1 / 30.5 / 91.6 / 40.2 -- and the three bow references above the first version's 50 / 31 / 51);
C's own seconds per build (not the row total); lines by kind per reference; which references are feasible under C;
the FULL item list of all six references with multi-line mods printed whole; and for bleed_bow's bow and stormbrand's
sceptre 1 the per-line candidate table (candidate, score before -> after, taken / refused, reason) so that the lead can
see the rules above at work. Also write the six C builds as PoB import codes
(`artifacts/runs/gear-templates/fix3-<reference>.pob.txt`): the user reads PoBs.

Tests: fast ones for rules 1-7 on fake mod lists (a weapon line with +0 value and -0.19 violation loses to a +142 k
line; a gem-level mod blocks the item's other open lines; the elemental group predicate; the hybrid label; the
per-item and per-set attribute caps). Focused tests (`tests/test_wishlist_gear.py tests/test_wishlist_gear_pob.py
tests/test_explain.py tests/test_gear_transplant.py tests/test_bench_unlocks.py`), then the whole suite once,
foreground, with `-p no:faulthandler`. Check `cmd /c dir /AL` first (junctions). Do not edit `docs/ROADMAP.md` or
`docs/DECISIONS.md`. Commit early and after each rule; begin your final message with `=== FINAL REPORT ===`.
