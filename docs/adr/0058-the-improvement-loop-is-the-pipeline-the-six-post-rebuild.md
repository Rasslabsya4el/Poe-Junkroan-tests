# 2026-09-16 D58. The improvement loop is the pipeline; the six post-rebuild stages are deleted

Status: Accepted

Context: after "tree rebuilt on gear" the chain ran six stages (reoptimize,
path swaps, gear pass 3, touch-up, joint tree+gear, re-judged picks), each
an approximation of one pass of a fixed-point loop and each judged by its
own objective (D55 measured that three of them do not pay alone but pay
together). 7.1c built one loop over moves (tree refine, path swaps, one
rare slot re-rolled with its tree repair, the discrete picks; two kicks,
ruin-and-recreate over the tree and over tree + gear, when a pass keeps
nothing), every move judged by the full objective under re-derived lanes,
kept above 0.5%, run to the pass that keeps nothing.

Evidence (smoke set x 3 seeds, medians of ours / author under our lane):
the first loop (no kicks, refine and swaps as one batch, gear rolls
needing a repair rejected) lost to the chain on cold_dot and bleed_bow;
loop-smoke-2 (kicks with one draw) beat the chain on 4 of 5 comparable
references; loop-smoke-3 (kicks with the chain's 3 + 4 draws, 5400 s) beat
it on all six: cold_dot 137 vs 119, bleed_bow 147 vs 116, SRS 242 vs 198,
impale_ballista 84 vs 65, stormbrand 165 vs 124 (both under the brand
rule), burning_arrow_snipe 200 vs 169; 14 of 18 builds ended at a fixed
point. The one-draw kicks had called a fixed point 4.8% short on cold_dot
s1 (both draws missed where the chain's rounds 2 of 3 and 4 of 4 hit), and
stopping at the first kept draw starved the joint kick on bleed_bow s1
(148% -> 89% between two runs of the same seed), so every draw of both
kicks runs and is judged on its own, as the chain's rounds were.

Decision: `BuildPipeline.run` has one path after the rebuild, the loop
(`loop=True` is no longer a flag); the chain's stage code and its flags
(`reopt_rounds`, `path_swaps`, `gear_pass_3`, `touch_up`, `joint_rounds`,
`rejudge_picks` as stages) are deleted, `_joint_round` stays as the kick's
move, `screen=True` keeps its cheap path. Defaults: 16 passes, the time
budget (5400 s in the benchmark) is the real cap, min gain 0.5%. Spreads
across seeds stay large (bleed_bow 89 / 147 / 161) and are 7.3's subject:
restarts over loop runs, not per-build fixes.

