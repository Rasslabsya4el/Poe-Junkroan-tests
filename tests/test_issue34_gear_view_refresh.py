"""#34 unit 1: the gear filler's objective follows every refresh (self-cost, castability, ramp),
so it ranks rolls under the same contexts the loop judges with. PoB-free, on `_judging`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from judging_fakes import _judging

from junkroan.optimizer.judging import CASTABILITY, RAMP, SELF_COST, VIEWS


@pytest.fixture
def tagged(monkeypatch):
    def tag(name):
        return lambda objective: objective.replace(maximize=f"{objective.maximize}+{name}")

    monkeypatch.setattr("junkroan.optimizer.ramp.with_ramp", lambda objective, **_c: tag("ramp")(objective))
    monkeypatch.setattr("junkroan.optimizer.self_cost.with_self_cost", lambda objective, _ctx: tag("self_cost")(objective))
    monkeypatch.setattr("junkroan.optimizer.castability.with_castability_floors",
                        lambda _pob, objective, *, context: tag("castability")(objective))


def test_gear_view_carries_the_main_objectives_contexts_after_rejudge(tagged) -> None:
    judging, _trees, gear = _judging([], counts_changed=True)
    judging.rejudge(SimpleNamespace())
    assert judging.objective.maximize == "dps+self_cost+castability+ramp"
    assert gear.objective.maximize == judging.objective.maximize


def test_gear_view_follows_the_self_cost_refresh_alone(tagged) -> None:
    judging, _trees, gear = _judging([])
    judging.refresh_self_cost()
    assert gear.objective.maximize == "dps+self_cost" == judging.objective.maximize


def test_gear_view_follows_all_three_and_keeps_its_holders_off() -> None:
    assert VIEWS["gear"].follows == frozenset({SELF_COST, CASTABILITY, RAMP})
    assert not VIEWS["gear"].receives_holders


def test_tree_restore_puts_the_gear_view_back_with_the_main_objective(tagged) -> None:
    from junkroan.optimizer.judging import TREE

    judging, _trees, gear = _judging([])
    at_mark = gear.objective
    mark = judging.mark(TREE)
    judging.rejudge(SimpleNamespace())
    assert gear.objective is not at_mark
    judging.restore(mark)
    assert gear.objective is at_mark and judging.objective.maximize == "dps"
