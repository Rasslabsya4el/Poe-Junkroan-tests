# 2026-09-12 D37. Minion main skills maximize FullDPS

Status: Accepted

PoB keeps minion damage out of the player's `CombinedDPS` (it stays 0), so
Summon Raging Spirit screened at 0 for every ascendancy and the support
pick found nothing. `objective_select.objective_for` swaps the maximized
stat to `FullDPS` when the main gem carries the minion tag; floors and
relations stay the rails'. On a bare Necromancer rig the support pick then
finds Added Chaos Damage, Minion Damage, Added Lightning, Minion Speed,
Elemental Penetration. The search, the rig and the pipeline all go through
this selector.

