"""#1162: the day-1 loadout crafts no utility flask; only Flask 1 (the Life flask) is crafted.

The rail is `gear.flasks.flask_utility_crafting` in rails_default.json (false on day 1). With it off the flask step
makes no craft trial outside Flask 1, and the trace class `utility-flask-craft` (counted at the PoB boundary by
TracingFlaskProbe, and read from the output build by trace_output) is 0. The audit `flask-slot-empty` does not flag
Flask 2-5 while the rail is off. PoB-free: the probe is `tests.test_flask_step.FakeProbe`.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import junkroan.optimizer.pipeline as pipeline_mod
from junkroan.optimizer.audit import audit_flask_slots
from junkroan.optimizer.flask_trace import UTILITY_CRAFT_CLASS
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_output import trace_output_from_xml
from tests.test_flask_step import FakeProbe


def _value(cand) -> float:
    return 0.5 if cand.base.kind == "utility" else 1.0


class _Recording(FakeProbe):
    """FakeProbe that records every slot a craft trial touches and every PoB call the step makes."""

    def __init__(self, value) -> None:
        super().__init__(value)
        self.touched: set[str] = set()
        self.pob_calls = 0

    def score(self):
        self.pob_calls += 1
        return super().score()

    def defence(self):
        self.pob_calls += 1
        return super().defence()

    def put_flask(self, slot, c):
        self.touched.add(slot)
        self.pob_calls += 1
        return super().put_flask(slot, c)

    def clear_flask(self, slot):
        self.touched.add(slot)
        self.pob_calls += 1
        return super().clear_flask(slot)

    def measure_active(self, slot, c):
        self.touched.add(slot)
        self.pob_calls += 1
        return super().measure_active(slot, c)


DAY1 = Rails.load().gear.flasks  # the shipped day-1 rails: flask_utility_crafting false
CONTROL = dataclasses.replace(DAY1, flask_utility_crafting=True)


def _run(monkeypatch, flasks):
    TRACE.reset()
    holder: dict = {}

    def factory(pob, objective, *, item_level):
        holder["probe"] = _Recording(_value)
        return holder["probe"]

    monkeypatch.setattr(pipeline_mod, "PobFlaskProbe", factory)
    pob = SimpleNamespace(
        stats=lambda keys: {"CombinedDPS": 100.0, "Life": 3000.0, "EnergyShield": 100.0},
        equip=lambda items, **_kw: None,
    )
    objective = SimpleNamespace(stat_keys=["CombinedDPS"], score=lambda s: SimpleNamespace(value=s["CombinedDPS"]))
    gear = SimpleNamespace(flasks=flasks, item_level=68, wishlist=SimpleNamespace(base_level_max=70))
    me = SimpleNamespace(
        pob=pob, rails=SimpleNamespace(gear=gear), objective=objective, log=lambda _l: None,
        _step_start=lambda *a, **k: None, _record=lambda *a: None,
        judging=SimpleNamespace(rejudge=lambda sk: None),
    )
    BuildPipeline._flask_step(me, None, SimpleNamespace(pure_es=False))
    return me, holder["probe"], TRACE.considered().get("flask", {})


def test_day1_makes_no_craft_trial_outside_flask_1(monkeypatch):
    _me, probe, _ = _run(monkeypatch, DAY1)
    assert probe.touched == {"Flask 1"}
    assert all(c.base.kind != "utility" for c in probe.put)


def test_day1_flask_1_is_the_crafted_life_flask(monkeypatch):
    me, probe, _ = _run(monkeypatch, DAY1)
    assert set(me._flasks) == {"Flask 1"}
    assert "Divine Life Flask" in me._flasks["Flask 1"]
    assert any(c.base.kind == "life" for c in probe.put)


def test_day1_utility_craft_counter_is_zero(monkeypatch):
    _me, _probe, considered = _run(monkeypatch, DAY1)
    assert considered[UTILITY_CRAFT_CLASS] == {"generated": 0, "evaluated": 0}


def test_day1_spends_fewer_pob_calls_than_utility_on(monkeypatch):
    _, day1, _ = _run(monkeypatch, DAY1)
    _, control, _ = _run(monkeypatch, CONTROL)
    assert control.pob_calls > 0
    assert day1.pob_calls < control.pob_calls


def test_control_with_utility_crafting_on_the_counter_moves(monkeypatch):
    _me, probe, considered = _run(monkeypatch, CONTROL)
    assert any(c.base.kind == "utility" for c in probe.put)
    assert considered[UTILITY_CRAFT_CLASS]["evaluated"] > 0
    assert considered[UTILITY_CRAFT_CLASS]["generated"] > 0


def _output_xml(flasks):
    """flasks: (slot, raw, active) triples; item ids follow their order."""

    items = "".join(f'<Item id="{n}">{raw}</Item>' for n, (_slot, raw, _a) in enumerate(flasks, 1))
    slots = "".join(f'<Slot name="{slot}" itemId="{n}" active="{active}"/>' for n, (slot, _raw, active) in enumerate(flasks, 1))
    return f'<PathOfBuilding><Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>'


def test_output_counts_the_active_utility_flask():
    xml = _output_xml([
        ("Flask 1", "Rarity: MAGIC\nDivine Life Flask", "true"),
        ("Flask 2", "Rarity: MAGIC\nRuby Flask", "true"),
        ("Flask 3", "Rarity: MAGIC\nRuby Flask", "false"),
    ])
    assert trace_output_from_xml(xml)[UTILITY_CRAFT_CLASS] == 1


def test_output_is_zero_with_no_active_utility_flask():
    xml = _output_xml([("Flask 1", "Rarity: MAGIC\nDivine Life Flask", "true")])
    assert trace_output_from_xml(xml)[UTILITY_CRAFT_CLASS] == 0


def _flask_xml(filled: set[int]) -> str:
    items = "".join(f'<Item id="{n}">Rarity: MAGIC\nRuby Flask\n</Item>' for n in sorted(filled))
    slots = "".join(f'<Slot name="Flask {n}" itemId="{n}"/>' for n in sorted(filled))
    return f'<PathOfBuilding><Items activeItemSet="1">{items}<ItemSet id="1">{slots}</ItemSet></Items></PathOfBuilding>'


def _rails(utility: bool) -> Rails:
    base = Rails.load()
    return dataclasses.replace(base, gear=dataclasses.replace(base.gear, flasks=dataclasses.replace(base.gear.flasks, flask_utility_crafting=utility)))


def test_rail_off_empty_flask_2_to_5_is_not_flagged():
    assert audit_flask_slots(_flask_xml({1}), _rails(False)) == []


def test_rail_off_empty_flask_1_is_still_flagged():
    found = audit_flask_slots(_flask_xml(set()), _rails(False))
    assert [f.detail.split(" is empty")[0] for f in found] == ["Flask 1"]


def test_rail_on_empty_flask_2_to_5_is_flagged():
    assert len(audit_flask_slots(_flask_xml({1}), _rails(True))) == 4
