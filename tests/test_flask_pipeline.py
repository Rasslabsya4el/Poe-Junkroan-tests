"""#436 unit 6: the flask step wired into the pipeline.

Plain tests (no PoB): the step runs on a full run and is skipped on `screen` and `construction_only`; `_restore_flasks`
puts back a flask a later move dropped and leaves a build that still wears its flasks alone.

`pob` tests (#575: flags are PoB's uptime verdict, nothing sets them): one short build of the Stormbrand fixture, the step
places no flask (none reaches 100 % uptime, score 898,678 -> 898,678), every flag is the derived one and the XML
round-trips `CombinedDPS` to the digit; and `_restore_flasks` brings back a dropped flask, the flag derived by the next read.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
_RUNTIME_MISSING = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


def needs_pob(test):
    return pytest.mark.pob(_RUNTIME_MISSING(test))


# -- no PoB ------------------------------------------------------------------------------------------------------------


def _count_flask_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(BuildPipeline, "_flask_step", lambda self, result, skeleton: calls.append(("flask", id(self))))
    return calls


def test_the_full_run_calls_the_step_once(monkeypatch) -> None:
    from tests.test_anoint_pipeline import _run

    calls = _count_flask_calls(monkeypatch)
    _run(monkeypatch)
    assert len(calls) == 1


def test_the_screen_skips_the_step(monkeypatch) -> None:
    from tests.test_anoint_pipeline import _run

    calls = _count_flask_calls(monkeypatch)
    _run(monkeypatch, screen=True)
    assert calls == []


def test_construction_only_skips_the_step(monkeypatch) -> None:
    from tests.test_construction_rig import _run_construction

    calls = _count_flask_calls(monkeypatch)
    result, _pob, _trees, _loots = _run_construction(monkeypatch, "classic")
    assert result.stages[-1].name == "tree rebuilt on gear"
    assert calls == []


class _FakePob:
    def __init__(self, held: dict[str, str], active: dict[str, bool]) -> None:
        self.held, self.active, self.events = dict(held), dict(active), []

    def equipped_item_raws(self) -> dict[str, str]:
        return dict(self.held)

    def flasks_active(self) -> dict[str, bool]:
        raise AssertionError("flasks_active must not be called (#575)")

    def equip(self, items: dict) -> None:
        self.events.append(("equip", dict(items)))
        self.held.update({k: v for k, v in items.items() if v})

    def set_flasks_active(self, flags: dict) -> None:
        raise AssertionError("set_flasks_active must not be called (#575)")


def _restore(pob: _FakePob, placed: dict[str, str]) -> tuple[list[str], list[str]]:
    logs: list[str] = []
    me = SimpleNamespace(pob=pob, _flasks=placed, log=logs.append)
    return BuildPipeline._restore_flasks(me), logs


def test_restore_puts_back_a_dropped_flask_and_never_touches_flags() -> None:
    placed = {"Flask 1": "raw one", "Flask 2": "raw two"}
    pob = _FakePob({"Flask 2": "raw two"}, {"Flask 1": False, "Flask 2": True})
    fixed, logs = _restore(pob, placed)
    assert fixed == ["Flask 1"]
    assert pob.events == [("equip", {"Flask 1": "raw one"})]
    assert logs and "put back" in logs[0]


def test_restore_leaves_a_build_that_wears_its_flasks_alone() -> None:
    placed = {"Flask 1": "raw one"}
    pob = _FakePob({"Flask 1": "raw one"}, {"Flask 1": True})
    fixed, logs = _restore(pob, placed)
    assert fixed == [] and pob.events == [] and logs == []


def test_restore_with_no_flasks_placed_asks_pob_nothing() -> None:
    pob = _FakePob({}, {})
    fixed, _logs = _restore(pob, {})
    assert fixed == [] and pob.events == []


class _StepPob:
    """A build with a CombinedDPS the step's placement moves; stats carry Life / EnergyShield for the pure ES read."""

    def __init__(self, life: float = 3000.0, es: float = 100.0, dps: float = 100.0) -> None:
        self.life, self.es, self.dps, self.loads = life, es, dps, []

    def stats(self, keys) -> dict:
        return {"CombinedDPS": self.dps, "Life": self.life, "EnergyShield": self.es}

    def equip(self, items: dict, **_kw) -> None:
        pass

    def export_xml(self) -> str:
        return "<build/>"

    def load_xml(self, xml: str) -> None:
        self.loads.append(xml)


def _run_step(monkeypatch, pob, *, pure_es=False, divine_placed=True, after_dps=None, slots=2):
    import junkroan.optimizer.pipeline as pipeline_mod
    from junkroan.optimizer.flask_lines import flask_bases
    from junkroan.optimizer.trace import TRACE

    TRACE.reset()
    other = next(b for b in flask_bases(100) if b.kind == "life")
    divine = pipeline_mod.flask_base("Divine Life Flask")  # the real base: PoB tags it not_for_sale, flask_bases screens it out
    seen: dict = {}

    def fake_step(probe, bases, mods_for, make, *, slots, item_level, base_level_max, fixed=None):
        seen["fixed"] = fixed
        if after_dps is not None:
            pob.dps = after_dps
        chosen = []
        for k, slot in enumerate(slots):
            base = divine if (k == 0 and divine_placed) else other
            chosen.append(SimpleNamespace(slot=slot, chosen=SimpleNamespace(base=base, raw=lambda lvl, s=slot: f"raw {s}")))
        return SimpleNamespace(slots=chosen, measured=5)

    monkeypatch.setattr(pipeline_mod, "run_flask_step", fake_step)
    monkeypatch.setattr(pipeline_mod, "flask_log_line", lambda r: f"flask: {r.slot} placed")
    records: list[tuple] = []
    rejudged: list = []
    objective = SimpleNamespace(stat_keys=["CombinedDPS"], score=lambda s: SimpleNamespace(value=s["CombinedDPS"]))
    gear = SimpleNamespace(flasks=SimpleNamespace(slots=slots, tinctures=True, flask_utility_crafting=True), item_level=68, wishlist=SimpleNamespace(base_level_max=70))
    me = SimpleNamespace(pob=pob, rails=SimpleNamespace(gear=gear), objective=objective, log=lambda _l: None, _step_start=lambda *a, **k: None,
                         _record=lambda *a: records.append(a), judging=SimpleNamespace(rejudge=lambda sk: rejudged.append(sk)))
    BuildPipeline._flask_step(me, None, SimpleNamespace(pure_es=pure_es))
    return seen, me, records, rejudged, divine, TRACE


def test_a_life_build_fixes_the_divine_in_flask_1(monkeypatch) -> None:
    seen, me, _records, _rejudged, divine, TRACE = _run_step(monkeypatch, _StepPob())
    assert seen["fixed"] == {"Flask 1": divine}
    assert sorted(me._flasks) == ["Flask 1", "Flask 2"]
    assert TRACE.considered()["flask"]["flask-life-build-without-divine"] == {"generated": 0, "evaluated": 0}


def test_a_pure_es_build_passes_no_fixed(monkeypatch) -> None:
    seen, *_ = _run_step(monkeypatch, _StepPob(life=100.0, es=5000.0), pure_es=False)
    assert seen["fixed"] is None
    seen, *_ = _run_step(monkeypatch, _StepPob(), pure_es=True)
    assert seen["fixed"] is None


def test_a_life_build_without_the_divine_counts_the_class(monkeypatch) -> None:
    *_, TRACE = _run_step(monkeypatch, _StepPob(), divine_placed=False)
    assert TRACE.considered()["flask"]["flask-life-build-without-divine"]["evaluated"] == 1


def test_a_placement_scoring_lower_is_kept_not_reverted(monkeypatch) -> None:
    pob = _StepPob(dps=100.0)
    _seen, me, records, rejudged, *_ = _run_step(monkeypatch, pob, after_dps=50.0)
    assert pob.loads == []
    assert sorted(me._flasks) == ["Flask 1", "Flask 2"] and len(rejudged) == 1
    assert "100 -> 50" in records[-1][3] and "reverted" not in records[-1][3] and "5 measured" in records[-1][3]


def test_the_probe_defence_reads_the_three_stats_in_order() -> None:
    from junkroan.optimizer.flask_probe import PobFlaskProbe

    asked: list = []

    class Pob:
        def stats(self, keys):
            asked.append(tuple(keys))
            return {"TotalEHP": 10, "PhysicalMaximumHitTaken": 20}

    probe = PobFlaskProbe(Pob(), lambda: None, item_level=68)
    assert probe.defence() == (10.0, 20.0, 0.0)
    assert asked == [("TotalEHP", "PhysicalMaximumHitTaken", "EffectiveMovementSpeedMod")]


# -- PoB ---------------------------------------------------------------------------------------------------------------


@needs_pob
def test_restore_flasks_re_equips_and_the_next_stats_read_derives_the_flag() -> None:
    """#575: `_restore_flasks` only equips; the slot's flag is PoB's uptime verdict after the next stats read."""

    xml = decode_import_code((FIXTURES.parent / "stormbrand_s4_flasks_saved_active.pob.txt").read_text(encoding="utf-8").strip())
    with PobSession(run_id="test-flask-restore", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as pob:
        pob.load_xml(xml)
        placed = {slot: raw for slot, raw in pob.equipped_item_raws().items() if slot.startswith("Flask") and raw}
        assert len(placed) == 5, sorted(placed)
        slot = "Flask 2"  # the Diamond Flask: PoB prints an uptime line for it (0 % here)
        pipeline = SimpleNamespace(pob=pob, _flasks=dict(placed), log=lambda _line: None)
        pob.equip({slot: None})
        assert not pob.equipped_item_raws().get(slot)
        assert BuildPipeline._restore_flasks(pipeline) == [slot]
        assert pob.equipped_item_raws().get(slot)
        pob.stats(["CombinedDPS"])
        uptimes = pob.flask_uptimes()
        print(f"\nrestored {slot}: uptime {uptimes[slot]}; flags {pob.flasks_active()}")
        for name, info in uptimes.items():
            assert pob.flasks_active()[name] is info["full"] is info["active"]
        assert not any(pob.flasks_active().values())  # the saved flasks sat active in the fixture; none is at 100 %


def test_the_divine_life_flask_is_found_by_name() -> None:
    """#589: `flask_base` finds the Divine Life Flask by name with its mods."""

    from junkroan.optimizer.flask_lines import flask_base, flask_bases, flask_mods

    divine = flask_base("Divine Life Flask")
    assert (divine.kind, divine.drop_level) == ("life", 60)
    assert "Divine Life Flask" in {b.name for b in flask_bases(100)}
    mods = flask_mods(divine, 70)
    assert any(m.affix == "prefix" for m in mods) and any(m.affix == "suffix" for m in mods)
