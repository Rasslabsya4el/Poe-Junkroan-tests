# 2026-09-18 D65. A gem of a limited family is licensed by the skeleton, not by the author's tree

Status: Accepted

The skeleton derived from an author's build carried every golem gem and every hex they had, and
the finished build then ran four golem buffs on a limit of 3 (cold_dot, the frozen campaign's
audit). Two different facts behind it, both measured:

1. **PoB applies every enabled golem's buff whatever `ActiveGolemLimit` says** (probed 2026-09-16):
   a build over the limit is scored on buffs the game cannot give it.
2. **PoB does respect `EnemyCurseLimit`**: `CalcPerform.lua` fills `curseSlots` in
   `for i = 1, source.limit do`, and a curse takes a slot only when one is free or its
   `determineCursePriority` beats the curse already there. The number is honest; what is not is
   the skeleton, which spends sockets on gems PoB never applies and disagrees with the audit.

So the drop happens at derivation (`build_from_skeleton.drop_over_limit_gems`, on the path the
benchmark's author row and our builds share), and **the limit is the one the skeleton guarantees**,
measured by removing the author's ordinary tree from the build PoB holds (their ascendancy,
keystones, uniques and jewels stay). The author's own readback is not it: cold_dot reads
`ActiveGolemLimit` 4 because they allocated the notable Golem Commander, an ordinary node no
skeleton carries and the tree optimizer did not take. A build whose curse limit is its maximum
power charges gets a floor here, written down rather than special-cased.

Which gems stay is PoB's call: every subset of size = limit is scored by disabling the other gems
of the family (the gem-level `enabled` flag, as `optimizer/buff_gems` does for a guard skill) and
reading the objective's own stat; a tie keeps the author's order, and a main-link gem is never
dropped. cold_dot golems: Chaos+Lightning+Flame 228,121 = Chaos+Flame+Stone 228,121 >
Chaos+Lightning+Stone 212,758 > Lightning+Flame+Stone 203,622, so Summon Stone Golem goes; its
hexes: Frostbite 188,082 against Elemental Weakness 176,642. Across the references the rule drops
a golem on burning_arrow_snipe (Lightning, 1,140,756 against 979,488 for the subset that drops
Ice), cold_dot, ignite_penance_brand and kinetic_fusillade, and a hex on cold_dot,
soulrend_chaos_dot (Despair 269,105 against Punishment 207,430) and summon_raging_spirits
(Elemental Weakness 617,448 against Flammability 568,080 and Punishment 429,199, on FullDPS).

The hex family is the audit's own pair of tags (a curse that is a hex): the corpus tags Hexblast
and Bane "hex" without "curse", and a main damage skill must never be dropped as a curse. Marks
are not counted -- the limit is written for hexes. The audit checks are unchanged: a finished
build that exceeds a limit (the picker is free to add a golem after the tree moved) still warns.

