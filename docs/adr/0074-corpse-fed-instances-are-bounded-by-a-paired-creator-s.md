# 2026-09-18 D74. Corpse-fed instances are bounded by a paired creator's capped pool

Status: Accepted

`derived_counts` does not treat Volatile Dead's `3 corpses x Spell Cascade areas` as an unconditional
instance count. It now derives `min(consumer corpses x consumer areas, creator corpses x creator
areas, creator pool cap)`, with one creator cast per consumer cast for both hand-cast alternation and
triggered pairs. The two-casts-per-consumer case is deliberately unmodelled until the skeleton can
express it.

The numbers all come from PoB data: consumer and creator facts and Cascade areas from skill blocks;
pool-cap modifiers from the passive corpus, applied only when their node is allocated in PoB's live
tree. This makes Undertaker's corpus line raise Desecrate / Unearth from cap 10 to cap 12 without a
hard-coded passive id or skill list in the arithmetic.

Measured under the current author lane with rails gems and the derived count written through
`flag_main_group_for_full_dps`: Archmage Volatile Dead (cascaded creator) is 9 instances and
936,332.00 FullDPS; VD Spellslinger is 9 and 365,858.91; removing Spell Cascade only from the
Archmage Desecrate group is 5 and 522,055.16. `tests/test_corpse_counts.py` proves the pool cap
10 -> 12 and all three fixture cases; the full suite passed 684 tests, 6 deselected.

