# Spec: finish the D79 amendment -- the template filler spends its few lines badly

Branch `gpt-2026-09-19-day1-gear-templates-amendment`, commit ebb0487 (the lead's WIP commit of the worker's tree; the
stall watchdog killed the worker at minute 238 during its six-reference measurement). Original specs:
`docs/specs/2026-09-19-day1-gear-templates.md`, `...-amendment.md`. Its partial measurement:
`docs/research/2026-09-19-day1-gear-templates-amendment-smoke.md` on that branch.

## Where it stands (gear transplant, seed 1: A = the author's rares, B = loot best of 600, C = templates)

| reference | B / A | C / A first version | C / A amendment WIP |
|---|---:|---:|---:|
| cold_dot | 90.1% | 81.4% | 71.8% |
| bleed_bow | 146.5% | 49.8% | FAILED ("item is not valid for slot Weapon 2"; a later single run gave 79.9%) |
| summon_raging_spirits | 115.3% | 101.1% | 87.9% |
| impale_ballista | 38.3% | 30.9% | 30.5% |
| stormbrand | 100.5% | 100.5% | 72.5% |
| burning_arrow_snipe | 92.8% | 51.0% | 39.6% |

The template shape is NOT the handicap: the authors' day-1 rares carry a median of 2-3 USEFUL mods per item
(`docs/research/2026-09-18-author-rares.md`: 0 useful 9%, 1: 14%, 2: 30%, 3: 25%, 4: 18%, 5: 5%), and a template item
has life + resistance + one line (+ a craft). The lines are spent badly. Read from the WIP's item lists:

1. **Attribute payments eat the open lines.** stormbrand: both Void Sceptres carry "+(28-32) to Strength", so do the
   amulet and the belt of cold_dot; the armour bases are Vaal Gauntlets / Vaal Greaves / Royal Burgonet (strength
   bases) on casters. A base that needs a payment is ranked at the base screen (D73 amendment) and then the payment
   takes the item's ONLY free line. Rule: the base is chosen on the FINISHED item -- base + payment + what is left --
   against a base that needs no payment and keeps its open line for the objective. Across the set the template
   filler may pay requirements with at most `attribute_affixes_max` lines IN TOTAL beyond implicits (not per item),
   and only when no base of the slot's allowed types avoids the payment at a better finished score.
2. **Lines that move nothing are still bought.** cold_dot's sceptre: "+1 to Level of all Physical Spell Skill Gems"
   (a two-line rare mod, zero effect on a cold build); the first version's bow took "reduced Attribute Requirements"
   and "an additional Arrow" at delta +0. Rule: an open / craft line is taken only when it improves the objective
   (value up, or violation down); otherwise the line stays EMPTY and the shopping list says "free line: anything".
   A two-line mod is taken only when its measured gain beats the best two ordinary lines it displaces.
3. **Extra resistance lines are added to capped sets.** impale_ballista: overcap 81 / 88 / 67 with 2 extra lines;
   stormbrand 134 / 57 / 85 with 2 extra lines and 3 resistance crafts. The fixed resistance line per item is the
   user's design and overcap from it is accepted; an EXTRA line or a resistance CRAFT is legal only while some
   element is below the floor after fixed lines + implicits + uniques + tree, and is removed again when a later
   choice makes it unnecessary (one re-check at the end of the fill).
4. **The Weapon 2 failure** on bleed_bow ("item is not valid for slot Weapon 2"): find it, fix it, test it.
5. Whatever else the item lists show as a line no player would buy for that build: report it with the PoB delta.

## Task

1. In your worktree: `git merge gpt-2026-09-19-day1-gear-templates-amendment` (main has since gained the bench-unlock
   rail in `wishlist_gear.bench_rows` / `rails`, D82 in `pipeline.py` / `generator.py`, the buffs rule: resolve
   keeping both sides).
2. Fix 1-4 as general rules (no per-build logic, no mod-name lists).
3. Measure with ONE detached PoB run (it takes ~40 min; you will see no output meanwhile -- that is normal, do not
   poll processes; read the report file when the command returns):
   `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe scripts/gear_transplant.py --set smoke --seed 1
   --results artifacts/runs/gear-templates/finish-results.json --report artifacts/runs/gear-templates/finish-report.md`
   and put into your final message: the table above with a fourth column, per reference the number of lines by kind
   (life, resistance fixed, resistance extra, resistance craft, attribute, objective line, free line), seconds for C
   (must stay under 180 s per build), and the full item list of stormbrand and bleed_bow.
   Target, not a gate: C / A at or above the first version on every reference, and no line in any item list that
   moves nothing.
4. The ilvl question of the amendment spec (72 / 76 against 70 everywhere): one extra run only if time allows.
5. Focused tests (`tests/test_wishlist_gear.py tests/test_wishlist_gear_pob.py tests/test_explain.py
   tests/test_gear_transplant.py tests/test_bench_unlocks.py`), then the whole suite once, foreground. Commit EARLY
   (after the fixes' tests are green) and again after the measurement. Do not edit `docs/ROADMAP.md` or
   `docs/DECISIONS.md`.
