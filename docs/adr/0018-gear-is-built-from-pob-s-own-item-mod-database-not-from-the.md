# 2026-09-11 D18. Gear is built from PoB's own item mod database, not from the PoEDB scrape

Status: Accepted

The PoEDB catalog (84,907 rows) carries no tier and no spawn weight: those
fields are empty in every row, the scrape never captured them. PoB ships the
same affix ladders in `Data/ModExplicit.lua` (and essence / delve / influence
files) with mod ids, affix names, ranged text, required level, group, mod
tags and spawn weights per base tag, plus `Item:Craft()` which builds a rare
from `Prefix:` / `Suffix:` lines by mod id and `Item:CanHaveMod` /
`GetModSpawnWeight` for legality. The gear layer therefore asks the running
PoB for the legal mod list of a base (worker action), crafts candidates
through PoB, and evaluates them with the what-if calculator's item override
(`repSlotName` + `repItem`). Tiers are ranks within a group by level. The
PoEDB catalog stays in the repo as a cross-check source only.

