# 2026-09-12 D34. Self-degen is a rail: net life + ES change per second >= -100

Status: Superseded by D63

Righteous Fire Berserkers came out audit-clean at -1,316 life per second:
the sustain relations cover skill *costs*, not self-degen. New floor
(`rails_default.json`): PoB `NetLifeRegen` + `NetEnergyShieldRegen` (regen
minus degen per pool) + life leech gain rate + recoup >= -100/s. PoB sends
degen to energy shield first while ES regenerates, which is how an RF
Inquisitor with Pious Path (life regen also recovers ES) sustains at +157
while an RF build with The Untouched Soul sits at -239 and fails. References
span -89 (Blood Rage, no leech) to +733. The audit treats this floor as an
error. Not covered: self-hit damage (Boneshatter trauma), which PoB judges
through `SustainableTrauma`.

