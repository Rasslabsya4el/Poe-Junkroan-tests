# Rails

Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there. CLAUDE.md section "Rails worth remembering".

## Rails worth remembering

- Gems: level 18, quality 0 (main skill 0) — `rails_default.json` `gems`.
  20/20 gems inflated results by up to 70% before D23. Never compare a
  generated build with an author's on unequal gem levels.
- Spectres (#173): `--spectre <id or name from Spectres.lua>` (repeatable) fixes the spectre of a Raise Spectre
  build. A Raise Spectre request without it is rejected, and the flag with another main skill is rejected too:
  the system never chooses the spectre on day 1. `Skeleton.apply` writes the id into the build's `spectreList`
  and the gem's `skillMinion`; a trial that rewrites a whole build XML without `<Spectre id>` is counted
  `forced-missing:spectre:<id>`.
- Gear: best-of-200 random rares per slot + one bench craft (D19/D21).
- Movement speed: `EffectiveMovementSpeedMod >= 1.2`, delivered by boots, with
  the benchmark's 0.97 slack (D55: the loot's boots reach 1.19x against an
  author at exactly 1.20x); tree stages optimize without that floor (D28).
- Config: conservative lane needs proof; skill options are assumptions;
  list options (stance) are judged by PoB (D22/D24) except ramp-type ones,
  computed from the ramp budget and written as a custom-mod block (D62 amd 3:
  Pride is not a free MIN/MAX choice); numeric inputs come from build proof +
  `rails_default.json` `assumptions` (D26), ramp counts from `ramp_inputs.py`.
- Pipeline (D58): construction (skeleton -> config -> gear 1 -> tree
  greedy -> gear 2 -> tree rebuilt on gear) -> the improvement loop
  (`BuildPipeline._improvement_loop`: tree refine, path swaps, one rare
  slot re-rolled with its tree repair, the picks; kicks = ruin-and-recreate
  over the tree and over tree + gear, 3 + 4 draws each judged on its own,
  when a pass keeps nothing) run to the pass that keeps nothing. The old
  chain of six stages is gone; `--loop` is a no-op. The picks move also
  drops one reserving socket group per pass while the build is infeasible
  (D72, `SkeletonGenerator.drop_reserving_group`): the only move that can
  lower reservation. Which groups reserve is read from PoB
  (`ManaUnreserved` / `LifeUnreserved` rising when the group is disabled),
  never from gem names; on a feasible build the move is inert.
- Tree moves: greedy -> refine (1-for-1) -> ruin-and-recreate -> path-for-path
  subtree swaps (D27). Every odd-looking node has a PoB number behind it;
  the user's "this looks wrong" is a hypothesis to measure, not an order.
- The +30 attribute-requirement cap (`attribute_plus30_nodes_max`, #430) holds on every
  allocation path, before PoB (#516): greedy, clusters, refine's add-probe and swaps,
  `repair_target_first`.
- Self-degen: no degen while idle (D63.3, replacing D34's -100):
  `NetLifeRegen + NetEnergyShieldRegen + SelfCostPerSecond >= 0`, without
  leech and without recoup, scaled against the life pool.
- Uniques: PoB "Source:" class `core`, req level <= 70, wiki drop-rate tier
  3-5, not drop-disabled (D31; `Rails.unique_allowed`). Refresh
  `corpus_data/unique_tiers.json` once a league through a browser (the wiki
  blocks bots), then rerun `scripts/build_unique_index.py`. Sustain: regen +
  leech + recoup >= 85% of per-second cost per resource, and 100% for a
  channelling main skill (D63.2, `objective_select.with_skill_floors`); rig
  stages use `Objective.without_sustain()` because a bare rig has no regen
  gear yet.
- After any search or rebuild: run the audit AND open the top PoB XMLs
  yourself (tree, gems, items, config) looking for logical errors the
  numbers cannot see. Turn each new kind of error into an audit check.
