# 2026-09-20 D86. The level of a flat-reservation aura is a build decision, not the gem rail's 18

Status: Accepted

The gem rail (D23) wrote EVERY gem at level 18. For an aura that reserves FLAT mana the level is a deliberate player
choice: PoB's gem data gives Precision 22 mana at level 1 and 167 at 18, Clarity 129 at 8 and 251 at 18. Measured:
20 references carry 60 enabled flat-reservation gems below 18; all 33 of our delivered builds on the 11 Tuadh references
carried the aura at 18; impale_cyclone's author went from +73 to -37 unreserved mana under our lane; three of the
"cannot use a skill" builds of D85's scan (shockwave_cyclone) were uncastable only because of the rail.
Rules: the set is derived from PoB's data (a reservation skill type, no mine type, `manaReservationFlat` in the level
table: today Clarity, Precision, Vitality); on OUR side every level 1..rail is tried under the full objective and the
best Score wins, at construction and as a loop move of its own after the picks; on the AUTHOR's side the gem keeps
min(author's level, rail). Consequence: the authors' numbers of those 20 references move (shockwave_cyclone's author
440,187 -> 416,727 under our lane), so campaigns before and after D86 are not comparable on them. One seed each, for
the record only: impale_cyclone 93 -> 103% (Precision 11), shockwave_cyclone 165 -> 189% (Precision 17), winter_orb
297 -> 326% (Clarity 1, and the build took Supreme Ego: on the reading list).

