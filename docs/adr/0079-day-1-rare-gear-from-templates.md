# 2026-09-19 D79. Day-1 rare gear from templates (the owner's design)

Status: Accepted; amended by D89, D92

Written 2026-09-26 from `docs/specs/2026-09-19-day1-gear-templates.md` and the merges behind it; the entry was never
written into the old `docs/DECISIONS.md`.

Day-1 rares follow a fixed template per slot class instead of "add a mod only while the objective improves", because
the owner ruled that such items must look alike from build to build so a person can check them: life (energy shield on
a pure ES build) on every item that can roll it, resistances solved for the whole set, and PoB choosing only the open
lines and the craft. The real day-1 rares agree (`docs/research/2026-09-18-author-rares.md`: life on 61-100% of the
items of every armour / jewellery slot). Templates are data the owner edits
(`src/junkroan/mechanics/day1_gear_templates.json`); three lines per armour / jewellery item is deliberate (the owner,
2026-09-26: fix which lines, never add lines). Templates are the product's gear (the owner, ROADMAP State of 2026-09-26);
the benchmark still defaults to loot (D19) and runs templates as `--gear wishlist`.
