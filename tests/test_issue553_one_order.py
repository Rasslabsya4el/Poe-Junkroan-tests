"""#553 unit 8: under the priced order, sorting (loop_key) and acceptance (better_loop_score) agree; PoB-free."""

import itertools

from junkroan.optimizer.objective import Score, accepts_under, better_loop_score, loop_key


def test_priced_tie_sort_pick_is_accepted():
    cur = Score(-0.5, 0.0)
    a = Score(-1.2, 1e6)
    b = Score(-0.3, 0.0)
    assert loop_key(a) > loop_key(b)
    assert better_loop_score(a, cur)
    assert better_loop_score(b, cur)
    pick = max([a, b], key=loop_key)
    assert pick is a and better_loop_score(pick, cur)


def test_sort_and_acceptance_agree_for_all_pairs():
    scores = [Score(nv, v) for nv in (0.0, -0.02, -0.3, -0.5, -1.2) for v in (-1.0, 0.0, 1e6, 2e6)]
    for x, y in itertools.permutations(scores, 2):
        assert better_loop_score(x, y) == (loop_key(x) > loop_key(y)), (x, y)


def test_gem_line_keep_follows_order():
    gem, ordinary = Score(-0.02, 2e6), Score(0.0, 1e6)
    assert accepts_under("priced")(gem, ordinary) is True
    assert accepts_under("floors")(gem, ordinary) is False
