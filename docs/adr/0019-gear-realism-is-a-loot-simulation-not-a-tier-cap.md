# 2026-09-11 D19. Gear realism is a loot simulation, not a tier cap

Status: Accepted

Tier caps derived from the reference rares still let the filler assemble
items with six on-theme mods (Stormbrand: 213% of the author's DPS in 11 s).
A per-mod rarity measure (sum of -ln p over PoB spawn weights) does not
separate them either: the author's rares are just as "rare", only with useless
mods. What differs is selection. So realism is modelled as "best of N random
rares per slot": roll N items on the base with PoB's own spawn weights
(`PobSession.random_rares`), keep the one the objective likes most, equip,
next slot. Calibration on Stormbrand: N=30 -> 58%, 100 -> 63%, 300 -> 94%,
1000 -> 159% of the author's DPS. Day-1 gear ~= best of ~300 drops per slot.
N is the single realism knob; bench crafts and essences are added on top as
deterministic steps later. The greedy affix filler remains for "what would
the ideal rare be" questions (crafting targets), not for day-1 output.

