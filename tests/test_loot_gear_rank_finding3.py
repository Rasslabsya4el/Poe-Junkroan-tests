"""`_rank` keeps main's order (#179, round 3): the first round's violation-first change of `_rank`
on an emptied slot was reverted; the fill's guard against a worse pass 2 is the whole-set judge
(`tests/test_loot_gear_keep_best_179.py`), not the per-slot ranking.

Dropped from round 2: `test_an_emptied_slot_still_prefers_the_lower_violation_candidate`
(asserted violation first against an `inf` current; main's order does not). Kept: a finite
infeasible `current` ranks as it always did. Unit 3 of #179 brings violation-first back as a
second construction.
"""

from __future__ import annotations

from junkroan.optimizer.loot_gear import _rank
from junkroan.optimizer.objective import Score


def test_a_finite_current_ranks_the_same_as_today() -> None:
    """`current` is infeasible but finite (violation 0.5): A (violation 0.2, value 100) outranks
    B (violation 0.3, value 200)."""

    current = Score(neg_violation=-0.5, value=0.0)
    a = Score(neg_violation=-0.2, value=100.0)
    b = Score(neg_violation=-0.3, value=200.0)

    assert _rank(current, a) > _rank(current, b)
