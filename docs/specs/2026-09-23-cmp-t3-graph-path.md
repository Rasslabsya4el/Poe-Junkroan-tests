# Task T3 (model comparison, 2026-09-23): why our tree graph calls a bridge node a leaf

CODE ONLY (pure Python on the repository's corpus data), about 30 minutes. Do NOT start Path of Building,
`machine_load`, benchmarks or the whole test suite. Do not read files other than those named. No scratch files in the
repository.

## The fact to explain

Build file `C:\Coding\poe-junkroan-archive\benchmark\20260921-2020-core14-tpl\spark-s1.pob.txt` (a PoB import code).
Our pure-Python graph `src/junkroan/optimizer/tree_graph.py` says allocated node 8198 has two allocated neighbours
(55993, 13164) and `TreeGraph.cascade_if_removed(allocated, 8198)` = {8198}: removing it disconnects nothing. PoB's own
removal of 8198 also removes 13164 (Divine Judgement). So our graph believes 13164 stays connected to the class start
through some other path that PoB does not accept.

## Steps

1. Write `scripts/graph_path_probe.py`: decode the build (`junkroan.pob.session.decode_import_code`), read the
   allocated ids (`junkroan.optimizer.tree_graph.parse_allocated_from_xml`), load `TreeGraph.load()`, find the class
   start the allocation hangs from (`TreeGraph.roots(allocated)` / `class_starts`), then BFS through allocated nodes
   EXCEPT a given node (default 8198) using `TreeGraph.neighbours`, from the root to a target (default 13164). Print
   the path found, one node per line: id, `node(id).kind`, `node(id).name`. Arguments: `--build`, `--remove`,
   `--target` (defaults as above). Read only `src/junkroan/optimizer/tree_graph.py` for the API.
2. Run it once and put the printed path in your final report. Then look at the kinds on that path and state in one
   sentence which node on it is one PoB would NOT treat as a connection (for example a mastery, a class start of
   another class, an ascendancy node) -- only if the printed kinds show it; otherwise say what the path is and that
   no kind stands out. Do not change `tree_graph.py`.
3. A test `tests/test_graph_path_probe.py` (new) for the BFS helper on a tiny hand-made adjacency (no corpus): path
   found / not found when the removed node is the only bridge. Run exactly:
   `python -m pytest -q -p no:cacheprovider -p no:faulthandler tests/test_graph_path_probe.py`
   Fix until green; `git add` the two files; commit.
4. Final message: `=== FINAL REPORT ===`, commit hash, `git diff --stat`, the pytest line, the printed path and your
   one-sentence observation.
