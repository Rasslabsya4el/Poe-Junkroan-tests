# 2026-09-11 D25. Scaling vectors are derived from PoB's parser

Status: Accepted

`scaling_vectors.json` is built by running every mod line of every unique,
notable, keystone, mastery effect, ascendancy node and support through
`modLib.parseMod` and collecting `PerStat` / `Multiplier` / `Condition`
tags. A vector is `per:Str`, `per:FrenzyCharge`, `cond:LowLife`... with its
payoff sources and, for `per:` vectors, the sources that grant the stat
directly. 477 vectors, 1,310 of 9,662 lines unsupported by PoB (those are
unsupported in PoB itself, so they cannot be judged and are skipped). This
is the retrieval index the hypothesis layer reads; no hand-named keys.

