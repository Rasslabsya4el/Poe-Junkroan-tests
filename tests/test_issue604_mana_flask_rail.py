"""#604: the mana sustain rail never counts a Mana Flask whose PoB uptime is under 100 %.

The sustain inputs (ManaRegenRecovery, ManaLeechGainRate, ManaRecoup, ManaPerSecondCost) are read after the worker
derived the Flask flags (active iff "Flask uptime: 100%"), so a below-100 flask is inactive when they are read.
Trace class `mana-sustain-inactive-flask` = active Mana/Hybrid Flask with uptime < 100 in a build: must be 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from junkroan.optimizer.flask_trace import MANA_SUSTAIN_CLASS, count_generated
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.trace_output import trace_output_from_xml
from tests.test_flask_uptime_pob import FLASKS, STORMBRAND, TOXIC_RAIN, _xml, needs_pob

SUSTAIN = ["ManaRegenRecovery", "ManaLeechGainRate", "ManaRecoup", "ManaPerSecondCost"]


def _xml_flasks(flask1_text: str, active: str) -> str:
    return (
        '<PathOfBuilding><Items activeItemSet="1">'
        f'<Item id="1">{flask1_text}</Item><ItemSet id="1">'
        f'<Slot name="Flask 1" itemId="1" active="{active}"/></ItemSet></Items></PathOfBuilding>'
    )


def test_counts_only_active_mana_flask_below_100():
    mana, life = "Rarity: Magic\nLarge Mana Flask", "Rarity: Magic\nLarge Life Flask"
    below, full = {"Flask 1": {"full": False}}, {"Flask 1": {"full": True}}
    assert trace_output_from_xml(_xml_flasks(mana, "true"), flask_uptimes=below)[MANA_SUSTAIN_CLASS] == 1
    assert trace_output_from_xml(_xml_flasks(mana, "false"), flask_uptimes=below)[MANA_SUSTAIN_CLASS] == 0
    assert trace_output_from_xml(_xml_flasks(mana, "true"), flask_uptimes=full)[MANA_SUSTAIN_CLASS] == 0
    assert trace_output_from_xml(_xml_flasks(life, "true"), flask_uptimes=below)[MANA_SUSTAIN_CLASS] == 0


def test_class_written_zero_by_the_flask_step():
    TRACE.reset()
    with TRACE.move("flask"):
        count_generated([])
    assert TRACE.considered()["flask"][MANA_SUSTAIN_CLASS] == {"generated": 0, "evaluated": 0}
    TRACE.reset()


@pytest.mark.pob
@needs_pob
def test_below_100_mana_flask_is_inactive_when_the_sustain_inputs_are_read(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-issue604", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(STORMBRAND))
        assert pob.flasks_active() == dict.fromkeys(FLASKS, True), "saved all active"
        pob.stats(SUSTAIN)  # the derive runs before this read
        up = pob.flask_uptimes()
        assert pob.flasks_active() == dict.fromkeys(FLASKS, False)
        assert all(not row["active"] for row in up.values() if not row["full"])
        out = trace_output_from_xml(pob.export_xml(), flask_uptimes=up)
        assert out[MANA_SUSTAIN_CLASS] == 0


@pytest.mark.pob
@needs_pob
def test_toxic_rain_mana_flask_counts_only_at_full_uptime(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-issue604-toxic", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(TOXIC_RAIN))
        stats = pob.stats(SUSTAIN)
        up = pob.flask_uptimes()
        for row in up.values():
            assert row["active"] == (row["line"] == "Flask uptime: 100%")
        print({k: stats.get(k) for k in SUSTAIN}, {n: (r["line"], r["active"]) for n, r in up.items()})
        out = trace_output_from_xml(pob.export_xml(), flask_uptimes=up)
        assert out[MANA_SUSTAIN_CLASS] == 0
