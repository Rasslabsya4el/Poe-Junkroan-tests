"""#550 R1 + R2 (kind A, D113): a support re-pick never ends on fewer supports than the incumbent main link at a score
not above the incumbent's, and a pass in which every trial raises re-raises (#556 R5). The trace counter
`support-repick:fewer-at-equal` generated >= 1 and evaluated 0. No PoB."""

from __future__ import annotations

import pytest
from types import SimpleNamespace
from typing import Callable

from junkroan.optimizer.objective import Score
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.search.generator import SkeletonGenerator

INCUMBENT = ["Raise Spectre", "Elemental Penetration", "Spell Echo", "Minion Damage", "Concentrated Effect"]
BARE = ["Raise Spectre"]
LEGAL = ["Elemental Penetration", "Spell Echo", "Minion Damage", "Concentrated Effect", "Added Fire Damage", "Controlled Destruction"]
KEY = "support-repick:fewer-at-equal"


def _gen(main_link: list[str], value_of: Callable[[list[str]], float], *, raises_on: Callable[[list[str]], bool] = lambda _l: False):
    gen = object.__new__(SkeletonGenerator)
    gen.rails, gen.picks, gen.log, gen.castability_context = Rails.load(), [], (lambda *_a, **_k: None), None
    sk = SimpleNamespace(main_link=list(main_link), fixed_supports=[], enablers=lambda: [])
    state: dict = {"link": list(main_link), "written": []}

    def set_link(_sk, link, **_k) -> None:
        state["link"] = list(link)
        state["written"].append(list(link))

    def score() -> Score:
        if raises_on(state["link"]):
            raise RuntimeError("trial refused")
        return Score(0.0, value_of(state["link"]))

    gen.legal_supports = lambda _sk: list(LEGAL)
    gen._set_main_link = set_link
    gen._reconfigure = lambda *_a, **_k: None
    gen._restore_castability = lambda *_a, **_k: None
    gen._score = score
    return gen, sk, state


def test_equal_score_everywhere_keeps_the_incumbent() -> None:
    gen, sk, state = _gen(INCUMBENT, lambda _l: 100.0)
    link = gen.pick_supports(sk, n_supports=4)
    assert link == INCUMBENT and link != BARE
    assert sk.main_link == INCUMBENT
    assert state["link"] == INCUMBENT  # the last link written into the stub state


def test_every_trial_raising_reraises() -> None:
    def raises(link: list[str]) -> bool:
        return link not in (INCUMBENT, BARE)

    gen, sk, state = _gen(INCUMBENT, lambda l: 100.0 if l == INCUMBENT else 50.0, raises_on=raises)
    with pytest.raises(RuntimeError):
        gen.pick_supports(sk, n_supports=4)


def test_every_candidate_write_raising_reraises() -> None:
    gen, sk, state = _gen(INCUMBENT, lambda _l: 100.0)
    inner = gen._set_main_link

    def set_link(_sk, link, **k) -> None:
        if list(link) not in (INCUMBENT, BARE):
            raise RuntimeError("write refused")
        inner(_sk, link, **k)

    gen._set_main_link = set_link
    with pytest.raises(RuntimeError):
        gen.pick_supports(sk, n_supports=4)


def test_fewer_supports_at_a_strictly_better_score_is_taken() -> None:
    gen, sk, state = _gen(INCUMBENT, lambda l: 11.0 if l == BARE else (10.0 if l == INCUMBENT else 5.0))
    link = gen.pick_supports(sk, n_supports=4)
    assert link == BARE and sk.main_link == BARE and state["link"] == BARE


def test_bare_incumbent_still_gets_its_supports() -> None:
    value = {"Spell Echo": 30.0, "Minion Damage": 20.0, "Added Fire Damage": 10.0}
    gen, sk, state = _gen(BARE, lambda l: 100.0 + sum(value.get(g, 0.0) for g in l))
    link = gen.pick_supports(sk, n_supports=3)
    assert link == ["Raise Spectre", "Spell Echo", "Minion Damage", "Added Fire Damage"]
    assert sk.main_link == link


def test_trace_counter_fewer_at_equal_generated_not_evaluated() -> None:
    TRACE.reset()
    gen, sk, _state = _gen(INCUMBENT, lambda _l: 100.0)
    gen.pick_supports(sk, n_supports=4)
    merged = {c: v for classes in TRACE.considered().values() for c, v in classes.items() if c == KEY}
    assert merged[KEY]["generated"] >= 1 and merged[KEY]["evaluated"] == 0
    TRACE.reset()
