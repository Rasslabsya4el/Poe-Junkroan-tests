# Spec: a bench craft is legal only if its recipe can be unlocked at the loadout's stage

## Why

Day-1 gear takes one bench craft per item from `PobSession.list_bench_mods(base, ilvl=)` filtered by item level only
(`optimizer/loot_gear.py::bench_candidates`, used by both fillers; `wishlist_gear.py` also walks `list_bench_mods`
itself near line 415). PoB's bench table (`Data/ModMaster.lua`) knows nothing about WHERE a recipe is unlocked or
what it costs. In the game a recipe is an object in a campaign area, a Labyrinth trial or a MAP, and the map's tier
changes every league. A day-1 loadout ("white and yellow maps up to tier 10", the user's loadout book) cannot have a
recipe that sits in a tier 11-16 map.

Data (the lead fetched it from the wiki's Cargo tables on 2026-09-19; read it, do not re-fetch, the wiki refuses bots):
`var/cache/wiki/2026-09-19-crafting-bench-unlocks.json` -> `{"series": [...5 leagues...], "options": [{"id",
"mod_id", "name", "rank", "affix", "location", "kind": "start" | "campaign" | "labyrinth" | "map", "area_id",
"tier_3_29", "tiers": {series id: base tier}, "cost": ["4x Chaos Orb"], "classes", "unveils"}]}`. The human-readable
digest is `docs/rulebook/2026-09-19-bench-and-pantheon-unlocks.md`. Numbers the join must reproduce: **829 options:
start 79, campaign 187, labyrinth 18, map 545, of which 422 at tier <= 10 and 123 at tier 11-16** (3.29, the wiki's
series id `Deepwater`). Unique maps carry `tier_3_29` 0 (no tier in the 3.28-3.29 series; they hold the five
meta-crafts and Maelström of Chaos): treat tier 0 of a `map` row as "unknown tier", not as tier 0. Strings carry HTML
entities (`&#039;`): unescape them.

The wiki's `mod_id` is the game's mod id, the same namespace as `junkroan.pob.bench_mod_ids.bench_mod_id` (RePoE
`crafted` domain), e.g. `EinharMasterIncreasedLife5_` (flat life rank 5: Sulphur Vents, tier 7 in 3.29, tiers over
3.25-3.29 = 10 / - / 15 / 3 / 7) and `EinharMasterIncreasedLife4` (Frozen Cabins, tier 3).

## Task

1. `scripts/build_bench_unlocks.py [--cache var/cache/wiki/<date>-crafting-bench-unlocks.json]` writes
   `src/junkroan/mechanics/bench_unlocks.json`: `{"league", "series_id", "fetched", "source", "by_mod_id": {mod id:
   {"where", "location", "tier" (int, or null for start / campaign / labyrinth / unknown), "rank", "cost": [...]}}}`.
   Options without a `mod_id` (socket, link, colour, meta and flask crafts identified by `name`) go under `"by_name"`
   the same way. Commit the generated file: tests must not need `var/`.
2. `PobSession.list_bench_mods` annotates every row with `"unlock"` (the entry above, or None), next to `mod_id` and
   `families`. A row whose `bench_mod_id` is None (16 of 732 rows: the text matches several crafted mods) takes the
   entry of its candidate ids (`bench_mod_ids.crafted_text_mods` or what that module offers) when they all agree on
   `where` and `tier`; when they disagree, the LOWEST requirement wins (the craft is reachable through that recipe).
   Report how many of the 732 PoB rows end up with an entry, and list the ones without.
3. Rails: `gear.bench` in `optimizer/rails_default.json` = `{"max_map_tier": 10, "unknown_tier_allowed": false,
   "excluded_cost_currencies": []}` with a loader on `Rails` like the neighbouring gear rails. A row is legal when its
   unlock is `start` / `campaign` / `labyrinth`, or `map` with `tier <= max_map_tier`; a `map` row of unknown tier
   follows `unknown_tier_allowed`; a row with NO entry at all stays legal (a data gap is not evidence) and is counted;
   a row whose cost names a currency in `excluded_cost_currencies` is illegal (the list is empty today: the user has
   not decided whether 4x Exalted Orb crafts belong to day 1; the knob must work, a test covers it with a rails
   override). `max_map_tier: null` switches the whole rail off.
4. Apply it in ONE place that both fillers go through (`bench_candidates`), and at the wishlist filler's own walk over
   `list_bench_mods` if that walk can pick a craft `bench_candidates` never sees. No per-build logic.
5. Measurements (one PoB worker only, a 5-worker benchmark and two other workers share the machine):
   a. over the finished run `artifacts/benchmark/20260919-0130-new18-rules` (54 builds; read its PoB XMLs, do not
      rebuild): every `{crafted}` line on every rare -> bench row -> unlock. Table: crafts total; legal under the new
      rail; illegal because tier 11-16 (list craft, map, tier, how many builds); costing Exalted / Divine (list);
      without an entry. This is the number the lead takes to the user.
   b. `scripts/benchmark.py` on ONE reference that (a) shows losing a craft, `--seeds 1 --no-variants --workers 1
      --loop --loop-seconds 300`, on the parent commit and on your tree (run as
      `C:\Users\user\AppData\Local\Programs\Python\Python312\junkroan.exe`): the before / after number and the craft
      that replaced the illegal one. If (a) finds no illegal craft at all, say so and skip (b).
6. Tests (fast, no PoB unless the runtime fixture is present): the generated file reproduces the counts above (by
   `where`, and the 422 / 123 split counted over ALL options incl. `by_name`, unknown-tier unique maps on the <= 10
   side as in the digest; state the split you pin); `EinharMasterIncreasedLife5_` is legal at `max_map_tier` 10 and
   illegal at 6; a tier-12 craft (`JunMaster2MinimumFrenzyCharges1_`, Iceberg) is illegal at 10 and legal at `null`;
   the currency knob; a row without an entry stays legal.
7. `docs/DATA_FRESHNESS.md`: in the bench row, name the script and the mechanics file. Do not edit
   `docs/ROADMAP.md` or `docs/DECISIONS.md`.

Another worker is rewriting the wishlist filler for gear templates on branch `gpt-2026-09-19-day1-gear-templates-2`
(`wishlist_gear.py`, `rails_default.json`, `mechanics/day1_gear_templates.json`): keep your edits to those two shared
files minimal and local so the merge is mechanical. Focused tests first, the whole suite once in the foreground.
Commit EARLY (after step 3's tests are green) and again after the measurements.
