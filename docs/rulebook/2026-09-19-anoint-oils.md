# Anointments by loadout (derived 2026-09-19; the user's rule: relate each oil's drop level to the loadout's level rail)

Sources: the 472 anointment recipes of PoB's own tree data (`vendor/pob/source/src/TreeData/3_29/tree.lua`, the
`recipe` field of a notable: three oil names) and the oils' drop levels from poewiki
(`var/cache/wiki/2026-09-19-oils-extract.md`). Level rails from the loadout matrix: day-1 up to level 70, T16 up to
83, endgame 86+; Prismatic Oil from endgame by the user's explicit ruling ("no Golden Oil on day 1; Prismatic from
endgame").

| oil | drop level | earliest loadout |
|---|---:|---|
| Clear, Sepia, Amber, Verdant, Teal, Azure, Indigo, Violet, Crimson, Black | 1-68 | day-1 |
| Opalescent, Silver | 73 / 78 | T16 |
| Golden | 80 | endgame -- the user's exception (2026-09-19): it drops from level 80 like Silver but is far rarer |
| Prismatic | 80 | endgame (the user's ruling) |

A notable's loadout is that of its most demanding oil: **208 notables can be anointed on day 1, 143 more from T16,
121 (every recipe with a Golden or a Prismatic Oil) from endgame**. Oil use over the 472 recipes is even (95-114 each; Prismatic 33).

Static data (the user: oil levels have not changed for years); re-derive the counts at a PoB tree bump.
