"""Derived child seeds of the optimizer (#464): no PoB."""

from junkroan.optimizer.seeds import PURPOSES, PURPOSE_TREE_KICK, derive_seed


def test_derived_seeds_are_distinct_and_exact_doubles():
    seen = set()
    count = 0
    for s in range(1, 1001):
        for purpose in PURPOSES:
            for p in range(1, 17):
                for d in range(4):
                    v = derive_seed(s, purpose, p, d)
                    assert 0 <= v < 2**53
                    seen.add(v)
                    count += 1
    assert count == 1000 * 16 * 4 * len(PURPOSES)
    assert len(seen) == count, f"{count - len(seen)} collisions"


def test_old_tree_kick_formula_collided_the_new_one_does_not():
    p = 2
    old = {s + 7919 * p + d for s in (7, 8, 9) for d in range(3)}
    assert len(old) == 5
    new = {derive_seed(s, PURPOSE_TREE_KICK, p, d) for s in (7, 8, 9) for d in range(3)}
    assert len(new) == 9


def test_derive_seed_is_deterministic_and_pinned():
    assert derive_seed(7, PURPOSE_TREE_KICK, 2, 1) == derive_seed(7, PURPOSE_TREE_KICK, 2, 1)
    assert derive_seed(7, PURPOSE_TREE_KICK, 2, 1) == 6988737254251125
