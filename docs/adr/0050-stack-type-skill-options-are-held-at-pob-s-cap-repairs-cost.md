# 2026-09-14 D50. Stack-type skill options are held at PoB's cap; repairs cost DPS, not points; the author's uniques are the current variant

Status: Accepted

Three references sat below their authors after the 14-reference baseline
(Poison Spectral Throw 74%, Spark 77%, Cold DoT 86%). Each had a general
cause, none of them a tree or gear weakness:

- **Spark: a stack the skill builds had no config rule.** The author's
  `intensifyIntensity=4` (Pinpoint) was kept "from the build's config";
  our from-scratch lane never set it, so our Spark ran at 0 intensity
  (11 projectiles, no Pinpoint damage) and the number was 354k. The same
  finished build at intensity 3: 569k (124% of the author under our lane).
  `config_rules.is_stack_option`: a count-type Skill Option whose label
  names a stack the skill builds ("# of Intensity", "Stages", "Stacks";
  not the ones PoB fills itself, "(if not maximum)" / "(if not average)")
  is the class of D36/D42: a state built by using the skill and held, the
  ramp rail judges the time. PoB judges the value (`judge_stack_options`):
  the input is set to the rails ceiling (50) and kept only when PoB caps it
  below (the number at 50 equals the number at 49 and differs from 0);
  the cap itself (3 for Pinpoint, 4 with the Caster Mastery) and the share
  of the number the stacks carry (1 - number at 0 / number at the cap,
  38% on Spark) go to the ramp as `option_stacks`, so only that share
  ramps, one stack per cast. The input stays at the ceiling so a mastery
  or item raising the cap is credited in every later trial; an option PoB
  does not cap within the ceiling is an assumption about the fight and
  stays off. Sigil of Power's stages are the same class and moved the
  Spark author under our lane 460k -> 585k (both sides get it).
- **Cold DoT: repairing a floor by "violation removed per point".** Seed 3's
  regrown tree (D45) reached 232k with life 0.56 short, then the refine's
  repair swapped in Quick Recovery (-45k) and Wind Dancer (-36k) because
  the infeasible-state ranking was violation removed per point: points are
  already spent in a swap, so the real cost is DPS. The tree ended at 133k
  and lost to the old 142k; seed 1 paid the same way (295k -> 189k) and
  recovered by luck. `TreeOptimizer.repair_key`: while a floor is missed a
  swap is ranked by violation removed per DPS lost (a free repair first),
  with its own round budget (`repair_rounds=60`) so many cheap 1-for-1
  swaps are allowed; `max_rounds` counts feasible rounds only. That alone
  was not enough (regrown Cold DoT seed 1: 295k short by 0.28 -> 186k and
  stuck at 0.001, "no improving swap": once the damage leaves are swapped
  out only life leaves remain and no 1-for-k swap nets a reduction). The
  greedy itself is why the regrown tree ends short: its repair estimate
  (which points a repair will need, so it can keep buying damage) sums
  every candidate's total violation reduction, and five +Str nodes that
  each fix the same attribute count five times. `Objective.violations`
  gives the shortfall per constraint; two other estimates were measured
  against it on eight finished builds regrown from scratch (final after
  the refine; sum / paid per constraint / greedy cover of all
  constraints): Absolution s2 673k / 575k / 578k, Absolution s3 495k /
  456k / 456k, Bleed Bow s2 368k / 526k / 437k, Cold DoT s1 186k (short
  by 0.001, no swap could repair it) / 244k / 210k, Cold DoT s3 221k /
  172k / 172k, Poison ST s1 129k / 122k / 120k, Spark s1 820k / 779k /
  861k, Stormbrand s1 654k / 522k / 690k. No estimate wins alone: the
  optimistic one reaches the strongest trees when the repair works and
  strands the tree when it does not; the careful ones buy defence first
  and leave 10-30% behind on half the builds (a full run with the
  per-constraint estimate everywhere put Absolution at 67-68%, from
  123-138%). So the rebuild stage grows two trees, one per estimate
  ("sum", then "cover"), each refined and re-laned, and PoB keeps the
  better; every other stage keeps the optimistic estimate it always had.
- **Poison Spectral Throw: the author plays a legacy unique.** The author's
  Natural Hierarchy is the "Pre 3.29.0" variant (32% increased damage, 32%
  chaos); our skeleton takes PoB's current variant (a gain-as-extra
  chain). Our builds with the author's amulet: +14-16%; the author with
  the current one: 87% of their own number. The rails require obtainable
  items (D31), so the benchmark now re-equips the author's uniques from
  PoB's database (current variant, mid roll), exactly as the skeleton does
  for ours; the author's own number stays as built and the report line
  logs the change.

- **Numbers a rule derived were frozen at the bare-rig value.** Our own
  config is never authored, yet `derive_config` kept any numeric input the
  build already carried "from the build's config" (D26, meant for reading
  an author's build): Poison Spectral Throw's "# of poison on enemy" was
  PoB's estimate of 4 stacks on the bare rig and stayed 4 through every
  later lane while PoB's estimate had grown to 17-19; The Wasp Nest's
  added chaos needs 5. The three smoke builds at PoB's current estimate:
  +26-27% (165,715 -> 209,142; 127,766 -> 162,334; 123,932 -> 157,931).
  `derive_config(prefer_rules=True)` (the pipeline and the benchmark's
  author lane): a value the rules derive (PoB's poison estimate, the
  rails' numeric rules, stack caps, list choices) is derived again on every
  reconfigure; an existing value survives only where no rule exists.
  Reading a build as it is (audit, describe) keeps the default.

Also found on the way: the audit's "not modelled by PoB" list ran the
template text of uniques (every variant's lines, ranges unresolved:
"(25-35)% increased Damage") through the parser, 22 false warnings on
Poison Spectral Throw. The worker now returns item lines as PoB uses them
(the selected variant only, ranges resolved at the item's roll,
`Item:BuildModList` order), a two-line mod (The Wasp Nest) is parsed as
one, and "Corrupted" is a flag, not a mod: 22 -> 5 warnings, all real.
`build_text` (config proofs) reads the same lines, so unselected variant
text can no longer prove a generator.

