# 2026-09-18 D67. The author is scored on the tree our build is grown on

Status: Accepted

36 of the 37 reference fixtures declare an older passive tree in their `<Spec treeVersion=…>`
(3_25 x2, 3_26 x5, 3_27 x13, 3_28 x16) and PoB keeps it: `TreeTab:Load` builds the spec at the
version the XML names (`TreeTab.lua:511`) and never converts by itself -- `ConvertToVersion`
(`:588`) sits behind a UI button. Our own builds start from
`new("PassiveSpec", build, latestTreeVersion)` = 3_29. So the benchmark's "% of author" compared
two different passive trees, and the floors it demands of our build (Life, TotalEHP, max hit,
resists) were read off the old one (`docs/research/2026-09-18-pob-version-audit.md`, section 2).

The harness now has PoB's conversion: `PobSession.tree_version()` / `latest_tree_version()` /
`convert_tree(version=None)`, the last one calling `TreeTab:ConvertToVersion` (a fresh spec at the
target version with the old spec's class, hash list, mastery selections, tattoos and jewels
replayed onto it) and reporting
`{"from", "to", "converted", "nodes_before", "nodes_after", "lost_node_ids"}`, where "lost" are
allocated nodes the target tree does not have or that PoB pruned for losing their path.
`read_state()["tree_state"]` carries `tree_version` / `latest_tree_version` next to
`user_allocated_node_ids`; before this the harness was blind to which tree a loaded build sat on.

`scripts/benchmark.py` converts the author's build right after it is loaded (and again after the
full-DPS-count reload), and `scripts/build_from_skeleton.py --from-fixture` does the same; the
author's row, their floors and their "under our lane" number are then on our tree.
`scripts/audit_build.py` and `describe_build.py` do **not** convert: they read a build as it is.
Neither does `load_xml` -- a read-only load stays faithful to the build it was handed. The
benchmark's author memo now carries `tree_version`, and a memo without it (written before this) or
with another one is ignored instead of replayed.

Measured (author's own config, before -> after conversion):

| fixture | tree | CombinedDPS | FullDPS | Life | TotalEHP | allocated nodes whose stats changed |
|---|---|---|---|---|---|---|
| stormbrand | 3_28 -> 3_29 | 898,678 -> 898,678 (+0.00%) | 1,797,356 -> 1,797,356 | 4,156 -> 4,156 | 10,822 -> 10,822 | 2, both cosmetic ("Global Accuracy Rating" -> "Accuracy Rating", stat-line order) |
| impale_cyclone | 3_27 -> 3_29 | 783,488 -> 783,488 (+0.00%) | 0 -> 0 | 3,877 -> 3,877 | 10,761 -> 10,761 | 11: 9 cosmetic accuracy rewordings, plus Attack Mana Cost -> Attack Cost Efficiency and Spirit of War, which move cost and not this build's damage |
| arc_archmage | 3_25 -> 3_29 | 535,630 -> **537,202** (+0.29%) | 1,022,549 -> 1,024,121 (+0.15%) | 4,023 -> 4,023 | 21,573 -> 21,573 | 12: the 3.29 cost rework on 8 mana/life nodes, Arcane Blessing "grants" -> "also grants", 1 cosmetic |

`lost_node_ids` was empty on all three and the allocated set came back identical (110 / 107 / 104
nodes), as the additive ids predict. The effect is small -- the largest is arc_archmage's +0.29%,
well inside the 41.6-point seed spread -- so this is a correctness fix, not a scoring change, and
it closes the one systematic bias the comparison had no number for.
