# Spec 2026-09-22: every reference fixture loads, and the skeleton taken from a fixture obeys the rails

Lead: Opus 5.5. Worker: one coder in its own worktree (this spec is given to TWO coders independently to compare
models: do your own work, do not look for another branch). Harness task (ROADMAP Phase 1 kind); no optimizer decision
changes.

## Why

`ziz-rules` (`C:\Coding\poe-junkroan-archive\benchmark\20260922-0524-ziz-rules`, reading
`docs/readings/2026-09-22-ziz-rules-gaps.md`): six of 26 Zizaran references never produce a counted build, and none of
the six is an optimizer problem.

| reference (fixture under `tests/fixtures/zizaran_*/early`) | what happens now, all 3 seeds |
|---|---|
| z325_champion_explosive_arrow, z329_champion_explosive_arrow | FAILED at load: `PoBHeadlessHostContractError: config_payload.config_sets[1].inputs references unknown PoB config var(s): enemyHit` |
| z328_hierophant_kinetic_fusillade | FAILED at load: `ascendancy_node_ids[1] references node 43376 outside selected ascendancy Hierophant.` (a 3.28 tree) |
| z328_hierophant_shock_nova_archmage | FAILED at load: `unknown unique: Foulborn Kikazaru` |
| z325_berserker_ground_slam_autocry | built and feasible, rejected by the audit: `ascendancy points: 9 ascendancy nodes allocated; the rails allow 8 (4 labs)` |
| z327_assassin_poison_spark | built, rejected by the audit: `legacy unique: Ring 1: Winterweave is no longer obtainable (wiki: drop disabled)` |

The rule (the lead): the skeleton a benchmark takes from a fixture must already obey the rails, so that the audit can
only reject what the search chose. The AUTHOR's own build is measured as the author made it (their items stay on the
author's side); only OUR build's skeleton is cleaned.

Code to start from: `scripts/benchmark.py` ~420-500 (author load, `convert_tree`, `skeleton_from_xml`, unique
normalization), `scripts/build_from_skeleton.py:338` `skeleton_from_xml`, `src/junkroan/optimizer/audit.py:125` and
`:149`, `src/junkroan/optimizer/rails.py:206` `Rails.unique_allowed`, `src/junkroan/pob/headless_runtime_worker.py:639`
(unknown unique), `:3527` (ascendancy check), `:5869` (config var check). Find the real paths yourself; these are hints.

## Requirements

1. **Unknown config vars.** Find where the fixture's config inputs reach `config_payload.config_sets[...]`. A var PoB
   does not know is dropped before the call, with one log line per var: `fixture config var dropped: <name> (unknown to
   PoB)`. Do not weaken the contract check in `headless_runtime_worker.py` (it stays an error for our own code).
2. **Ascendancy nodes after tree conversion.** Find why 43376 reaches `set_tree` although the selected ascendancy is
   Hierophant (which tree version the id comes from, which version the check uses). The skeleton's ascendancy nodes
   must be ids of the tree our build uses. An id that does not exist in the selected ascendancy there is mapped by
   node NAME within the same ascendancy if exactly one node has that name, else dropped; one log line each
   (`fixture ascendancy node <id> '<name>' -> <new id> | dropped`).
3. **Uniques PoB does not know.** Find why `Foulborn Kikazaru` is unknown (how PoB 2.67.2 / our uniques corpus
   represents Foulborn items). Our skeleton keeps a fixture unique only if our uniques corpus knows it AND
   `Rails.unique_allowed` accepts it; otherwise the unique leaves OUR skeleton (the slot is filled by the gear filler
   like any rare slot, with the base the author's item had if it is a legal rare base, else the filler's choice), one
   log line: `fixture unique dropped from our skeleton: <slot>: <name> (<reason>)`. The author's side keeps the item
   (use the author's raw item text where a name lookup fails, so the AUTHOR still loads).
4. **Drop-disabled uniques.** Same rule as 3 through `Rails.unique_allowed`: Winterweave leaves our skeleton of
   z327_assassin_poison_spark.
5. **Ascendancy points above the rail.** First report how many ascendancy nodes the fixture of
   z325_berserker_ground_slam_autocry allocates (raw XML, and after `convert_tree`), with names. If the FIXTURE has
   more than `rails.ascendancy_points`, our skeleton keeps that many: drop the node(s) whose removal costs the least
   objective value, measured by PoB on the author (one stats call per candidate), log which. If the fixture has 8 or
   fewer and our build still ends with 9, do NOT fix anything in the optimizer: stop that item and report the chain
   you found.
6. No other skeleton may change. Write `scripts/dump_fixture_skeletons.py` (needs PoB, one session, sequential) that
   writes the skeleton JSON of every fixture in the sets `ziz`, `new18`, `core14` to a folder; run it on `main` (a
   second checkout is not needed: `git stash` is forbidden; run the script from your branch with the new behaviour
   switched off by a keyword argument, or run it before your first code change) and on your branch; diff.
7. Tests: fast tests for the pure parts (config var filter, name mapping, unique filter, ascendancy trimming with a
   fake value function); one PoB-backed test (skipped when `var/cache/pob` is missing) that builds the skeletons of
   the six references above and applies each to a fresh PoB session without an error.

## Numbers to report (in the final report, one table each)

- A. The six references: before / after for "loads", ascendancy node count of our skeleton, uniques of our skeleton,
  the log lines requirement 1-5 printed.
- B. Skeleton diff over all fixtures of `ziz` + `new18` + `core14`: how many identical, how many changed, and for each
  changed one what changed. Expected: exactly the six above changed (fewer if one of them needs no change), every
  other skeleton byte-identical.
- C. Construction-only benchmark on the six, seed 1:
  `python scripts/benchmark.py z325_champion_explosive_arrow z329_champion_explosive_arrow z328_hierophant_kinetic_fusillade z328_hierophant_shock_nova_archmage z325_berserker_ground_slam_autocry z327_assassin_poison_spark --construction-only --no-variants --workers 2 --tag fixfix-<your model>`
  (check `python scripts/machine_load.py --need 2 --role other` first; if WAIT, wait for GO in bounded steps of at
  most 10 min, at most 2 h, and say how long you waited). Per build: loaded yes / no, construction value, % of the
  author, audit errors verbatim. Expected: 6 of 6 load, no `ascendancy points` or `legacy unique` error.
- D. Fast test files you touched: pytest summary line; the whole suite once at the end: summary line.
- E. Your own cost: wall time of your work, and the number of tool calls / turns if you can see them.

## Rules

- Your worktree reaches `var/`, `vendor/` and `artifacts/` through junctions: read them, write only under
  `artifacts/`, never delete anything there, never remove the worktree.
- PoB budget: at most 2 PoB processes of yours at once, never your benchmark next to your own pytest; one whole-suite
  run. Stop every background shell you start before your final report.
- Commit on your branch with the numbers in the message. Do not merge into main.
- Durations in every report and log line for a human: seconds under ~90 s, then minutes, then hours + minutes.
- Principles (CLAUDE.md): no gates, ledgers or waivers; a function returns or raises; no game content typed from
  memory -- read PoB's data.
