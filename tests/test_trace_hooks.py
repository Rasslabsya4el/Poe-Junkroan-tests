"""PoB-free checks that the trace counter is wired at the PoB boundary (#498)."""

from __future__ import annotations

import pytest

from junkroan.optimizer.loot_gear import LootGear
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.pob.session import PobSession


def flask(n: int) -> str:
    return f"Rarity: Magic\nSapphire Flask of Test {n}\nSapphire Flask\n"


class _Adapter:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def trial_stats(self, handle, payload):
        if self.fail:
            raise RuntimeError("pob down")
        return [{"ok": True, "stats": {"CombinedDPS": 100.0 + i}} for i, _t in enumerate(payload["trials"])]


def _session(fail: bool = False) -> PobSession:
    s = PobSession.__new__(PobSession)
    s._adapter = _Adapter(fail)
    s._handle = object()
    s.fulldps_shortcut = False
    s.mean_parts = ()
    return s


@pytest.fixture(autouse=True)
def _reset():
    TRACE.reset()
    yield
    TRACE.reset()


def test_flask_generated_three_evaluated_two_flushed_to_picks():
    pob = _session()
    cands = [{"item": {"slot": "Flask 1", "raw": flask(i)}} for i in range(3)]
    TRACE.count_candidates(cands)
    pob.trial_stats(cands[:2], ("CombinedDPS",), mode="fast")
    TRACE.flush("picks")
    assert TRACE.considered()["picks"]["flask"] == {"generated": 3, "evaluated": 2}


def test_raising_adapter_counts_nothing_evaluated():
    pob = _session(fail=True)
    with pytest.raises(RuntimeError):
        pob.trial_stats([{"item": {"slot": "Flask 1", "raw": flask(1)}}], ("CombinedDPS",), mode="fast")
    TRACE.flush("picks")
    assert TRACE.considered().get("picks", {}).get("flask", {"evaluated": 0})["evaluated"] == 0


def test_loot_gear_fill_slot_counts_generated_and_evaluated():
    pob = _session()
    rolls = [{"raw": flask(i), "mod_ids": []} for i in range(4)]
    pob.stats = lambda keys: {"CombinedDPS": 1.0}
    pob.equip = lambda items: None
    pob.random_rares = lambda base, **kw: rolls
    gear = LootGear(pob, Objective(maximize="CombinedDPS"), Rails.load())
    gear.fill_slot("Flask 1", "Sapphire Flask", n=4, bench=False)
    TRACE.flush("picks")
    cells = TRACE.considered()["picks"]
    assert cells["flask"] == {"generated": 4, "evaluated": 4}
    for cls, cell in cells.items():
        assert 0 < cell["evaluated"] <= cell["generated"], cls
