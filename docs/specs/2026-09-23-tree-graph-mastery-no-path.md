# Spec 2026-09-23: a mastery is taken through its notables but never passed through (CODE ONLY, ~20 min)

Lead: Opus 5.5. No PoB, no `machine_load`, no benchmarks, no whole suite. Only the files named. No scratch files.

## The rule (the game, confirmed by the owner)

A mastery can be allocated when ANY notable of its cluster is allocated, but it is not a path: a notable is connected
to the tree only through its own passives, never through the mastery to another notable of the cluster.

## The bug (found 2026-09-23 by `scripts/graph_path_probe.py`)

`src/junkroan/optimizer/tree_graph.py`, `TreeGraph.load`, ~lines 104-110, builds `adjacency` symmetrically from the
corpus, so a mastery node expands to every notable of its cluster. On spark-s1 our graph connects Divine Judgement
(13164) through Divine Wrath (14665) -> Elemental Mastery (44298) -> 13164, and `cascade_if_removed(allocated, 8198)`
returns {8198}; PoB's own removal of 8198 also removes 13164.

## Steps

1. In `TreeGraph.load`, right after the symmetric adjacency loop: for every mastery node id (`mastery_ids`, already
   computed in that function) set `adjacency[m] = set()` -- a mastery expands to nothing; the notables keep the edge
   to their mastery (so the mastery stays reachable and allocatable from any allocated notable of its cluster). One
   short comment with the rule above. Nothing else changes in `tree_graph.py`.
2. Check with the probe (no PoB): `python scripts/graph_path_probe.py` must now report that no path to 13164 exists
   without 8198. Quote its output in your report.
3. Tests in `tests/test_tree_graph.py` (add, do not remove existing ones): on the real corpus (`TreeGraph.load()`,
   no PoB) with the spark-s1 allocation (decode the build file named in `scripts/graph_path_probe.py` the same way the
   probe does): `cascade_if_removed(allocated, 8198)` contains 13164 and 8198; `neighbours(44298)` is empty; 44298 is
   in `neighbours(14665)`. Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_tree_graph.py tests/test_graph_path_probe.py tests/test_graph_tree_authoring.py`
   If an EXISTING test fails, do not change it: stop and put its name and failure in the report. Otherwise commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, `git diff --stat`, the pytest line, the probe output.
