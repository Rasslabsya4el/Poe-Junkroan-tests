# 2026-09-20 D91. The loop re-chooses the weapon base as the build mutates (written 2026-09-22, owed)

Status: Accepted

The user: a build that drifted into crit must not keep its non-crit base; weapon bases are among the strongest choices
of an attack build. Merged 23b6e65 (spec `docs/specs/2026-09-20-loop-weapon-base-move.md`). Once per loop pass, after
the gear moves and before the picks, each rare weapon slot's own affixes (mod ids, rolls, quality, sockets, bench craft)
are rebuilt on every other legal base of the same class through `craft_rare` (a base where a mod is illegal is skipped),
ONE fast item what-if per base, the best judged like a gear move with an exact restore; shields, quivers and uniques are
never touched. Replay bench, seed 1, 96 delivered builds: 57 / 39 / 0 improved / unchanged / worse, mean +1.58%, 2.8 s
a build; spells +2.03% (Opal Sceptre, Prophecy Wand implicits), attacks +1.33% (Thicket -> Imperial Bow, Vaal ->
Despot Axe), minions 0. The rejected-trial fingerprint covers the gems and every other item (crit multiplier on a ring
is what makes a high-crit base pay). In real loops (move-ledger reading 2026-09-22, 180 loot builds): improved 104 of
156, median 0.5-1.0% a build, 27% of final value per minute of worker time, the best yield per minute of any move. On
TEMPLATE gear it keeps almost nothing (6 of 323 tries on core14-tpl, 7 of 397 on new18-tpl, 0 of 139 on the smoke):
the template already ranks bases by effective value (D92), so the move is its check, not its source.

