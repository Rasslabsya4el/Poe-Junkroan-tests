"""#553 / D116: the priced score of the improvement loop. PoB-free."""

import math

from junkroan.optimizer.objective import Score, better_loop_score, better_score, loop_key, priced_value

V = 1_000_000.0


def test_row_1a_crumb_of_floor_does_not_buy_a_dps_collapse():
    cur, new = Score(-0.0195, V), Score(-0.0024, 0.2547 * V)
    assert better_score(new, cur) is True  # the defect
    assert better_loop_score(new, cur) is False


def test_row_1b_feasible_with_small_loss_wins():
    assert better_loop_score(Score(0.0, 0.99 * V), Score(-0.0195, V)) is True


def test_row_1c_far_from_floor():
    cur = Score(-1.469, V)
    assert better_loop_score(Score(-0.648, 0.05 * V), cur) is True
    assert better_loop_score(Score(-1.2, 0.01 * V), cur) is True
    assert better_loop_score(Score(-1.6, 2 * V), cur) is False


def test_feasible_min_gain():
    cur = Score(0.0, V)
    assert better_loop_score(Score(0.0, 1.004 * V), cur, min_gain=0.005) is False
    assert better_loop_score(Score(0.0, 1.006 * V), cur, min_gain=0.005) is True


def test_feasible_to_infeasible():
    cur = Score(0.0, V)
    assert better_loop_score(Score(-0.1, 1.5 * V), cur) is True
    assert better_loop_score(Score(-0.1, 1.05 * V), cur) is False


def test_dead():
    assert better_loop_score(Score(0.0, 0.0), Score(-0.5, V)) is False
    dead = Score(-1.0, float("-inf"))
    p = priced_value(dead)
    assert p == float("-inf") and not math.isnan(p)
    live = Score(-1.0, 5.0)
    assert sorted([dead, live], key=loop_key)[0] is dead
    assert max([dead, live], key=loop_key) is live


def test_loop_key_max():
    a, b = Score(-0.0195, 0.2547 * V), Score(0.0, 0.99 * V)
    assert max([a, b], key=loop_key) is b
    c, d = Score(-1.6, 2 * V), Score(-1.2, V)
    assert max([c, d], key=loop_key) is d
