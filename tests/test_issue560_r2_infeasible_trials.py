"""#560 (kind B, D113, PoB-free): R2 of #550 in `pick_supports` - a legal incumbent link whose every support trial scores
infeasible (a scored result: violation > 0, or a dead value 0; never a raise) is delivered unchanged, never `[]`.
Trace: `support-trial:raised` 0 (generated and evaluated), `support-repick:fewer-at-equal` evaluated 0. No PoB."""

from __future__ import annotations

import pytest

from junkroan.optimizer.objective import Score
from junkroan.optimizer.trace import TRACE
from test_issue550_repick_keeps_supports import INCUMBENT, _gen


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _counter(key: str, field: str) -> int:
    return sum(v[field] for classes in TRACE.considered().values() for c, v in classes.items() if c == key)


def _run(other: Score) -> None:
    gen, sk, state = _gen(INCUMBENT, lambda _l: 100.0)
    # the incumbent is feasible at 100; every other link scores `other` (a result, never a raise)
    gen._score = lambda: Score(0.0, 100.0) if state["link"] == INCUMBENT else other
    link = gen.pick_supports(sk, n_supports=4)
    assert link == INCUMBENT and link != []
    assert sk.main_link == INCUMBENT
    assert state["link"] == INCUMBENT
    assert _counter("support-trial:raised", "generated") == 0
    assert _counter("support-trial:raised", "evaluated") == 0
    assert _counter("support-repick:fewer-at-equal", "evaluated") == 0


def test_a_every_other_link_infeasible_keeps_the_incumbent() -> None:
    _run(Score(-1.0, 500.0))  # neg_violation -1.0 = violation 1.0


def test_b_every_other_link_dead_keeps_the_incumbent() -> None:
    _run(Score(0.0, 0.0))
