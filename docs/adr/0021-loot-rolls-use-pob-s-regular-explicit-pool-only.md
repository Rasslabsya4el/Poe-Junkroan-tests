# 2026-09-11 D21. Loot rolls use PoB's regular Explicit pool only

Status: Accepted

PoB keeps mod sources in separate tables (`Explicit` = regular drops plus
influence mods, `Delve`, `Synthesis`, `Scourge`, `Corrupted`, `Eldritch`
implicits, `ItemExclusive`, `Master` = bench) but hands items without a
sub-type the merged `Item` table. Delve mods carry plain base tags and passed
the weight filter, so simulated day-1 rares showed "+1 to Level of Socketed
Dexterity Gems" and "Curse Enemies with Despair on Hit". `list_item_mods` and
`random_rares` now iterate `data.itemMods.Explicit`; influence-only (influence
tags), essence-only and incursion mods (zero weight without their source) fall
out through `GetModSpawnWeight`. Titan Greaves: 84 regular mods, 104 merged.
Eldritch implicits are a separate, cheap-to-get layer and can be added later
as an explicit rail option; they are not regular drops.

