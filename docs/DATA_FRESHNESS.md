# Data we hold from outside PoB, and when to refresh it

The user (2026-09-19): some of our inputs rest on players' tests or on the current league's atlas and change
without notice; keep one list of what is current and when it must be checked again. Check this list at every league
start and at every PoB bump (`docs/LAYOUT.md`, "Bumping PoB", moved from CLAUDE.md).

| data | where it lives | source | refresh |
|---|---|---|---|
| PoB release and its Lua data | `locks/pob.lock.json`, `vendor/pob/source/` | PoB Community release | at a PoB bump: re-clone, rebuild the three corpora, `scripts/fixture_stats.py`, tests |
| Unique drop-rate tiers | `src/junkroan/pob/corpus_data/unique_tiers.json` | poewiki, read through a browser (bots are refused) | once a league, then `scripts/build_unique_index.py` |
| Wiki extracts used by rules | `var/cache/wiki/` (raw page + compact extract, dated) | poewiki | when the rule that cites it is touched, and once a league |
| Approved / pending game facts | `src/junkroan/mechanics/`, `mechanics/pending_facts.json` | the user's verdicts, wiki, Reddit through GPT | when a source changes; every pending fact is reviewed at a league start |
| Day-1 gear templates | `src/junkroan/mechanics/day1_gear_templates.json` | the user; tiers from the Tuadh snapshots | when the user changes them; tiers re-measured when new reference snapshots arrive |
| Reference builds | `tests/fixtures/tuadh_329/`, `tests/fixtures/zizaran_*/` | the authors' PoBs | new league: new snapshots; old ones stay as they are |
| Tattoo tiers (NOT HELD YET) | to come with the T16 loadout | poewiki tattoo article (players' tests) | once a league; re-parse when the article changes |
| Anointment recipes and oil drop levels | `docs/rulebook/2026-09-19-anoint-oils.md`, `var/cache/wiki/2026-09-19-oils-extract.md` | PoB tree data (`recipe`) + poewiki Oil | static (the user: unchanged for years); re-derive the counts at a PoB tree bump |
| Bench-recipe unlock places and tiers, Pantheon upgrade maps | `src/junkroan/mechanics/bench_unlocks.json`; `docs/rulebook/2026-09-19-bench-and-pantheon-unlocks.md`; raw `var/cache/wiki/2026-09-19-bench-pantheon-cargo.json`, joined `var/cache/wiki/2026-09-19-crafting-bench-unlocks.json` | poewiki Cargo tables through the browser (`api.php?action=cargoquery`: `crafting_bench_options`, `crafting_bench_options_costs`, `atlas_nodes`, `areas`, `pantheon_souls`) | **every league**: run `scripts/build_bench_unlocks.py`; measured over 3.25-3.29, 49 of 82 recipe maps crossed the T10 line and only 10 stayed at T10 or below; recipes of removed maps move to other maps How: `scripts/wiki_cargo_snippet.js` in the Browser pane + `scripts/wiki_cargo_recv.py` (a local one-shot receiver; the page's CSP blocks fetch to localhost, a form POST passes) + `scripts/wiki_cargo_join_bench.py` |
| Runegraft tiers and talisman level requirements (NOT HELD YET) | to come with the endgame loadouts | poewiki Runegraft article (players' mass reports), poewiki Talisman | once a league: the Runegraft tiers move with new reports |
| Loadout matrix | `docs/rulebook/2026-09-19-loadout-matrix.md` / `.json` | the user | when the user edits the form (https://claude.ai/artifact/8NUYbPusXf4XoekHdXhDaG) |
