# Reading 2026-09-22: ziz-rules gap list (Opus 5.5 lead)

Source: `C:\Coding\poe-junkroan-archive\benchmark\20260922-0524-ziz-rules` (Zizaran early loadouts, loot gear, seeds
1-3, code of 20.09 evening, 26 references / 78 builds, 9 h 27 min on 5 workers); table built by a Sonnet agent from
`report.md` + `results.json` without PoB. Percentages are of the author under our config lane. Median of medians
136.7. Its template twin `ziz-tpl` is still queued.

## Where the 26 references stand

| group | references | what stops them |
|---|---|---|
| fail at load, 0 builds | z325 + z329 champion_explosive_arrow | unknown PoB config var `enemyHit` in the fixture's config set |
| | z328_hierophant_kinetic_fusillade | ascendancy node 43376 "outside selected ascendancy Hierophant" (a 3.28 tree) |
| | z328_hierophant_shock_nova_archmage | "unknown unique: Foulborn Kikazaru" |
| built, 0 seeds counted | z325_berserker_ground_slam_autocry | audit: 9 ascendancy nodes against the rail's 8 (4 labs), all 3 seeds, feasible otherwise |
| | z327_assassin_poison_spark | audit: the author's Winterweave ring is drop-disabled (legacy unique), all 3 seeds |
| below the author | z327_necromancer_raise_spectre | 12% (FullDPS 267k against 2.2M), feasible, one seed stopped on the time budget |
| | z325_slayer_ground_slam | 21% (440k against 2.1M); seed 1 lost 57% at "gear pass 2 (with tree)" |
| | z326_necromancer_zombie_army_early | 41% on 1 counted seed; 2 seeds miss the physical max-hit floor (15.3-15.6k < 16.3k), all 3 stopped on time |
| | z327_hierophant_storm_burst | 48% (channelling: the 100% sustain floor of D63.2 is the first suspect, unchecked) |
| | z326_trickster_blight_of_contagion | 61% (channelling too); seed 1 not counted: audit dead nodes "per Endurance / Frenzy Charge" |
| | z326_chieftain_righteous_fire | 80%, clean |
| | z327_slayer_earthshatter | 100% |
| above the author | the other 12 | 111-690%; the top three (z327 earthquake 690%, z325 eviscerate 431%, z329 earthquake 368%) are measurement suspects before they are wins |

## What it says

1. **Six of 26 references (23%) never produce a counted build, and none of the six is an optimizer problem**: three
   loader errors (a config var, a tree-version ascendancy node, a Foulborn unique name) and two skeleton-vs-audit
   contradictions (the benchmark carries the author's drop-disabled unique into our build -- and, unchecked, most
   likely the author's 9th ascendancy node -- then the audit rejects our build for them). The rule for the second kind: the skeleton a benchmark
   takes from a fixture must already obey the rails (8 ascendancy points, `Rails.unique_allowed`), so the audit can
   only reject what the search chose.
2. **The two real gaps to read first**: spectres (12%) and the Slayer's Ground Slam (21%). Both are feasible and
   clean, so the number is the optimizer's or the skeleton's: for spectres which monster is raised (the table shows
   2 spectres, the monster was not checked); for Ground Slam the loss appears when real gear meets the tree
   (seed 1, -57%). One PoB reading each.
3. **The two channelling skills (Storm Burst 48%, Blight 61%) are the test of D63.2's 100% sustain floor** for
   channelling: if the floor is what binds, it is a rule question for the owner, not a bug.
4. **4-7x the author is not credible for a day-1 Zizaran PoB** (hand-tuned meta starters): check the author lane of
   z327_gladiator_earthquake first (a wrong main socket group or an aftershock counted on one side only would do it).

No code before the owner's word; proposed order when allowed: the loader errors and the fixture-skeleton rails (six
references back, no optimizer change), then the two readings, then the channelling floor question.

## Addendum 22:20: the spectre gap is the supports, not the monster

z327_necromancer_raise_spectre, read from the XML (no PoB): the author and all three of our seeds raise the SAME
spectre (`Metadata/Monsters/LeagueCrucible/Cold/Pyromaniac`) with the same side groups (Raise Zombie, Stone Golem +
Animate Guardian, Skitterbots, Skeletons). The main link differs in two supports: the author runs Greater Volley +
Faster Casting, ours Cold Penetration + Concentrated Effect (Minion Damage, Spell Echo, Controlled Destruction kept).
FullDPS 2.2M against 267k. Next (one PoB what-if, when a slot is free): Greater Volley back into our s1 -- if the
number jumps, find why the picks never offered or kept it (candidate list, a rule, or the projectile-count config).
