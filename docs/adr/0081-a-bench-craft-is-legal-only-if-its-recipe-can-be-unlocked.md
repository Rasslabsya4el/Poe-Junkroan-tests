# 2026-09-19 D81. A bench craft is legal only if its recipe can be unlocked at the loadout's stage

Status: Accepted

PoB's bench table knows nothing about where a recipe is found or what it costs; the gear fillers took any craft the
item level allowed. The game puts a recipe in a campaign area, a Labyrinth trial or a MAP, and the map's tier is
league data: the wiki's Cargo tables (`crafting_bench_options`, `atlas_nodes`; read through the Browser pane,
`docs/rulebook/2026-09-19-bench-and-pantheon-unlocks.md`) give 829 options -- 79 unlocked from the start, 187 in the
campaign, 18 in the Labyrinth, 422 in maps of tier 1-10 and 123 in maps of tier 11-16 in 3.29 -- and over 3.25-3.29
49 of the 82 recipe maps sat on both sides of the tier-10 line (flat life rank 5: T10 / - / T15 / T3 / T7). The user
had asked whether GGG keeps recipes at similar tiers between leagues: it does not, so the data is refreshed every
league (`docs/DATA_FRESHNESS.md`), never a constant. A GPT report on the same question was rejected (a 3.27
third-party recipe list; its tiers disagree with the wiki).

Rule: `mechanics/bench_unlocks.json` (built by `scripts/build_bench_unlocks.py` from the cached Cargo join) puts an
`unlock` on every row of `PobSession.list_bench_mods` (all 732 PoB rows matched: 716 by mod id, 16 ambiguous ones
take the lowest requirement); rails `gear.bench` = `max_map_tier` 10, `unknown_tier_allowed` false (the unique-map
meta-crafts: endgame in the user's book), `excluded_cost_currencies` [] (the user has not ruled on 4x Exalted Orb
crafts at day 1). Both fillers obey it: `loot_gear.bench_candidates`, and the template filler's `bench_rows` BEFORE
its best-rank pick, so a legal lower rank survives an illegal higher one.

Measured: in `new18-rules` (54 builds) 21 of 342 crafted lines (6%) were recipes of T11-16 maps in 3.29 (6% attack
and cast speed x5, -mana cost x2, +mana / cost efficiency x3, cooldown recovery x2, AoE / projectile hybrids, crit
hybrids), none cost Exalted or Divine Orbs; static_strike s1 on the parent and with the rail: 238.3% -> 237.1% (the
belt's T11 cooldown-recovery craft removed, nothing legal replaced it). The loadout the rails describe is day 1;
later loadouts raise `max_map_tier` (the rulebook, entry "Бенч-крафты").

