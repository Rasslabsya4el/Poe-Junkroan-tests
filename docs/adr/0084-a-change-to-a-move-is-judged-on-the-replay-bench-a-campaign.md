# 2026-09-20 D84. A change to a move is judged on the replay bench; a campaign confirms, a smoke run only alarms

Status: Accepted

Measured on our own campaigns (`docs/research/2026-09-19-judging-plan.md`): one build's noise inside a reference is 15%
of its value; the smoke six x 3 seeds sees effects of ~15%, the full 32 x 3 of ~6%; identical code on other seeds
"shows" -2.0% at the median and -14.5% on cold_dot; the same seed does not carry over between code versions
(r = +0.10). `scripts/replay_bench.py` runs a move (a whole loop pass or one named move) from the same DELIVERED
builds under today's rules: the same code twice is bit-identical on all six smoke builds, another seed flips one kept
move on 2 of 6 (about 2 points each; mean +0.74%), a six-build run takes 21-25 minutes on 5 workers. Rules: (1) a
change to a move of the improvement loop is accepted on the bench (paired report over the same builds, gain and
seconds) and on structural counts from logs, never on one seed's final value; (2) a whole-pipeline campaign is the
confirmation, judged per reference with an interval over REFERENCES; (3) a smoke run is an alarm only, its mechanical
gate is -15 (2 sd of the A/A noise) or a count, never -5; (4) the bench replays under TODAY's rules: a build delivered
under older rules may start lower or infeasible (impale_ballista: recorded 963,133, replayed 674,530) and the report
says so and prints the paired statistics with and without such builds.

