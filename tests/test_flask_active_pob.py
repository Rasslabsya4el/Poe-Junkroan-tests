"""#436 unit 2: PoB's per-slot `active` flag of Flask 1..5 (`PobSession.set_flasks_active`).

bleed_perforate carries 5 saved flasks, inactive. A flask's mods count only while its slot is active:
all inactive -> CombinedDPS a; all active -> b != a. `read_state` reports the flags, the export
writes `<Slot ... active="true"/>`, and a load_xml round trip keeps them and the numbers to the digit.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "bleed_perforate.pob.txt"
FLASKS = [f"Flask {i}" for i in range(1, 6)]


def _active_in_xml(xml_text: str) -> dict[str, bool]:
    root = ElementTree.fromstring(xml_text)
    items = root.find("Items")
    active_set = items.get("activeItemSet") or "1"
    node = next(s for s in items.findall("ItemSet") if s.get("id") == active_set)
    return {s.get("name"): s.get("active") == "true" for s in node.findall("Slot") if s.get("name") in FLASKS}


@pytest.mark.pob
@needs_pob
def test_flask_slots_active_flag_moves_the_numbers_and_survives_the_export(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-flask-active", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(FIXTURE.read_text(encoding="utf-8").strip()))
        state = pob.read_state()["items_state"]
        assert [n for n in FLASKS if state["slots"][n]["occupied"]] == FLASKS, "the fixture's 5 saved flasks"

        # the setter's own effect: `calc()` reads the flags as saved (a stats read derives them first, #575)
        pob.set_flasks_active(False)
        assert pob.flasks_active() == dict.fromkeys(FLASKS, False)
        off = pob.calc()

        pob.set_flasks_active(True)
        assert pob.flasks_active() == dict.fromkeys(FLASKS, True)
        on = pob.calc()
        msg = f"CombinedDPS {off['CombinedDPS']} -> {on['CombinedDPS']}; Life {off['Life']} -> {on['Life']}"
        print(msg)
        assert on["CombinedDPS"] != off["CombinedDPS"], msg

        # a mapping sets only the named slots
        pob.set_flasks_active({"Flask 1": False, "Flask 3": False})
        assert pob.flasks_active() == {"Flask 1": False, "Flask 2": True, "Flask 3": False, "Flask 4": True, "Flask 5": True}

        # #575: a stats read and the export derive the flag of every flask from PoB's flask uptime, whatever the setter left.
        # `flask_uptimes` lists the flasks (the fixture's Flask 3 is a tincture: the derivation leaves its flag as it was).
        pob.set_flasks_active(True)
        uptimes = pob.flask_uptimes()
        flask_slots = sorted(uptimes)
        assert flask_slots == ["Flask 1", "Flask 2", "Flask 4", "Flask 5"]
        derived = {slot: uptimes[slot]["active"] for slot in flask_slots}
        assert not any(derived.values()), "the fixture's flasks are not at 100 % uptime, so the forced-on flags are overridden"
        pob.set_flasks_active(True)
        derived_stats = pob.stats(["CombinedDPS", "Life"])
        assert {s: pob.flasks_active()[s] for s in flask_slots} == derived
        pob.set_flasks_active(True)
        xml_derived = pob.export_xml()
        assert {s: v for s, v in _active_in_xml(xml_derived).items() if s in derived} == derived
        pob.load_xml(xml_derived)
        assert {s: pob.flasks_active()[s] for s in flask_slots} == derived
        again = pob.stats(["CombinedDPS", "Life"])
        assert again["CombinedDPS"] == derived_stats["CombinedDPS"] and again["Life"] == derived_stats["Life"]
