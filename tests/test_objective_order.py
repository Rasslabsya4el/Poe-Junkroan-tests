"""D88 in the Score ordering itself: a score with value <= 0 never ranks above one with value > 0.

PoB-free. Order key: (value > 0, neg_violation, value)."""

from junkroan.optimizer.objective import Score


def test_dead_never_outranks_live():
    assert not (Score(0.0, 0.0) > Score(-0.012, 100.0))
    assert Score(-0.012, 100.0) > Score(0.0, 0.0)
    assert Score(0.0, 0.0) < Score(-0.012, 100.0)
    assert Score(-0.5, 10) > Score(-0.012, 0)
    assert Score(-0.5, 10) >= Score(-0.012, -3)
    assert Score(0.0, -1.0) <= Score(-9.0, 0.5)


def test_live_keeps_old_order():
    assert Score(0, 100) > Score(-0.012, 200)
    assert Score(0, 200) > Score(0, 100)
    assert Score(-0.1, 5) < Score(-0.01, 1)


def test_dead_is_violation_first():
    assert Score(0, 0) > Score(-0.012, 0)
    assert Score(0, -5) > Score(-0.012, 0)
    assert Score(0, 0) > Score(0, -5)


def test_sorted_puts_dead_last_and_max_is_live():
    scores = [
        Score(0.0, 0.0),
        Score(-0.3, 50.0),
        Score(0.0, -4.0),
        Score(-0.012, 100.0),
        Score(0.0, 10.0),
        Score(-0.012, 0.0),
    ]
    ordered = sorted(scores, reverse=True)
    values = [s.value > 0 for s in ordered]
    assert values == [True, True, True, False, False, False]
    assert ordered[:3] == [Score(0.0, 10.0), Score(-0.012, 100.0), Score(-0.3, 50.0)]
    assert max(scores) == Score(0.0, 10.0)
    assert max([Score(0.0, 0.0), Score(-0.012, 100.0)]) == Score(-0.012, 100.0)
    assert min(scores).value <= 0


def test_equality_hash_construction_unchanged():
    assert Score(0, 1) == Score(0, 1)
    assert Score(0, 1) != Score(0, 2)
    assert len({Score(0, 1), Score(0, 1), Score(-0.1, 1)}) == 2
    s = Score(neg_violation=-0.2, value=3.0)
    assert (s.neg_violation, s.value) == (-0.2, 3.0)
    assert s.violation == 0.2 and not s.feasible
    assert Score(0, 1) <= Score(0, 1) and Score(0, 1) >= Score(0, 1)
    assert Score(0, 1).__lt__((0, 1)) is NotImplemented
    assert Score(0, 1).__ge__(5) is NotImplemented


def test_better_score_keeps_its_own_tuple_rule():
    """#15: the type orders live over dead, but `better_score` keeps its behaviour exactly: a live
    move that misses more floors does not replace a dead build, and D88's guard still holds."""
    from junkroan.optimizer.objective import better_score

    assert not better_score(Score(-0.5, 10.0), Score(0.0, 0.0))
    assert better_score(Score(0.0, 10.0), Score(-0.5, 0.0))
    assert not better_score(Score(0.0, 0.0), Score(-0.012, 100.0))
    assert better_score(Score(0.0, 110.0), Score(0.0, 100.0), min_gain=0.05)
    assert not better_score(Score(0.0, 104.0), Score(0.0, 100.0), min_gain=0.05)
