# 2026-09-20 D90. With Eldritch Battery and no damage taken from mana, energy-shield recharge sustains an ES cost (amends D63.2)

Status: Accepted

The user's verdict on the template-gear reading + the wiki's EB page ("Energy shield recharge is not interrupted by energy
shield spent to pay costs. Unless interrupted by damage to mana or energy shield, energy shield will continually recharge";
`var/cache/wiki/2026-09-20-eldritch-battery-extract.md`): with EB the shield protects MANA, so without a "damage taken from
mana before life" source nothing ever damages it. Derived stat `EnergyShieldRechargeForCosts` = PoB's `EnergyShieldRecharge`
when `EnergyShieldProtectsMana` is on and `sharedMindOverMatter` and all five typed `MindOverMatter` outputs read exactly 0
(a missing output = not proven = 0); it joins ONLY the ES sustain relation. With Mind over Matter hits cut the recharge: not
counted; ES REGEN counts in every case (it already did). summon_raging_spirits (Guardian, EB): recharge 109/s against a cost
of 153.9/s, the author's ES sustain violation 1.000 -> 0.167, the loot transplant becomes feasible at unchanged FullDPS
(115.3% of the author); on the merged main the template set stays feasible at 115.8% WITHOUT the two ES-regen crafts it
bought before (it takes ES bases instead; 119.4% before -- the greedy's path, both feasible), the no-EB control cold_dot is
bit-identical (256,823). Six EB fixtures can move (Tuadh lightning_trap, poison_spark, soulrend_chaos_dot,
summon_raging_spirits; Zizaran wave_of_conviction, z327 poison_spark), four with MoM 40% stay excluded. The craft
"Regenerate N Energy Shield per second while a Rare or Unique Enemy is Nearby" stays a legal, good BOSS line. MAPPING
BACKLOG (nothing models mapping yet): it does not sustain while mapping; there sustain is ES / mana gained on kill.

