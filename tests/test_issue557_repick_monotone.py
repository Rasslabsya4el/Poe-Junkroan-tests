"""#557 R1' + R1'' (kind B, D113, PoB-free): the support re-pick is monotone (the result replaces the incumbent only at a
strictly greater score, whatever the sizes), and an incumbent holding a support outside the legal list, missing a gem of
the start link, scoring not above 0 or raising is no incumbent (an illegal one is never written into PoB). Trace
counters: `support-repick:below-incumbent` generated >= 1 and evaluated 0; `support:illegal` evaluated 0 (generated 1
when an illegal incumbent is met)."""

from __future__ import annotations

from typing import Callable

import pytest

from junkroan.optimizer.trace import TRACE
from test_issue550_repick_keeps_supports import BARE, _gen

MAIN = "Raise Spectre"
ILLEGAL = "Awakened Spell Cascade"
INCUMBENT4 = [MAIN, "Spell Echo", "Minion Damage", "Concentrated Effect", "Added Fire Damage"]


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _counter(key: str, field: str) -> int:
    return sum(v[field] for classes in TRACE.considered().values() for c, v in classes.items() if c == key)


def _by_size(incumbent: list[str], incumbent_value: float, sizes: dict[int, float]) -> Callable[[list[str]], float]:
    """The incumbent link scores `incumbent_value`; any other link scores `sizes[number of supports]`."""

    return lambda l: incumbent_value if l == incumbent else sizes.get(len(l) - 1, 0.0)


def test_a_same_size_below_keeps_the_incumbent() -> None:
    gen, sk, state = _gen(INCUMBENT4, _by_size(INCUMBENT4, 100.0, {0: 50.0, 1: 60.0, 2: 70.0, 3: 80.0, 4: 90.0}))
    link = gen.pick_supports(sk, n_supports=4)
    assert link == INCUMBENT4 and sk.main_link == INCUMBENT4 and state["link"] == INCUMBENT4
    assert _counter("support-repick:below-incumbent", "generated") >= 1
    assert _counter("support-repick:below-incumbent", "evaluated") == 0


def test_b_larger_at_equal_keeps_the_incumbent() -> None:
    incumbent = [MAIN, "Spell Echo", "Minion Damage", "Concentrated Effect"]
    gen, sk, _state = _gen(incumbent, _by_size(incumbent, 100.0, {0: 50.0, 1: 60.0, 2: 70.0, 3: 80.0, 4: 100.0}))
    link = gen.pick_supports(sk, n_supports=4)
    assert link == incumbent and sk.main_link == incumbent
    assert _counter("support-repick:below-incumbent", "evaluated") == 0


def test_c_strictly_greater_with_fewer_supports_stands() -> None:
    gen, sk, _state = _gen(INCUMBENT4, _by_size(INCUMBENT4, 100.0, {0: 50.0, 1: 60.0, 2: 110.0, 3: 70.0, 4: 70.0}))
    link = gen.pick_supports(sk, n_supports=4)
    assert len(link) == 3 and sk.main_link == link


def test_c_strictly_greater_with_more_supports_stands() -> None:
    incumbent = [MAIN, "Spell Echo", "Minion Damage"]
    gen, sk, _state = _gen(incumbent, _by_size(incumbent, 100.0, {0: 50.0, 1: 60.0, 2: 70.0, 3: 80.0, 4: 110.0}))
    link = gen.pick_supports(sk, n_supports=4)
    assert len(link) == 5 and sk.main_link == link


def _revive(value_of: Callable[[list[str]], float]):
    return _gen([MAIN, "Spell Echo", "Minion Damage", "Concentrated Effect", ILLEGAL], value_of)


def test_d_illegal_incumbent_at_zero_gives_the_bare_link_and_is_never_written() -> None:
    gen, sk, state = _revive(lambda _l: 0.0)
    link = gen.pick_supports(sk, n_supports=4)
    assert link == BARE and sk.main_link == BARE and state["link"] == BARE
    assert not any(ILLEGAL in w for w in state["written"])
    assert _counter("support:illegal", "evaluated") == 0
    assert _counter("support:illegal", "generated") == 1


def test_e_illegal_incumbent_and_one_live_trial_stands() -> None:
    gen, sk, _state = _revive(lambda l: 50.0 if l == [MAIN, "Spell Echo"] else 0.0)
    link = gen.pick_supports(sk, n_supports=4)
    assert link == [MAIN, "Spell Echo"] and sk.main_link == link
    assert ILLEGAL not in link


def test_f_legal_incumbent_at_value_zero_is_no_incumbent() -> None:
    gen, sk, state = _gen([MAIN, "Spell Echo", "Minion Damage"], lambda _l: 0.0)
    link = gen.pick_supports(sk, n_supports=4)
    assert link == BARE and sk.main_link == BARE and state["link"] == BARE
    assert _counter("support:illegal", "generated") == 0


def test_g_incumbent_missing_a_fixed_support_is_no_incumbent() -> None:
    fixed = "Added Fire Damage"
    incumbent = [MAIN, "Spell Echo"]
    gen, sk, state = _gen(incumbent, _by_size(incumbent, 100.0, {n: 50.0 + 10 * n for n in range(5)}))
    sk.fixed_supports = [fixed]
    link = gen.pick_supports(sk, n_supports=3)
    assert fixed in link and link != incumbent and sk.main_link == link
    assert incumbent not in state["written"]


def test_h_same_supports_in_another_order_at_equal_score_is_no_rejection() -> None:
    incumbent = [MAIN, "Spell Echo", "Minion Damage"]

    def value(l: list[str]) -> float:
        supports = set(l[1:])
        return 100.0 if supports == {"Spell Echo", "Minion Damage"} else (60.0 if supports == {"Minion Damage"} else 20.0 if supports else 10.0)

    gen, sk, _state = _gen(incumbent, value)
    link = gen.pick_supports(sk, n_supports=3)
    assert link == [MAIN, "Minion Damage", "Spell Echo"] and sk.main_link == link  # the result as is, not rewritten to the incumbent
    assert _counter("support-repick:below-incumbent", "generated") == 0
    assert _counter("support-repick:fewer-at-equal", "generated") == 0


def test_i_incumbent_whose_score_raises_is_no_incumbent_and_the_pick_goes_on() -> None:
    incumbent = [MAIN, "Spell Echo", "Minion Damage"]
    gen, sk, _state = _gen(incumbent, lambda l: 100.0 + 10 * (len(l) - 1) if l != incumbent else 0.0, raises_on=lambda l: l == incumbent)
    link = gen.pick_supports(sk, n_supports=2)
    assert len(link) == 3 and link != incumbent and sk.main_link == link
    assert _counter("support-trial:raised", "generated") == 1
    assert _counter("support-trial:raised", "evaluated") == 1


def test_j_incumbent_with_a_negative_value_is_dead() -> None:
    incumbent = [MAIN, "Spell Echo", "Minion Damage"]
    gen, sk, state = _gen(incumbent, lambda l: -5.0 if l == incumbent else -10.0)
    link = gen.pick_supports(sk, n_supports=4)
    assert link == BARE and sk.main_link == BARE and state["link"] == BARE
