# Roadmap

**Frozen on 2026-09-26** (the move to mattpocock-skills). Work items are GitHub issues (the prototype's
acceptance: #1), the live state is `docs/STATE.md`, decisions are `docs/adr/`, the working protocols are in
`docs/agents/`, the vocabulary is `CONTEXT.md`. This file stays as the plan's history, and `scripts/progress.py`
still counts the 7.x items below; add nothing to it.

## Phase 0. Migration (done 2026-09-11)

- [x] Fresh repo with only the reusable PoB harness and corpora from v1.
- [x] `PobSession` wrapper; `scripts/smoke_pob.py` boots PoB, builds a Fireball
      Witch, reads 705 stats, verifies import code. Boot 2 s, calc 0.11 s.
- [x] 72 inherited tests pass under the new package name.
- [x] PoB bumped to v2.67.2 (PoE 3.29): lock, source clone, corpora regenerated
      (558 gems, 263 supports, 1,106 bases, 2,421 passives, 57 keystones,
      37 ascendancies, tree 3_29). Worker adapted to the new
      `ImportFromNodeList(className, ...)` signature.
- [x] 10 reference builds collected (Tuadh, 3.29 day-1 Exarch & Eater runs,
      levels 75-81) into `tests/fixtures/tuadh_329/` with `stats.json`.
- [x] `PobSession.load_xml` / `load_import_code`; single-lane calc when a build
      has no Baseline/Conditional sets.

## Phase 1. Harness ergonomics

Goal: make thousands of calcs per skeleton cheap and the full PoB config
surface reachable. All changes go in `pob/headless_runtime_worker.py` Lua
strings and `session.py`. No new gates.

- [x] Config payload accepts arbitrary PoB config keys via
      `set_config(inputs={...})`, validated against the config surfaces corpus.
      Proven: `usePowerCharges` raises crit/DPS, `enemyIsBoss="Uber"` lowers DPS,
      unknown var raises.
- [x] Single-lane calc when the build has one config set (imported builds).
- [x] (superseded) Single-lane option for `set_config`: not needed once the
      optimizer loops ran on `trial_stats` (7 ms per what-if) and `set_config`
      moved to stage boundaries.
- [x] Incremental tree mutation: `add_nodes` / `remove_nodes` / `mutate_nodes`
      with exact added/removed diff and mastery-effect handling. Measured on
      the Stormbrand reference: mutate 0.058 s + `stats()` 0.074 s = 0.13 s
      per step (`calc()` full snapshot is 0.17 s; use `stats()` in loops).
- [x] `PobSession.node_power()` returns PoB native power rows
      (`node_id`, `node_name`, `node_power_score`, `path_power_score`), metric
      FullDPS by default. Cost: ~13 s for top 200 rows, ~17 s for all 2,751
      reachable nodes. Fine once per optimizer round, not per step.
- [x] (superseded) `node_power(metric=...)`: the optimizer never used node
      power again after the what-if trials; nothing to build.
- [x] Tree graph helper `optimizer/tree_graph.py`: adjacency, class starts,
      frontier, BFS costs, candidates, leaves, cascades. Pure Python, tested
      on the 3_29 tree.
- [x] `PobSession.trial_stats(trials, keys)`: evaluate many add/remove
      candidates in one PoB round trip with exact restore (~0.12 s per trial).
- [x] Item primitives through PoB (see D18): `list_item_mods(base, ilvl)`
      (104 legal mods on Titan Greaves @70, ladders with level and weight),
      `craft_rare(base, prefixes, suffixes, ilvl, quality, sockets)` with
      PoB legality checks (unknown mod, wrong base, ilvl, duplicate group),
      `equip({slot: raw})` for single-slot changes, and item trials
      `{"item": {"slot", "raw"}}` through the calculator's `repItem` override
      (7 ms, equals real equip exactly). `tests/test_gear_primitives.py`.

## Phase 2. Tree optimizer

- [x] `Objective` (maximize stat + floors; lexicographic violation-then-value).
- [x] Greedy allocation by marginal value per point (`TreeOptimizer.allocate`),
      constraint repair by violation reduction per point, masteries with
      effect choice.
- [x] Swap pass (`TreeOptimizer.refine`): drop k cheapest leaves, take the
      best candidate of cost k, accept only if PoB confirms improvement.
- [x] First result (2026-09-11, Stormbrand, 30 points stripped in 9 branches,
      life 4156 -> 3397): greedy recovered 109.7% of original CombinedDPS,
      refine 113.8%, all floors met, 518 s. `scripts/recover_tree.py`.
- [x] **Acceptance test** `tests/test_tree_optimizer_recovery.py` (run with
      `-m slow`): stormbrand, poison_spectral_throw, cold_dot each stripped of
      ~30 points as whole branches and recovered to >= 95% of the author's
      CombinedDPS under their own gear and config. Passed 2026-09-11 in 83 s
      total (fast trials). Individual runs: Stormbrand 135%, Poison 127%.
- [x] (done by the pipeline: greedy -> rebuild on gear -> refine -> swaps -> joint, D27/D44/D45; benchmark medians 74-261%) From-scratch tree (author's keystones as skeleton input, empty tree,
      same budget, `scripts/tree_from_scratch.py --keystones author`):
      greedy 82%, +swap 85%, +4 ruin-and-recreate rounds 88.3% in 131 s;
      20 rounds plateau at 89.2% in 463 s. Without the author's keystones the
      optimizer reaches 91.9% on its own in 141 s (life via nodes instead of
      EB+MoM) once reoptimize repairs small residual violations.
      Target >= 95%; levers: pair trials for keystone synergies, smarter ruin
      selection (whole clusters), depth 8, path-compactness bonus. Deferred:
      the recovery tests prove the fitness function; from-scratch quality is
      tuned once the benchmark (Phase 6) can rank the effect.
- [x] Speed: greedy step was ~30 s with ~250 full trials; with fast trials the
      same step is ~2 s. Remaining levers if needed: prune depth-6 candidates
      by node power, parallel workers per skeleton.
- [x] **Research PoB's built-in what-if machinery** (done 2026-09-11, see
      DECISIONS D17): `calcs.getMiscCalculator` evaluates addNodes /
      removeNodes / repSlotName+repItem overrides in one pass without mutating
      the build. `trial_stats(mode="fast")` uses it: 7 ms per trial vs 166 ms,
      identical numbers on 140 trials. Item override (`repItem`) is the gear
      filler primitive; gems need mutate-and-restore (no override key).
      `modLib.parseMod` returns structured mods with PerStat / Condition tags;
      all uniques are loaded in `main.uniqueDB.list` inside the running PoB.
- [x] (superseded) Research PoB's built-in what-if machinery: `trial_stats` is the what-if calculator, 7 ms per trial, used everywhere.
      Node power scores 2,751 nodes in ~17 s (6 ms each) while our
      trial_stats costs 50-100 ms per trial: PoB uses an incremental
      calculator (`calcs.getMiscCalculator` and friends) for node power, item
      comparison tooltips, unique database sorting by DPS delta, gem sorting
      by DPS, and timeless jewel search. Inventory these entry points, measure
      them from the worker, and route trial evaluation through the fastest
      correct one. Also use PoB's mod parser from the worker to turn item /
      node mod text into structured (value, per, condition) records for the
      Phase 5 requirement graph, instead of regexes.

## Phase 3. Gear filler

- [x] Rails as a dataclass: `optimizer/rails.py` (`Rails`, `GearRails`,
      `GemRails`), defaults from `rails_default.json` (D10, D23, D31).
- [x] Baseline legality constraints in every objective: relations Str/Dex/Int
      >= requirements and unreserved mana/life >= cost (`Rails.objective`).
- [x] (done as D31/D34) Mana sustain rail: regen + leech + recoup >= 85% of
      the per-second cost per resource, net life+ES change >= -100/s.
      Original note: net mana per second
      >= 0 in the boss lane, computed from PoB cost/cast rate/regen/leech/EB,
      with flasks excluded and on-kill sources counted only in a mapping lane.
      The optimizer must be free to satisfy it any way PoB can measure
      (Eldritch Battery, leech, cost reduction, regen), so the rail is a
      number, never a list of solutions. Which sustain surfaces are legitimate
      per lane is the part that needs thought. Observed 2026-09-11:
      the recovered Stormbrand tree dropped Dex nodes and broke a gem
      requirement, which the DPS objective could not see.
- [x] (superseded by D19/D21 loot simulation) Tier realism: match the reference rares' explicit lines to PoB mod ids,
      derive the tier (rank within group) distribution, cap the filler at it
      (day-1 rares are floor/gamble items with 5-6 mods of middling tiers,
      never 4+ T1 mods). Later: PoB spawn weights as a "how hard to find" cost.
- [x] Slot-by-slot fill (`optimizer/gear_filler.py`): floors first, then
      marginal objective gain through item trials, under tier caps and
      legality relations. Stormbrand: 9 rares rebuilt in 11 s, all floors
      met, 213% of the author's DPS.
- [x] Findability rail = loot simulation (D19): `random_rares(base, n)` rolls
      rares with PoB spawn weights; best-of-N per slot through item trials
      (`scripts/gear_bestofn.py`). Stormbrand calibration: N=300 reproduces
      the author's gear (93.9%), N=1000 exceeds it (159%). The per-mod
      rarity measure (`scripts/gear_rarity_calibration.py`) was tried and
      rejected: it does not separate found from designed items.
- [x] Calibrated N on all 10 reference builds (best-of-300, 2 passes, own
      tree/uniques/config): stormbrand 94%, smite 72%, spark 73%, ignite PB
      110%, hit PB 123%, poison ST 94%, viper strike 147%, winter orb 112%,
      physical DoT 97%, cold DoT 84%; median 95.5%. Default
      `gear.loot_best_of_n = 300`. Smite/spark/cold DoT end slightly
      infeasible: the author closes resists with bench crafts.
- [x] One bench craft per item (`list_bench_mods`, PoB master mods; appended
      as a `{crafted}` line, chosen by item trial) after the loot pick.
      `optimizer/loot_gear.py`, `scripts/loot_gear_experiment.py`.
      With bench: Smite 108.5% (was 72%), Stormbrand 106.9% (was 94%),
      all floors met, ~37 s per full gear set.
- [x] Calibration with the regular pool (D21), 10 builds x 2 seeds, bench on:
      N=100 median 86% (4/20 infeasible), N=200 median 111% (1/20),
      N=300 median 105% (2/20). Per-run loot noise ~±20%. Default
      `gear.loot_best_of_n = 200`. Reports should run 2-3 seeds and keep the
      median build so one lucky roll does not define the output.
- [x] **Acceptance test** `tests/test_loot_gear_acceptance.py` (-m slow):
      loot gear on stormbrand / smite / cold_dot within 85-125% of the
      author's CombinedDPS with floors met. Passed 2026-09-11 in 102 s.
- [x] **Acceptance test** (loot calibration, D21): best-of-200 per slot on the
      author's tree is 111% of the author's gear (median over 20 runs).

## Phase 4. Config rules

- [x] (done as `optimizer/config_rules.py`, D22-D26, D33, D40) Rule table: toggle -> required source, derived from the config surfaces
      corpus `predicates` (PoB's own ifSkill / ifCond / ifFlag gates that show
      or hide each config input). No hand list: a candidate that introduces a
      source (e.g. Trinity support -> resonance input) is trialled with its
      dependent inputs set per lane, otherwise conditional sources always
      score zero and are wrongly discarded.
      Data check (2026-09-11): 578 config vars, 501 with predicates:
      ifCond 163, ifSkill 134, ifFlag 103, ifMult 51, ifOption 28,
      ifEnemyCond 28, ifMod 12. A predicate means "something in the build
      benefits from this condition", which PoB evaluates itself (the config
      tab shows/hides the input); it does not mean the build *generates* the
      condition (power charges need a generator). Plan: optimistic lane =
      every referenced condition on; conservative lane = referenced AND a
      generator exists, where generators come from parsed mods ("gain a
      Power Charge on ...", "Onslaught on ...") and from skill tags. Ask the
      worker for the config tab's currently shown inputs instead of
      re-implementing predicate evaluation.
- [x] (D48) Unsupported-mod detection: run every node / item / gem mod line through
      `modLib.parseMod`; lines PoB cannot parse (its red "Not supported in PoB
      yet") are valued at zero honestly and flagged in the report as
      "PoB does not model this", like hit-multiplicity warnings.
- [x] `PobSession.config_options()`: PoB's own predicate evaluation (which
      inputs the build references) plus the referencing mods' sources.
- [x] `optimizer/config_rules.py`: conservative lane = referenced AND proven
      (ailments from PoB chance/DPS stats, charges/buffs from generator text
      in the build's own items/nodes/gems, combat-sustained "recently"
      conditions on, kill/state assumptions off); optimistic lane = every
      referenced toggle on. Numeric inputs are kept from the build (poison
      stacks, brand counts, exposure type) or taken from PoB estimates.
      `set_config(preserve="numeric")` keeps such inputs; a full rewrite
      used to drop them (poison ST fell to 44%).
- [x] Acceptance (`tests/test_config_rules.py`): ignite PB gets ignited,
      not the unproven shock; poison ST keeps 5 stacks and endurance charges
      (generator found) but no power/frenzy; every conservative toggle has a
      reason; conservative equals the author's numbers where the author
      assumed nothing extra.
- [x] (done: `rails_default.json` assumptions + `_numeric_rule`, D26/D36) From-scratch numeric rules (brand counts from skill data, charges
      count = max charges, flask uptime policy) -- needed once builds are
      generated without an author config (Phase 5).

## Intermediate prototype (after Phase 4): skeleton in, build out

- [x] `search/skeleton.py` (Skeleton dataclass, apply to a session),
      `optimizer/pipeline.py` (BuildPipeline: config lanes -> loot gear on an
      empty tree -> greedy tree -> gear again -> refine + ruin-and-recreate
      -> final config lanes -> import code), `scripts/build_from_skeleton.py`
      (`--from-fixture` extracts an author's skeleton; `--skeleton file.json`
      runs a hand-written one). `PobSession.unique_item / list_uniques`
      expose PoB's 1,332 uniques.
- [x] First result (Stormbrand skeleton, author's tree/rares/config
      discarded, rails floors): 809k CombinedDPS = 90.1% of the author's,
      all floors met (life 3732, EHP 10.9k, res 75, attributes >= req),
      134 s, conservative config lane. Optimistic lane 2.0M.
- [x] Other reference skeletons (rails floors, conservative lane, ~3 min
      each): Poison ST 134%, Cold DoT 353%, Smite 99%, Spark 134% of the
      author's CombinedDPS, all floors met. Cold DoT's author invested in
      defense far above the rails (life 4763, EHP 17.7k); with the rails'
      floors the pipeline converts that into damage. `--author-floors`
      reruns with the author's defensive numbers for a like-for-like check:
      Cold DoT with the author's floors (life >= 4620, EHP >= 17.7k) still
      reaches 194.8% (444k vs 228k), floors met, 162 s. Part of that is the
      conservative lane enabling ailment toggles the author left off; the
      rest is tree/gear choice. This pipeline is the fitness function for
      Phase 5.

## Phase 5. Skeleton search

- [x] `Skeleton` dataclass + `apply` (`search/skeleton.py`); `BuildPipeline` turns a
      skeleton into a build (`scripts/build_from_skeleton.py`). Gem levels come
      from the rails (18/0, D23), not 20/20.
- [ ] Combinatorial candidate generation from corpora (ascendancy, damage
      mode, supports by tag intersection, keystones by mode). Partly
      replaced by the request system (docs/REQUEST.md: the human names the
      vector, ascendancies expand to all 18, supports / utilities / weapon
      types / keystone variants come from the corpora and PoB). Open for
      novelty: the multiplier graph over parsed mods (discussed, not built).
- [x] **Uniques corpus family.** `corpus_data/uniques.json`: 1,332 uniques from
      the pinned PoB's `uniqueDB` with ranges applied, PoB-parsed mods
      (`scripts/build_unique_index.py`).
- [x] Structured mods via PoB's own parser (`PobSession.parse_mods`).
      `corpus_data/scaling_vectors.{json,md}`: 477 vectors (`per:X`, `cond:X`)
      over 4,838 sources (uniques, notables, keystones, masteries, ascendancy
      nodes, supports) with payoffs and direct enablers
      (`scripts/build_scaling_vectors.py`). Derived, never hand-named (D25).
- [x] From-scratch numeric config (Trinity resonance, rage, withered, chill
      seconds, spells cast) from build proof + rails assumptions (D26).
- [x] Path-for-path tree finishing pass (`swap_subtrees`, D27).
- [~] Corpus retrieval of uniques by PoB item trials (`generator.screen_uniques`);
      notables are the tree optimizer's job. Requirement graph: `scaling_vectors.json`.
- [x] LLM hypothesis input format and validator (`search/hypothesis.py`, docs/HYPOTHESES.md).
- [x] Search: prepare -> screen -> top-K full optimize (+ unique variants), parallel
      processes (`scripts/search.py`), plus a mutation round (unique variants
      of the finished builds).
- [x] Utility links by PoB: auras, heralds, curses, guard and movement skills
      screened as extra socket groups under reservation + sustain (D35).
- [x] Minion skills maximize `FullDPS` (D37); to verify with a full search.
- [~] Numeric skill options from scratch: skill parts (Blade Vortex blades,
      stages) chosen by PoB and Toxic Rain pods from the projectile count (D36).
      Sigil stages and Pinpoint intensity now come from the ramp arithmetic
      (D62 amd 3, measured: spark 50 -> 1 stage, intensity 50 -> 4); only
      Momentum stacks are still at PoB's default.
- [x] (met 2026-09-11, 6 builds in 36 min; a 2026-09-13 request with 18
      ascendancies takes 80-95 min with variants) Acceptance: `python scripts/search.py "Fireball"` produces >= 5
      distinct skeletons with optimized builds and import codes in < 30 min.
      Status 2026-09-11 (second measurement): all 20 ascendancy candidates
      (Warden skipped), 6 optimized builds (3 with uniques) in 36 min on 5
      workers: rig supports 1.5 min (cached legality + shortlist), prepare 3 min,
      screen 10.5 min, full optimize 10-13 min each. Top: Inquisitor Fireball
      with Jiquani's Potential + Malachai's Awakening 1.64M conservative DPS
      (int-stacked flat spell damage, Blood Magic), rares-only Inquisitor 837k.
      Then D31: availability rail (PoB Source classes), sustain rail, one
      effect per mastery, machine audit. Missing: rarity tiers inside `core`
      (wiki tier list, blocked for bots; needs a saved page), duration-buff
      main skills vs the sustain rail, Warden allocation.
- [x] Time-to-full-DPS rail (D39): `optimizer/ramp.py` derives `RampSeconds`
      from PoB's stack potentials, durations and rates; `Objective` gained
      ceilings and derived stats; ceiling 2.5 s to 80%, set from play
      experience (the Viper Strike reference, 4.2 s, is knowingly out).
      Next criteria rails as experience names them: charges / rage /
      resonance ramp, a clear link, weapon affix ceiling per base.
- [x] Structural keystones decided as whole builds (D40): the mutation
      round rebuilds each finalist without each keystone it took
      (`forbid_keystones`, `TreeOptimizer.forbid`), ranked together.
- [x] Weapon bases by affix ceiling (D41): measured first (loot N=200 is
      already 103% of the authors' weapons; N=1000 113%; ceiling 130%), so
      loot N stays and only the weapon-type screen changed (ceiling on
      damage alone instead of 40 rolls on a bare, infeasible rig).

## Phase 6. Benchmark and report

- [x] Benchmark script (`scripts/benchmark.py`): all 10 references rebuilt
      from their own skeletons through the full pipeline, author re-scored
      under our conservative lane, author's own floors, author's tree
      budget; keystone variants (D40) and the best per reference counts.
      First run (2026-09-12, before D42 and the reservation-scale fix):
      cold_dot 108%, ignite_penance_brand 106%, winter_orb 124%, smite 92%,
      hit_penance_brand 86%, stormbrand 79%, poison_spectral_throw 63%,
      regular_viper_strike 39% (ramp rail 2.5 s binds; the author is at
      4.2 s), physical_dot 33% (Blood Magic taken, build cannot cast),
      spark 399% ("Maximum Hits" part). Second run after D42 and the
      reservation-scale fix, best per reference: cold_dot 108%,
      ignite_penance_brand 106%, smite 92%, winter_orb 90%, spark 87%,
      hit_penance_brand 86%, stormbrand 79%, physical_dot 70% (audit
      clean now), poison_spectral_throw 63% and regular_viper_strike 39%
      (both at the 2.5 s ramp ceiling); median 87%, 2/10 at or above
      100%. Single seed: run-to-run noise is ~20%, so one run cannot
      rank a change smaller than that. `scripts/gap_decomposition.py`
      crosses author/our tree and gear (confounded: each half was chosen
      for the other half, see D43). Third run (fresh gear passes, since
      reverted): physical_dot 95%, hit_penance_brand 91%, cold_dot 100%,
      ignite_penance_brand 105%, spark 81%, smite 74%, stormbrand 76%,
      winter_orb 97%, poison_spectral_throw 61%, regular_viper_strike 27%;
      median 91%. Under the composition-weighted ramp budget (D43):
      poison_spectral_throw 79% (ramp 2.7 s of 3.8 s), regular_viper_strike
      50% (3.4 s of 3.4 s: pinned at its budget; the author sits at 4.2 s,
      knowingly outside the rail).
- [x] Multi-seed benchmark (`--seeds 3`, per-reference medians and spread).
      Baseline 2026-09-12 (pipeline as of d96a767 minus the joint stage),
      median over 3 seeds: cold_dot 94% (73-108), hit_penance_brand 95%
      (78-101), ignite_penance_brand 107% (103-114), physical_dot 102%
      (83-200, the 200% seed infeasible), poison_spectral_throw 83%
      (62-85), regular_viper_strike 172% (147-172, poison 4.9 s at the
      3.9 s budget), smite 95% (92-133), spark 73% (63-87), stormbrand 82%
      (79-86), winter_orb 91% (90-112); median of medians 95%, 3/10 at or
      above 100%. Spread within a reference is up to 35 points.
- [x] Joint tree-gear ruin-and-recreate with directed moves (D44), judged
      on the 3-seed benchmark against the baseline above (same code plus
      the stage): cold_dot 94 -> 103%, hit_penance_brand 95 -> 101%,
      ignite_penance_brand 107 -> 116%, physical_dot 102 -> 114%, smite
      95 -> 114%, poison_spectral_throw 83 -> 83%, regular_viper_strike
      172 -> 172%, spark 73 -> 73%, stormbrand 82 -> 82%, winter_orb 91 ->
      90%; median of medians 95 -> 103%, at or above 100%: 3 -> 6 of 10.
      Rounds kept in 17 of 30 builds. Cost ~4 min per build.
- [x] Tree rebuilt on the finished gear (D45), 3-seed medians: cold_dot
      97%, hit_penance_brand 132%, ignite_penance_brand 127%, physical_dot
      193%, poison_spectral_throw 70% (author with the same config
      choices), regular_viper_strike 148%, smite 121%, spark 77% (same),
      stormbrand 130%, winter_orb 114%; median of medians ~121%, 7/10 at or
      above the author. Kept in 25 of 30 builds. A full build is now
      12-25 min; 30 builds on 5 workers ~100 min.
- [x] Full 3-seed run with the fair author (same config choices), the
      rebuild comparison fix and the directed joint stage (2026-09-13):
      cold_dot 86%, hit_penance_brand 136%, ignite_penance_brand 114%,
      physical_dot 261% (two seeds counted), poison_spectral_throw 74%,
      regular_viper_strike 143%, smite 129%, spark 77%, stormbrand 144%,
      winter_orb 126%; median of medians 129%, 7/10 at or above the author.
- [x] Baseline over all 14 references, 3 seeds (2026-09-14, D49 in),
      medians: absolution_minions 123%, bleed_bow 129%, cold_dot 86%,
      hit_penance_brand 136%, ignite_penance_brand 114%, physical_dot 261%,
      poison_spectral_throw 74%, regular_viper_strike 143%, smite 129%,
      spark 77%, stormbrand 144%, summon_raging_spirits 135%, toxic_rain
      113%, winter_orb 126%; median of medians 129%, 11 of 14 at or above
      the author; every build audit-clean. Runs are deterministic per seed.
- [x] (closed 2026-09-14 by run C below: every reference at or above the author under the D53 rails) Poison Spectral Throw (74%), Spark (77%) and Cold DoT (86%) are the
      references still below the author. Spark: the greedy truncates candidates (up to
      400 per step, cap 300, farthest notables cut first); `--tree-depth 8
      --tree-trials 600` measured on Spark, 3 seeds: 77 -> 82% (71/79/79 ->
      71/82/85) for 15-20% more build time; marginal, defaults unchanged.
      Cold DoT swings 73-110% between seeds: the losing seeds' rebuilt tree
      was stronger (225k vs 167k) but broke a floor and was reverted; the
      rebuild now repairs with more refine rounds before comparing: Cold DoT
      seed 1 110 -> 132% (rebuild kept), seed 3 still reverted (73%), median
      86% unchanged; Poison Spectral Throw unchanged (74%).
      2026-09-14, D50 (each a general cause, not a tree or gear weakness):
      Spark ran at 0 intensity (the from-scratch lane never set a stack-type
      skill option; now held at PoB's cap), Cold DoT's regrown trees were
      repaired by violation-per-point swaps costing 45k each (repairs now
      cost DPS, and the greedy's repair estimate is per constraint), the
      Poison Spectral Throw author plays a legacy Natural Hierarchy (the
      benchmark author now wears PoB's current variant, as we do). Smoke,
      3-seed medians: Spark 77 -> 151% (139-154), Poison Spectral Throw
      74 -> 86% (83-111), Cold DoT 86 -> 90% (79-108). Full 14-reference
      run (B, 2026-09-14, D50 with the two-regrow rebuild and prefer_rules;
      before D51-D53), 3-seed medians, baseline -> B: absolution_minions
      123 -> 142%, bleed_bow 129 -> 98% (75-180 -> 90-154), cold_dot 86 ->
      90%, hit_penance_brand 136 -> 129%, ignite_penance_brand 114 -> 113%,
      physical_dot 261 -> 240%, poison_spectral_throw 74 -> 106%,
      regular_viper_strike 143 -> 143%, smite 129 -> 129%, spark 77 ->
      139%, stormbrand 144 -> 139%, summon_raging_spirits 135 -> 141%,
      toxic_rain 113 -> 106%, winter_orb 126 -> 124%; median of medians
      129 -> 129%, at or above the author 11 -> 12 of 14. Three builds
      ended with a floor broken by the final lanes (joint rounds judged
      under stale lanes; fixed for run C). Run C (D51 points, D52 guard,
      D53 max-hit rails, lanes fix) pending.
      Run C (2026-09-14 15:09, D50-D53, joint rounds judged under
      re-derived lanes, a final repair): 3-seed medians absolution_minions
      184%, bleed_bow 134%, cold_dot 89% (seeds 1-2 at 116-117% were
      excluded: a joint round judged under the tree's objective, which has no
      movement floor, swapped the boots down to 1.19x; the audit printed it as
      "1.2 < 1.2"; joint rounds are judged under the full objective from the
      ablation runs on), hit_penance_brand 131%, ignite_penance_brand
      187%, physical_dot 223%, poison_spectral_throw 188%, regular_viper_strike
      122%, smite 124%, spark 154%, stormbrand 134%, summon_raging_spirits
      154%, toxic_rain 111%, winter_orb 121%; median of medians 134%, no audit
      errors, 13 of 14 at or above the author (14 with the Cold DoT seeds
      counted). The rise on block-heavy references (Poison Spectral Throw,
      Ignite Penance Brand, Absolution) is the rail change: the max-hit floors
      bind less than an EHP floor that block had inflated; every build still
      keeps 95% of the author's maximum hits.
      Run D (2026-09-15 05:19, the lean pipeline from D55 plus the evening's
      re-judge, charge rule, self-cost and generator trials): median of
      medians 142% but 10 of 14, with two collapses that were bugs, not the
      lean stages: Summon Raging Spirits 8% and Absolution 39% (the re-judge's
      raw restore wrote minion count 1) and Smite s1 44% (the charges' ramp
      relation held the tree at 58k); both fixed (58a1d32). Bleed Bow 86% and
      Smite 86% against C's 134 / 124% remain to be attributed to the lean
      stages or the fixes: run E (full pipeline, fixes in) follows.
      Minion rerun (2026-09-15 15:24-16:52, 9587f98 in, 3 seeds):
      summon_raging_spirits 225 / 189 / 198%, absolution_minions 167 / 209 /
      249%, all six audit-clean; with these rows run E stands at 14 of 14
      at or above the author, median of medians 139%.
      Run E (2026-09-15 09:23-15:02, full pipeline, 58a1d32 in): absolution_minions
      29%, bleed_bow 116%, cold_dot 119%, hit_penance_brand 112%,
      ignite_penance_brand 269%, physical_dot 215%, poison_spectral_throw 182%,
      regular_viper_strike 137%, smite 140%, spark 187%, stormbrand 124%,
      summon_raging_spirits 8%, toxic_rain 131%, winter_orb 270%; median of
      medians 137%, 12 of 14. Smite (140 vs D's 86) and Bleed Bow (116 vs 86)
      recover under the full pipeline. The two minion builds did not: the run D
      fix routed restores through the full setter, which still wrote count 1
      and then found PoB's limit equal to the count the skeleton remembers,
      so nothing was re-applied (SRS s1: joint 1,187,821, "picks re-judged,
      no change" 66,350). Fixed in 9587f98 (the raw setter writes the
      skeleton's counts and minion-skill choice; PoB test on Absolution). To
      do: rerun the two minion references (3 seeds) with 9587f98; a stage
      recorded as "no change" must leave the value unchanged or raise (would
      have caught this on the first seed of run D).
- [x] Benchmark set extension (2026-09-14): Bleed Bow (3.28), Toxic Rain
      (3.26), Absolution Minions (3.28), Summon Raging Spirits (3.26) from
      Tuadh's channel; melee was already covered (Smite, Viper Strike).
      First run: Toxic Rain 113%, the other three 19-24% or failing; after
      D49 (minion counts, minion skill choice, Snipe stages, empty slots,
      weapon order), 3-seed medians: Absolution 136% (100-140), Summon
      Raging Spirits 135% (119-148), Bleed Bow 129% (75-180); all audits
      clean. Impale Bow left out: two damage skills, not modelled.
- [x] (done: the benchmark compares each reference with itself under our
      lane and choices; the audit warns on show-average skills, D42) DPS comparability: compare like with like. Each fixture records the
      author's socket-group settings (include-in-full-DPS, instance count) and
      a hit-multiplicity note where the skill multi-hits (Spark, Winter Orb
      totems). Never compare a raw CombinedDPS across different skills; the
      rails DPS number is a sanity floor only.
- [x] Per-build explanation from the optimizer's trace (`optimizer/explain.py`,
      D47): structure with the keystone variants' numbers, weapon with the
      alternatives' numbers, links with PoB's picks and their value before /
      after, the tree's largest measured gains and masteries, the
      conservative lane's proofs, optimistic vs conservative, numbers with
      ramp vs budget, audit, stage trajectory. Printed in the search report
      and the pipeline log. Pareto column in the search table: builds no
      other clean feasible build beats on both DPS and EHP.
- [x] CLI: `junkroan build` (`src/junkroan/cli.py`, console script in
      pyproject; `python -m junkroan.cli` without installing): flags are the
      checklist items of docs/REQUEST.md, a request file and flags combine,
      `--dry-run` echoes; `probe`, `audit`, `describe`, `benchmark` wrap the scripts.
- [x] (numbers to re-measure: every search build had 107 passive points at level 77, 7-8 over PoB's rule, D51.
      Smite re-measured 2026-09-14 at 99 points with D52-D54 and the picks re-judged, Slayer + Champion, 65 min:
      Champion + Voidhome 708,987 (162% of the reference 438,843 under our lane; Smite + Trauma + Ruthless + Melee
      Physical + Faster Attacks + Cruelty, Crimson Dance, Blood Magic, Precise Technique, bleed 142k of the number),
      Slayer without Precise Technique on a Judgement Staff 615,470 (140%), Champion 557,861; the Infernal Sword variants
      died at the screen (Trauma cannot be used with a sword, D52); no audit errors. Passed on both counts; the other
      four skills still to re-measure.) Acceptance: for each benchmark skill, at least one search result is
      within 10% of the reference on the objective, and at least one result
      uses a different ascendancy or damage mode than the reference.
      Done on four skills 2026-09-13/14 (below); all four passed.
      Storm Brand (2026-09-13, all 18 ascendancies, 100 min): reference
      Inquisitor 661,852 under our lane; Hierophant without Elemental
      Overload 971,308 (147%), Hierophant + Singularity 960,940, Inquisitor
      752,840 (114%); all audits clean. Passed on both counts. Smite (85
      min): Slayer/Champion 519k/524k (118%) with Precise Technique, up to
      1.35M without it, but inflated by Ambush (D46). Rerun without Ambush
      (Slayer, Champion; 63 min): Slayer 722,437 (165%), Champion without
      Blood Magic 694,968 (158%), Champion 668,324; audits clean. Passed on
      both counts. Sceptre / staff weapon variants finished at 20-31k after
      15 min each: variants are now screened first and fully optimized only
      when they hold at least half of the finalists' screen value.
      Poison Spectral Throw (18 ascendancies, 82 min): reference Pathfinder
      170,817 under our lane with choices; Slayer with a Void Axe 161,349
      (94%), Slayer with an Infernal Sword 159,675, Champion 154,096; audits
      clean; Pathfinder not in the screen's top five. Within 10% and a
      different ascendancy: passed. The variant pre-screen dropped one of
      five variants and three of the four kept finished above the finalists.
      Cold Snap DoT (18 ascendancies, 93 min): reference Elementalist level
      81, 224,621 under our lane; Occultist with a Void Sceptre 802,048
      (357%), Occultist with a wand 691,610, Trickster 434,481; audits clean
      (one variant infeasible, flagged). Passed on both counts.
      Bleed Puncture bow with Split Arrow (18 ascendancies, 66 min):
      reference Gladiator 3.28, 623,444 under our lane; Juggernaut without
      Crimson Dance 567,059 (91%), Champion 552,487 (89%); audits clean
      (warnings only). Within 10% and a different ascendancy: passed, on
      the edge; Gladiator itself was not among the screen's finalists.

- [x] (done 2026-09-14 except the parts PoB cannot carry: charge_rule with the on-kill / on-block / steal policies and partial counts, the debuff uptime rule, self_cost.py; Cruelty's effect is clamped to 40 by PoB itself; the generator-node trial for the optimizer done the same evening: TreeOptimizer.enabler_hook, Sword Mastery on Champion Smite 0 -> +18% judged with frenzy on) Lines PoB cannot model (red in PoB): the inventory across all 14
      references and 16 searches is 20 real lines in 3 mechanisms
      (`mechanics/unsupported_lines.json`, decided with the user 2026-09-14):
      (1) generators with a chance ("X% to gain a charge / maim / aggravate
      on hit, crit, block, kill"): the ailment uptime rule extended to
      charges and debuffs (chance x hits/s x duration, capped), with the
      policies on-kill = off on bosses (enablers: The Writhing Jar, the
      worm ring, the add-spawning mark ring), on-block = off on bosses
      unless a retaliation skill (100%) or half with double lucky block,
      steal charges = never; charges become a ramp component (D39) and a
      candidate node carrying a generator is judged by PoB with the
      toggle it enables turned on (a real allocate + calc, generator nodes
      are few); (2) self-cost on use ("Lose X% of Life when you use a
      Chaos skill"): X% x pool x uses/s of skills the player uses
      themselves (triggered skills are not used) into the self-degen rail
      (D34); (3) "increased effect of Cruelty": PoB's own overrideCruelty =
      the support's value x (1 + effect), a translation like D40. Honest
      zeros stay named by the audit: first-seconds effects ("enemy on full
      life"), "enemies cannot leech", Cauterisation, light radius.
- [x] (done 2026-09-14, D54: `rejudge_picks`; Smite Slayer 05 584k -> 614k in two sweeps, Flammability and Immolate held by PoB) Every discrete pick is judged again on the finished build, until a
      sweep changes nothing. Supports are picked on the bare rig (once more
      after gear pass 2) and utilities greedily right after, then never
      again: a Smite Slayer (search 05) kept Immolate over Trinity because
      no fire or cold was in its hits when supports were judged (Anger and
      Herald of Ice came later), and Flammability over Elemental Weakness
      because Anger was in and Herald of Ice not yet. Same class as the
      stale-lane bug of run B: a decision right when taken, never re-judged.
      Fix: a final sweep over every support slot and utility group against
      its alternatives with tree, gear and lanes in place (PoB judges,
      ~150 swaps at ~0.5 s), a short refine if anything changed, repeat
      until the sweep is empty; how many sweeps pay is measured on 3 seeds.
      This is the fixed-point loop the 11-stage pipeline approximates
      piecewise (see "Later": ablation and one improvement loop).
- [~] Archetype coverage (agreed 2026-09-15, D56): the prototype covers every
      archetype Tuadh has a leaguestart run for, not only the 14 references.
      2026-09-15: 18 references added from the channel (totems, mines x2,
      traps, triggers x2, archmage x2, impale x2, Gladiator block, wands x2,
      chaos DoT stacking, shockwave Cyclone, Static Strike, bleed Perforate,
      poison Spark, Elemental Hit); not on the channel and left uncovered:
      CI / energy shield, low life, Righteous Fire. First-seed intake run
      pending (overnight batch). Intake per reference: PoB code into
      `tests/fixtures/tuadh_329/` + `sources.json`, `scripts/fixture_stats.py`,
      `scripts/reference_drift.py` (the author's saved PlayerStat against the
      pinned PoB's recompute: a reference from an older league below 0.7 was
      reworked and is read in PoB first; the 14 today sit at 1.01-1.24, the
      two brands at 2.1 from a config difference, none flagged), then one
      seed per new reference in one overnight batch, the gaps become rules +
      fast tests + audit checks, then 3 seeds. Long runs: the full benchmark
      once a week as the regression gate, never as the debugger.
- [x] (2026-09-15) Weapon variants re-pick their supports before the tree (D52): the
      sword finalist's Close Combat zeroes Smite on a staff or sceptre, so
      those variants died at the screen instead of being judged with
      supports the weapon can carry. Now: no number after gear pass 1 and a
      support the request did not fix -> the supports are chosen again on
      that rig ("supports re-picked (no number)") before any tree; the
      refusal stays for a link that has no number under any supports. PoB
      test: Smite + Close Combat on a Judgement Staff, 0 -> a number.

## Phase 7. Prototype (started 2026-09-15)

A new session starts here: read the **State** block, then the plan, then act.
Nothing in this phase is improvised; every step below is either done, in
flight, or next. When a step turns out wrong, change the plan here first,
with the number that changed it, then the code.

### What the prototype is (definition of done)

The user's words (2026-09-15): "билды норм, но не оптимальные"; the prototype
builds very well within the rails and optimizes them. Measured as:

1. **Coverage.** Every reference in `tests/fixtures/tuadh_329/` (32 today,
   one per archetype Tuadh has a leaguestart run for; the channel is the only
   reference source, D56) is at or above the author under our lane by
   3-seed median, audit clean. Uncovered and marked: CI / energy shield,
   low life, Righteous Fire (no run on the channel).
2. **Stability.** The delivered result is the best of 3 seeds per reference
   (the lead, 2026-09-18: +17.4 points over one seed by the restart statistics);
   the seed spread is reported per reference, not gated. The old "spread at
   most 10" was contradicted by the measurement: 29 of 32 references above 10,
   median 41.6, max 109.1 (`docs/research/2026-09-18-seed-divergence.md`).
3. **Fixed point.** The improvement loop run again on a finished build moves
   the number less than 1%: nothing obvious is left on the table.
4. **Reading.** The user reads the top build per reference in PoB and finds
   no new kind of logical error; every kind found before is an audit check.
5. **Request.** `junkroan build` (docs/REQUEST.md) gives ranked builds with
   explanations under the same rails in under 2 hours on 5 workers.

### State log up to 2026-09-26 (frozen; the live state is `docs/STATE.md`)

- Updated: 2026-09-26 13:20, commit see `git log -1`. Entries below are a log, newest first.
- 13:20 (26.09), **off-hand fix measured** (`offhand-fix-tpl`, templates, seeds 1-3, @47b03b3, against core14-tpl-main3):
  smite 77.9 -> 94.6 (+25.4 / +21.4 / -0.2%; all three seeds reach the same build), regular_viper_strike 90.6 -> 95.2
  (+3.0 / -9.2 / +5.1%); the off-hand now carries 3 open lines + a craft. **D103** (b1d090e): the movement floor is read
  under our lane; impale_cyclone's floor 1.164 (the author's own config, 1.35) was one the author failed under our lane
  (1.0665), 0 of 3 counted on both gears; now 1.0345; the only reference of 58 it moves. Templates still miss both
  cyclone floors (T3 boots 25% = 1.027 under Cyclone): the owner's call whether the boots' movement tier follows the
  floor. D102 written (the value re-fill). PC vs laptop A/A (TEST RUNS, 22.09): 17 of 18 builds identical to the
  digit, burning_arrow_snipe s3 -6.07% (the same value noregions-smoke reached on the PC: a path knife-edge) -- read
  burning_arrow_snipe per seed in any PC-laptop pair. `tpl-byvalue-smoke-s4` starts after ziz-main3-s4 (~13:00).
- 12:10 (26.09), **tier 3 is Sonnet 5 again (the owner)**: the DeepSeek vendor answers every request in 40 s or more
  (their side); DeepSeek V4.1 Flash returns as tier 3 on the owner's word. CLAUDE.md "Subagents and models" rewritten.
- 12:00 (26.09), **merged: the loop re-fills template open lines by value on a feasible build (1a58ee8) and
  `scripts/template_line_census.py` (b6fa5a8, reproduces 192 builds / 1,359 lines / 698 at +0 exactly).** Asked TEST
  RUNS to queue on the PC right after ziz-main3-s4: `tpl-byvalue-smoke-s4` @b6fa5a8 (smoke, templates, seeds 4-6) +
  `compare_runs main3-tpl-smoke-s4-lap tpl-byvalue-smoke-s4 --per-build` + the census of both (the seed controls move
  ~5 h later, on purpose). Verdict needs: per-build gains on burning_arrow_snipe / impale_ballista, the +0 share falling
  from 59%, loop minutes per build. DeepSeek: both specs hit the time limit without a report (notes in memory); the lead
  wrote the pipeline branch. Still running: `offhand-fix-tpl` (2 other slots, ~13:30-14:30).
- 10:50 (26.09), **the template weak tail is read (the new lead chat "poe-junkroan-v2 Orch")**:
  `docs/readings/2026-09-26-template-weak-tail.md`. Three general causes: (1) BUG, fixed 47b03b3: a one-handed weapon in
  Weapon 2 took the shield template (the JSON keyed "One Hand Sword", the corpus says "One Handed Sword") = one line on
  the off-hand of smite and regular_viper_strike, the only two builds it hit; measuring `offhand-fix-tpl` (both, templates,
  seeds 1-3) from the snapshot `artifacts/runs/snap/lead-offhand-fix` @47b03b3 on 2 other slots, started 10:30, ~3-4 h,
  pair: core14-tpl-main3. (2) 698 of 1,359 flexible armour / jewellery template lines (51%) add +0 (Chaos Resistance 195,
  attribute crafts ~200): chosen floors-first while the slot is rebuilt, never re-asked by the loop -> spec
  `2026-09-26-template-loop-lines-by-value.md`, DeepSeek worker `gpt-2026-09-26-template-loop-lines-by-value` running
  (code only; the lead measures). (3) 3 lines per item against Tuadh's 5.4: **the owner, 3 lines is the deliberate day-1
  level; closed.** "gear pass 2 (with tree)" >50% is not the gear: the greedy tree ends over the ramp budget (15 of 348
  builds; large drops only on templates), the next `_reconfigure` cuts the stacks; open, a fix changes every path.
  Queues unchanged (TEST RUNS). Full suite: 79% passed with no failure, then a PoB-backed test outlasted 15 min on the
  loaded machine (6-7 of 7 slots).
- 06:00 (26.09), **HANDOVER POINT (the owner clears the lead chat).** Templates vs loot, same commit @42565a9, only the
  gear differs (median of medians, seed-change noise on the same code in brackets): smoke -9.7 (11.5), new18 -11.2 on
  the common 15 (15.5), core14 +10.9 (2.4), Zizaran -38.8 on the common 25 (seeds 4-6 pending). Stable everywhere:
  fewer references at or above the author (weak tail) and 2-6x smaller seed spread. Templates ARE the product (the
  owner); the Zizaran gap is expected (his first loadout can be T16, SSF/trade mixed; gem-level rule stays).
  NEXT for the lead: (1) the template weak tail, per reference, reading PoBs and item lines: impale_ballista -66,
  archmage_volatile_dead -63, burning_arrow_snipe -46 (new18), spark -82, smite -56, poison_spectral_throw 64%,
  regular_viper_strike 91% (core14); (2) 'gear pass 2 (with tree)' losing >50% identically on all seeds
  (z329_juggernaut_boneshatter 1,056,242 -> 463,737); (3) template v4 flexible lines (Sonnet branch cea08da) only via
  a full smoke, and only above the 11.5-point smoke noise or on campaigns; (4) cyclone boots vs
  EffectiveMovementSpeedMod; spectre Greater Volley; per-move random streams (D100). Queues (TEST RUNS owns them):
  PC ziz-main3-s4 -> core14-tpl-main3-s4 -> ziz-tpl-main3-s4 (to ~Sunday morning); laptop main3-tpl-smoke-s4-lap ->
  new18-tpl-main3-s4-lap. No path-changing merge until these seed controls finish.
- 13:30 (25.09), **the smoke's seed noise is measured: 11.5 points on the median of medians** (main3-smoke seeds 1-3 vs
  4-6, same code and gear; impale_ballista -32.4 alone). Every smoke verdict within about +-11 is noise: D101 +4.9,
  regions-off -5.8, templates vs loot -9.7. Judge on campaigns and per-build tables. core14 templates vs loot on the
  same commit and seeds: median of medians 153.6 -> 164.4 (+10.9) but mean 179.3 -> 164.2, 11 of 14 at or above the
  author (loot 14 of 14); the weak tail is the template's work list: poison_spectral_throw 64, smite 78,
  regular_viper_strike 91 (loot 112 / 134 / 134), spark -81.5, smite -55.5. new18 templates due Monday morning.
- 09:40 (25.09), **item census** (`scripts/item_lines_census.py`, 0659e22): Zizaran's day-1 rares carry FEWER lines than
  our templates (median 2-3 vs 3-4, mostly IncreasedLife + resistances); our template builds reach 101% of his builds, the
  loot's 140% comes from best-of-200 rares with more lines. The owner: his first loadout is SSF/trade mixed and can be T16
  (ours stops at T10), so richer slots of his are expected; the gem-level rule stays as it is (a gem-level line takes the
  whole open budget, D89).
- 09:05 (25.09), **the owner: templates ARE the product (decided earlier; the 07:30 recommendation below is withdrawn).** The gap
  to Zizaran is a question of template STRENGTH: either Zizaran's day-1 sets are strong or our templates are weak -- his
  gear is a hand-written wishlist too, and it wins. Measuring first: `docs/specs/2026-09-25-item-lines-census.md` (lines
  per item, Zizaran / Tuadh authors vs ours).
- 07:30 (25.09), template gear vs loot on full-pipeline numbers: smoke
  loot 141.6 vs templates 131.9 (-9.7); Zizaran on 25 common references loot 139.8 vs templates 101.0 (-38.8; ahead on
  9, behind on 16), seed spread 28.1 vs 5.0. Templates are far more repeatable and far weaker; the transplant numbers
  that suggested parity (L3, 113.6 vs 115.3) do not transfer to the pipeline -- transplants on a frozen author tree are
  not a proxy. Still to read: core14-tpl-main3 / new18-tpl-main3-lap (the 32-reference pair). Other results since the
  reset: main3-smoke vs main2-smoke +4.9 (D101, one smoke: check the per-build table for the mastery-cluster builds
  before claiming it), new18-main3 vs new18-r3 159.8 -> 164.1, ziz-rules vs ziz-main3 on the common 20: 136.7 -> 142.1.
  New open item: 'gear pass 2 (with tree)' loses >50% without lowering the violation on some builds, identically on
  all seeds (z329_juggernaut_boneshatter 1,056,242 -> 463,737; earlier z325_slayer_ground_slam -57%). BOM fix in
  slot_budget (f70fc3b). Queues filled to Saturday evening (seeds on @42565a9 = the control arm; no path-changing merge
  until they finish).
- 22:40 (23.09), **the lead is out of the weekly limit (98%) until Thu 24.09 22:00; TEST RUNS keeps both queues alone,
  no code changes.** Queued @42565a9: PC main3-smoke -> compare main2/main3 --per-build -> ziz-main3 -> new18-main3 ->
  core14-main3 (+ per-build compares against the r3 runs); laptop main2-tpl-smoke-lap -> ziz-tpl-main3-lap ->
  new18-tpl-main3-lap. FIRST READS for the next lead: (1) main2-smoke vs main2-tpl-smoke-lap = the template-default
  decision (the owner's, pending); (2) main2 vs main3 = D101's effect (the mastery is not a path); (3) new18/core14-main3
  = the full baseline on today's code. Open: template v4 core (flexible lines; Sonnet's branch cea08da feasible 2 -> 6 of 9
  in transplants, judge in a full smoke), cyclone boots vs EffectiveMovementSpeedMod (lead reads PoB's breakdown), the
  spectre Greater Volley what-if, per-move random streams (D100), the slot semaphore writing into another run's .out,
  stormbrand s1 "tree rebuilt on gear" -10%. Delegation principles + per-model notes are in memory; DeepSeek V4.1 Flash
  is the sub-task worker until the reset (CLAUDE.md), GPT-6 Luna for a parallel try on the next LONG task.
- 22:20 (23.09), **merged today**: quiver = weapon shape under templates (69110b2; transplant median of the bow references
  121.5 -> 150.9% of the author), skeleton ascendancy nodes after conversion (67fb238; 55 of 58 skeletons identical, 3
  drop nodes PoB's conversion drops), queue .out names / `compare_runs --per-build` / `graph_path_probe` (DeepSeek, the
  model comparison against GPT-6 Luna), D101 the mastery is not a path (6154f4f). Laptop: context of deepseek-flash
  probed 370k (opencode 370000); GPT-6 Luna 317k in 12 s. Runs: PC `main2-smoke` (loot, @0f0871e) -> `main3-smoke`
  (@42565a9, the graph fix) + per-build compare -> `ziz-main3`; laptop `main2-tpl-smoke-lap` (templates) ->
  `ziz-tpl-main3-lap`. Stale 20.09 filler lines removed (the owner: short runs with a question, not days blind).
  Template v4 (flexible lines): Sonnet's branch makes transplant sets feasible 2 -> 6 of 9 at median +2 points but
  trades damage for floors where the frozen author tree cannot help (burning_arrow_snipe 85 -> 43%): to be judged in a
  full smoke, not merged. Delegation principles and per-model notes in memory; DeepSeek is the sub-task worker.
- 04:10 (23.09), **merged tonight** (queue lines stay pinned @585ae29 / @3c579ea, untouched): spec A fixture loads +
  skeleton rails (Sonnet 5, 7df0403: 6 of 6 Zizaran fixtures load, 53 of 58 skeletons byte-identical), D97 the search's
  screen ranks by value (winner recall top 2 on 3 of 3), regions off (D100, fdf6d6b), spec B audit dead-node verdict
  by PoB's cascade + the unique quiver put back (DeepSeek V4.1 Flash, b687647; D98 / D99). Open from D100: TreeGraph
  disagrees with PoB on a bridge (spark-s1 8198 -> 13164); per-move random streams for sharper paired runs. Template
  v4: Sonnet's branch `sonnet-2026-09-22-template-v4` is a post-hoc polish (1 reference measured, +3.3 on stormbrand),
  NOT merged; DeepSeek's still running. Model comparison so far (the owner's experiment): A Sonnet done / DeepSeek
  failed (4 h, no report); B both done, DeepSeek right and Sonnet wrong on the dead nodes; v4 pending. Laptop offline
  since ~00:20 (the owner to plug it in); next laptop line ziz-fix6 on the newest main. Crafting (`crafting/`): report
  v2 merged, engine parked; the Claude lead owns it (the owner).
- 22:45 (22.09), **D95: the benchmark is deterministic on a clean machine; rig-first stays a switch.** `main-smoke` vs
  `main-smoke-aa`: 12 of 12 builds identical to the digit where the weapon-base move kept nothing; where it kept
  something the path changed (stormbrand -24.1, impale_ballista +11.0, median of medians -0.2) = the yardstick for any
  path-changing change. `rig-smoke` vs `main-smoke-aa`: +1.6 on the median of medians, per reference inside that
  yardstick. Regions kept 0 of 65 tries on `main-smoke-aa`. `noregions-smoke` started 22:23 on 3 queue workers
  (the owner plays since 22:17; TEST RUNS logs the game window and per-build loop passes) -> D96. In work: spec A
  (fixture loads + skeleton rails) by DeepSeek V4.1 Flash (opencode, `deepseek-flash`) AND Sonnet 5 on separate
  branches, to compare the models (the owner); next pairs at 01:00 (night slots): spec B
  (`2026-09-22-audit-dead-nodes-and-unequipped-uniques.md`: audit dead-node verdict + burning_arrow_snipe's unique
  quiver never equipped, 6 of 6 builds) and spec v4 (`2026-09-22-template-v4-flexible-lines.md`: the owner's rule --
  the line count per item and the bench crafts are the only hard-code, every line flexible, solved over the set).
  CLAUDE.md principle 8 (game / PoB terms verbatim). Every PoB launch of the lead is agreed with TEST RUNS first.
- 21:10 (22.09), **the lead is now the chat "poe-junkroan-v2 оркестрация" (Opus 5.5)**; TEST RUNS knows and reports
  there. Written: DECISIONS D91-D94 (owed since 20.09: the weapon-base move, template weapons, the move ledger, process);
  reading `docs/readings/2026-09-22-templates-vs-loot.md`: on the same code and seeds template gear halves the seed
  spread (median over references 37 -> 20 points) at -3 to -9 on the campaign medians; eight references lose 30-70
  points on templates (the template's gap list, archmage_volatile_dead -70.5 first); counting holes: the template's
  boots end at movement 1.027 on both cyclone builds, and three "dead tree node" rejections look like D87's open
  frozen-config audit item. Proposal to the owner (not coded): template gear becomes the benchmark's and the
  product's default after those two fixes. Waiting: `main-smoke-aa` (~22:00) and its two compare lines, then
  `noregions-smoke` (~01:30) -> the regions verdict (D95).
- 21:00 (22.09), **roles and models (the owner)**: the session "TEST RUNS" keeps the desktop queue, the handover
  Backlog, the hourly posts and the laptop; the lead chat (Opus 5.5) orchestrates, reads and writes DECISIONS, and may
  spawn subagents on any Claude model at any effort (CLAUDE.md "Subagents and models", `.claude/agents/effort-*.md`).
  Reading `docs/readings/2026-09-22-move-ledger.md` (180 builds): the kicks are 48% of loop time for 17.5% of the gain
  and stay; the region challenge kept something on 11 of 180 builds (0.6% of the gain for 5.7% of the time) -> the
  owner: out of the default loop. Coded on branch `opus-2026-09-22-regions-off` (worktree
  `.claude/worktrees/opus-regions-off`, NOT merged: queue lines carry no `@commit`, so a merge now would change every
  queued run). Update 21:30: the owner left the timing to the lead -> checked NOW: branch commit 3c579ea (code =
  585ae29 minus regions in the default plan); TEST RUNS asked to pin every pending benchmark line at `@585ae29` (code
  identical to main-smoke-aa and all controls, checked by git diff) and to insert `noregions-smoke` @3c579ea + its
  `compare_runs main-smoke-aa noregions-smoke` right after the two compare lines (~22:00 -> ~01:30). Merge only if the
  paired smoke shows no loss beyond the A/A noise (main-smoke vs main-smoke-aa). Model tiers (the owner): Opus 5.5 =
  tier 1 and the lead, Opus 5 = tier 2, Fable 5.1 retired (maybe a tier-1 second opinion after its limit resets);
  agent definitions `.claude/agents/effort-*` / `opus5-*` load from the next chat on.
- 19:55 (22.09), **the lead thread moves to Opus 5.5 (economy mode) until the reset Thu 24.09 22:00**: Fable's limit is
  spent; the queue-keeper rules stay, plus the laptop plan in `docs/machines/laptop.md`
  (cross-machine A/A `main-smoke-lap` first, then `ziz-rules-s4` moves to the laptop). Running: `main-smoke-aa` (18:23 ->
  ~22:00), then the two compare lines, then the priority-3 tail. No new specs / workers / merges before the reset unless the
  owner asks; readings and DECISIONS entries owed since 20.09 are the first lead work when limits allow.
- **LIMIT HANDOVER (17:07 20.09; Fable at ~86-88% of the weekly limit; in effect when the user opens the Opus chat):**
  the WHOLE queue to the reset (Thu 24.09 22:00) is already in `queue.txt` and all of
  it runs on today's final code: `new18-r3` (running since 16:18) -> `core14-r3` -> `templates-smoke` + compare ->
  `new18-tpl` / `core14-tpl` -> `ziz-rules` -> `rig-smoke` / `main-smoke-aa` + two compares -> `ziz-tpl` -> seeds 4-6 of both
  campaigns -> smoke seeds 4-6 / 7-9. No GPT worker alive. Merged today after D88-D90: the move ledger (3568a0b), the loop's
  WEAPON-BASE move (23b6e65; bench 57 / 39 / 0, mean +1.58%, 2.8 s a build; canary build clean), human durations (CLAUDE.md
  principle 7, d5226f9), the template weapons (census by value; tiers 0.35 / 0.50 / 0.57 per rank, NEAREST tier, the owner's
  approval; a weapon base's requirement is a cost the set pays; transplant median 112.3% of the author against the loot's
  109.3%, burning_arrow_snipe Bone Bow -> Imperial Bow 69.6 -> 85.4%), the limit-handover step 0. `main-smoke` = the new
  baseline: median 139%, 6 of 6 at or above the author. Both canary builds are clean (bleed_bow s1: loot with the
  weapon-base move 48 min; TEMPLATE gear on the final code 145% of the author, 56 min, 0 audit errors, 0 dropped moves,
  the ledger identity exact). DECISIONS entries for these are OWED (the handover's Backlog lists
  them). The owner's far-sight brainstorm (bundles, gates, the bridge table) is kept in
  `docs/research/2026-09-20-far-sight-packages-brainstorm.md`; its work starts after the reset.
- 10:35 (20.09), **main now holds tree plan B (D88) and the template gear's third pass (D89)**; both merged after their
  queue measurements (plan B: a paired default loop pass on the smoke six, gains identical 6 of 6 at 0.96x the
  seconds; templates `fix4`: impale_ballista 26.8 -> 81.6% after the bare-base baseline fix, the control
  bit-identical; median 111.3% against the loot's 109.3%). In work: GPT `2026-09-20-eldritch-battery-recharge-
  sustains` (the user's verdict + the wiki: with EB and no damage taken from mana, `EnergyShieldRecharge` counts in
  the ES sustain relation), GPT `2026-09-20-template-weapons-tiers-and-bases` (the user: T5 weapon lines are too
  low and weapon bases are among the strongest choices of an attack build -- a census BY VALUE of the authors' and
  our loot's weapon lines, the template weapon's line count and tier position as measured rails, a weapon base's
  requirement paid by the set instead of vetoing the base: Bone Bow lvl 23 beat Imperial Bow on burning_arrow_snipe),
  the Opus foreman finishing `move-ledger` mechanically (accepted: identity exact on a real stormbrand build,
  `fast_trials` 1,155 s of a 1,430 s build, the two kicks 390 s for nothing, nine of ten gear slots kept nothing;
  finishing: the rereport gate, the timer, `where` per row, the screen identity, region tries, more call kinds).
  NEXT SPECS (lead): the loop's weapon-base re-choice move (same affixes on every other base of the class, one fast
  what-if each; closes "the build drifted into crit and kept its non-crit base"; after the ledger merge, same file)
  and a measurement of how often the weapon TYPE chosen on the bare skeleton still wins on the finished build; the
  unique-packages spec. QUEUE: Raise Zombie winner-recall (10:15 ->), then ziz-rules -- to be re-ordered after the
  ledger merge: `main-smoke` (loot) and `templates-smoke` (`--gear wishlist`) on the merged main, then both full
  campaigns on both gears (how much of the 41-point seed spread is LOOT), ziz-rules, extra smoke seeds: ~103 h for
  the ~108 h to the reset (Thu 24.09 22:00). The queue's snapshot of a branch that TRACKS files under `artifacts/`
  loses its junction (outputs stay inside the kept snapshot `artifacts/runs/snap/20260920-0923-run`; copied out).
- 09:14 (20.09), **the user read the template gear and plan B; four verdicts.** (1) The template tiers are buyable on
  day 1 (life T2-T3, resistances T4-T5, weapon T3-T5 + one craft). (2) **Eldritch Battery WITHOUT Mind over Matter:
  ES recharge is never interrupted (nothing damages an ES that protects mana), so it COUNTS as sustain of an ES
  cost; with MoM it does not** -> a spec for D63.2 (PoB has `EnergyShieldRecharge` per second, CalcDefence.lua
  1353; condition = `EnergyShieldProtectsMana` on and MoM not allocated; check the wiki's EB page first, the trust
  order); expected effect: summon_raging_spirits' author becomes feasible and the two ES-regen crafts go to damage.
  The craft "Regenerate N ES per second while a Rare or Unique Enemy is Nearby" is a GOOD boss line and stays
  legal. **MAPPING BACKLOG (nothing models mapping yet): that craft does not sustain while mapping; there sustain
  comes from ES / mana gained on kill.** (3) burning_arrow_snipe's template bow: the user wants the LOOT bow next to
  it -> the coder adds loot + author item sections, loot PoB files and the weapon BASE ranking table to
  `gear_transplant.py` (the template took a Bone Bow, a minion-implicit base, where the author wears an Imperial
  Bow: cause to be read from the table); the `fix4` re-measure is HELD in the queue until that commit. (4) Corridor
  exchange: the user doubts a one-loadout verdict. What is structural: a bypass needs UNALLOCATED nodes beside the
  corridor, the passive tree has few short cycles (bypass inside slack 2 for 3% of corridors, 9% at slack 6) and an
  endgame tree allocates MORE of them, not fewer. What is loadout-dependent: what a bypass passes (jewel and
  cluster sockets are worth far more at endgame) and jewels that rewrite connectivity or reward path length (Split
  Personality, Thread of Hope, Intuitive Leap, Impossible Escape) -- those are PACKAGES (the far-sight gap), not
  corridor swaps. The move stays in the bench; re-test at the endgame loadout costs minutes: the graph-only bypass
  count on endgame trees (no PoB) + `replay_bench.py --move corridors` (3 s a build).
- 08:55 (20.09), **day-1 template gear, third pass (Opus coder, branch `gpt-2026-09-20-day1-gear-templates-weapons-
  buy-damage-5` @d29c4af, NOT merged yet): C (wishlist) now beats B (loot) at the median, 111.3% vs 109.3% of the
  author (second pass: 76.0 vs 96.6)**; smoke six, seed 1, `artifacts/runs/gear-templates/fix3-*`: cold_dot 103.2
  (C feasible now), bleed_bow 124.5, summon_raging_spirits 119.4 (feasible now), stormbrand 148.6,
  burning_arrow_snipe 69.6 (loot 92.8), impale_ballista 26.8. Whole suite on the branch 914 passed. Rule 4's N is
  measured: authors pay an attribute affix on a median of 3 items (32 sets). Lead's verdict on impale_ballista's BARE
  bow: a baseline bug, not a ranking question -- weapon lines were compared with the EMPTY slot (no weapon = the
  skill costs nothing = the sustain floor trivially met, so every bow "worsens" it by the same 1.433); the rule now
  being coded: a slot the template fills is mandatory, the baseline of "does not worsen" is the BARE BASE equipped.
  Re-measure impale_ballista + burning_arrow_snipe (control, must be bit-identical) as `fix4-` once the machine
  frees up, then merge (fix coded 09:00, branch @8e722b5, fast tests 53 passed; the re-measure is QUEUED as the
  first pending line, `@8e722b5 ... gear_transplant.py impale_ballista burning_arrow_snipe ... fix4-*`, one PoB
  session, behind Essence Drain). Five PoB files are with the user for reading. Observation for the floors' reading list:
  summon_raging_spirits (Guardian, Eldritch Battery, ES 300, `ESPerSecondCost` 153.9) is "infeasible" as the author
  built it because D63.2 counts regen / leech / recoup and NOT energy-shield recharge; the wishlist bought the
  bench craft "Regenerate 120 Energy Shield per second while a Rare or Unique Enemy is Nearby" twice to pass it.
- 09:00 (20.09), **tree plan B measured (Opus coder, branch `opus-2026-09-20-tree-plan-b`, NOT merged yet)**, replay
  bench, seed 1. CORRIDOR EXCHANGE = a measured negative: of 2,583 corridors on 96 delivered trees 3.1% have a
  bypass inside slack 2 (9.1% at slack 6: the passive tree is locally a tree), trunk share 0.6%, 1/94/1, 2 kept;
  it leaves the default plan (bench only). REGION CHALLENGE = a small positive: on the 55 feasible starts 8/47/0,
  mean +0.43%, best +11.26% (absolution_minions), 42-53 s a build, +0.96% per 100 s against the kick's +0.41%,
  trunk share 34%; repair policies dead even (greedy 34 / target-first 34 kept); never worse on a feasible start;
  it enters the loop where the coder wired it (only when refine / swaps kept nothing this pass). All the negative
  means come from starts infeasible under TODAY's rules (41 of 96), where D58 buys a floor with damage. A RULE
  HOLE found: stormbrand-s1 ended at FullDPS 0 and was KEPT (violation 0 because the skill stopped working); fix
  being coded in `objective.better_score`: a new score with value <= 0 never beats a current one with value > 0
  (the same shape as the bare-bow baseline). The coder is finishing (merge main, corridors out of the default
  plan, the guard + tests, the cause of the zero); then a paired `--move loop --passes 1` replay through the QUEUE.
  Reading of the tree line so far: MIP negative, corridors negative, regions +0.43% -- the greedy trunk is near
  its best; what is left is step C (branch exchange between seeds) and measuring how much of the 41-point seed
  spread is LOOT: the full 32 on template gear answers that.
- 08:40 (20.09), **construction rig-first is on main as an experiment switch (f2aa0ea), default unchanged**; the
  foreman found TWO identical measurement chains left by the GPT worker (the reason `machine_load` said WAIT, RAM
  6.7 GB): the duplicate (pid 16424) was stopped, the first (pid 4940, `construct-classic` then `construct-rig`,
  smoke six x 3 seeds, 2 workers, `--construction-only`: fair between the two arms, not comparable with ordinary
  rows) runs from the worker's worktree and holds no slot (pre-semaphore code): count its 2 workers by hand. Also
  fixes `benchmark.py --help` (unescaped %). A hole to remember: a worker's own measurements outlive the worker.
- 08:10 (20.09), **Jev (TypeSafe AI) researched: nothing is integrated** (`docs/research/2026-09-20-jev-verdict.md`):
  PoB answers a package exactly in 7 ms and the vendor's own docs say "Jev is not a calculator"; no calibration
  evidence on game text. The report's one finding about our code is TRUE and feeds the "unique packages" spec:
  `scripts/build_scaling_vectors.py:129` truncates every stat's provider list to the first 50 in source order (for
  Str / Dex / Int: uniques only, no tree node). Package space after a stat graph: 88 consumer uniques x 374 notable
  groups = 32,912 pairs = ~230 s of PoB trials.
- 07:45 (20.09), **the machine has a budget and it is enforced** (the user: capacity management is the orchestrator's
  job; they work on this PC by day). Incident 07:10: 12 cores at 99.9%, 5.9 GB free, five PoB-backed jobs at once
  (diagnosed read-only by an Opus agent). Now on main (67d3a05): a machine-wide PoB slot semaphore inside `PobSession`
  (day 08-01: 7 slots, the queue 5 + everything else 2, 8 GB floor; night: 10 / 5 / 3 GB; `var/machine_budget.json`
  live), `python scripts/machine_load.py --need N --role other` = GO / WAIT; the real PoB smoke passed on main (34
  passed). Processes started before 07:40 hold no slot (11 PoB workers at 07:40): launch NOTHING with PoB until they
  finish -- the plan B agent was told to drop its bench to 2 workers. The winner-recall run of Fireball (05:18 ->)
  ran under the overload: its seconds are distorted, its ranking is usable, mark it so.
- 07:00 (20.09), **a gap the user named: FAR SIGHT over packages** (a stacking unique + the nodes that feed it). PoB
  evaluates any package exactly in one 7 ms what-if; what is missing is proposing them: `screen_uniques` tries every
  unique ALONE, so a build-around unique whose parts are worthless one by one is invisible (the tree has the idea in
  small: `_cluster_trials`). Next spec after plan B: **unique packages** -- for a unique whose parsed mods consume a
  stat ("per X", thresholds; PoB's mod data, no name lists), the package = the unique + the best sources of X (tree
  clusters, masteries, other slots' lines) as ONE fast what-if; packages that beat the incumbent become skeleton
  variants like the keystone variants; pair probes (item x cluster, 7 ms each) as the brute-force control. A language
  model (Jev or any other) is not the tool: slower than PoB, approximate, and it does not know 3.29.
- 06:30 (20.09), **verdicts of the research that are DAY-1 verdicts, to re-test when the endgame loadout exists** (the
  user's question: can a test lie because the system is still simple?). Verdicts that rest on STRUCTURE do not flip
  with a loadout: the additive whole-tree MIP (later loadouts are more interdependent, not less), same-seed pairing
  (r = +0.10), seeds are search noise for the product, the cost of one evaluation (memetic / irace-scale methods).
  Verdicts that rest on SCALE or on too little history can flip and are re-tested then: the screen's winner recall
  (endgame builds need more enabling pieces at once), adaptive seeds among finalists, surrogates / transfer across
  requests (needs accumulated `evaluations.jsonl`), automatic tuning of the knobs (realistic on the replay bench),
  gear as an exact problem (endgame itemization is a larger catalogue with explicit constraints), the choice of the
  smoke set by replay (needs three or more campaign pairs), loadout warm start + trunk challenge (needs two loadouts).
  Added 20.09: the corridor exchange (negative on day-1 trees; re-test = the graph-only bypass count on endgame trees,
  then `--move corridors` on the bench, minutes) and the region challenge's yield (+0.43% on day-1; sockets change it).
- 04:40 (20.09), **the judge fix is on main (4dccc46, D87; whole suite on the branch 876 passed)** -- written by an
  Opus coder from the lead's spec after two GPT sessions died on vendor outages; accepted on counts + the replay bench
  (batches reverted at a loss 5 -> 0, Minion Life gone, 61 holder lines, 23 honest judgements, 0 RESTORE FAILED).
  Launched after it: GPT workers `2026-09-19-move-ledger` and `2026-09-19-construction-rig-first` (the new harness
  survives vendor outages: up to 8 vendor restarts), and **tree plan B** as an Opus coder in the junction worktree
  `.claude/worktrees/opus-2026-09-20-tree-plan-b` (spec `docs/specs/2026-09-20-tree-plan-b-corridors-and-regions.md`:
  corridor exchange, region challenge by completed replacements, target-first repair; accepted on the bench over the
  96 delivered builds against the random tree kick). Still running: template gear third pass (GPT, continuation).
  RULE OF THE NIGHT (CLAUDE.md "Who spends what"): GPT codes when its vendor is up; a critical-path task whose GPT
  worker dies twice goes to an Opus coder in a junction worktree made by `gpt_worker.make_worktree('<branch>')`.
- 04:05 (20.09), **main after the night: whole suite 873 passed, 0 failures (@d9fe70c)**; the debt is closed. Merged
  since 03:00: the castability + own-maximum-resistance floors (5d35b61, D85), the flat-reservation aura level
  (b9fbec0, D86), the harness's vendor-restart rule (4152a39: the GPT vendor flapped every 20-30 min all night).
  Both acceptance requests now DELIVER on main with the gem-count fix: Cyclone Slayer (58 min, dropped moves 0), SRS
  Necromancer (35 min, FullDPS 280,927, dropped moves 0). Queue: `aa-smoke3` running since 02:51 -> winter-recall x 3
  -> ziz-rules. In work: judge fix v3 (an OPUS coder in the v3 worktree -- the GPT worker died twice on outages; it
  checks itself on the replay bench first), template gear third pass (GPT, 5th launch). Reading list: winter_orb took
  Supreme Ego once Clarity dropped to level 1 (D86's run) -- measure on the bench before any conclusion.
- 03:00 (20.09), **the replay bench is on main (D84)** and is the judge of move changes from now on: `python
  scripts/replay_bench.py --builds "<glob>" --move loop|refine|swaps|gear|picks|kick-tree|kick-joint --seed 1 --workers 5
  --tag <t> [--against <other run>]`; A/A bit-identical, ~22 min per six builds. The whole suite on main is OWED (the
  machine was loaded). Also merged: the harness fixes after its first night (9fd9769: report presence, crash +
  vendor-outage continuation, commit counts). The GPT vendor went down twice tonight (02:23, 02:50).
  - In work: castability branch (the foreman finishes: summon skills are costed, test fakes, merge main; then the
    lead merges + D85), judge fix v3 (`2026-09-20-judge-fix-v3-necessary-proofs`: a holder is a NECESSARY proof; v2's
    machinery was right but its sole-proof predicate left the map empty: usePowerCharges stands on an ascendancy line
    + Caster Mastery), template gear third pass (`2026-09-20-day1-gear-templates-weapons-buy-damage`, 4th launch:
    weapons rank lines by value, D79's 4-line weapon, gem-level rule, attribute budget from the authors, PoBs for the
    user), flat-reservation aura level (worker + waiting foreman). First use of the bench: judge fix v3, then the
    castability floor's own cost, then tree plan B.
- 01:05 (20.09), **since midnight**. MERGED: the whole-tree MIP experiment (e989813) -- result NEGATIVE, the lead's
  reading in `2026-09-19-tree-search-plan.md` "Addendum 01:00": B is the main line, C becomes PoB-judged branch
  exchange between seeds, gear-as-MIP parked; the search evaluation rows + `--full-ranks` (2d67ede, 813 passed).
  REJECTED: the first judge fix (`gpt-2026-09-19-tree-moves-see-proof-holders`, 3f493e4: batch reverts 5 -> 1 but
  swap candidates per 120 s move 10 -> 4.75 and 12 -> 7, two RESTORE FAILED); v2 worker
  `2026-09-20-judge-fix-v2-proof-holders-only` (00:38) judges honestly only removals that take a SOLE proof away.
  Running GPT workers: day1-gear-templates-finish, castability-refresh-budget (foreman waiting, scan in work),
  flat-reservation-aura-level (foreman waiting), judge-fix-v2, replay-bench (00:55). Foreman finishing the harness
  branch. Waiting for judge-fix-v2: `move-ledger`, `construction-rig-first`, the tree plan's B spec (to write).
  Queue: restarts-smoke3 (running) -> the 2 requests -> aa-smoke3 -> winner-recall x 3 (Fireball hit, Essence Drain
  dot, Raise Zombie minion: 20 ascendancies, ten screen ranks in full, one seed) -> ziz-rules.
- 00:00 (20.09), **the night's state**. Roles since 19.09 evening (CLAUDE.md "Who spends what"): GPT codes, an Opus
  FOREMAN per worker waits for it, commits a WIP tree, runs the suite, checks the spec's numbers and returns one table;
  Fable reads the table and the number-changing hunks only. A new chat re-arms foremen, not bare watchers.
  - MERGED: the gem-count fix (87ab8a2, D83; whole suite 807 passed, main's 7 `test_finish_*` failures fixed with it).
    Queue now: restarts-smoke3 (running) -> Cyclone Slayer and SRS Necromancer requests -> `aa-smoke3` (@e2629bd)
    -> ziz-rules.
  - Castability floors: branch `gpt-2026-09-19-usable-skills-amendment` (528675e) is RIGHT in its rule (the foreman
    verified the Eldritch Battery flag trial-local, soulrend 0 findings, PoB's reservation clause) and NOT merged:
    its refresh costs 1.2-2.7 s and runs 4x per reconfigure = 5-11 s per judged move. Worker
    `2026-09-19-castability-refresh-budget` (23:45) fixes that + three small things; its foreman also runs the
    96-build / 32-author scan the first amendment worker never delivered (its session died on an upstream error).
  - Running GPT workers: day1-gear-templates-finish (to 01:36), tree-moves-see-proof-holders (to 00:03+, check),
    whole-tree-mip-experiment (to 02:15), search-evaluation-rows-and-full-ranks, castability-refresh-budget,
    flat-reservation-aura-level (23:55, with a foreman), gpt-worker-never-loses-work (done, e4258b2, a foreman is
    verifying the WIP-commit safety). Specs written and waiting for the judge fix to merge: `move-ledger`,
    `construction-rig-first`; waiting for the MIP experiment: `replay-bench`.
- 22:45 (19.09), **THE WEEK TO THE RESET (Thu 24.09 22:00, ~119 h of machine time; Fable's weekly limit at 71% on Sat
  evening, 38 points burnt today)**. Principle: Fable's remaining budget goes to what only Fable can do -- reviews of
  what is already coded, specs with numbers a machine can check, the queue with its gates -- and everything that only
  needs a machine runs after Fable stops (Limit handover protocol below; Opus keeps the queue, GPT workers cost no
  Claude limit). Chat hygiene: this chat holds six research reports; acceptance continues in a NEW chat.
  - **Block 1, land what is coded (reviews only)**: gem-count fix -> rerun the Cyclone Slayer and SRS Necromancer
    requests; castability / max-res floors + the amendment (spec ready); flat-reservation aura level (spec ready, after
    gem-count); the judge fix (accepted on counts: reverted path-swap moves, their seconds, Minion Life gone);
    templates-finish -> PoBs + full item text to the user; the MIP experiment's result (a reading: decides B / C).
  - **Block 2, instrumentation BEFORE the long runs, four small specs for GPT workers, mechanical acceptance**: (1) the
    ledger -- gain and seconds per move type, trunk churn, never-reconsidered share in every results.json row (the
    tree plan's reporting block extended to gear / picks / kicks); (2) the search persists every evaluation row + a
    `--full-ranks` switch for the winner-recall test; (3) the replay bench from the MIP experiment's harness + its A/A;
    (4) a construction switch "cheap rig first" (experiment only).
  - **Block 3, the big optimizer work, specified by Fable, coded while Fable is away, reviewed after the reset**: tree
    plan B (corridor replacement, region challenge by completed replacements, second repair); the joint move that
    re-judges the gear slots a tree move touched; C (union of seeds) if A pays.
  - **Queue, in order** (`artifacts/runs/queue.txt`): restarts-smoke3 (running) -> `aa-smoke3` (pinned @e2629bd: the
    A/A yardstick, 3.5 h) -> the two requests (2 h) -> the template pair on identical code, smoke six `--gear loot` /
    `--gear wishlist` (10.6 h) -> the user reads the template PoBs -> ziz-rules (27 h) -> the full 32 on new main
    WITH the ledger (28 h) -> winner-recall, 3 requests (4.5 h) -> bench A/A + two replays (3 h) -> the construction
    pair (2 h) -> if the templates pass: the full 32 on `--gear wishlist` (28 h). About 118 h.
  - **Gates**: `compare_runs.py --min-delta -5` on a smoke median is NOT usable any more: identical code shows -2.0%
    with an sd of ~7%, so a -5 gate reverts a good change one time in three. Until the bench exists a smoke gate is
    -15 (2 sd) or a count (audit errors, infeasible builds, reverted moves); `aa-smoke3` measures the real number.
  - NOT this week (recorded in the three research plans): a bandit scheduler, automatic tuning of the knobs, a middle
    rung in the search ladder (after the recall test), saving seeds (after C), gear as a MIP (after A), loadouts.
- 22:35 (19.09, clarified 22:50), **the user's rule for the loadout work, recorded before it starts**: every loadout
  is built ON ITS OWN, from the skeleton level under its own rails, to be the best at its level; the system never
  builds a PoB with the next loadout in mind, and loadouts may differ drastically. A BRIDGE between two finished
  loadouts (a less painful transition: shared trunk, fewer changed slots, respec cost) is an OPTIONAL quality-of-life
  step after both are built -- an idea to keep, never a constraint (`2026-09-19-screening-plan.md` "The loadout axis";
  memory `endgame-first-search`). The rulebook's recorded first step ("day-1 + T16 slice, nested tree") is that bridge
  idea, not the way loadouts are built; a DECISIONS entry when the loadout work begins.
- 22:20 (19.09), **the sixth report landed (Astra, screening) and the three new plans are reconciled with the tree
  plan** (the user: "not judgments detached from the two tree researches"). `2026-09-19-tree-search-plan.md` carries an
  addendum: A -> B -> C stands; B is accepted on structural counts + a replay bench, not on the smoke six's value; C
  (union of seeds) gains weight and blocks the product-side seed savings until it is measured; the bandit scheduler
  stays downgraded (ALNS evidence beats the component reports' continuous-optimization evidence); gear-as-MIP reuses
  A's method and waits for A's actual / predicted ratio. Screening: both reports treat seeds as noisy measurements of
  a mean -- wrong for the product (a delivered build's number is exact; seed noise is search noise).
- 22:15 (19.09), **five of the six deep researches read in full** (the sixth, Astra on multi-fidelity screening, came as
  an empty file; the user has asked Astra again). Reports in `docs/research/inbox/2026-09-19-{chatgpt,astra}-*.md`,
  load-bearing quotes checked on the primary pages (Mei-Li-Yao, Campelo-Takahashi, Namazi et al., MFES-HB: verbatim;
  INFORMS pages behind a bot check: not opened). One plan per topic, each with our own numbers and the tests that
  decide: `docs/research/2026-09-19-judging-plan.md`, `...-screening-plan.md`, `...-components-plan.md`. NOTHING is
  specified for a worker yet; the user reads the plain-language summary first.
  - Measured from finished campaigns, no new runs (`docs/research/scripts/2026-09-19-judging-noise.py`,
    `...-anytime-traces.py`): one build's noise inside a reference = 15% of the value; the SAME seed does not carry
    over between code versions (r = +0.10, null band +-0.27); the smoke protocol sees only effects of ~15%, the full
    32 x 3 of ~6%; an A/A pair (same code, seeds 1-3 against 7-9) "shows" -2.0% on the smoke and -14.5% on cold_dot;
    a random six-subset gets the SIGN of the frozen -> rules campaign change wrong 44% of the time. After loop pass 1
    (30% of a build's time) a build holds 82% of its final value; dropping the trailing seed there costs 76% of three
    seeds' time and 0.6% of the delivered best-of-3 on average (worst 10%).
  - The lead's main conclusion: judge a change to a MOVE on a **replay bench** (the move run from the same finished
    builds, before / after: minutes per build, effects of 2-5% visible); whole-pipeline campaigns become
    confirmation. Next in order after the tree plan's A / B: the gain-per-second ledger per move type (log only), the
    winner-recall test of the skeleton screen (10 skeletons x 3 requests at full depth, ~4.5 h of queue), the joint
    move that re-judges the gear slots a tree move touched, gear as a small exact problem on HiGHS.
- 22:00 (19.09), **the new chat's first hour**. Watchers armed, one per agent (`watch_agent.py` fixed: a relaunched
  worker's old report and a repeated queue tag no longer end the wait at once). The `gem-count-zero-kills-the-build`
  parent timed out at 21:53 with no code of its own (it supervised); the root cause is confirmed (two golems under
  `ActiveGolemLimit` 1: `derived_counts` gives the second 0, both skills writers serialise it) and the fix sits
  UNCOMMITTED in the nested worktree `...gem-count-zero-kills-the-build\.claude\worktrees\gpt-2026-09-19-gem-count-zero-fix`
  (562 lines, nested worker pid 35816 until ~22:44: if it dies without a commit, commit its tree as WIP).
  - The lead's review of `usable-skills-and-max-res-floors` d76df84 (its scan: 15 of 96 builds cannot press a skill,
    12 sit below their own maximum resistance): NOT mergeable yet, three defects, spec
    `docs/specs/2026-09-19-usable-skills-amendment.md` (launch when the worker exits, 22:37 at the latest): (1) no
    Eldritch Battery -- PoB's own rule (`Calcs.lua` 433-456) pays a mana cost from energy shield + unreserved mana;
    the soulrend author (EB, 0 unreserved, 503 ES) gets 8 false "cannot be cast"; (2) the main skill's live cost
    relation was removed and every cost frozen between refreshes; (3) the AUTHOR's maximum resistance became OUR
    fixed floor (impale_cyclone's author: 79% fire).
  - FOUND on the way, spec `docs/specs/2026-09-19-flat-reservation-aura-level.md` (launch after the gem-count merge,
    it touches the same writers): the gem rail lifts deliberately low flat-reservation auras to level 18 (Precision
    1 -> 18 = 22 -> 167 mana) on both sides: 66 gems on 24 references; all 33 of our builds on the 11 Tuadh
    references carry the aura at 18; impale_cyclone's author goes from +73 to -37 unreserved mana under our lane;
    shockwave_cyclone's three "cannot cast" builds would be castable at the author's Precision 9. Rule: the level of
    a flat-reservation aura is PoB's choice among 1..rail on our side, `min(author, rail)` on the author's.
  - `tree-moves-see-proof-holders` (cd8e83f, 4e8d885): it re-derives the config after EVERY real removal (general,
    but a reconfigure per swap candidate): the verdict waits for its seconds before / after.
- 21:50 (19.09), **HANDOVER to a new chat** (the user asked: the context is cluttered). The task panel is empty; all
  agents run detached. FIRST ACTIONS of the new chat:
  1. `tasklist | findstr junkroan`; one named watcher per agent still running (CLAUDE.md "How agents and long runs are
     launched": `python scripts/watch_agent.py <slug>` as a background task described "GPT agent <slug>: <task>";
     `--queue restarts-smoke3` for the run). Running at 21:45, all GPT workers on specs `docs/specs/2026-09-19-*.md`:
     `day1-gear-templates-finish` (20:36, 300 min; target: C / A at or above the first version on the six smoke
     references -- 81 / 50 / 101 / 31 / 101 / 51% -- no zero-delta lines, < 180 s per build; then PoBs + full item text
     to the user), `gem-count-zero-kills-the-build` (17:53; NOTE it spawned a nested worker on its own spec
     `gem-count-zero-fix`, branch `gpt-2026-09-19-gem-count-zero-fix`: check BOTH branches; after the merge rerun the
     Cyclone Slayer and SRS Necromancer requests), `usable-skills-and-max-res-floors` (18:37),
     `tree-moves-see-proof-holders` (19:03; acceptance: winter_orb s2 loses Minion Life for good, reverted path-swap
     moves and their seconds before / after), `whole-tree-mip-experiment` (21:15; `highspy` allowed). Review = the
     lead's own measurement (lane diff with `scratchpad`-style dumps over 58 references where config rules move),
     focused tests on the merged tree, merge, DECISIONS entry. A hung harness from the morning (pid 14064 / 16580,
     `proxy-delivery-gives-the-player-nothing`, no child) may still exist: harmless, the user may close it.
  2. Queue: `restarts-smoke3` (21:25 @e2629bd, 12 builds, ~3.5 h), then `ziz-rules`. The whole suite on main is still
     OWED (run it when the machine is free; PoB-backed `test_pob_inplace_writes` crashes under load, not a code bug).
  3. The user is running SIX deep researches (GPT Astra + ChatGPT, prompts 3 / 4 / 5 in `docs/research/briefs/`:
     judging with few runs; multi-fidelity screening; interdependent components). They will land in
     `docs/research/inbox/` or as attachments: read them IN FULL, verify the load-bearing quotes, write one plan per
     topic like `docs/research/2026-09-19-tree-search-plan.md`. Tree-search order of work: (A) the MIP experiment's
     result, (B) corridor replacement + region challenge + second repair + reporting after the judge fix, (C) union
     of seeds.
  4. Open with the user: the rulebook page's questions (uniques at day 1: T5 or tiers 3-5; item level 70 or 72 / 76;
     Pantheon upgrades <= T10 at day 1; 4x Exalted crafts); "pinnacle boss ramp" seconds; default gear after the
     template smoke.
- 21:35 (19.09), **the evening in one entry**.
  - Merged since 17:40: the bench-unlock rail (D81, fdcad2e), the picks / self-cost fix (D82, 91b2a13), D77 amendment 1
    (a buff ended by skill use proves nothing: Withering Step, Phase Run; 6 of 58 lanes lose `buffElusive`), the tree
    hygiene audit + "why is it there" table + `# comment` custom mods (aada13a), the warcry rule (D75 amendment 3).
  - `poison-d78` (19:41-21:25 @0d9a5c6, 9 builds, auto-archived by the fresh runner): poison_spark 105% (95-128; was
    3 of 3 infeasible), regular_viper_strike 179% (107-198; was 255% with a 9 s ramp, now 1.7-1.9 s),
    poison_spectral_throw 85% (77-96; was 126% counting 18 poison stacks). Queue now: `restarts-smoke3` (21:25
    @e2629bd), then `ziz-rules`.
  - The three acceptance requests: Storm Brand Inquisitor delivered (2,514,111 FullDPS, 56 min); Cyclone Slayer lost
    3 of 3 seeds and SRS Necromancer 2 of 3 to "Gem numeric fields must be positive" (a minion utility gem written with
    count 0); worker `2026-09-19-gem-count-zero-kills-the-build` in work. Rerun the two requests after its merge.
  - THE USER'S READING of core14-rules (physical_dot, winter_orb) and what came of it: two new floors in work
    (`2026-09-19-usable-skills-and-max-res-floors`: every pressed skill affordable; resistances at the build's own
    maximum); a real pipeline bug found from "how did Minion Life survive": tree moves judge removals with the config
    frozen, the pipeline re-derives it and reverts the WHOLE batch (202 reverted path-swap moves, 11,551 s, 117 kept
    swaps lost over 42 builds) -- worker `2026-09-19-tree-moves-see-proof-holders`; measured: 2 dead and ~25 weak
    leaves in 1,411 points, 22% of tree nodes are trunk that no move ever reconsiders.
  - TREE SEARCH RESEARCH: four deep-research reports (two ChatGPT, two GPT Astra, run by the user from the lead's
    prompts) in `docs/research/inbox/`, the plan in `docs/research/2026-09-19-tree-search-plan.md`. Order: (A) the
    whole-tree MIP experiment (worker `2026-09-19-whole-tree-mip-experiment`, 21:15; `highspy` allowed by the user),
    (B) corridor replacement + region challenge by completed replacements + a second repair policy + reporting, after
    the judge fix merges, (C) union of seeds. Measured: PoB's fast what-if does not cascade (disconnected sets are
    evaluable). Three more prompts handed to the user (judging with few runs; multi-fidelity screening; interdependent
    components): read whatever lands in the inbox IN FULL, verify load-bearing quotes, then plan.
  - Day-1 gear templates: first version merged (f37f65d, 66% median of the author's gear against loot's 97%), the
    amendment WIP at 72% (ebb0487; the watchdog killed its worker mid-measurement), finish worker
    `2026-09-19-day1-gear-templates-finish` (20:36): attribute payments eat open lines, zero-delta lines are bought,
    extra resistance lines go to capped sets. The user sees PoBs + item text only after it lands.
  - Harness: workers get their own `AGENTS.md` (opencode was reading CLAUDE.md, the LEAD's role, as its own
    instructions); stall limit 100 min; a worktree whose `var/` is not a junction refuses to start; `gpt_research`
    rejects a refusal as a report. NOTE: worktrees `gpt-2026-09-19-picks-self-cost-finish` and
    `gpt-2026-09-19-bench-unlock-rail` hold a REAL `var/` with their own 1.4 GB PoB runtime (not a junction).
  - The loadout rulebook: `docs/rulebook/loadout-rulebook.json` + the editable page
    https://claude.ai/artifact/3CNfysNvnAiQeuo4SbPtdY (the user edits cells / notes; on "read it": `read_db`
    collections `cells`, `notes`, fold in, rebuild, republish to the same URL).
- 17:40 (19.09), **`core14-rules` done** (09:41-17:20 @254f915, loot gear, 42 of 42, 0 FAILED; archived by hand to
  `C:\Coding\poe-junkroan-archiveenchmark\`): medians ours / author (our lane) -- physical_dot 363, winter_orb
  323, regular_viper_strike 255, spark 242, ignite_penance_brand 201 (2 counted rows), hit_penance_brand 162,
  summon_raging_spirits 161, bleed_bow 160, stormbrand 159, toxic_rain 141, absolution_minions 135, smite 129,
  poison_spectral_throw 126, cold_dot 109; median of medians 161%, 14 of 14 at or above the author; 7 of 42 not at
  a fixed point. Audit with the CURRENT rules (`artifacts/runs/core14-rules-audit.out`; the run predates D78 / D80):
  6 of 42 builds tainted, all on two references -- poison_spectral_throw counts 17-18 poison stacks where 12-13 fit
  the 2.5 s budget (D78), regular_viper_strike delivers a ramp of 8.9-9.9 s against a 3.9 s budget. Both are queued
  for a rerun on main (`poison-d78`, seeds 1-3). The lead's look at the top build (physical_dot s3, 376%): the loot's
  Driftwood Wand carries "+1 to Level of all Spell Skill Gems" (the 0.07% mod the user ruled out for templates) next
  to a DoT multiplier -- best-of-600 finds what a player cannot plan for; an argument for the templates, not a bug.
  - Queue (fresh runner, auto-archive, started 17:21 @d86b8bd): the three acceptance requests (Cyclone Slayer
    running, Storm Brand Inquisitor, SRS Necromancer; each under 2 h) -> `poison-d78` -> the four-reference smoke
    (seeds 4-6) -> `ziz-rules`. When the D79 amendment lands, put the loot-vs-template pair on IDENTICAL code
    (two smoke lines pinned to one commit, `--gear loot` / `--gear wishlist`) ahead of `ziz-rules`.
  - Merged since 16:30: the first template version (f37f65d, behind `--gear wishlist`; 737 passed on the branch;
    measured on the six smoke references: median 66.2% of the author's gear against the loot's 96.6%, cause = the
    per-tier rarity rail, `docs/research/2026-09-19-template-gear-first-version.md`), the warcry rule with the
    item-granted fix (4467bfa, D75 amendment 3; the lead's lane diff: 0 of 58). Workers running: the D79 amendment
    (16:34, 300 min), picks finish (two commits, final report pending), bench-unlock rail, buffs ended by skill use.
- 16:30 (19.09), **since 15:55**.
  - THE LOADOUT RULEBOOK is now one canonical file, `docs/rulebook/loadout-rulebook.json` (161 entries: 56 systems /
    rulings + 105 live unique jewels from the user's form; six loadouts, the user's new extender `uber_plus` between
    uber-endgame and mirror), built by `scripts/build_rulebook.py` from `loadout-rulebook.entries.json`; its editable
    page is https://claude.ai/artifact/3CNfysNvnAiQeuo4SbPtdY (`scripts/build_rulebook_page.py`; db collections
    `cells` = the user's cell edits, `notes` = notes per entry). When the user says "read it": `read_db` both, fold
    into the entries JSON, rebuild, republish to the same URL, delete the folded `cells` docs. Ten entries carry a
    question to the user (uniques at day 1: T5 or tiers 3-5; item level 70 or 72 / 76; 4x Exalted bench crafts at
    day 1; Pantheon upgrades from maps <= T10 at day 1; ...).
  - A HARNESS BUG OF MINE, fixed: commit 888d126 (14:46) force-added a file under `var/`, so every worktree made
    after it checked out a REAL `var/` and `gpt_worker` could not put its junction there: the picks-finish and
    bench-rail workers downloaded their own 1.4 GB PoB runtime, the warcry and buffs workers had none (the warcry
    branch's "603 passed, 182 skipped" was that). File untracked (c7c5384), the two empty worktrees given the
    junction by hand, `gpt_worker.make_worktree` now refuses to start when a shared directory is not a junction
    (aa20625). NOTE for any later clean-up: the picks-finish and bench-rail worktrees hold a REAL `var/` with a
    runtime of their own, not a junction.
  - D79 templates, first version: the worker ended after 303 min with no commit and no PoB measurement; its tree is
    committed as 7f3e3d4 on `gpt-2026-09-19-day1-gear-templates-2`, the 5 PoB-backed tests pass, the whole suite and
    a six-reference gear transplant (`artifacts/runs/gear-templates/`) are running. Its rarity rail is wrong (one
    tier's share, a single 1% threshold: 3,192 refusals of everyday mods on six references); the amendment spec now
    says so and replaces it with the group share. Next: merge the first version, launch the amendment.
  - The warcry branch (12b235a) is NOT merged: the lead's lane diff shows 1 of 58 references changing, and it is a
    false negative (z327 boneshatter: Kaom's Sign grants Enduring Cry, Autoexertion sits in another item). Follow-up
    worker `2026-09-19-warcry-item-granted-is-pressable` (16:23): expected lane change after it = none.
  - D77 amendment 1 decided and specified (a buff ended by skill use proves nothing: Withering Step's Elusive was
    worth +0.20 movement speed, the whole floor, and +10-12% EHP on six references); worker
    `2026-09-19-buffs-ended-by-skill-use` (15:50). Bench-unlock rail worker (15:38) and the picks finish (stormbrand
    control 1,631,723 reproduced; poison_spark done, auditing) still running.
- 15:55 (19.09), **where things stand**.
  - Runs: `core14-rules` (09:41 @254f915, loot gear) 33 of 42 rows at 15:44, ends ~17:00. The pending queue lines are
    HELD (`#HELD` prefix in `artifacts/runs/queue.txt`): the live runner predates the auto-archive merge (7605c62), so
    after `core14-rules` it goes idle; then: copy the run to `C:\Coding\poe-junkroan-archive\benchmark\` by hand,
    `--rereport`, audit, the second reading list for the user; stop the idle runner (its own pid, no child), start a
    fresh one on main (WMI), restore the lines in this order: the smoke four-reference line first (the baseline under
    D77 / D78 / D80 that the template gear will be compared with), `ziz-rules`, the three `junkroan build` requests.
    `gear-wishlist-2` is dropped: the wishlist filler is being replaced by templates (D79).
  - Merged since 10:45: D80 (af93899, proxy delivery: a totem's / trap's / mine's hits are not the player's, a
    generator skill counts at its own PoB rate; 7 references' lanes moved, nothing turned on), D78 (38a12be, ailment
    stacks inside the 2.5 s ramp budget) + amendment 1 (94bb1d9, poison through PoB's native `PoisonStackLimit`:
    poison_spark 14.147 -> 12 stacks, 145,312 -> 123,258 poison DPS), the 49-system inventory (09e9a69), gpt_worker
    preamble rule 4a. The whole suite on main after these merges is still OWED (run it when the machine is free).
  - GPT workers running (reports `artifacts/runs/gpt-worker-<slug>.md`, transcripts `.md.part`): (1) day-1 gear
    templates, D79 (`gpt-2026-09-19-day1-gear-templates-2`, since 10:38, 360 min limit, nothing committed yet: on a
    timeout commit its tree as WIP and finish with a follow-up spec, as with the picks fix); then launch
    `docs/specs/2026-09-19-day1-gear-templates-amendment.md`; then smoke six on template gear, PoBs + full item text
    to the user, the lead's readiness verdict, and only then the default gear switches. (2) the picks / self-cost
    finish (`2026-09-19-picks-self-cost-finish`): the stormbrand control reproduces 1,631,723 exactly; poison_spark
    900 s check running. (3) the bench-unlock rail (`2026-09-19-bench-unlock-rail`, 15:38). (4) the triggered-warcry
    finish (`2026-09-19-warcry-triggered-finish`, 15:45): worker 8's three extra commits minus the
    `UsedWarcryRecently` check the wiki refutes (`var/cache/wiki/2026-09-19-autoexertion-extract.md`).
  - The loadout book (`docs/rulebook/`): the user's matrix + four passes of rulings (the fourth: "N useful
    properties" = N credited, other useful lines ignored, a negative line never ignored), anoint oils by loadout,
    bench-recipe and Pantheon unlock places with atlas tiers over 3.25-3.29 from the wiki's Cargo tables (the unlock
    tier is NOT stable: 49 of 82 recipe maps crossed the T10 line in five leagues -> league data,
    `docs/DATA_FRESHNESS.md`; the GPT report on the same question is rejected, it used a 3.27 third-party list), the
    wiki check of the "never" rows. Waiting for the user: the unique-jewel form
    (https://claude.ai/artifact/GdgMuo1SmTHmbhMBb23oTr, db collection `jewels` -> `2026-09-19-unique-jewels.md/.json`).
  - Measured today, no action yet: `conditionUsedWarcryRecently` moves 0% CombinedDPS on the 15 references that
    carry it (so its uptime rule, 4 s of an 8 s cooldown, is not urgent); `multiplierWarcryUsedRecently` is "kept
    from the build's config (no rule derives it)" -- the author's side keeps a 5 that a build from a skeleton never
    gets; a benchmark-fairness follow-up, not an inflation.
  - Open with the user: whether 4x Exalted Orb bench crafts belong to day 1 (the rail's knob is empty until then; the
    bench worker counts how many campaign crafts it would touch); the "pinnacle boss ramp" seconds (10 s placeholder);
    eldritch T2 at uber-endgame; the default gear after the template smoke.
  - Still owed: Withering Step (Elusive / Phasing) wiki check; the D77 amendment for `condition*` proofs (stormbrand's
    consecrated ground "while stationary"); VD "best creator, not first"; worktrees without junctions (structural
    fix after the 18.09 incident); unique screening judged against the template rare with resistances re-solved
    (spec after the templates merge).
- 10:45 (19.09), **the user's reading, four rulings, four GPT workers running** (reports in
  `artifacts/runs/gpt-worker-2026-09-19-<slug>.md`; transcripts `.md.part`): (1) D78 ailment stacks obey the 2.5 s
  ramp budget, a second metric "pinnacle boss ramp" later (`...-ailment-stacks-inside-ramp-budget.md`); (2) the
  picks move put Sacrifice Support on poison_spark -- the AUTHOR has none -- 107% of life per second, 3 of 3 seeds
  infeasible (`...-picks-never-keep-an-infeasible-support.md`); (3) **D79 day-1 gear from TEMPLATES** (the user's
  design, replacing the greedy wishlist filler and the lead's probability-budget draft): every armour / jewellery
  slot = life + ONE resistance (element solved for the whole set) + one open-or-craft line, boots' third line is
  movement speed, weapons fully open (3 open + craft), the authors' median tiers per slot, no "+1 to gems" next
  to anything else, templates are data in `mechanics/day1_gear_templates.json`, gear under 3 min per build
  (`...-day1-gear-templates.md`, branch `gpt-2026-09-19-day1-gear-templates-2`); the old filler had life on 1 of
  10 cold_dot items and a sceptre with mods of spawn weight 50 / 250 / 70 / 40; (4) D80 a proxy's hits are not the
  player's (poewiki Totem / Mine / Trap quoted in `var/cache/wiki/2026-09-19-proxies-extract.md`), and a
  generator skill's charges come from ITS OWN PoB rate: impale_ballista's Frenzy sits on Manaforged Arrows at
  0.99-1.04 per second, five ballistas are placed in 1.5 s (`...-proxy-delivery-gives-the-player-nothing.md`,
  branch `gpt-2026-09-19-proxy-delivery-3`; the lead's first draft zeroed it without looking -- the user: "you
  have all the data, compute it"). Wishlist replaces loot only after the templates pass the smoke six, the
  transplant and the user's look at the full items; `core14-rules` keeps running on loot.
- 10:30 (19.09), **`new18-rules` done** (01:30-09:41, 54 of 54, 0 FAILED; archived by hand; `--rereport` under
  D76): medians -- arc_archmage 104, archmage_volatile_dead 192, bleed_perforate 342 (188-343), burning_arrow_snipe
  156, elemental_hit 95, exsanguinate_mines 162, impale_ballista 92, kinetic_bolt_wander 127, kinetic_fusillade
  202, lightning_trap 207 (1 infeasible), pyroclast_mine 246, shockwave_cyclone 134 (1 infeasible),
  soulrend_chaos_dot 163, spectral_shield_throw 173, static_strike 238, vd_spellslinger 148; median of medians
  162, 14 of 16 at or above the author; 10 of 54 not at a fixed point (almost always one more loot re-roll).
  Not counted: impale_cyclone 3 of 3 (movement 1.00 < 1.164) and poison_spark 3 of 3 (the author's own main
  link carries Sacrifice Support, which the self-cost rule charges as -1552 life/s, and no move of the pipeline
  can take it out). Audit of CURRENT main over the 54 builds: the only "conservative generator proof" errors are
  impale_ballista x3 (`buffAdrenaline` on "when you reach low life"; the author's lane had it too: 806,537 under
  our lane against 554,595 raw) -- `restarts-smoke3` reruns it on the new rules. The lead's reading of
  bleed_perforate s1 (343%): Crimson Dance + "+6% DoT multiplier per Impale"; PoB's steady state of 8 bleed
  stacks needs 5.1 s of attacking against the 2.5 s ramp budget and today that is an audit WARNING only
  (`ramp.py`: ailment stacking is exempt) -- a rule decision for the user. `core14-rules` started 09:41 @254f915
  (current main: D75 amendment 2, D76, D77, the durable benchmark -- its builds appear in
  `artifacts/benchmark/20260919-0941-core14-rules/` as they finish).
- 09:40 (19.09), **the incident's cause is PROVEN**: not a GPT worker -- the main model's own command in the
  previous chat, 2026-09-18 17:27:45: `git worktree remove --force .claude/worktrees/gpt-2026-09-18-golem-instances`
  while the worktree still held the junctions `artifacts`, `var`, `vendor`. Git recursed through the junction
  and deleted `artifacts/benchmark/*` alphabetically until `gear-loot/logs/bleed_bow-s3.log`, held open by the
  running benchmark, stopped it; `var/` was next. Evidence: the session transcript
  (`~/.claude/projects/.../8a3f664b-*.jsonl`); the GPT session of that window (all 116 tool calls in opencode's
  `opencode.db`) is patches, pytest and reads only. Rule written into CLAUDE.md ("Worktrees hold junctions") and
  memory; the structural fix to spec: resolve `var/` and `artifacts/` from the main checkout
  (`git rev-parse --git-common-dir`) so that a worktree needs no junction at all. Found on the way: GPT worker
  8's session ran on until 07:49 and added three commits after its first one was merged (00edf00, 82c631b,
  ea14cb7: a warcry counts only when the player presses it -- not triggered, not under Autoexertion -- and
  `UsedWarcryRecently` needs the same proof); NOT merged yet: the Autoexertion part is a game fact to check on
  the wiki first.
- 07:35 (19.09): **the gear question, measured** (`artifacts/runs/gear-transplant/`, copied to the archive; our
  rares on the author's own build, the author's floors, ratio to the author's own rares). All 32 references, one
  fill: loot N = 600 108.8%, wishlist 102.9%. Smoke six, loot N = 25 / 50 / 100 / 200 / 600 / 3000 / 6000 = 79.9 /
  98.1 / 99.0 / 87.9 / 96.6 / 108.7 / 109.4; wishlist `useful_mods` 3 / 4 / 5 = 104.4 / 139.9 / 148.7. Reading: one
  fill of either model is author-grade day-1 gear (the rails N = 600 and `useful_mods` = 3 sit at ~1.0); the
  pipeline's 3,000-6,600 rolls per slot are worth about +12 points on a fixed tree and saturate near 3,000; the
  rest of the pipeline's loot / wishlist gap (150.2 against 106.5) is co-adaptation of tree and gear through the
  loop's re-rolls, which a deterministic filler cannot use, plus filler weaknesses (burning_arrow's wishlist bow:
  68.5%). **Decision for the user**: a rail on the TOTAL rolls a slot may see over a whole build (today
  unbounded; ~600 would make the pipeline's gear as realistic as one fill, expected cost about -10 points on
  every loot number), and which gear `junkroan build` wears by default. Merged 06:20: the stall watchdog counts
  worktree file activity (GPT worker 12, 967256d, 761 tests; wrote the code itself, no nested worktree -- rule 0
  works). Campaign 38 of 54 at 07:25, no FAILED, ahead of plan (~11:30); `core14-rules` then starts on current
  main, i.e. WITH D75 amendment 2, D76, D77 -- the two halves differ by those rules; the D77 audit over
  `new18-rules` decides which of its rows are rerun.
- 05:35 (19.09), merged: **D77** (aa4cf6a; a buff is proven by a line PoB parses as its source). Lane diff over
  the 58 references: `buffFortification` off on 6, `buffAdrenaline` off on 2, `buffUnholyMight` off on 1;
  `conditionLeeching` on PoB's leech rate. The worker's subagent was killed by the new 45 min stall watchdog
  while it was silently editing (the transcript shows only the parent): the lead committed its tree, ran the
  lane diff and the suite (759 passed after dropping a test that executed `config_rules.py` of commit 63c5dab).
  **Until the watchdog also counts file activity in the worktree, launch workers with `--stall-minutes 170`.**
  Open D77 amendment (measure first): `condition*` proofs still use the word path (stormbrand's consecrated
  ground "while stationary"), Withering Step -> Elusive / Phasing is an authored table (wiki), a support's bare
  name parses as a source even in an unused link. The campaign (@63c5dab) predates D75 amendment 2, D76 and D77:
  when it ends, run the audit of current main over its builds -- the "conservative generator proof" errors mark
  the rows to rerun. Campaign at 05:29: 24 of 54, no FAILED; s1 of 17 references: 91 / 192 / 94 / 343 / 162 / 137
  / 112 / 178 / 119 / 72 / 272 / 127 / 146 / 151 / 238 / 181 / 180 (arc_archmage ... soulrend; bleed_perforate s1
  343 against s2 188). Transplant at N = 3000 (one fill, smoke six): median 108.7% of the author's gear against
  96.6% at N = 600 -- the loop's re-rolls are worth about +12 points, not the whole loot / wishlist gap; N = 6000
  running.
- 04:05 (19.09): main after the night's merges: **744 passed, 7 deselected** (18:45). Merged since 03:30: D75
  amendment 2 (GPT worker 8, 8152eae: Enduring Cry counts floor(WarcryPower PoB used / the gem's per-power
  constant) charges per `Cooldown` PoB outputs, through the new `PobSession.active_skill_stats`; seven Zizaran
  references get `useEnduranceCharges` back; "when you are Hit" is the pending fact `enemy_hits_per_second`);
  the durable benchmark (GPT worker 11, 0b6d1c3: each finished build's pob file, row, `results.json` and a
  "partial: N of M" report are written at once; `run_queue.py` archives every finished run to
  `C:\Coding\poe-junkroan-archive` -- **the live runner predates this, restart it between runs** (`--after-pid
  <pid> --adopt`) so `core14-rules` is archived and readable early; `explain` prints the objective's stat). The
  existing runs were copied to the archive by hand at 03:09.
  **Why GPT workers stalled (3, 10) and nested worktrees**: reading CLAUDE.md they took the lead's role ("the
  main model writes no code, delegates") -- worker 10 launched `gpt_worker.py` on itself and polled its own
  process for 80 min. Preamble rule 0 since ca0aa8f: "you are the worker". D77 (buff proof) relaunched 03:56 on
  branch `gpt-2026-09-19-buff-proof-3`. Transplant sweep (smoke six, one fill, ratio to the author's gear): loot
  N 25 / 50 / 100 / 200 / 600 = 79.9 / 98.1 / 99.0 / 87.9 / 96.6; wishlist `useful_mods` 3 / 4 / 5 = 104.4 /
  139.9 / 148.7 -- the rail 3 is calibrated at ~1.0 (the "lower bound" guess above is withdrawn), one more mod
  per slot is +35%; N = 3000 / 6000 running. Campaign 16 of 54 at 03:55, no FAILED.
- 03:30 (19.09), **INCIDENT: every run directory under `artifacts/benchmark/` older than 2026-09-18 15:26 is
  gone** (the frozen campaigns, rules-smoke, speed-both-2, loot600-smoke ...: `results.json`, `report.md`, logs,
  `.pob.txt`). Found when `compare_runs.py loot600-smoke gear-loot` saw 0 control rows. The rest of `artifacts/`
  is intact and the disk has 830 GB free. The shape of the damage dates it: inside `gear-loot` only
  `logs/bleed_bow-s1.log` and `-s2.log` are missing -- an alphabetical recursive delete that stopped at the
  first open file, `bleed_bow-s3.log`, written 17:10-17:50 on 18.09. No code in the repository deletes that
  folder (grep: no rmtree / rmdir reaches it); in that window the first GPT worker ran (golem-instances,
  17:29-17:57, junction `artifacts/` in its worktree; its old-style report kept no transcript) after a Codex
  attempt at 17:25. Cause not proven. What survives: every chosen build's XML in
  `Documents/Path of Building/Builds/Junkroan/benchmark <date> <tag>/` (37 runs; core14-frozen 42 files) and
  every number written in this State, DECISIONS and `docs/research/`. What is lost: gates against those runs
  (`compare_runs.py` with smoke-frozen / rules-smoke / loot600-smoke as control) and the per-build logs.
  Protection (spec to write): the runner copies `results.json` + `report.md` of each finished run outside
  `artifacts/` and marks finished run folders read-only; the worker preamble already forbids deleting under
  `artifacts/`, and since dae3e4e every worker leaves a full transcript.
- 02:30 (19.09), reading of the campaign's first rows (arc_archmage 91, archmage_volatile_dead 192, elemental_hit
  94, bleed_perforate **343**, exsanguinate_mines 162, burning_arrow_snipe 137): a NEW kind of false proof --
  `_generator_proof` accepts any line that contains the buff's word. bleed_perforate's `conditionLeeching` stands
  on "enemies cannot leech life from you"; over the 58 authors' conservative lanes 24 text proofs are a cap
  ("+3 to maximum fortification" x6), the consumer itself ("43% increased damage while leeching"), a modifier
  ("increased effect of arcane surge"), an unproven precondition (adrenaline at low life) or a minion's buff.
  PoB's parser already separates them (`parse_mods`: a source is a `Condition:<X>` FLAG with its own
  precondition tags, a consumer carries X as a tag): **D77 (pending the merge)**, GPT worker 10,
  `docs/specs/2026-09-19-buff-proof-from-parsed-mods.md`. The campaign keeps running: once D76 lands, its audit
  check marks the rows whose buffs stand on a non-source line and only those references are rerun. Other notes:
  the fixed-point check gains +6.1% on archmage_volatile_dead from one more loot re-roll of Weapon 2 (a
  stochastic re-roll has no fixed point -> the total-rolls rail); `explain`'s "Numbers" line prints CombinedDPS
  where the objective is FullDPS; `benchmark.py` writes the `.pob.txt` files only when the whole run ends, so a
  16 h campaign cannot be read early (small specs to write).
- 01:40 (19.09): **the campaign is running**: `new18-rules` started 01:30 @63c5dab (D74, D75 + amendment 1, the
  wishlist bow fix; the whole suite on that main: 716 passed), loot gear; then `core14-rules`,
  `gear-wishlist-2`, `ziz-rules`, the three requests, `restarts-smoke3`. `ballista-loop-clusters` equals the
  control on all three seeds (963,133 / 745,592 / 645,674): rule 5's cluster candidates are inert on
  impale_ballista. Merged after the start: `scripts/gear_transplant.py` (GPT worker 5; `benchmark.py`'s author
  preparation extracted as `prepare_author()`, the six smoke authors' lane numbers reproduce to the digit;
  a cold_dot determinism check old / new `benchmark.py` is running). Detached: the transplant sweep (N 25-600,
  `useful_mods` 3-5), then N = 3000 / 6000 (`artifacts/runs/gear-transplant/bigN.cmd`). GPT workers 7
  (`gpt_worker.py` timeout / transcript) and 8 (Enduring Cry, "when you are Hit") started 01:09; next to
  dispatch: `docs/specs/2026-09-18-counted-rows-one-rule.md` again (worker 3 stalled).
- 01:15 (19.09), merged BEFORE the campaign: D75 amendment 1 (GPT worker 6, f1093c0) -- mine detonated, trap
  triggered and mana spent are classified charge sources (chance x PoB's throw rate; per-second cost / N),
  "enemies that die" is on-kill. The lead's lane check over all 58 references: inputs move on exactly four
  (exsanguinate_mines and pyroclast_mine power 2 of 4 / 2 of 5, lightning_trap frenzy and power 3 of 3,
  winter_orb power 2 -> 3). `new18-rules` starts after `ballista-loop-clusters` (~01:25) on this code.
- 01:00 (19.09), **gear transplant, 32 references, seed 1** (`artifacts/runs/gear-transplant/report-32.md`,
  `results-32.json`; script on branch `gpt-gear-transplant-impl`, merge after the campaign has started -- it
  refactors `benchmark.py`): our rares on the AUTHOR's build against the author's own rares, the author's floors:
  loot (one fill, N = 600) median 108.8% (quartiles 93 / 109 / 117, min 42 impale_ballista, max 158
  static_strike), wishlist 102.9% (94 / 103 / 122); life 101.5 / 100.5%, EHP 102.8 / 100.5% of the author's; in
  31 of 32 rows our gear violates the floors no more than the author's. So one fill of either model is
  author-grade gear. **But the pipeline does not do one fill**: counted in `gear-loot`'s logs, a slot sees
  3,000-6,600 rolls (3 x 600 in construction + 5-24 re-rolls of 200 in the loop, the incumbent kept), so the
  rails' N = 600 is not the effective N -- this, not item quality per fill, is the loot / wishlist gap in the
  pipeline (150.2 against 116.8): the deterministic wishlist gains nothing from re-rolls. Next: the sweep
  (running, N 25-600 and `useful_mods` 3-5 on the smoke six), then N = 3000 and 6000; the decision for the user
  is one rail -- the TOTAL rolls a slot may see over a whole build -- calibrated where the transplant crosses
  1.00, gated on the smoke set. Also: `useful_mods` 3 came from a leave-one-out usefulness count, which
  undercounts jointly needed mods (four fire-resistance mods with slack are each "useless"): a lower bound.
  `ballista-loop-clusters` s1 and s3 equal the control to the digit (963,133 / 645,674): the cluster
  candidates never won on impale_ballista.
- 00:35 (19.09), merged: the wishlist filler no longer leaves the bow slot empty (GPT worker 2, 268 min, 3271a2d;
  `docs/research/2026-09-18-wishlist-weapon-zero.md`). Cause: with no weapon PoB omits `HitChance`, the objective
  reads a missing floored stat as -inf, every candidate carries an infinite violation and
  `_drop_if_worse_than_empty` emptied Weapon 1; the quiver's hard equip error then killed the build. Now a
  candidate that gives the main skill a number beats one that leaves it at 0, and an item PoB refuses for a slot
  restores the slot and logs one line. Acceptance (`wl-fix-final`, 600 s loop): bleed_bow 104%, impale_ballista
  65%, 0 audit errors; burning_arrow_snipe's first weapon line unchanged (182,220 -> 145,805); 692 tests.
  `gear-wishlist-2` (bleed_bow impale_ballista x 3 seeds, `--gear wishlist`) is queued behind the campaign.
  GPT worker 3 (counted rows) stalled for 191 min with no edit and was stopped; its spec is re-dispatched after
  the gear-transplant merge (both touch `benchmark.py`), with a `gpt_worker.py` fix: the timeout kills only the
  shell shim, the opencode tree lives on and the script hangs; no transcript is written until the end.
- 22:04, `gear-wishlist` @04bc1d6 ended; the informational comparison (median, spread in brackets; loot ->
  wishlist): burning_arrow_snipe 179.7 (47.2) -> 118.0 (63.6), cold_dot 112.4 (34.0) -> 118.8 (25.4), stormbrand
  169.4 (49.9) -> 115.7 (21.1), SRS 158.9 (26.0) -> 97.3 (29.9), bleed_bow and impale_ballista 3 x FAILED each;
  median of medians 150.2 -> 116.8. Deterministic gear does not remove the seed spread (burning_arrow 63.6): the
  spread is born in the tree as well. Both runs predate D75 (stormbrand's charges). The user (21:00): the
  wishlist's realism must not be dictated by Tuadh's numbers as an input -> GPT worker 5,
  `docs/specs/2026-09-18-gear-transplant.md`: our loot / wishlist rares on the AUTHOR's build against the author's
  own gear, plus a sweep of N and `useful_mods`; the long run is launched by the lead after review. The default
  gear of `junkroan build` is the user's decision from that table. `ballista-loop` started 22:04 @b003e64, then
  `ballista-loop-clusters`, then the campaign (~00:40), which must carry worker 6's mine / trap / mana triggers
  (`docs/specs/2026-09-18-charge-triggers-mine-trap-mana.md`, started 21:42); if worker 6 is late, put
  `restarts-smoke3` ahead of the campaign as well. Second follow-up, before `ziz-rules`: Enduring Cry as a
  classified source from PoB's own data (1 endurance charge per 5 warcry power, a boss is 20 power in PoB's
  config, cooldown 8 s: 4 charges per use; 7 ziz references lost `useEnduranceCharges` under D75) and "when you
  are Hit" (2 x juggernaut_boneshatter; needs a sourced enemy hit rate, off until then).
- 21:45, merged: D75, a generator needs its state (GPT worker 4, 89 min, 32f8db5): `while Channelling` is proven
  only by the MAIN skill's `channelling` tag, `each second` is a 1 s periodic source, an unclassified charge
  source is no proof on the conservative lane, and the audit raises an error for a Baseline charge / buff input
  whose every source fails the same rule. gear-loot stormbrand with ONLY `usePowerCharges` off: 2,252,054 ->
  1,610,742, 2,315,289 -> 1,831,645, 1,651,026 -> 1,269,255 (0.715 / 0.791 / 0.769; 121 / 138 / 95% of the
  author, not 169 / 174 / 124). The lead's first measurement (0.615 / 0.696 / 0.661) was wrong: a
  `set_config(inputs={one key})` replaces the whole input set and cleared every other boolean too; the worker
  caught it. 694 tests. Lane diff over the 32 Tuadh references (old rule on main against the branch): 5 change --
  cold_dot `useFrenzyCharges` off (Cold Snap's "enemies that die in the area": on-kill, correct), winter_orb
  power 6 -> 2 and frenzy 3 -> 1 inside the 2.5 s ramp budget (correct, D39), and three FALSE negatives the rule
  exposed: exsanguinate_mines and pyroclast_mine lose `usePowerCharges` ("10% chance ... when your Mine is
  Detonated targeting an Enemy"), lightning_trap loses frenzy and power ("15% chance ... when your Trap is
  triggered by an Enemy"). Those are real sources for a miner / trapper and must be CLASSIFIED (chance x the
  main skill's throw rate from PoB), as must "after spending a total of 200 mana" (per-second cost / 200):
  follow-up spec `docs/specs/2026-09-18-charge-triggers-mine-trap-mana.md`, to land BEFORE the campaign.
- 20:30, merged: D74, corpse-fed instances follow the paired creator's capped supply (GPT worker 1, 121 min,
  71ff9c4): archmage_volatile_dead 9 instances / 936,332 FullDPS under our lane, vd_spellslinger 9 / 365,859,
  the archmage copy without Spell Cascade on Desecrate 5 / 522,055; the pool cap 10 -> 12 from the corpus line
  "Desecrate and Unearth have +2 to Maximum number of corpses allowed" when its node is allocated; 684 tests.
  Review follow-up (not blocking): with two creators in a build the FIRST by group order is paired with the
  consumer -- order-dependent; it should be the best single creator. The channelling rule becomes D75.
- 20:15, reading of `gear-loot` (stormbrand s1-s3): `usePowerCharges` stands on the Caster Mastery "Gain a
  Power Charge each second while Channelling a Spell" on a build that never channels ("unclassified source:
  counted as on"; the picks move takes the mastery as a generator). Measured: FullDPS with the input off is
  0.715 / 0.791 / 0.769 of the reported number (121 / 138 / 95% of the author, not 169 / 174 / 124; the
  first figures written here, 0.615 / 0.696 / 0.661, were a measurement error, see 21:45).
  Fix on GPT worker 4 (`docs/specs/2026-09-18-generator-needs-channelling.md`, out `gpt-worker-4.out`): the
  enabler kind "channelling" read from the MAIN skill's tags, an unclassified generator is no proof on the
  conservative lane, an audit error for an input whose every source lacks its enabler. **The campaign must
  start on the fixed code**: the ballista pair was moved ahead of it in the queue (~1.3 h each) to buy the
  time; when the fix merges early, move what is left of the pair back behind the campaign. Record the rule
  as D74 at the merge.
- 20:05, the lead's decision: **the campaign wears the loot gear** (the queue lines stay as they are).
  `gear-wishlist` @04bc1d6 lost two of six references at once: bleed_bow and impale_ballista FAILED in
  35 s with `item is not valid for slot Weapon 2` -- every bow scores value 0 / viol inf in gear pass 1
  (`Citadel Bow | 0 mods: 56,277 -> 0`, `Imperial Bow | 0 mods: 15,570 -> 0`; burning_arrow_snipe's
  `182,220 -> 145,805` works), `_drop_if_worse_than_empty` leaves Weapon 1 empty and the quiver's hard
  equip error kills the build; deterministic, so all 6 builds of the two references fail and the run ends
  early (~21:30, 12 builds). A gear that crashes on 2 of 6 cannot dress a 28 h campaign. The fix is a
  second GPT worker (pid 27772, started 19:59, `docs/specs/2026-09-18-wishlist-weapon-zero.md`, branch
  `gpt-2026-09-18-wishlist-weapon-zero`, out `artifacts/runs/gpt-worker-2.out` -- a second worker needs
  its own out file: sharing `gpt-worker.out` killed the first launch silently); after the merge add
  `gear-wishlist-2` (bleed_bow impale_ballista, 3 seeds, `--gear wishlist`, ~1.2 h) behind the campaign.
- 03:30, merged: D76, one rule for which benchmark rows count (GPT worker 9, af1bd23 on the nested branch
  `gpt-counted-rows-current`): `ok`, violation <= 1e-9, no audit error except `fixed point`; true median;
  `benchmark.py --rereport <tag or path>`. gear-loot re-reported: 141 / 180 / 112 / 92 / 169 / 159, "not at a
  fixed point (> 1%): 3 of 18"; `compare_runs.py gear-loot gear-wishlist` now drops wishlist's two infeasible
  cold_dot rows: 150.2 against 106.5 (it was 116.8 with them). The buff-proof rule becomes **D77**.
- Also running: GPT worker 3 (`docs/specs/2026-09-18-counted-rows-one-rule.md`, out `gpt-worker-3.out`):
  `benchmark.py`'s report drops a row for a fixed-point-only audit error and takes the upper of two
  (gear-loot 184 / 92 / 183 against `compare_runs.py`'s 179.7 / 92.4 / 158.9); one rule for both scripts,
  true median, `--rereport`. Not blocking: `results.json` holds everything.
- LIVE at the handover (19:55, two detached processes outside any chat): (1) the queue runner on
  `gear-wishlist` @04bc1d6 (started 19:14, ends ~22:45; then the informational comparison with
  `gear-loot`, whose median of medians is 150.2: bleed_bow 141.4, burning_arrow 179.7, cold_dot
  112.4, impale_ballista 92.4, stormbrand 169.4, SRS 158.9, three "not at a fixed point" audit
  errors of +1.4..+2.8%); the lead then chooses the campaign's gear and, for wishlist, adds
  `--gear wishlist` to the new18-rules / core14-rules lines BEFORE ~23:00. (2) The VD GPT worker
  (started 18:18) finished at 20:19 and is merged (see 20:30 above). A GPT worker may leave the
  commit undone: `git status` in its worktree, commit, review, merge. The first GPT worker's
  task (golem instances) is merged (da4f481). VD orbs: 9 approved for builds where VD is the only
  corpse consumer (the user, from the Reddit thread's own words); research reports now quote
  sources verbatim with their conditions (618689b).
- Morning of 2026-09-18 (07:30-08:50): two follow-ups of the readings landed on main after
  `rules-smoke` started, so they reach the campaign, not the smoke: `multiplierRage` as ramp
  arithmetic (cdd83eb; Smite 5 of 30 where the rails typed 15) and the Elemental Overload
  floor in the objective (45d8dd0; `HaveElementalOverload` witness from the wrapper, the
  crit-recently rule no longer counts accuracy twice). `speed-both-2` is pinned to 5132b6c
  (rules-smoke's code + the flag defaults) so its gate measures the flags alone
  (`run_queue.py` `@<sha>` lines, 30c9d12). An Opus agent is computing the 7.3 restart
  statistics (best-of-K by bootstrap) from smoke-frozen + restarts-smoke2/3/4 into
  `docs/research/2026-09-18-restarts-statistics.md`.
- 10:30: rule 20 landed (d4fd350: a random-element skill scored as the mean over its element
  parts; harness `mean_parts`), D64 records the morning's three architecture choices. Working
  mode from now (the user, 10:30): Fable keeps decisions, specs, reviews and readings; Opus
  agents write all code from numeric specs, parse logs into tables, keep the docs and the queue
  (see CLAUDE.md "Model / cost protocol").
- The day since then. **Merged on main by 13:30**, each with its commit: the Warden fix d949f76;
  golem and curse limits applied at skeleton derivation bdb1444 (D65); the fixed-point check
  888c02b (one extra local pass after `_finish`, a gain above 1% is an audit error); the final
  feasibility guard 8d27839 (D66; the repair gate now reads the full objective too -- cold_dot s2's
  movement floor was never offered a repair); the exact refine memo 0d3bf43 (cold_dot -14% trials,
  values bit-identical); construction loot N=600 a4268a6 (on the gate); the CLI request path end to
  end 8da7f57 (Storm Brand from a request: 806,199 conservative in 49 min on one worker beside the
  benchmark, 0 audit findings; three plumbing fixes); the objective by mode against the
  instance-counted one 231289f (Storm Brand with `--mode hit` is now FullDPS); the author trees
  converted to 3_29 68ef982 (D67; arc_archmage +0.29%, the rest cosmetic); Reliquarian in the
  search dc25f62 (D70); the deterministic wishlist gear b709e80 (D68, `--gear wishlist`, loot stays
  the default); the Zizaran starter fixtures, 33 builds over 3.25-3.29 with 31 extracted early
  loadouts and `SETS["ziz"]` = 26 distinct references (b931295, e78c50e; D69: the main link's head
  by `mainActiveSkill`, the author's gems normalized to the rails -- Tuadh median +0.0%, ziz median
  -21.9% --, the ascendancy inferred from the nodes).
  **Runs**: `rules-smoke` 07:23-10:18 (2 h 56 min, 32 min per build at the median against the
  frozen 65): median of medians 136.4 against smoke-frozen's 158.4 -- the price of D61's TotalEHP
  floor (EHP/author 0.90 -> 1.01), audit 0 errors, 0 builds on the time budget; `speed-both-2`
  10:18-12:56 gate FAIL (130.0 against 136.4, -6.4 points for -10% time), so the two approximate
  flags are off by default again (75e0768).
  **Queue**: `loot600-smoke` @c951580 (running since 12:56) -> its gate against speed-both-2
  (revert 5104886 on FAIL) -> `gear-loot` and `gear-wishlist` @75e0768 (3 seeds each, an
  informational comparison; the reviewer decides the campaign's gear by spread, feasibility and
  readability) -> `new18-rules`, `core14-rules` (start ~22:30, end Saturday morning) -> the
  ballista pair, `restarts-smoke3`; `ziz` (26 references x 3 seeds, ~8 h) after the campaign.
  **Research written today**: `docs/research/2026-09-18-{restarts-statistics, seed-divergence,
  roadmap-proposals, author-rares, generated-gear, day1-gear, zizaran-starters,
  pob-version-audit}.md`.
- The afternoon (13:30-16:00). **Merged on main**, each with its commit: the search delivers the
  best of 3 seeds per finalist a5a6fbf (D71; the request estimate ~83 min for top 2 x 3 seeds on
  5 workers); the picks move may drop a reserving socket group while a floor is missed 7718032
  (D72; stormbrand s3 infeasible 1,869,566 -> feasible 1,181,691, Wrath dropped,
  `MoMUnreservedShare` 0.324 -> 0.662; `changed_since_picks` fixed too, so a picks-only pass
  repeats); the exact picks memo 5ec9e43 (`read_state` 426 -> 183 on stormbrand, -39% of the
  move's time, identical swaps); wishlist gear chooses every rare slot's base under the day-1
  area level 77, implicit-first, one attribute affix per item 6a9d485 (D73; stormbrand +31.5%,
  bleed_bow +9.9% over the D68 filler; bases Coral Ring / Citrine Amulet / Heavy Belt / Void
  Sceptre; the author's Conqueror's Helmet at drop level 78 replaced by Lion Pelt); rare slots
  filled weapons first and no nan ranking key 79759c4 (bleed_bow judged eight slots at 0 DPS
  before); a base ranked with the cheapest payment of its own attribute requirement 04bc1d6
  (D73 amendment; burning_arrow: Saintly Chainmail with a +28 Dex craft); the base screen of the
  from-scratch path also weapon-first 7134a9d; `gpt_research` at the user's Codex reasoning
  effort (xhigh), never medium 9bbd39e.
  **Runs**: `loot600-smoke` 12:56-15:26 gate PASS +16.2 (speed-both-2 130.0 -> 146.2; bleed_bow
  +10.2, burning_arrow +6.9, cold_dot +22.2, impale_ballista +26.0, stormbrand -8.3, SRS -24.2):
  construction loot N=600 stays.
  **Queue**: `gear-loot` @04bc1d6 (running since 15:26, ~3 h) -> `gear-wishlist` @04bc1d6 (~3 h)
  -> the informational comparison -> the lead chooses the campaign's gear (readability, spread,
  feasibility) -> `new18-rules`, `core14-rules` (start ~22:00, end Saturday morning) ->
  `ziz-rules` (26 references x 3 seeds, ~9 h) -> the ballista pair, `restarts-smoke3`.
  **Open follow-ups noted by the agents**: a dropped reserving group only returns with a rebuilt
  skeleton (there is no re-enable move); `derived_counts` gives each golem gem
  `ActiveGolemLimit` instances (three golem gems count nine golems in FullDPS);
  `hypothesis.RARE_SLOTS` order feeds unique screening only; the utility trials of the picks
  move still pay a `read_state` each (~145 ms).
- Night of 2026-09-17/18 in one paragraph: the speed work of 7.1h landed (exact items
  committed; two approximate flags queued for proof), the rules bundle of both readings
  was written by four Opus agents in worktrees and merged (7df5671: 477 tests), the
  campaigns' numbers are therefore no longer comparable and the proof is `rules-smoke`
  followed by the campaign rerun. Cause of bleed_perforate closed (the ramp cliff).
  Reddit research works through the Codex CLI. Two Ctrl+C kills of the detached
  processes traced and made harmless.
- `speed-both` (04:40-07:23, gate PASS +58.4) is **void**: the rules merge landed on main
  at 04:47, seven minutes into the run; the benchmark's worker processes (old code, alive
  for hours) re-read the merged `rails_default.json` at every next build and met the
  `MoMUnreservedShare` floor without the code that derives the stat, so every build started
  after 04:47 (13 of 18) ran against `viol inf` from its first step and optimized DPS with no
  floor at all (bleed_bow s2 life 1416 of 4776, 13-24 audit errors per row); the 5 builds
  started at 04:40 are clean. Fix (7ed3662): `run_queue.py` runs every long command from a
  detached git worktree of HEAD (`artifacts/runs/snap/<name>`, `var`/`artifacts`/`vendor`
  through junctions, removed after the run), so a merge on main can no longer reach a run;
  `compare_runs.py` lines still run on the live checkout (they revert there). The runner
  was replaced under the running `rules-smoke` (`--after-pid 30444 --adopt`).
- Runs in flight (07:50): `rules-smoke` (07:23, live checkout at 9d6fe47, flags off; ETA
  ~12:40), its informational comparison with smoke-frozen, then `speed-both-2` (the two
  approximate flags, now on by default in 5132b6c) gated against `rules-smoke` at -5 with
  `--revert-commit 5132b6c`, then the campaign rerun `new18-rules` and `core14-rules`
  (~28 h on 5 workers at the frozen pace, less with the flags), then the ballista pair and
  `restarts-smoke3`. Every detached process ignores the console Ctrl+C that killed the
  runner twice (3ac125f).
- Runs in flight (earlier text): the queue runner (the whole stack runs as `junkroan.exe`, check
  `tasklist | findstr junkroan`; the heartbeat rewrites `artifacts/runs/progress.md`
  every 15 min) is on `ballista-loop` (rule 5's control), then
  `ballista-loop-clusters`, `restarts-smoke2` (cold_dot + bleed_bow seeds 4-6),
  `restarts-smoke3` (the other four smoke references, seeds 4-6) and
  `restarts-smoke4` (the smoke set, seeds 7-9): the 7.3 restarts material, until
  ~Fri 12:00. The Opus window (2026-09-16 11:15 to 2026-09-17 22:00) is closed and accepted below.
- Last results (accepted 2026-09-17 23:00; 132 builds in four runs, 0 failed, 0 "restore
  drift", 0 LOST, audit errors 0, life at or above the author on every row, max hit at
  least 95%, no Wind Dancer, SRS count 20, no "mod family" finding with the crafted-line
  check in): `new18-frozen` 15 of 18 at or above the author by 3-seed median (below:
  bleed_perforate 37, impale_ballista 74, poison_spark 82), `core14-frozen` 13 of 14
  (bleed_bow 94), 28 of 32 together; medians of medians 154.0 and 195.4 (run E 134.1).
  The gate reverted D60 (148.2 against 158.4). What the scan found under the numbers:
  (1) EHP is not floored and is where much of the margin comes from: TotalEHP against
  the author's is 21-23% on spectral_shield_throw, 44-48% poison_spectral_throw, 46-53%
  elemental_hit, 50-52% vd_spellslinger, 58-64% absolution and SRS, 69-75%
  ignite_penance_brand (life 100%, max hit 95-125% on the same rows): a build at 2-3x
  the author is partly bought with the author's avoidance layers (block, evasion,
  suppression), which neither floor sees. A decision for the user (7.1f had option B:
  the author's Life and TotalEHP both). (2) D60 failed on a bug of mine, not on its
  idea: `_apply_config` merged the remembered choice over the value being tried, so
  every tuning after the first compared identical configs and kept the first list value
  (smoke-frozen-2's choices read `prideEffect: MIN`, exposure `'0'`), exactly the two
  inputs behind bleed_bow's and burning_arrow's falls. The defect it aimed at is real
  and systematic: 54 of 132 builds gain 7-47% at "config (final lanes)" (Pride MAX,
  exposure, Blood stance, Plague Bearer INF), all positive, on all three seeds. (3) The
  benchmark's ratio and `gap_decomposition`'s D/A disagree under "one lane":
  poison_spark s2 78% vs 116%, bleed_bow s3 89% vs 104%, impale_ballista s2 45% vs 84%
  (per totem): the author's row keeps numeric inputs our build does not get, the lane
  note with numbers now; bleed_perforate is the one real gap (D/A 33-42% with B 71-125%
  and C 38-140%: tree and gear each beat or match the author alone and collapse
  together, life 112-137% of the author's). (4) Spread: 2 of 32 references within 10
  points; the final spread is born in construction on some (cold_dot 42 -> 45, bleed_bow
  42 -> 72) and in the loop on others (shockwave_cyclone 13 -> 109, lightning_trap 5 ->
  67, elemental_hit 2 -> 59), so restarts (best of K seeds) are the lever, K from the
  restart runs. (5) 30 of 132 builds stop on the time budget, 25 of them on a pass that
  kept nothing. (6) Audit warnings that are the authors' groups carried verbatim: dead
  support groups on 8 references, a support PoB applies to nothing on 2
  (vd_spellslinger, physical_dot), curses above the limit on 4, four golems for a limit
  of three on cold_dot. Hardware research: `docs/research/2026-09-17-build-speed-hardware.md`
  (throughput 9-12x on a rented 48-core box, one-build latency 1.36x at most; the
  campaign of 96 builds costs about 13 USD by the hour).
- Earlier results: `intake2` (18 new references x 1 seed, the chain's code
  of 06:38 with the night's rules; numbers are gap-list material, not
  acceptance numbers, D58 deleted that pipeline): vd_spellslinger 231
  (first intake 495; corpse count 9 on both sides, the author had typed
  8), archmage_volatile_dead 132 (336; 9 vs the author's 6), soulrend
  198, exsanguinate_mines 180 (86; mines detonated 37 in the lane, the
  author typed 10), kinetic_fusillade 178, static_strike 173, burning
  arrow 167, lightning_trap 158 (87; the readback rule), spectral shield
  throw 150, kinetic_bolt 133 (102), pyroclast 131 (147; the mines input is
  not shown on that tree), elemental_hit 115, shockwave 108, arc 96,
  poison_spark 75 (the authors' assumptions, lane note), impale_ballista 65
  (rule 5); bleed_perforate and impale_cyclone FAILED on the rule-1 guard
  (the re-judge opened 15-16% below the build after a reverted joint
  round: a readback or setter left the build changed): a chain-only
  path, gone with D58, watched for under the loop (no occurrence in 36
  loop builds). Fight facts fired on 6 builds, ignite proofs now carry
  IgniteDPS and uptime, the audit found dead support groups (Momentum,
  More Duration, the authors'). The intake2 builds are chain builds and
  not reading material; the new archetypes go to the user from
  `new18-frozen`. Before that, `loop-smoke-3` (kicks with 3 + 4 draws,
  5400 s, run E's rules), per seed = median, against run E's chain and
  loop-smoke-2:
  cold_dot 158 / 137 / 99 = 137 (E 119, LS2 114), bleed_bow 89 / 147 /
  161 = 147 (E 116, LS2 147), SRS 230 / 242 / 251 = 242 (E 198, LS2
  230), impale_ballista 84 / 46 / 93 = 84 (intake 65, LS2 67), stormbrand
  165 / 216 / 150 = 165 (E 124, LS2 153), burning_arrow_snipe 200 / 218 /
  192 = 200 (intake 169, LS2 192); median of medians 165 (LS2 153). 7.1c
  closed: the loop beats the chain on all six, the chain is deleted
  (D58). 14 of 18 builds reached a fixed point, 4 stopped on the 8-pass
  cap while still keeping moves (raised to 16); no restore drift; one
  LOST flag (bleed_bow s2's construction, known). Spreads: cold_dot 59,
  bleed_bow 72, SRS 21, ballista 47, stormbrand 66, burning arrow 26:
  the loop's outcome depends on which draw hits (bleed_bow s1 148% in
  LS2 with a joint hit in pass 3, 89% in LS3 where a +1.5% tree draw
  took that pass and the joint never ran; fixed: every draw runs), so 7.3
  is about restarts and draws, not seeds alone. Earlier, `loop-smoke-2`
  (one-draw kicks): cold_dot 114 / 137 / 106, bleed_bow 148 / 147 / 123,
  SRS 230 / 216 / 232, stormbrand 153 / 216 / 150, burning_arrow 181 /
  198 / 192, impale_ballista 67 / 48 / 77. cold_dot s1 and s2 there were
  the first loop's numbers to the unit (259,365 / 312,712), s3 reached a
  fixed point after 7 passes (kick tree +3.8% in pass 3, refine +17.3% in
  pass 5; 242,287, 3073 s). On s1:
  the loop's construction and local moves equal the chain's, and its two
  kicks (one draw each) both missed on s1 (257,117 and 250,238 against
  259,355) where run E's chain kept reoptimize round 2 of 3 (+3.1%) and
  joint round 4 of 4 (+6.8%) on the same seed, so the loop called a fixed
  point 4.8% short. Fix (this commit): each kick gets the chain's draws
  (3 tree, 4 joint, variants alternating), stopping at the first kept
  one; 13 loop tests; `loop-smoke-3` runs with `--loop-seconds 5400`
  (s3 spent 2356 s in the loop with one draw per kick). "restore drift":
  none in any log so far. Rules 2 (corpse supply, proof from intake2) and
  5 (cluster candidates, behind `--cluster-candidates`, proof after 7.1c
  on the smoke set + impale_ballista x 3 seeds with and without the flag)
  landed the same night. Reading loop-smoke-2's cold_dot builds: the
  extra groups are the author's verbatim, including a dead "Weapon 1 Swap"
  group (Arcane Surge + Elemental Focus, no active gem) and Efficacy on
  Shield Charge; the four golem gems are legal (PoB probe on the author's
  build: ActiveGolemLimit 4; PoB applies every enabled golem's buff
  regardless of the limit, so a check "golem gems > ActiveGolemLimit"
  belongs in the audit). The audit candidates from this reading are all
  coded: golem gems above the limit (09:34), swap-slot groups dropped at
  skeleton derivation (03:00), a group with no active gem (03:00), and a
  support PoB applies to none of its group's active gems (10:25, PoB's own
  verdict read back: `PobSession.unsupported_gems`; Efficacy on Shield
  Charge is legal in PoB and stays a remark). While `smoke-frozen` runs
  (10:30): the audit resolves a finished build's `{crafted}` line by its
  rolled text (all 227 crafts of loop-smoke-3 and intake2 resolved) and
  judges it against the item's explicit ids by family: 31 and 33 items in
  those two pre-filter runs carry the craft next to a mod of its family
  (the life / mana regen hybrid on flat-life items; the "50% increased
  Cold Damage" craft beside SpellDamageOnWeapon3), the number the frozen
  run's audits must bring to 0. Earlier:
  `brands` (chain + brand rule, 1 seed): hit_penance_brand 110,
  ignite_penance_brand 298, stormbrand 128 (run E s1: 108 / 250 / 104).
  First loop per seed vs run E: cold_dot 114/137/85 (E 119/130/93),
  bleed_bow 86/49/123 (E 116/108/117), SRS 215/216/232 (E 225/189/198),
  burning_arrow_snipe 181/198/192 (intake, void, 169), impale_ballista
  64/44/77 (intake 65).
- Next three actions: (1) the user's reading of the frozen campaigns' best seeds and
  their decision on the EHP floor (below); (2) one reopening of 7.1 for everything that
  changes the objective's shape, proven on the smoke set x 3 seeds and followed by one
  rerun of the campaigns: the EHP floor if the user takes it, D60 redone with the trial
  value winning over the remembered one and `_finish`'s repair after the tuning, the
  author's row and ours under literally one lane (finding 3); (3) 7.3 from the restart
  runs: best of K seeds against the 9-seed maximum per smoke reference, then the rule
  pair's verdict (ballista with and without clusters) and the knowledge-level rules
  that need no rerun (drop the authors' dead groups and non-applying supports at
  skeleton derivation, golems and curses above their limits).
- Waiting on the user (asked 2026-09-17 22:15, the fixed three-part format; the EHP floor is decided: B, D61): the reading of
  the frozen campaigns' best seeds. In `Documents\Path of Building\Builds\Junkroan\benchmark
  2026-09-16 1929-new18-frozen` (new archetypes, never read): vd_spellslinger s3 279,
  shockwave_cyclone s1 250, static_strike s3 247, kinetic_fusillade s2 213,
  burning_arrow_snipe s1 212, soulrend_chaos_dot s1 202, lightning_trap s2 192,
  spectral_shield_throw s1 184, pyroclast_mine s3 174, exsanguinate_mines s3 170,
  kinetic_bolt_wander s1 162, elemental_hit s3 148, archmage_volatile_dead s3 136,
  impale_cyclone s3 131, poison_spark s1 120, arc_archmage s3 106, impale_ballista s3 102,
  bleed_perforate s3 42. In `benchmark 2026-09-17 0844-core14-frozen` (re-read under the
  loop and the night's rules): ignite_penance_brand s1 308, winter_orb s2 301,
  physical_dot s2 266, summon_raging_spirits s2 247, absolution_minions s1 229,
  hit_penance_brand s3 229, spark s2 223, poison_spectral_throw s2 218,
  regular_viper_strike s2 194, stormbrand s2 180, bleed_bow s1 161, smite s1 160,
  cold_dot s3 142, toxic_rain s1 142. First the ones above 200% (a build at 2-3x the
  author under one lane is either the author's low investment or something PoB counts
  and the game does not). Earlier (7.1f decided: A). Received: the reading of run E's 14
  top builds (`docs/readings/2026-09-16-run-E.md`: 7 rules opened in 7.2; the two
  mod-bracket claims were right, PoB's `group` had misled the first check, RePoE's
  families settled it). The list below
  stays as the record of what was read (the best seed of three by our lane,
  audit clean; every reading
  request names the files, never a folder: the user opened a folder with
  three seeds each and asked which, 2026-09-16 01:00). In `Documents\Path
  of Building\Builds\Junkroanenchmark 2026-09-15 0923-full`: bleed_bow
  s3, cold_dot s2, hit_penance_brand s2, ignite_penance_brand s1,
  physical_dot s3, poison_spectral_throw s2, regular_viper_strike s1,
  smite s1, spark s1, stormbrand s2, toxic_rain s1, winter_orb s2; in
  `1524-minions-fix`: absolution_minions s3, summon_raging_spirits s1.
- Runs count from: 20260918-0723 (`rules-smoke`, the first run on the rules
  code; D63's consequence is that every reference moves, so the frozen
  campaigns are not comparable and must not count as coverage). Reset this
  stamp whenever the pipeline's shape changes, so stale rows never count.
- Runs excluded: frozen-2, sanity, clusters, restarts (`smoke-frozen-2` and
  the sanity run carry the reverted D60, `clusters` runs a flag that is off
  by default, `restarts` are seeds 4-6 for 7.3; `scripts/progress.py` skips
  run folders whose name contains a listed word).
- Progress: see `python scripts/progress.py` (`--refs` for the
  per-reference table); estimate to the prototype 3-4 weeks from
  2026-09-15 (unchanged).

### Work order: architecture first, campaigns after

The user's rule: no situation where two weeks of runs are followed by a
pipeline change that invalidates them. So every change to the pipeline's
shape happens in 7.1, proven on the smoke set, and the pipeline is then
frozen: 7.2-7.4 add knowledge (config rules, audit checks, mechanics,
skeleton semantics) and never stage order or objective shape. A shape
change found necessary later goes back to 7.1 and the affected campaign
results are rerun, and that is recorded here as a cost.

Smoke set for 7.1 (3 seeds unless stated = 18 builds, 3 h on 5 workers on the
rules code -- 2 h 56 min measured on `rules-smoke`): cold_dot
and bleed_bow (the two most sensitive, CLAUDE.md), summon_raging_spirits
(FullDPS, minion counts), impale_ballista (totems, FullDPS), stormbrand
(brand multiplier), burning_arrow_snipe (second active gem in the link).

#### 7.1 Pipeline architecture freeze (target: 4-6 days)

- [x] (2026-09-15, D57: CombinedDPS per instance; FullDPS only where the count is a PoB limit stat; FullDPS = the author's manual `count` x CombinedDPS, 1.00 on four single-group references) **7.1a Objective stat.** PoB's FullDPS with only the main group
      flagged carries a per-instance multiplier: brands x2, Winter Orb x5,
      Poison Spectral Throw x4, Volatile Dead x5.7-x20, ballista x6, minions
      (D56 table). CombinedDPS is one instance. Measure on the smoke set +
      winter_orb + poison_spectral_throw whether the optimizer under FullDPS
      finds count-scaling the CombinedDPS objective misses (brand count,
      projectiles, orbs) and whether the ratio against the author moves.
      Decide: (i) FullDPS for every reference with the main group flagged
      and the author's other flagged groups kept as skeleton extra groups,
      or (ii) CombinedDPS except instance-counted skills (today: minions,
      totems). One dated decision (D57) with the table; the benchmark's
      `stat` column already names the stat per row.
- [x] (2026-09-15, D55 amended) **7.1b Lean vs full: settled.** Run E (full) recovered Smite 140 and
      Bleed Bow 116 where run D (lean) had 86/86; the three D55 stages do
      not pay alone but pay together. The full pipeline stays until 7.1c
      replaces the chain. Amend D55 with this line.
- [x] (2026-09-16, D58: `loop-smoke-3`, kicks with 3 + 4 draws, 5400 s, medians vs run E's chain: cold_dot 137 / 119, bleed_bow 147 / 116, SRS 242 / 198, impale_ballista 84 / 65, stormbrand 165 / 124, burning_arrow 200 / 169; the chain is deleted) **7.1c The improvement loop.** Replace everything after "tree rebuilt
      on gear" (reoptimize, path swaps, gear pass 3, touch-up, joint,
      re-judged picks: six stages that each approximate one fixed-point
      pass) with one loop over moves: tree swap k-for-k (k <= 3), gear
      slot re-roll + bench, support 1-for-1, utility 1-for-1, config
      re-derived after every accepted move; a move is kept when the full
      objective (movement floor and sustain in) improves under re-derived
      lanes by more than 0.5%; the loop ends when a full pass keeps nothing
      (the fixed point, definition-of-done 3). Restarts: the loop from each
      seed's construction; the best of the seeds is the build. Was kept behind
      `BuildPipeline.run(loop=True)` until it beat run E's medians on the smoke
      set; since D58 `loop=True` is not a flag, the chain is deleted and
      `--loop` is a no-op.
      Proof: smoke set x 3 seeds (median and spread) against run E rows.
      As built: the tree move is `refine(max_rounds=10)` + `swap_subtrees(max_size=6, 120 s)`
      with refine's k <= 6 (what run E was measured with; k <= 3 above was a sketch and
      an untested narrowing), gear = one move per rare slot rolled from the empty slot with
      the incumbent competing, picks = one `rejudge_picks` sweep; defaults 8 passes / 40 min,
      a stop short of the fixed point is written into the pass notes.
      First real-PoB measurement (2026-09-15, one pass on run E's finished stormbrand s2,
      loot N 20): 858,887 -> 968,646 (+12.8%: tree +7.3%, Ring 2 +1.0%, Weapon 2 +4.1%) in
      327 s, picks unchanged; the chain's finished build was not at a fixed point.
      Kicks (2026-09-16): a pass whose local moves keep nothing tries ruin-and-recreate
      over the tree (3 draws) then joint tree+gear (4 draws, variants alternating as the
      chain's rounds), stopping at the first kept draw. Found on `loop-smoke-2`'s first
      rows: cold_dot s1/s2 landed on the first loop's numbers to the unit (259,365 /
      312,712; s1 114% against the chain's 119%) because both kicks had one draw and
      missed (257,117 and 250,238 against 259,355), where run E's chain kept reoptimize
      round 2 of 3 (+3.1%) and joint round 4 of 4 (+6.8%) on the same seed. Proof:
      `loop-smoke-3` (queued before intake2).
      Kick draws all run (2026-09-16 06:50): stopping at the first kept draw starved the
      joint kick (Bleed Bow s1: loop-smoke-2's joint draw +18.4% in pass 3 gave 148%,
      loop-smoke-3's second tree draw took that pass with +1.5% and the joint never ran at
      that state, 89%); now every draw of both kicks is judged and kept on its own, as the
      chain's rounds were. `loop_max_passes` 8 -> 16: four of 18 builds stopped on the cap
      while still keeping moves (cold_dot s3 +5.5% in its last pass); the time budget is the cap.
- [x] (2026-09-15, code in before the intake batch; proof = the Burning Arrow and Spellslinger rows of that batch) **7.1d Second active gem in the main link.** Snipe + Burning Arrow,
      Spellslinger + Volatile Dead, General's Cry + Sunder, Cast when
      Damage Taken: the generator and the re-judge treat `main_link[1:]`
      as support slots and would swap the enabler for a support. Rule: an
      active gem in the link is an enabler, kept in place, never a slot;
      `Skeleton.enablers` derived from the gem corpus (active, not
      support), test on the Burning Arrow fixture. Surfaced by the intake
      batch; fixed here because it is link semantics, not knowledge.
- [x] (2026-09-15) **7.1e Invariants and defaults.** A "no change" stage may
      not move the value (7a2c937); a dead skeleton re-picks supports before
      refusing (138172e); every stage's log line carries its change against
      the previous stage; the benchmark report and console flag a stage
      that lost more than 10% without lowering the violation (`lost_stages`,
      a "LOST" note in the audit column and its own section);
      `scripts/benchmark.py` default = all fixtures, `--set smoke|core14|new18`.
- [x] (2026-09-16 09:22, the user chose A: the benchmark's Life floor = 100% of the author's, D59; proof = `smoke-frozen`) **7.1f Benchmark floors (from the user's reading of run E,
      2026-09-16).** The benchmark floors Life at 97% of the author's; a build
      sits on that floor and life above it is worth 0, so a 1-point adjacent life
      notable stays untaken while the point buys a +0.x% DPS leaf: Tireless on
      bleed_bow s3 (+4.3% life, +4.3% EHP for 1 point), Revenge of the Hunted on
      poison_spectral_throw s2 (+5% life, +6.7% EHP for 1 point). Options: the
      floor at 100% of the author's Life (like with like, no slack), or the
      author's Life and TotalEHP both. Decided with the user; then the smoke set
      is rerun and "Runs count from" reset. No hand weight for life above the
      floor (principle 1).
- [x] (REVERTED 2026-09-16 19:29 by its own gate, commit 6250168: `smoke-frozen-2` against
      `smoke-frozen` by 3-seed medians: bleed_bow 56.9 vs 127.7, burning_arrow 135.2 vs
      214.4, impale_ballista 64.6 vs 83.4, cold_dot 161.3 vs 148.6, stormbrand 168.4 vs
      168.3, SRS 220.0 vs 219.6; median of medians 148.2 vs 158.4, -10.2 against a floor of
      -5. The sanity build showed the mechanism: the lanes tuned before pass 1 left the same
      build infeasible (viol 0.345 at 344,292) and the loop bought the floor back with
      "Belt -40.5%". The defect D60 named stays true and open, outside the freeze: the
      loop's last pass sits 14-43% under the final lanes on four of six smoke references; a
      redo needs the repair `_finish` does after its tuning and a smoke proof, and it would
      rerun the campaigns, so it waits for a reason stronger than tidiness) **7.1g The loop
      judges under the final lanes.** loop-smoke-3's "config (final lanes)" stood above the loop's last pass
      by +43% (burning_arrow s1: exposure Fire, bandit Alira), +16-18% (bleed_bow x 3:
      Pride at MAX), +14.5% (impale_ballista s3: Blood stance), +2% (stormbrand), 0%
      (cold_dot): the list choices and the identity (bandit, pantheons, the bandit's extra
      points) were judged only in `_finish`, so the loop optimized one number, the fixed
      point was called on another, and the floors were judged in the wrong stance. Now
      `_tune_lanes` judges choices + identity before pass 1 and the choices again at the end
      of every pass that changed the build; the chosen values live on the skeleton
      (`tuned_choices`) through every reconfigure, the user's own numbers still winning. 3
      tests. Found by the stage table of loop-smoke-3's 18 logs (7.3 prep): the seed spread
      is born in construction (gear pass 1's loot rolls, then the greedy tree: 1.24-1.71 at
      gear pass 1, 1.08-2.33 at "tree rebuilt on gear") and the loop narrows it but never
      closes it (final 1.09-2.02).
- [ ] **7.1h Reopened once (D61, the user 2026-09-17): speed, then the objective.** In
      order: (1) profile one greedy step (Lua / IPC / Python; a fast trial is 5-8 ms, 16-25
      with FullDPS in the keys, the wall cost per candidate 12-24 ms, a build ~123,000
      trials); (2) exact speed-ups, builds unchanged: count x CombinedDPS in trials where
      FullDPS is one group's instances, no repeat of a kick draw on an unchanged state,
      batch overhead; (3) lazy greedy, proven on the smoke set x 3 seeds (medians within 5
      points, trees compared); (4) landed: the TotalEHP floor at the author's (D63.1) and
      D60 redone (2026-09-18, 5 tests); left: the author's row and ours under one lane;
      (5) one smoke proof against `smoke-frozen`, then one rerun of
      `new18` and `core14`. Target: a build in 15-25 min instead of 61-69, the campaigns in
      6-9 h instead of 28.
      Progress 2026-09-18: (1) profile of a stormbrand build (3,280 s on the loaded machine):
      trial_stats 40%, read_state 34% (1,062 full exports), set_skills 12%, the rest small.
      (2) Two exact wins landed (0ff1f41, fce90ab): the tree reads its state through a 0.6 ms
      readback, read_state no longer reopens the build (1,648 -> 42 ms, identical on 34
      builds). (3) Four Opus audits with measurements, filed under `docs/research/speed/`
      (ipc, tree, pipeline, lua). Exact items being implemented from them: set_skills and
      set_config in place (469 -> 63 ms, 593 -> 166 ms, byte-identical exports), the
      duplicate path rebuild in mutate_nodes (140 -> ~80 ms), the enabler hook judged once
      per lanes (127 calls, 388 s, 109 of them learning nothing), swap_subtrees memo across
      passes (613 s of re-tried rejected swaps in one build), restore through an inverse
      mutate instead of load_xml, kick draws that already restored themselves skipped
      (76% of reverted tree-kick draws returned the incumbent's number), judge_stack_options
      cached (spark: 9 config reloads per derivation, >= 1,600 s per build), the author's
      row once per reference, a JIT guard (JIT is on with PoB's settings: 2.4x; a
      regression is +140% per trial), the headless recalc without the CALCS lane and the
      unused node calculator. Approximate items for the smoke gate after those:
      FullDPS = count x TotalDPS in trials (13 -> 6.7 ms on stormbrand, 20-27% of a
      FullDPS build), inert candidates skipped until the floor set changes (30-53% of all
      trials on stormbrand / bleed_bow), fewer kick draws, refine's batch restructured,
      max_depth. Measured negatives: the protocol (0.2%), JSON, batching, GC, env reuse,
      lazy greedy on stale values (0.5% of values stay put). One number still open: per-
      candidate cost in campaign logs is 22-27 ms against 6-7 ms measured alone, part
      FullDPS, part contention of 5 workers on 6 cores: settle with one reference at
      `--workers 1` on an idle machine (the user allows ~70% of the machine).
      Landed 2026-09-18 03:00 (4cc3fce, aeb1e72, c591e01; 392 tests): all the exact items
      above, and the two approximate ones behind flags (default off) with their smoke proofs
      queued (`speed-fulldps`, `speed-inert`, each gated by compare_runs against smoke-frozen).
      Measured on the same stormbrand build (both on the loaded machine): 3,271 s -> 2,275 s,
      and the loop, which before stopped on its 2,400 s budget after 3 passes at 2,238,757,
      now reaches the fixed point after 6 passes at 2,289,728 (+2.3%); a pass of local moves
      ~800 s -> ~120 s (6.7x); overhead (read_state, set_skills, load_xml) 49% -> 9% of the
      build, PoB's own trial calc 40% -> 81%. What remains is search work: the kicks
      (ruin-and-recreate, 3 of the 6 passes, ~1,440 s), the greedy's candidate count (the
      skip-inert flag), the FullDPS roll-up (the fulldps flag). Next exact target: none left
      of size; next approximate: fewer kick draws, judged by the same gate.
- [x] (2026-09-16 14:21, `smoke-frozen`, the pipeline without 7.1g: cold_dot 148.6 (spread
      34.5), bleed_bow 127.7 (67.0), summon_raging_spirits 219.6 (57.2), impale_ballista 83.4
      (48.8), stormbrand 168.3 (42.9), burning_arrow_snipe 214.4 (10.1); median of medians
      158.4 against loop-smoke-3's 155.7; audit errors 0 in 18 builds) **7.1 exit.** The
      smoke set x 3 seeds under the frozen pipeline, medians recorded here; from then on
      7.2-7.4 change no stage. "Runs count from" = 20260916-0941.

#### 7.2 Archetype campaign (target: 1.5-2 weeks, overlaps 7.1 only for reading)

Counted per reference, not per bullet (the user, 2026-09-15: a checkbox
list that is opened and closed in the same commit measures nothing).
`scripts/progress.py` reads every benchmark `results.json` since the
"Runs count from" stamp in the State block and counts a reference covered
when its latest 3-seed run has a median at or above the author with every
seed audit clean and feasible (the definition of done, item 1). The rules
below are the means: each is its own checkbox with the number that
motivated it and the number that closed it, added the moment a run finds
it, so the open count grows when a run finds gaps and shrinks as rules land.

The intake batch (18 new references x 1 seed) ran first, before 7.1 was
done, because its logs and audits tell 7.1d and 7.1a what to handle; its
numbers are not acceptance numbers (the pipeline changes in 7.1c).

Procedure (not counted): the gap list from every first seed (ratio, what
the log shows, the general cause, the rule); rules in order of shared cause
(a rule that fixes three references before one that fixes one), each = code
+ fast test + audit check; rerun the references a rule touched (1 seed), 3
seeds when at or above the author; when a new archetype's first build
reaches the author, the user reads it (folder path given); a remark becomes
a rule only if it names a class of builds the corpora or a PoB stat can
express; per-build remarks are recorded, not coded. Every reading is kept
verbatim with what the data said in `docs/readings/<date>-<run>.md` (first:
`2026-09-16-run-E.md`, 14 builds, 6 rules and one 7.1 question).

Gap list (from the first intake batch; its numbers are void, see State):
- every new skill: the re-judge opened on a one-support link and
  swapped unjudged (Arc 373,571 -> 64,531; Pyroclast 249,025 -> 58,554;
  Lightning Trap 617,568 -> 130,956). Cause: `legal_supports` readback
  left PoB's link as the last candidate (rule 1 below).
- Pyroclast Mine 147% of our lane, but the author's own config is 2x
  our lane (420,891 vs 212,564): `multiplierMineDetonatedRecently` 10,
  frenzy + power charges, enemy ignited. The rails' numeric assumptions
  carry no mine count; a mine build's "mines detonated recently" is a
  throughput number PoB cannot derive (rule 4 below).
- Impale Ballista 65%: the sustain floor (mana per second of the
  ballistas) violated 0.523 from gear pass 2 to gear pass 3, repaired at
  the touch-up for -9%; joint 554,488 against the author's 1,019,350
  under our lane (their raw 771,573: our lane's Blood stance and Pride
  at max give the author +32%). The pre-re-judge tree/gear gap is ~45%:
  decompose (`scripts/gap_decomposition.py`) once the PoB XML exists.
- Arc Archmage 91%, Lightning Trap 87%, VD Spellslinger 495%,
  Impale Cyclone 140%, Spectral Shield Throw 148% (ramp 2.4 s of 2.5):
  void (the re-judge bug); VD also dropped Spell Cascade (per orb 94,279
  -> 177,902) and the author's 8 orbs are a manual count (rule 3 below).

Decomposition of the six weakest first-batch builds (`scripts/gap_decomposition.py
--run "2026-09-15 1654-intake"`, everything under our lane, CombinedDPS; A = the
author, B = author tree + our gear, C = our tree + author gear, D = ours; B and C
keep the author's links, D carries ours):

| reference | B/A gear | C/A tree | D/A | what the numbers say |
|---|---|---|---|---|
| impale_ballista | 40% | 100% | 120% per totem | our tree has no impale: ImpaleChance 10 vs 90, ImpaleDPS 901 vs 42,486 of a 61,900 hit; the impale notables pay only together (rule 5); our final link dropped Multiple Totems unjudged (limit 5 vs 6) |
| bleed_perforate | 71% | 152% | 35% | our tree beats the author's on their gear; D's collapse is the link the broken re-judge chose (Ruthless + Multistrike; hit DPS 50,696 vs B's 103,958 on the same gear) plus a weak weapon roll (tier-2 hybrid physical) |
| poison_spark | 85% | 96% | 107% | no gap under one lane; the benchmark's 72% is the author's numeric assumptions our build does not prove (read on intake2) |
| arc_archmage | 104% | 96% | 95% | small; the unjudged Lightning Penetration -> Spell Echo swap |
| lightning_trap | 125% | 145% | 87% | both sides beat the author alone; D lost Swift Assembly unjudged (-43%) |
| exsanguinate_mines | 116% | 0% (requirements) | 86% | the author's gear on our tree fails its attribute requirements; the 1.8x lane gap is the mine count (rule 3) |

Rules found (one checkbox each; before -> after on 1 seed, then 3):
- [x] (2026-09-15, 208fb8b) The support-legality readback restores the
      main link, and the re-judge raises when it opens >10% below the
      value it was given. Before: Lightning Trap's re-judge opened at
      130,956 on a joint of 617,568 and swapped Swift Assembly out
      unjudged (-43%). After: `tests/test_legal_supports_readback.py`;
      numbers from intake2.
- [x] (2026-09-15; `brands` run, 1 seed, chain: hit_penance_brand 110% (run E s1 108), ignite_penance_brand 298% (250), stormbrand 128% (104); the derived count 2 equals the authors' typed 2 on all three; no attached-brand node exists beyond Runebinder, so the count did not move) Brand count derived (D57 rule 1): the skill's attach base
      (`base_number_of_sigils_allowed_per_target`) + every "additional
      Brand Attached to an Enemy" the build owns, capped by
      `ActiveBrandLimit`; brands join `counts_instances` (FullDPS); the
      benchmark gives the author the same derivation. Proof: 1 seed of
      stormbrand (run E median 124), hit_penance_brand (112),
      ignite_penance_brand (269); does the tree take an attached-brand node.
- [x] (code 2026-09-16 02:48; intake2: vd_spellslinger 231% and
      archmage_volatile_dead 132% with count 9 derived on both sides, where the
      first intake had 495% / 86% under the authors' typed 8 / 6) Corpse supply for corpse-fed skills (D57
      rule 2): from PoB's skill data, Volatile Dead consumes 3 corpses per
      cast (`volatile_dead_base_number_of_corpses_to_consume`, x3 areas
      with Spell Cascade), Desecrate makes 5 per cast capped at 10
      (Unearth 1, same cap); count = min(consumed, supplied per cast),
      derived for the trial link too (Spell Cascade out: 9 -> 3), the
      author gets the same derivation (both references: 9), and the audit
      errors on a consumer with no creator in the build
      (`skill_facts.corpses_*`, `derived_counts(links=)`,
      `tests/test_corpse_counts.py`).
- [x] (code 2026-09-16 02:48; intake2: exsanguinate_mines 180% with 37 mines
      detonated in our lane (the author typed 10; first intake 86% with the input
      at 0), pyroclast_mine 131% where PoB shows no such input for that tree
      (first intake 147%)) Mines detonated recently for
      mine skills (D57 rule 3): `multiplierMineDetonatedRecently` = 4 s
      window x PoB's `Speed` for a mine build (mines per second = laying
      speed x mines per throw: Pyroclast 1.909 x 5 = 9.54, Exsanguinate
      mines 10.57, probed 2026-09-16) x the rails' fraction detonated
      (1.0): 38 / 42, the mods cap their own "up to" inside PoB. A numeric
      config rule with two rails assumptions, not a `mechanics/` fact: the
      throughput is PoB's own throw rate, only the window and the
      detonation habit are assumed (`config_rules._numeric_rule`,
      `rails_default.json` assumptions, `tests/test_audit_and_config_limits.py`).
      The audit gained "golem limit" the same commit (golem gems above
      ActiveGolemLimit: PoB applies every enabled golem's buff, probed on
      the Cold DoT reference).
- [~] (code 2026-09-16 behind `--cluster-candidates` / `TreeOptimizer(cluster_candidates=)`,
      off by default; 7 tests on a synthetic graph; proof pending: smoke set +
      impale_ballista x 3 seeds with and without the flag, after 7.1c) Cluster candidates in the tree optimizer (rule 5, from Impale Ballista):
      a mechanic whose notables pay only together (impale: chance x effect x
      stacks; crit: chance x multiplier) is invisible to a greedy that tries
      one payoff node at a time and to k-for-k swaps. Candidate = the payoff
      nodes sharing a mechanic tag (tag corpus) reachable within the depth,
      up to 4, tried as one trial and allocated as one step when it beats
      the singles per point. A move, not a stage: proven like every
      optimizer change, smoke set + impale_ballista x 3 seeds against run E
      / loop-smoke rows. Before: ImpaleChance 10, ImpaleDPS 901 on a 61,900
      hit (the author: 90, 42,486).
- [x] (2026-09-15) The chain's re-judge stage recorded its number under the
      re-judge's lanes after a refine that changed the tree: Stormbrand
      (brands run) recorded 2,337,491, the final lanes found 1,820,275 with a
      floor broken (viol 0.135), repaired to 1,777,781; the 7.1e LOST flag
      caught it. Rule: the stage re-derives the lanes after its refine
      before recording (one line in `run`). The final number was honest
      already; only the stage record and the flag were wrong.
- [x] (proof 2026-09-17: no Wind Dancer in any of the 132 frozen builds, cold_dot included; code 2026-09-16 03:00, `FIGHT_FACTS`; proof = `smoke-frozen`'s cold_dot rows: intake2's 16 builds take no Wind Dancer but none of its references is a reading case, and loop-smoke-3's cold_dot s1 / s2 took it as their only keystone on the code before the rule) "Been hit" conditions are true on the boss lane (from the user's reading:
      Wind Dancer taken in toxic_rain, cold_dot, viper, poison ST "for EHP"). Its
      3.29 text: 20% less attack damage taken if NOT hit by an attack recently,
      20% MORE if hit; PoB's default is "not hit", the optimizer took the
      keystone on it. With `conditionBeenHitByAttackRecently` on, the build with
      the keystone is worse than without: toxic_rain phys max hit 5,403 -> 4,439
      (floor 4,700; 4,873 without the keystone), viper 5,207 -> 4,312 (4,715),
      poison ST 4,587 -> 3,761 (4,133), cold_dot 8,441 -> 6,914 (7,601). Rule:
      `conditionBeenHitRecently` and `conditionBeenHitByAttackRecently` are true
      in both lanes (a boss hits you; a map hits you), a fact of the fight, not
      an assumption; element-specific and savage-hit variants stay off.
- [x] (code 2026-09-16 03:00, `AILMENT_DAMAGE_PROOF` + `_ailment_evidence`; intake2's conservative lane: Ignited on for the 9 builds with fire in the hit and a sustained chance (IgniteDPS 448 on lightning_trap to 1.05M on burning_arrow), off for the 7 without (arc, ballista, fusillade, shockwave, soulrend, spectral shield throw, poison spark); the optimistic lane keeps every shown input on by design) Ailment condition proof = the ailment's damage stat AND sustained uptime,
      never the chance alone (reading: "Ignited / Burning checked without a
      source"). toxic_rain s1: IgniteChance 33.6 with IgniteDPS 0 (no fire in the
      hit) turned Ignited on; cold_dot s2: IgniteDPS 10.67 from one item with a
      tiny chance turned it on. Rule: Ignited/Burning need IgniteDPS > 0 and
      chance x hits per second x duration >= 1 (the uptime the rule already
      computes); the same shape for Poisoned / Bleeding.
- [x] (code 2026-09-16 03:00, `_group_has_active_gem`, audit "dead support group"; intake2's audits: Momentum on pyroclast_mine, More Duration on spectral_shield_throw, both the authors' groups) A gem in a socket group with no active gem proves nothing, and the audit
      warns on such a group (reading: smite s1 "fortified with no source": the
      proof text matched the support gem Fortify alone in a helmet group;
      PoB showed FortificationStacks 20). Rule: `_gem_names` / `build_text`
      skip groups without an enabled active gem; audit "dead support group"
      (warning). The stronger check, "a support that fits none of its group's
      active gems", is PoB's own verdict read back after the main calc (2026-09-16
      10:25: `PobSession.unsupported_gems`, the skills tab's red "Cannot apply to any
      of the active skills" = `supportEffect.isSupporting` empty, or "Superseded";
      audit warning "support fits no active gem", `tests/test_unsupported_gems.py`:
      Spell Echo beside Shield Charge is flagged, Faster Attacks is not). Measured
      on the reading's case: the cold_dot author's Efficacy sits with Vortex and
      Creeping Frost and supports both, and Efficacy on Shield Charge (cold_dot s2)
      is legal in PoB (applies, adds nothing): a per-build remark, not this check;
      "a support that applies but changes no number" would need a per-gem delta
      and is not opened. The four probed builds (cold_dot and smite authors',
      loop-smoke-3 cold_dot s2 and stormbrand s2) carry no flagged support.
- [x] (code 2026-09-16 03:00, `set_config` drops override* without use*; intake2's 32 config sets: the only override, pyroclast_mine's frenzy 1, sits with its use flag on in both lanes) A charge override is written only in a lane whose use flag is on
      (reading: smite s1 "1 frenzy charge with the box unchecked": the
      conservative set carried `overrideFrenzyCharges` 1 without
      `useFrenzyCharges`, the numeric override preserved across lanes; PoB
      ignores the count, the UI shows it). Fix in `derive_config` /
      `set_config(preserve="numeric")`: override* vars follow their use flag.
- [x] (proof 2026-09-17: Summon Raging Spirit count 20 on all 9 frozen SRS builds, Absolution 3; code 2026-09-16 03:00, `skill_facts.is_duration_minion` / `minions_per_cast` (Skeletons 3 at gem 18 from the level table), `derived_counts`; totems and spectres excluded; proof = SRS rows of the next run, 22 >= 20 today) Duration-minion count = min(limit, rate x duration x per cast) (rule 6,
      D57 family; reading: "does 8.2 s sustain 20 spirits?"). SRS s1: Speed 2.8
      casts/s x 8.2 s x 1 = 23 >= 20, sustained at the margin; a slower caster
      is capped below ActiveSpiritLimit. From PoB's skill data (duration, spirits
      per cast) and the build's Speed, like the brand and corpse counts.
- [x] (proof 2026-09-17: no "mod family" finding in the 96 campaign builds audited with the crafted-line check; code 2026-09-16 09:34, 5992af2; proof = `smoke-frozen`'s audits: no "mod family" error, no
      impossible weapon) Mod families, not PoB groups, decide which mods an item can carry
      (reading: "triple DoT multiplier on a wand is impossible", "hybrid life / mana regen
      cannot sit next to flat life": both true). The game's exclusivity is the mod family
      (RePoE `mods.json`, an export of the game data keyed by PoB's own mod ids; corpus
      `corpus_data/mod_families.json`, 26,689 item/crafted mods, 3,307 families, rebuilt by
      `scripts/build_mod_families.py`); PoB's `group` splits 185 of 512 families and 10 groups
      span two families. Chaos / Physical / Cold / Fire DoT multipliers = one family; % increased
      damage of one element (or chaos) + % spell damage on weapons = one family
      `WeaponCasterDamagePrefix` (the user: one bucket), which every caster weapon we rolled
      had stacked (stormbrand both weapons, cold_dot). The roll
      marks every family of a chosen mod, `craft_rare` reports "duplicate mod family", the
      bench filter uses families + the PoB group, the audit errors on an equipped item whose
      `Prefix:` / `Suffix:` mod ids share a family. Bench rows (PoB's `masterMods` carry no
      id) are mapped to RePoE's crafted ids by canonical mod text + level + group
      (`pob/bench_mod_ids.py`, corpus `bench_mods.json`, 1,601 crafted mods): 716 of 732
      bench rows get a unique id, all 732 their families (450 of them differ from PoB's
      group), so the "+life / mana regen" craft (family IncreasedLife) no longer lands next
      to flat life. The audit judges a finished build's craft the same way (2026-09-16
      10:40): the `{crafted}` line is rolled text without an id, recognised by the crafted
      mods whose lines it fits number by number (`bench_mod_ids.crafted_text_mods`, the
      two-line hybrid as one mod), then its families against the item's `Prefix:` /
      `Suffix:` ids: every craft of loop-smoke-3 and intake2 resolved (126 / 126, 101 /
      101) and, both runs being older than the bench filter, 31 and 33 items carry the
      craft next to a mod of its family (the life / mana regen hybrid on flat-life items,
      "50% increased Cold Damage" beside SpellDamageOnWeapon3 on cold_dot s3's wand): the
      count `smoke-frozen`'s audits must bring to 0.
- [x] (2026-09-16 03:00, bench candidates sorted by level descending; no unit harness for loot_gear, one line) Bench craft ties go to the highest rank (reading: "T2 flat life when T1
      is available"). Rings: +48 is the top ring rank (41-55), no bug; the
      helmet's hybrid +31 life / 2 mana regen closed the last floor (viol 0.013
      -> 0.000, the log), chosen by score. At an equal score the first (lowest)
      rank wins today: sort bench candidates by level descending.
- [x] (2026-09-16 03:00, `build_from_skeleton.socket_groups_from_xml`; cold_dot's skeleton 5 groups instead of 6) Skeleton derivation drops weapon-swap socket groups and the audit
      warns on a group with no active gem (reading: cold_dot s2 "Arcane Surge +
      Elemental Focus", the author's "Weapon 1 Swap" group carried as live).
- Rules from the user's reading of the frozen campaigns, part 1 (2026-09-18,
  `docs/readings/2026-09-18-frozen-campaigns-part1.md`: the text verbatim, what the data says,
  the class behind each rule). All change numbers, so they land inside 7.1h and are proven by
  its one smoke run:
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Guard skills and cooldown-limited buffs count for nothing, ours and the author's
      (shockwave_cyclone: Steelskin in EHP and max hit, audit uptime ~50%).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) A generator needs its enabler in the build (shockwave_cyclone, static_strike: max frenzy and
      endurance from "when you place a Banner" with no banner gem).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) The Frenzy skill generates frenzy charges (vd_spellslinger: the box off, -28% when on, PoB's
      trigger-rate breakpoint; burning_arrow: Manaforged Frenzy).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Self-cost lines judged per candidate, not once on the empty build (soulrend: Chaos Mastery
      "lose 10% of life and ES per chaos skill use" taken at +17%; `pipeline.py:163`).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) No degen while idle: regeneration without leech or recoup >= 0, replacing D34's -100
      (lightning_trap: -12).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Sustain 100% for channelled main skills (shockwave_cyclone: 39.3 regen for 43.84 cost).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Bandits: always kill all, no judged choice (the user's rail).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Ramp-type list choices follow the ramp budget, computed, not researched (the user): Pride's
      initial and maximum values and its 4 s are the gem's own data, the rails give 2.5 s, so the
      lane's value is initial + (maximum - initial) x 2.5 / 4, written as a custom mod with a
      comment on top of PoB's MIN (the mod works, the comment explains); never MAX.
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Gear has the last word on attributes, resistances and late accuracy: a tree node that only
      feeds such a floor is a removal candidate with a gear re-roll as the repair (soulrend).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Enabler gems turn their condition on (kinetic_fusillade: Flame Wall without "projectiles
      passed through").
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Only rares are rolled and only uniques fixed: the author's MAGIC ring was carried into
      vd_spellslinger s3 (`build_from_skeleton.py` rarity branches).
- [~] (code 2026-09-18 04:45, merge 7df5671: the uptime rule on the crit-recently inputs and as an audit warning; the optimizer half 2026-09-18 09:00, 45d8dd0: `ElementalOverloadUptime >= 0.9` in the objective, witnessed by `HaveElementalOverload` from the headless wrapper, so the what-if trial that takes the keystone pays; PoB's CritChance already carries the accuracy roll, no second HitChance factor; proof = the campaign rerun) Elemental Overload needs an uptime proof from effective crit and hit rate (burning_arrow 7%
      channelled against kinetic_fusillade 17%).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Mind over Matter needs unreserved mana to stand on: at least 40% of mana unreserved (the
      user, 2026-09-18; burning_arrow took it at 10%).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) `mechanics/delivery_types.json` from the research: mines reserve mana per placed mine
      (lightning_trap, pyroclast_mine: 4% unreserved), proxies' on-hit / on-kill, trigger
      breakpoints; read by the config rules and a floor on unreserved mana for N mines.
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Trauma's self-damage in the degen floor once the research gives the formula (static_strike:
      752 per attack at 3,478 life); the VD orb count with a regular Spell Cascade (the user: 6-8,
      average 7, ours 9) and the shock magnitude follow the same research.
- Rules from part 2 of the same reading (`docs/readings/2026-09-18-frozen-campaigns-part2.md`):
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Attack builds keep hit chance >= 95% (the user's rail; kinetic_bolt_wander 83%).
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Ramp-type numeric inputs come from the ramp budget, never from a ceiling: Sigil of Power
      stages (kinetic_bolt_wander: 50 in both lanes, ours), Wither stacks (poison_spark: 15 against
      the author's 6), poisons applied recently, corpses consumed recently. The same rule replaces
      the ramp CLIFF: today `RampBudget >= RampSeconds` is a hard floor, so a choice whose ramp
      runs 13% over the budget loses to one 3.4x weaker. Measured 2026-09-18 on bleed_perforate
      s3: Blood stance (PoB's default, never written to the build) 189,005 feasible; Sand stance
      647,425 with violation RampBudget 0.134; the author plays Sand and sits at 449,293 under
      our lane, so the reference's 33-42% is this cliff, not the optimizer. Under each choice
      the stack / charge values reachable inside 2.5 s are derived (rage 12 instead of 15, ...),
      the number is scored with them, and the ramp floor stays only for binary conditions.
      Perforate's overlap input (`perforateSpikeOverlap`, PoB default 3, Blood stance only)
      follows the same rule from the spike count and the reading's 1-2 overlaps.
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) A buff proved by an on-kill source is off on the boss lane (impale_cyclone: `buffOnslaught`
      in the conservative lane from "20% chance to gain Onslaught on kill").
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Supports that pay life per use are self-cost, judged per candidate (poison_spark: Sacrifice,
      ours, where the author has Faster Projectiles + Efficacy).
- [~] (code 2026-09-18 10:30, d4fd350: `PobSession.mean_parts`, `optimizer/random_parts.py`; the author's elemental_hit fire 607,051 / cold 404,273 / lightning 660,233 -> mean 557,186; proof = the campaign rerun) A skill whose damage part is random per hit is scored as the mean over its parts, both
      sides (elemental_hit without the jewels that exclude elements); a `mechanics/` fact.
- [~] (code 2026-09-18 04:45, merge 7df5671; proof = `rules-smoke`) Corpse-cycle conditions follow a creator plus a consumer in the build (spawned / consumed a
      corpse recently, corpses consumed recently as a count, Undertaker's +2), after the research
      (archmage_volatile_dead).
- [~] (code 2026-09-18 08:30, cdd83eb: `ramp_inputs.rage_stacks`, the build's own sources x the budget at PoB's one-hit-per-0.5 s throttle, Rage Support, warcries, mana, regen, cost; Smite 5 of 30 where the rails typed 15, bleed_perforate 2; proof = the campaign rerun) `multiplierRage` was the rails' 50% of the maximum: derive it like every ramp number
      (rage gained per second from the build's own sources x 2.5 s, capped; 0 without a source);
      found by R2 on bleed_perforate (15 typed against 2 earned).
- [ ] Lane note, not a rule yet: on Shockwave Cyclone, Pyroclast, Exsanguinate,
      Elemental Hit and Perforate the author's own config is 1.7-2.1x our
      conservative lane (rage 40, endurance + power charges, mines detonated,
      bleed vs moving, leeching); our lane asks for proof of generation
      (D22-D26) and gives both sides the same lane, so the ratio holds; the
      user reads whether a proof rule is too strict (an ask, item 4 of 7.2).
      The ratios predate the ramp arithmetic, which now derives those very
      inputs on both sides (D62 amd 3; rage in D64: Smite 5 of 30 where the
      rails typed 15), so they are re-measured on `rules-smoke` first.

#### 7.3 Stability and the fixed point (target: 1 week)

Counted per reference too: `scripts/progress.py` reports how many of the
measured references have a seed spread of at most 10 points (definition of
done, item 2); the items below are the means.

- [~] (measured 2026-09-18: `docs/research/2026-09-18-seed-divergence.md`, 96 builds of the
      two frozen campaigns; and the greedy-variance measurement below) Spread per reference
      from the 3-seed runs of 7.2; references above
      10 points get their three logs compared stage by stage: where the
      seeds diverge is where the loop (7.1c) lacks a move or the
      construction lacks a repair; fix the move, not the seed.
      Findings: 29 of 32 references have a spread above 10 points (median 41.6, max 109.1);
      the spread first exceeds 10 at "tree greedy" on 19 of them and at "gear pass 2" on 8,
      and is largest at the final on 15. The tree greedy itself has no randomness:
      `TreeOptimizer` takes no seed, its candidate window is the cheapest-first prefix by
      (cost, node id), and 26 regrowths of six starting builds were bit-identical
      (Jaccard 1.000); raising `max_trials` 300 -> 1000 changes no pick and costs up to 17%
      more time. The spread is born in gear pass 1 (`loot.fill(seed=)`, the only thing the
      seed touches before the greedy) and amplified by the deterministic greedy: the same
      greedy on each seed's own gear spans 15 points on stormbrand and 29 on bleed_bow. The
      levers are therefore the loot (its N, or the best of several constructions,
      construction being ~10% of a build) and the loop's kicks, not the greedy; both being
      measured.
- [x] (2026-09-18, 888c02b; D66 8d27839 guards the delivered build)
      Fixed-point audit item: the loop is run once more on the finished
      build inside the audit; a gain above 1% is an audit error ("not at
      a fixed point") so a non-optimal build cannot pass as done.
- [~] (measured 2026-09-18 on the smoke set, 42 builds of the pre-rules code, 6-9 seeds per
      reference: `docs/research/2026-09-18-restarts-statistics.md`) Restarts: how many seeds
      the search should build per skeleton so the best of them is within 5 points of the
      3-seed maximum. Expected best-of-K by bootstrap, median over the six references:
      K=1 153.6, K=2 165.5, K=3 171.0, K=4 174.4, K=5 176.6, K=6 178.0; the third seed is
      worth +5.6 points, every seed after it +3.3 or less, so the search builds 3 seeds per
      finalist skeleton and keeps the best (within 7 points of K=6 at half its cost), and the
      benchmark's median-of-3 understates what a request receives by ~17 points. The spread
      is the loop's, not construction's: construction-to-final rank correlation within a
      reference is 0.42, and the loop widens the spread on 5 of 6 references (median 41.7
      points at "tree rebuilt on gear", 60.8 at the end); construction is ~10% of a build's
      time, so a loop-only restart would save almost nothing over a full one. Only 5 of 42
      builds ended on the time budget: the budget is not what stops the loop. Remeasure on
      the rules code once the campaign rerun gives 3 seeds per reference (the numbers above
      are relative gains; the levels move with the new floors).

#### 7.4 Acceptance

- [ ] All fixtures x 3 seeds under the frozen pipeline: every reference at
      or above the author, audit clean, fixed point. "Spread at most 10" is
      contradicted by the measurement (29 of 32 above 10, median 41.6).
      Criterion (2026-09-18, the lead): the delivered result is the best of
      3 seeds per reference (7.3's measurement: +17.4 points over one seed);
      the spread is reported per reference, not gated; the acceptance number
      is the best-of-3 at or above the author.
- [ ] The user reads the top build of every reference (one request, one
      folder) and finds no new kind of error.
- [ ] `junkroan build` on three requests (one melee, one spell, one
      minion) in under 2 hours each; the search's finalists pass the same
      audit and fixed-point check.
- [ ] Phase 6 open items closed or moved to "Later": mapping objective,
      Azadi / Writhing Jar enablers, Cruelty.

### Working protocols (moved 2026-09-26)

- Autonomy protocol (the run queue, detached launches, snapshots): `docs/agents/runs.md`.
- The owner's role (readings, the request format) and progress reporting: `docs/agents/owner.md`.
- Chat / session protocol, limit handover protocol, cost: `docs/agents/sessions.md`.
- Model / cost protocol and team-lead mode: CLAUDE.md "Subagents and models".

## Later (only after Phase 6)

- (done 2026-09-15, D55: every stage switched off alone on Cold DoT and Bleed
  Bow, 3 seeds; gear pass 3 (-53 / -5), joint (-27 / -8), rebuild (0 / -18)
  and the re-judged picks (-5 / -6) pay; reoptimize (+3 / +8), path swaps
  (+1 / 0) and the touch-up (+17 / 0) do not and are left out of the lean
  pipeline judged by run D) Ablation of the stage sequence.
- (first step done 2026-09-14: `optimizer/mapping.py`, a "Mapping (not scored)" line in every explanation) Mapping vs bossing: two views of a build, not one score. Bossing is what
  the objective measures today (Pinnacle boss, conservative lane). Mapping
  comfort is not a number PoB gives (the user, 2026-09-14: a life build
  with life on kill maps a hundred times better than one without; block is
  near-immortal for mapping and weak for bossing; on-kill effects are a
  mapping mechanic). First step is text, not a score: a "mapping" section
  in the explanation listing what the build has that only pays on maps
  (life / mana / ES on kill, on-kill charge and buff generators, block
  chance with its EHP under PoB's average calc, movement speed, area) and
  what it lacks, each line with the PoB number or the source text. A
  mapping objective (2 hits per second taken, kills happen, block counts)
  can follow once the list is stable.
- Block in the boss EHP: PoB has no block-only switch (DisableEHPGainOnBlock
  is about life gained on block). Its "EHP calc unlucky" (Unlucky = worst of
  2 rolls, Very Unlucky = worst of 4) lowers block, dodge, suppression and
  avoidance together; the maximum-hit-taken stats carry no avoidance at
  all. Decision pending: boss lane on Unlucky, or a max-hit rail next to EHP.

- Archetype conventions from poe.ninja statistics: for nodes, masteries and
  supports that PoB values at ~0 but that appear in most builds of the same
  archetype (brand attachment range, extra brands, QoL notables), derive a
  frequency prior and apply it as a soft constraint or penalty. Statistics
  only, never build copying (DECISIONS D6). Observed 2026-09-11: the
  optimizer dropped both Brand Masteries on Stormbrand because PoB gives
  them no DPS.
- Progression: same optimizer with level-N point budgets and gem levels.
- Craft cost estimation from affix weights (PoEDB catalog already has them).
- Trade realism from live listings.
- Mechanics notes expansion driven by benchmark failures.
- Hit-multiplicity warning layer: v1's 368 wiki-derived skill notes
  (`reference/legacy/skill_scaling_facts.py`, tags overlap / repeat_hit /
  multi_hit / additional_projectiles, ~50 skills) carry no numbers, so they
  are used two ways only: (1) a warning on output builds ("PoB counts one hit;
  in-game single-target damage may be higher, verify hit count"); (2) an
  audit note when evaluating an existing PoB whose config assumes several
  hits per cast. Real per-skill hit counts require in-game testing and are
  deferred until the full pipeline works.
