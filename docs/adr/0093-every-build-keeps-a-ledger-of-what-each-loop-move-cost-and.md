# 2026-09-20 D93. Every build keeps a ledger of what each loop move cost and gave; the kicks stay (written 2026-09-22, owed)

Status: Accepted

Merged 3568a0b. `BuildResult.moves` (per move: where, tries, kept, judged-and-reverted, gain, time), `pob_calls` (count
and time per kind of PoB round trip) and `tree_churn` (1 - Jaccard construction vs final) go into results.json, the
search's per-build JSON, `summary()`, `describe_build` and `benchmark.py --rereport`. No optimizer decision reads the
ledger and it adds no PoB call to any move. Identity on a real build exact (stormbrand s1: construction 1,028,597 + the
kept gains = 1,555,422). First reading over 180 loot builds (`docs/readings/2026-09-22-move-ledger.md`): the loop is
32 min a build; picks are the engine (29% of the summed gain for 15% of the time, 157 of 180 builds); the two kicks are
48% of the loop's time for 17.5% of its gain and STAY: they run only after a pass keeps nothing, hit 80-86 of 180 builds
for ~7-10% of the final value each, and dividing kick joint out moves `main-smoke`'s median of medians 139 -> ~133;
the region challenge kept something on 11 of 180 builds (0.6% of the gain for 5.7% of the time) -> out of the default
loop if a paired smoke shows no loss beyond the A/A noise (D100). Parallelism inside one build (the owner's question):
the kicks' 3 + 4 independent draws are the natural first target (about a third of one build's loop wall clock on 4
workers, identical results with per-draw seeds); it shortens one request's wait, not a benchmark's throughput.

