# 2026-09-15 D55. Stage ablation: reoptimize, path swaps and the touch-up do not pay; the rest does

Status: Accepted; amended by D55 amd 1, D103

The 11-stage pipeline accreted one stage per benchmark failure (D43-D45,
D54) and none was measured again after the later ones arrived. Each
stage was switched off alone on the two most sensitive references
(Cold DoT, Bleed Bow), 3 seeds, everything else as of the evening of
2026-09-14 (`scripts/benchmark.py --ablate`, `scripts/ablation_summary.py`;
per-seed ratios to the author under our lane, then the median; Cold DoT
seeds that missed the movement floor by the loot's 1% are counted):

| without | Bleed Bow s1/s2/s3 -> median | Cold DoT s1/s2/s3 -> median | build minutes |
|---|---|---|---|
| (baseline) | 116/108/117 -> 116% | 119/131/67 -> 119% | 35 |
| tree rebuilt on gear | 116/108/117 -> 116% (+0) | 113/101/92 -> 101% (-18) | 27 |
| reoptimize (3 ruin-and-recreate rounds) | 89/119/138 -> 119% (+3) | 127/150/84 -> 127% (+8) | 30 |
| path swaps | 226/98/117 -> 117% (+1) | 119/131/105 -> 119% (+0) | 30 |
| gear pass 3 | 63/41/77 -> 63% (-53) | 114/122/67 -> 114% (-5) | 34 |
| touch-up | 133/111/147 -> 133% (+17) | 119/131/67 -> 119% (+0) | 34 |
| joint tree+gear | 89/108/79 -> 89% (-27) | 111/131/67 -> 111% (-8) | 27 |
| picks re-judged | 111/122/108 -> 111% (-5) | 113/125/64 -> 113% (-6) | 33 |

Gear pass 3, the joint stage, the rebuild and the re-judged picks pay.
Reoptimize, path swaps and the touch-up do not: without each the medians
are equal or higher, inside the seed noise, so they are left out (run D,
the lean pipeline on all 14 references, judges the three together
against run C). Also seen: the loot's best-of-200 boots reach 1.19x
against an author at exactly 1.20x, so the benchmark's movement floor
gets the same 0.97 slack as life.

Amendment (2026-09-15, ROADMAP 7.1b): run D (the lean pipeline, the three
stages left out) on all 14 references gave Smite 86% and Bleed Bow 86%
where run E (the full pipeline) gave 140% and 116%. Reoptimize, path
swaps and the touch-up do not pay alone but pay together: each is one
more fixed-point pass over the same local optimum, and three of them
reach what one does not. The full pipeline stays until 7.1c replaces
the six post-rebuild stages with one improvement loop that runs to a
fixed point instead of a fixed count of passes.

