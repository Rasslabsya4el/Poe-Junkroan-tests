# 2026-09-18 D71. A request delivers the best of three seeds per finalist skeleton

Status: Accepted

One skeleton built twice is two different builds: the seed reaches the loot roll of gear pass 1 and
the loop's kicks, and the greedy tree in between is deterministic (26 regrowths bit-identical,
Jaccard 1.000). Measured over 42 builds of the smoke set, 6-9 seeds per reference
(`docs/research/2026-09-18-restarts-statistics.md`), the expected best of K seeds is 153.6 / 165.5 /
171.0 / 174.4 % of the author for K = 1..4: the third seed is worth +5.6 points, the fourth +3.4 and
every one after it less.

**The product therefore builds three.** The search's full stage fans each finalist skeleton out into
`seeds` jobs (default 3; `--seeds N` on `scripts/search.py` and `junkroan build`, `seeds` in a
request file) in the one process pool, so 2 finalists x 3 seeds = 6 jobs share `--workers`. The best
build by the objective's Score (feasibility first, then the violation, then the value; a tie keeps
the lowest seed) is the delivered one; the losing seeds are written next to it as
`<slug>-s<seed>.pob.txt` and their numbers stand in the report, so the spread is visible instead of
hidden behind the winner. The unique-variant and mutation rounds are single builds on their parent's
winning seed: the seeds are spent on the finalists, not multiplied by the variants.

**What the report says.** The summary table has a `seed` and a `spread` column (max - min as a share
of the best), and the winning build's explanation carries one line: "best of 3 seeds (seed 2):
806,199 / 741,002 / 690,113; spread 14.4% of the best."

**The echo's estimate follows the jobs, not the candidates.** `request.estimate_minutes` =
ceil(candidates / workers) x 3 min of screening + ceil(finalists x seeds / workers) x 40 min of full
builds; the default request (top 2, 3 seeds, 5 workers) echoes ~83 min, inside docs/REQUEST.md's
two-hour promise. `max_builds` now caps candidates and full builds both.
