# PobSession

Moved verbatim from CLAUDE.md on 2026-09-26 (#45); it binds every agent as if it were still written there. CLAUDE.md sections "PobSession cheat sheet" and "Known harness limitations".

## PobSession cheat sheet

- `load_xml` / `load_import_code`: replace the whole build (reference fixtures).
- `set_identity`, `set_tree`, `set_skills`, `set_items`, `set_config(inputs={...})`:
  full re-apply of one surface. Config `inputs` takes any PoB config var name.
- `mutate_nodes(add=, remove=, mastery_effects=)`: incremental tree edit,
  0.06 s. Removal cascades; the result lists exact diffs and lost mastery
  effects. Mastery adds need their effect id.
- `stats(keys)`: fast recalc + scalar stats, 0.07 s. Use in loops.
- `trial_stats(trials, keys, mode="fast")`: evaluate many {add, remove,
  mastery} candidates in one round trip through PoB's what-if calculator,
  7 ms per trial, build untouched. `mode="full"` really allocates and recalcs
  (0.1-0.17 s) and is only for cross-checking. The optimizer uses fast mode;
  do not loop mutate/stats by hand.
- `calc(lane)`: full two-lane snapshot, 0.17 s. Use for reports.
- Tree version (D67): a loaded build keeps the tree its XML declares (36 of 37 references
  are on 3_25-3_28) and `load_xml` never converts. `tree_version()` /
  `latest_tree_version()` read it, `convert_tree()` runs PoB's own
  `ConvertToVersion` to the latest and returns `{from, to, converted,
  nodes_before, nodes_after, lost_node_ids}`. The benchmark and
  `build_from_skeleton --from-fixture` convert the author first; the audit and
  `describe_build` never do.
- `node_power()`: PoB native per-node marginal value, ~17 s. Once per round.
- Config: `config_options(predicates)` = PoB's view of which inputs matter;
  `config_inputs()` = current values; `set_config(..., inputs=, conditional=,
  preserve="numeric")` writes Baseline/Conditional lanes and keeps numeric
  inputs; since 7.1h it applies in place, no XML reload (593 -> 166 ms,
  `set_skills` 469 -> 63 ms, byte-identical exports).
  `optimizer/config_rules.derive_config(pob)` builds both lanes.
- Day-1 gear = loot simulation (D19): `random_rares(base, n=)` rolls rares
  with PoB spawn weights, `list_bench_mods(base)` bench crafts;
  `optimizer/loot_gear.py` does best-of-N per slot + one bench craft.
- Gear: `list_item_mods(base, ilvl=)` legal mods with tier ladders and weights;
  `craft_rare(base, prefixes=, suffixes=, ilvl=, ...)` PoB-validated raw text;
  `equip({slot: raw})` single-slot change (`set_items` replaces the whole set);
  item trials `trial_stats([{"item": {"slot", "raw"}}], keys, mode="fast")`.
- Tree jewels (#434): `put_jewel(node_id, raw)` into an ALLOCATED socket (raises otherwise), `remove_jewel(node_id)`,
  `socketed_jewels()` -> {node_id: raw}; `equip` rejects socket slots on purpose. `set_tree(jewels={node_id: raw})`
  clears every socket first and re-applies only `jewels`; `mutate_nodes` leaves a socketed jewel alone; a `fast`
  removal trial of the socket sees the jewel go (`tests/test_jewel_socket_pob.py`).
- Boss ailment threshold (#703): `tests/test_ailment_threshold_pob.py` reads PoB's Guardian/Pinnacle threshold at Enemy Level 83 / 84 / 85 (5,473,455 / 6,349,995 / 6,741,575, CalcOffence.lua:5210-5218) and fails on a PoB bump that moves it.

## Known harness limitations (fix via roadmap Phase 1, not ad hoc)

- `set_items` replaces the whole item set through an XML round trip; use
  `equip` for slot changes.
- `PinnedPoBHeadlessRuntimeAdapter.equip_item` only supports Boots (v1 proof
  artifact). Use `PobSession.set_items`.
- ~~Warden (PoB id "Raider"): `set_tree(ascendancy_nodes=...)` reports the nodes
  did not materialize; the search skips Warden until fixed.~~ Fixed 2026-09-18:
  a node carries the ascendancy *id*, not its display name, so the worker matches
  on `curAscendClassBaseName`; the search no longer skips Warden and takes either
  spelling ("Warden" / "Raider").
