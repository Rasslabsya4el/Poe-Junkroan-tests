# Architecture

## Problem statement

Given a short request, find the strongest realistic builds and return PoB import
codes plus an explanation. "Strongest" is defined by an explicit objective over
PoB outputs under explicit constraints. "Realistic" is defined by gear rails
(affix tier limits, item level limits, no mirror-tier assumptions).

Path of Exile's build space is huge but two-level:

- **Skeleton (discrete, outer):** class + ascendancy + ascendancy notables,
  main skill, damage mode (hit / ignite / poison / bleed / DoT conversion /
  minion / trigger), support gems, keystones, 0-3 key uniques, aura set,
  weapon archetype.
- **Fill (near-continuous, inner):** which ~110 passive nodes, which rare
  affixes in each slot, which config toggles are legitimately on.

The inner problem is a numeric optimization with PoB as the objective function.
The outer problem is a search over candidates, where each candidate's fitness is
the result of the inner optimizer. This is the whole design.

## Layers

```
request ("fireball", "build around <unique>", "bow poison")
   |
   v
[search/candidates]  skeleton hypotheses
   |   sources: LLM proposals + combinatorial rules + corpus retrieval
   |   (tag_corpus / mod_corpus queries, condition graph from PoB mod parser)
   v
[search/screen]      cheap fitness: optimizer with tiny budget, keep top-K
   v
[optimizer]          full fitness per survivor
   |   tree_optimizer: greedy node power + swap passes under point budget
   |   gear_filler:    rares from PoEDB affix catalog under rails
   |   config_rules:   toggles enabled only if the build has a source
   v
[search/rank]        Pareto set over (DPS, EHP, resist compliance, cost proxy)
   v
[report]             import codes + per-build explanation (LLM writes prose
                     from optimizer traces; never invents numbers)
   ^
   |   optional second round: LLM proposes mutations of top results
```

### `pob/` (inherited)

Runs the pinned PoB Community release in-process via LuaJIT (`lua51.dll`
through ctypes) inside a worker subprocess. Python sends JSON, the worker
generates Lua that calls real PoB tab APIs, runs `OnFrame`, and dumps
`calcsTab.mainOutput` (~700 stats). Also exposes PoB's native node power
report and import-code round-trip verification.

Entry point: `junkroan.pob.session.PobSession`. Corpora:
`game_corpus` (gems, bases, passives, keystones, masteries, ascendancies,
config surfaces parsed from `vendor/pob/source`), `tag_corpus` (same, tag
indexed for search), `mod_corpus` (mod/stat families), `item_mod_lookup` and
`mod_data/poedb_affix_catalog` (84,907 affixes with tiers and weights).

Measured on this machine: boot 2 s, one calc 0.11 s.

### `optimizer/` (to build)

**Objective.** A function `score(stats) -> float` plus hard constraints. Default:

```
maximize  FullDPS
subject to  FireResist, ColdResist, LightningResist >= 75
            ChaosResist >= chaos_floor (default 0; rails may raise)
            Life (or ES/hybrid) >= life_floor
            <Type>MaximumHitTaken >= max_hit_floor per damage type (bossing defence, D53; TotalEHP is reported only)
            attribute requirements met (PoB reports missing requirements)
            unreserved mana >= cast cost * buffer
            allocated points <= budget(level)
```

Constraint violations are handled as penalties during search and as hard
filters at the end. The objective must be a small, swappable object so that
"bosser", "mapper", "tanky" profiles are just different objectives.

**Tree optimizer.** Input: skeleton + current tree. Loop:

1. Ask PoB for node power (marginal value of each reachable node under the
   current objective) or compute it by trial allocation.
2. Add the best node (value per point, path cost aware) until points run out.
3. Swap pass: remove the weakest allocated leaf, re-add the best candidate,
   accept if the objective improved. Repeat until no improvement.
4. Constraint repair: if a resist/life floor is violated, restrict the
   candidate set to nodes that fix it until satisfied.

Validation for this component: take a real strong build (XML from poe.ninja or
the user), strip N points, run the optimizer, require recovery within a few
percent of the original objective. This test is the definition of "done".

**Gear filler.** Input: skeleton (bases, uniques) + rails. For each rare slot,
choose affixes from the PoEDB catalog: first satisfy resist and attribute
floors at minimum affix cost, then spend remaining affix slots on the
highest marginal objective gain (measured in PoB, not assumed). Rails are
constraints: max tier, ilvl, number of explicit mods, influence allowed or not.

**Config rules.** A config toggle is on only if the build has a source for
it. Rules are small and mechanical, e.g. "enemy ignited" requires an ignite
source and a hit; "onslaught" requires a source; "power charges" requires a
generator. Where uncertain, report two lanes (conservative and optimistic).

### `search/` (to build)

**Skeleton model.** A dataclass with the fields listed above, serializable,
hashable, with a `to_session(pob)` method that applies it.

**Candidate generation.** Three sources, merged and deduplicated:

- Combinatorial rules: ascendancies compatible with the skill's tags, damage
  modes the skill supports (from gem stat data), support gems whose tags
  intersect the skill's tags (from `game_corpus`), keystones by damage mode.
- Corpus retrieval: uniques, notables and supports whose mods touch the
  relevant damage types / delivery / conditions. Conditional scalings
  ("per X", "if Y", "while Z") come from PoB's parsed mod structure and form a
  requirement graph, so an item that scales spell damage with evasion pulls in
  evasion sources as skeleton components.
- LLM hypotheses: free-form proposals in skeleton format. Wrong ones cost a
  few seconds of PoB time and are discarded by fitness.

**Search.** Beam search over skeletons: screen all candidates with a small
optimizer budget, keep top-K, fully optimize, then optionally mutate the top
results (swap one component) for another round. Evolutionary in spirit,
bounded in compute.

**Ranking.** Pareto front over the objective components, not a single scalar,
because PoB does not model clear speed, uptime or comfort. Every reported
build carries its optimizer trace: which nodes/affixes were chosen and the
marginal gain each added.

### `mechanics/` (hand-maintained, small)

Facts PoB does not compute: corpse supply limits, orb caps, overlap
breakpoints, uptime realities. Stored as JSON records with `skill_gates`,
`effect` (constraint | penalty | note), and numeric parameters where they
exist, so the optimizer and ranker can consume them. Sourced from
`reference/legacy/skill_scaling_facts.py` (353 community notes) as needed,
one at a time, only when a benchmark shows PoB-only ranking is misleading.

## Role of the LLM

- Proposes skeleton hypotheses (creative step).
- Writes or adjusts search space definitions for a request.
- Translates optimizer traces into explanation prose.
- Never chooses nodes, affixes, or config values. Never asserts numbers.

## Role of poe.ninja

Calibration only. If the optimizer's version of a common archetype is much
weaker than the ninja median under the same config, the optimizer is broken.
Ninja builds are never templates for output.

## Updating for a new league

1. Bump `locks/pob.lock.json` to the new PoB release; run the corpus
   regeneration commands (`game_corpus`, `tag_corpus`, `mod_corpus` CLIs).
2. Re-run PoEDB ingestion (`poedb_affix_ingestion.py refresh`).
3. Re-run the benchmark; investigate regressions.
4. Update `mechanics/` only where patch notes change a non-PoB fact.
