"""#556 R4 + R5 (kind B, D113, PoB-free): a support trial either returns a score or raises; a dead PoB worker is
never a rejected trial. R4: a PoB contract error propagates out of `_try_score` at once, uncounted. R5: any other
RuntimeError is counted `support-trial:raised`, rejects its candidate for the pick, and a round in which every
attempted trial raised re-raises. The healthy path is pinned to the trial sequence main produced on 25113ac."""

from __future__ import annotations

import pytest

from junkroan.pob.headless_runtime_worker import WorkerContractError
from junkroan.optimizer.trace import TRACE
from test_issue550_repick_keeps_supports import BARE, LEGAL, _gen

KEY = "support-trial:raised"
VALUE = {"Spell Echo": 30.0, "Minion Damage": 20.0, "Added Fire Damage": 10.0, "Controlled Destruction": 5.0, "Concentrated Effect": 7.0}
HEALTHY_LINK = ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage']
HEALTHY_WRITTEN = [
    ['Raise Spectre'],
    ['Raise Spectre', 'Elemental Penetration'],
    ['Raise Spectre', 'Spell Echo'],
    ['Raise Spectre', 'Minion Damage'],
    ['Raise Spectre', 'Concentrated Effect'],
    ['Raise Spectre', 'Added Fire Damage'],
    ['Raise Spectre', 'Controlled Destruction'],
    ['Raise Spectre', 'Spell Echo', 'Elemental Penetration'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage'],
    ['Raise Spectre', 'Spell Echo', 'Concentrated Effect'],
    ['Raise Spectre', 'Spell Echo', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Controlled Destruction'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Elemental Penetration'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Concentrated Effect'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Controlled Destruction'],
    ['Raise Spectre', 'Elemental Penetration', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Concentrated Effect', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Controlled Destruction', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Elemental Penetration', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Concentrated Effect', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Controlled Destruction', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Elemental Penetration'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Concentrated Effect'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Controlled Destruction'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage'],
    ['Raise Spectre', 'Spell Echo', 'Minion Damage', 'Added Fire Damage'],
]


@pytest.fixture(autouse=True)
def _fresh_trace():
    TRACE.reset()
    yield
    TRACE.reset()


def _raised() -> int:
    return sum(v["evaluated"] for classes in TRACE.considered().values() for c, v in classes.items() if c == KEY)


def _raising_writes(exc_type, *, only: set[str] | None = None):
    """A stub whose candidate writes raise (the bare link write does not); `only` limits it to links holding one of those."""

    gen, sk, state = _gen(BARE, lambda l: 100.0 + sum(VALUE.get(g, 0.0) for g in l))
    inner = gen._set_main_link
    attempts: list[list[str]] = []

    def set_link(_sk, link, **k) -> None:
        if list(link) != BARE and (only is None or only & set(link)):
            attempts.append(list(link))
            raise (exc_type("worker_dead", "write refused") if exc_type is WorkerContractError else exc_type("write refused"))
        inner(_sk, link, **k)

    gen._set_main_link = set_link
    return gen, sk, state, attempts


def test_contract_error_propagates_at_once() -> None:
    gen, sk, _state, attempts = _raising_writes(WorkerContractError)
    with pytest.raises(WorkerContractError):
        gen.pick_supports(sk, n_supports=3)
    assert len(attempts) == 1
    assert _raised() == 0


def test_all_contract_classes_are_runtime_errors() -> None:
    from junkroan.search.generator import POB_CONTRACT_ERRORS

    assert len(POB_CONTRACT_ERRORS) == 5 and all(issubclass(c, RuntimeError) for c in POB_CONTRACT_ERRORS)


def test_a_round_of_plain_runtime_errors_reraises_and_counts_each_trial() -> None:
    gen, sk, _state, attempts = _raising_writes(RuntimeError)
    with pytest.raises(RuntimeError, match="write refused"):
        gen.pick_supports(sk, n_supports=3)
    assert len(attempts) == len(LEGAL)
    assert _raised() == len(LEGAL)


def test_three_raising_candidates_are_counted_and_rejected() -> None:
    bad = {"Elemental Penetration", "Concentrated Effect", "Controlled Destruction"}
    gen, sk, state, attempts = _raising_writes(RuntimeError, only=bad)
    link = gen.pick_supports(sk, n_supports=3)
    assert _raised() == 3
    assert len(attempts) == 3
    assert not bad & set(link) and link[0] == "Raise Spectre" and len(link) == 4
    assert not any(bad & set(w) for w in state["written"])


def test_healthy_path_sequence_is_unchanged() -> None:
    gen, sk, state = _gen(BARE, lambda l: 100.0 + sum(VALUE.get(g, 0.0) for g in l))
    link = gen.pick_supports(sk, n_supports=3)
    assert link == HEALTHY_LINK
    assert state["written"] == HEALTHY_WRITTEN
    assert _raised() == 0


def test_raising_last_greedy_iteration_keeps_the_scored_link() -> None:
    """Iterations 1-2 score; every candidate of iteration 3 (a 3-support trial) raises: the phase had successes, so the pick finishes."""

    gen, sk, state = _gen(BARE, lambda l: 100.0 + sum(VALUE.get(g, 0.0) for g in l))
    inner = gen._set_main_link
    attempts: list[list[str]] = []

    def set_link(_sk, link, **k) -> None:
        if len(link) == 4:
            attempts.append(list(link))
            raise RuntimeError("write refused")
        inner(_sk, link, **k)

    gen._set_main_link = set_link
    link = gen.pick_supports(sk, n_supports=3)
    assert link == ["Raise Spectre", "Spell Echo", "Minion Damage"]
    assert len(attempts) == 4 == _raised()
    assert not any(len(w) == 4 for w in state["written"])
