# 2026-09-23 D101. A mastery is reached from its notables but never passed through (TreeGraph)

Status: Accepted

Found with `scripts/graph_path_probe.py` (model-comparison task T3, D100 item 3): our pure-Python `TreeGraph` built a
symmetric adjacency, so a mastery expanded to every notable of its cluster and our graph connected notables to each
other THROUGH the mastery. spark-s1 (core14-tpl): Divine Wrath 14665 -> Elemental Mastery 44298 -> Divine Judgement
13164, so `cascade_if_removed(8198)` said {8198} while PoB's removal of 8198 also takes 13164 (CombinedDPS 1,018,180 ->
966,608). The game rule (the owner: any notable of the cluster enables the mastery; clusters of 2-3 notables exist):
the mastery is allocatable from any allocated notable of its cluster and is never a path. Fix (merged 6154f4f):
`adjacency[mastery] = {}` after the symmetric build; notables keep their edge to it, so it stays reachable and it
cascades away with the last notable of its cluster. Every traversal (frontier, cascades, leaves, corridors, bypasses)
now follows PoB here. Changes tree moves wherever 2-3 notables of one mastery are allocated; judged by `main3-smoke`
against `main2-smoke` (per build, `compare_runs --per-build`).


