# 2026-09-12 D40. Structural keystones are decided by rebuilding without them

Status: Accepted; amended by D40 amd 1, D40 amd 2

The Puncture Gladiator took Blood Magic in the greedy tree, before the
utility links were picked; with life reserved for nothing, the aura pick
later found no room for Pride. The greedy step judged the keystone
against the build as it stood, not against the build the keystone rules
out. The same holds for Crimson Dance (attack rate and bleed duration are
bought afterwards), Eldritch Battery, Mind over Matter, Chaos Inoculation.

Coupled decisions are compared as whole builds: the search's mutation
round now rebuilds each finished build once per structural keystone it
took, with that keystone forbidden (`Skeleton.forbid_keystones`, honoured
by every tree stage through `TreeOptimizer.forbid`, including paths that
run through the node). The variant goes through the full pipeline, so the
auras, supports, gear and tree it enables are all in place when the two
builds are ranked by the same objective and audit. Cost: one full run
(~12 min) per keystone per finalist. Keystones fixed by the request are
not varied.

The first variant run also found why Crimson Dance kept winning: PoB 3.29
does not parse Jagged Technique's "Bleeding you inflict is Aggravated"
(the aggravation lines in Data/ModCache are empty), and the 200% more
bleed damage against a moving enemy is the only way to represent it. The
conservative lane left `conditionEnemyMoving` off ("referenced but no
generator rule"), so every non-Crimson-Dance bleed was judged at a third
of its value. `config_rules._aggravated_bleed`: aggravation text proves
"enemy is moving"; "X% chance to Aggravate on hit/crit" counts by the
ailment uptime rule; Crimson Dance ("cannot be Aggravated") removes it.

Puncture Gladiator (level 80, no uniques), conservative CombinedDPS:
before any of this 843k with Crimson Dance at 1.39 aps (ramp 4.6 s, fails
D39); with the ramp rail alone 420k (Crimson Dance kept, attack speed
bought to 1.55 aps); with the aggravation rule the greedy tree no longer
takes Crimson Dance: 566k with Blood Magic (Dash, Vulnerability, Flame
Golem), and the rebuilt variant without Blood Magic 533k with Malevolence
in its place. The 6% between the last two is inside loot noise (~20%);
both are ranked, the user sees both.


## Amendment 1 (2026-10-15, the brain, from the map "Reshaping choices" #1040 and its calibration #1064)

The rule "one full rebuild per structural keystone per finalist" is replaced by the ladder the owner settled in
#1028's grill (rounds 1-3, 2026-10-14) and #1064 calibrated:

1. **Step 1, the flip** (seconds): the keystone is flipped on the finished build; a PoB number that collapses a
   floor (Life 4053 -> 1 under Chaos Inoculation) marks it a reshaping choice (GLOSSARY). An additive choice
   (nothing collapses) is decided by the flip alone and gets no rebuild.
2. **Step 2, the repair** (minutes): a bounded local repair of the finished build with the choice forced or
   forbidden (`junkroan.optimizer.repair`: gain floor 1 % per pass, at most 2 passes; the dead points re-spent,
   auras re-picked, one gear pass). Verdict: *take* when the repaired variant is at least the parent, *drop* when it
   is below and flat, *climbing* when its last pass still gained more than the floor.
3. **Step 3, the full rebuild** (~70 min, D40's old rule) only for *climbing*: the variant goes through the whole
   pipeline as its own skeleton run, as before.

Calibration (#1064, 2026-10-15, ground truth = the recorded full rebuilds of the 2026-10-05 weekly run and of
core-3): **0 missed takes, 0 false takes** over 4 forced pairs and 9 counted forbidden pairs (6 more pairs sit
inside the 0.95-1.05 band where neither verdict is wrong); 2 of the 15 forbidden pairs were *climbing* and went
to step 3. Compute, repair against the recorded full rebuild of the same pairs: force 0.152, forbid 0.381 when the
two climbers' full rebuilds are charged to the ladder (0.316 without them, core-3 0.065). The map's bar of one
third (the owner's 3а) is met on the verdicts and missed by the climbers' share on this take-heavy sample; the
bar is re-measured on the first weekly core run that uses the ladder, over its whole keystone population, and the
map's ticket carries that number.

Consequences: the mutation round of every search and the weekly core run run the ladder instead of a rebuild per
keystone; the weekly's 15-19 keystone variant rows become only the climbers' rebuilds; the report shows both
outcomes of every reshaping choice as Pareto points with one line of numbers (lost CombinedDPS, won TotalEHP);
`Skeleton.forbid_keystones` and `TreeOptimizer.forbid` stay as step 3's mechanism. The 2026-09-12 numbers above
(Puncture Gladiator) stay as the record of why coupled decisions are compared as whole builds.


## Amendment 2 (2026-10-15, the brain, from the owner's bundles grill on the map "Reshaping choices" #1040)

The owner's grill of 2026-10-15 (two rounds and a confirmation, #1040 comment 6201364993) splits the ladder of
amd 1 by direction:

1. **Force leaves the search.** A build no longer adds a reshaping choice on its own initiative. A **bundle**
   (GLOSSARY: requirement + reward + variable slots, e.g. Chaos Inoculation + the Energy Shield sources) is
   measured offline on **stands** (one synthetic build per type: spell / attack / minion by damage type, not core14)
   into the **catalogue**. A build retrieves only the bundles the catalogue says paid on similar stands and gives
   each one PoB check: the forced repair of amd 1 (`BuildPipeline.repair`, direction `force`). PoB in the build has
   the last word; the outcome is two Pareto points and one line (lost `CombinedDPS`, won `TotalEHP`). Similarity
   starts as the same skill class (spell / attack / minion); every build logs the tree-node and gear overlap with
   the stand where the bundle paid, and the brain moves to whichever measure predicted PoB's in-build confirmations
   better once enough of them exist.
2. **Forbid stays in every build**, in the ladder form of amd 1 (#1091): a keystone the greedy tree took is a
   greedy-tree error to be tested on the build itself, not a bundle (the grill's count: 18 of 59 counted forbidden
   pairs beat their parent; summon_raging_spirits without Mind Over Matter 2.8-3.7x).
3. **No hand list of kinds.** "Day 1 = keystones only" (the map's earlier scope, #1042's count of parsed lines) is
   revoked: candidates come from the **bundle graph** over everything a loadout allows, sliced by loadout; a line
   PoB leaves unparsed enters it only once a layer above PoB has made it a PoB number. This supersedes the
   agreement of 2026-10-15 on #18 that the graph waits for a uniques loadout. Day 1 waits only for its own slice
   (unparsed lines -> graph -> stands -> catalogue for day-1 content).
4. **Re-measure is targeted.** A bundle is re-measured when its parts change; on a PoB bump every stored stand
   build is recalculated once (no optimization) and only bundles whose numbers moved are re-measured in full.

Why the split: forcing every candidate in every build multiplies the build's cost by the candidate count, and once
candidates come from a graph instead of 57 keystones that count is in the hundreds; measuring a bundle once per
stand pays for it across every build of that type. Forbidding is cheap (the build already holds the keystone) and
its errors are the build's own, so it cannot be measured elsewhere.

Consequences: amd 1's force direction keeps its mechanism and loses its in-build caller until the catalogue
exists; #1091 runs only the forbid direction; the map "Reshaping choices" is rewritten to the graph, the stands and
the catalogue; the weekly core run's `-no-<keystone>` rows stay as the forbid ladder's confirmation.
