# 2026-09-14 D49. Minions count at their limit; the minion's skill is a choice

Status: Accepted

The first bow and minion references (Absolution Necromancer, Summon Raging
Spirits Guardian, Bleed Bow Gladiator) went through the benchmark at
19-24% of their authors. Three causes, all general:

- Every socket group was written with `groupCount="1"`, and PoB's
  `getActiveSkillCount` takes the group count over the gems' own counts
  when it is set, so a Raise Zombie gem counted one zombie and Absolution
  one sentinel in FullDPS. The harness no longer writes a group count of 1
  (the app leaves it nil). `Skeleton.refresh_minion_counts` sets each
  minion gem's count to PoB's own limit for the build as it stands
  (`skill_facts.minion_limit_stat`: `base_number_of_zombies_allowed` ->
  `ActiveZombieLimit`, read from `Data/SkillStatMap.lua` and the skill's
  data), after the skeleton and on every reconfigure, since limits move
  with the tree. Bare Absolution skeleton: 19k -> 65k FullDPS.
- Which of a minion's skills PoB calculates (`skillMinionSkill`) is a
  choice, judged like stance or exposure type (D24): every minion gem
  tries skill 1..4, the best objective stays. Absolution's sentinels:
  skill 2 is 2.2x skill 1 (65k -> 144k on the bare skeleton).
- Snipe (Bleed Bow: Puncture + Snipe) had no stage count: `configSnipeStages`
  is now a rails assumption (6, channelled to full stages before release)
  when Snipe is linked, the same class as Blade Vortex blades (D36).

Also from those runs: a group PoB keeps without a socket slot gets one
when the skeleton is read from a build; the joint stage fills Weapon 1
before Weapon 2 (a quiver is only valid with a bow equipped); "used a
minion skill recently" is sustained by a minion gem; Feeding Frenzy's buff
is proven by the support; the chosen Elemental Army exposure type sets
the matching exposure condition. The benchmark compares minion builds on
FullDPS.


