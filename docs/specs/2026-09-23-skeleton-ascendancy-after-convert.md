# Spec 2026-09-23: our skeleton takes the author's ascendancy nodes AFTER tree conversion (CODE ONLY, ~30 min)

Lead: Opus 5.5. The lead verifies with PoB afterwards; you do NOT start PoB.

## Why (measured by the spec-A coder, merged 7df0403)

z325_berserker_ground_slam_autocry: the fixture allocates 8 ascendancy nodes on its old tree. `pob.convert_tree()`
drops node 59920 "Aspect of Carnage" (on the current tree its prerequisite 63673 is not allocated). Our skeleton is
read from the PRE-conversion XML, still lists all 8 ids, and `set_tree` later paths through the missing prerequisite:
our build ends with 9 ascendancy nodes and the audit rejects it ("9 ascendancy nodes allocated; the rails allow 8").
Rule (the lead): our skeleton's ascendancy nodes are the author's nodes that are STILL allocated after conversion.

## Hard limits

No PoB, no `machine_load`, no benchmark / dump scripts, no whole suite. Only the files below. No scratch files in the
repository. Commit after step 3.

## Steps

1. Read `scripts/benchmark.py` function `prepare_author` (the nested `load_author`: `pob.load_xml` then
   `pob.convert_tree()`, and the `skeleton_from_xml(...)` call after it) and `scripts/build_from_skeleton.py`
   (`skeleton_from_xml`, and `_fixed_ascendancy_nodes` which already filters ids by the selected ascendancy).
2. Add a keyword argument to `skeleton_from_xml`, e.g. `allocated_after_convert: set[int] | None = None`: when given,
   drop every ascendancy node id not in it, with one log line per id
   `fixture ascendancy node <id> '<name>' dropped: not allocated after tree conversion`. In `prepare_author`, after the
   FIRST `load_author` (the one that converts), read the allocated node ids from PoB (use the existing read API that
   `scripts/build_from_skeleton.py` / `src/junkroan/optimizer/tree_graph.py` already use to read allocated nodes -- find
   it in those two files only) and pass them. Default `None` keeps today's behaviour for every other caller.
3. Tests in `tests/test_skeleton_from_xml.py` (fake PoB / no runtime): an XML with 8 ascendancy ids and an
   `allocated_after_convert` set missing one -> the skeleton has 7 and the log line; `None` -> unchanged. Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_skeleton_from_xml.py tests/test_pipeline_invariants.py`
   Fix until green, `git add` the changed files, commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, `git diff --stat`, pytest summary line, one sentence per file.

Durations for a human (seconds under ~90 s, then minutes).
