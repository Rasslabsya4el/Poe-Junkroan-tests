"""#575 row 2: a Flask slot is `active` only when PoB's own uptime calculation prints "Flask uptime: 100%".

The worker derives the flags before every stats read, every trial and the export. Witnesses: a gate delivery
whose 5 saved-active flasks have no generation (stormbrand-s4, copied from the gate run's output) and the
toxic_rain author (Flask 5, an Eternal Mana Flask of Quelling, is at 100 %).
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
STORMBRAND = PROJECT_ROOT / "tests" / "fixtures" / "stormbrand_s4_flasks_saved_active.pob.txt"
TOXIC_RAIN = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "toxic_rain.pob.txt"
FLASKS = [f"Flask {i}" for i in range(1, 6)]
ZERO = "Flask uptime: 0% average, 0% minimum"


def _xml(path: Path) -> str:
    from junkroan.pob.session import decode_import_code

    return decode_import_code(path.read_text(encoding="utf-8").strip())


def _active_in_xml(xml_text: str) -> dict[str, bool]:
    items = ElementTree.fromstring(xml_text).find("Items")
    active_set = items.get("activeItemSet") or "1"
    node = next(s for s in items.findall("ItemSet") if s.get("id") == active_set)
    return {s.get("name"): s.get("active") == "true" for s in node.findall("Slot") if s.get("name") in FLASKS}


def _lines(pob) -> dict[str, str | None]:
    return {name: row["line"] for name, row in sorted(pob.flask_uptimes().items())}


@pytest.mark.pob
@needs_pob
def test_stormbrand_s4_saved_active_flasks_are_all_inactive_once_derived(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-flask-uptime-a", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(STORMBRAND))
        assert pob.flasks_active() == dict.fromkeys(FLASKS, True), "the delivery saved all 5 active"
        as_saved = pob.calc()["FullDPS"]  # the snapshot reads the flags as the slots hold them
        assert round(as_saved) == 1_753_896
        derived = pob.stats(["FullDPS"])["FullDPS"]
        assert round(derived) == 1_552_665
        print(f"FullDPS as saved {as_saved:,.0f} -> derived {derived:,.0f}")
        assert pob.flasks_active() == dict.fromkeys(FLASKS, False)
        up = pob.flask_uptimes()
        assert sorted(up) == FLASKS
        assert _lines(pob) == {"Flask 1": None, "Flask 2": ZERO, "Flask 3": ZERO, "Flask 4": None, "Flask 5": None}
        assert all(row["active"] is False and row["full"] is False for row in up.values())


@pytest.mark.pob
@needs_pob
def test_toxic_rain_author_has_exactly_flask_5_at_100_percent(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-flask-uptime-b", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(TOXIC_RAIN))
        stats = pob.stats(["FullDPS", "ManaRegenRecovery"])
        assert round(stats["FullDPS"]) == 608_508
        up = pob.flask_uptimes()
        assert up["Flask 5"] == {"line": "Flask uptime: 100%", "full": True, "active": True}
        assert {name: row["active"] for name, row in up.items()} == {**dict.fromkeys(FLASKS, False), "Flask 5": True}
        assert up["Flask 3"]["line"] == "Flask uptime: 63% average, 43% minimum"  # generates, but under 100 %
        assert stats["ManaRegenRecovery"] > 100, "Flask 5's effect counts while active"


@pytest.mark.pob
@needs_pob
def test_export_load_derive_round_trip_changes_nothing(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    for fixture in (STORMBRAND, TOXIC_RAIN):
        with PobSession(run_id="test-flask-uptime-c", artifacts_root=tmp_path) as pob:
            pob.load_xml(_xml(fixture))
            xml = pob.export_xml()  # no stats read before: the export derives by itself
            derived_flags = _active_in_xml(xml)
            assert derived_flags == {name: row["active"] for name, row in pob.flask_uptimes().items()}
            fulldps = pob.stats(["FullDPS"])["FullDPS"]
            lines = _lines(pob)
            pob.load_xml(xml)
            assert pob.flasks_active() == derived_flags
            assert pob.stats(["FullDPS"])["FullDPS"] == fulldps
            assert _lines(pob) == lines
            assert _active_in_xml(pob.export_xml()) == derived_flags


@pytest.mark.pob
@needs_pob
@pytest.mark.parametrize("mode", ["fast", "full"])
def test_a_trial_that_removes_the_charge_source_loses_the_flask_and_keeps_nothing(tmp_path: Path, mode: str) -> None:
    from junkroan.pob.session import PobSession

    # Nature's Adrenaline (node 51101, "Flasks gain 3 Charges every 3 seconds") is what takes Flask 5 to 100 %
    with PobSession(run_id="test-flask-uptime-d", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(TOXIC_RAIN))
        keys = ["ManaRegenRecovery"]
        base = pob.stats(keys)["ManaRegenRecovery"]
        kept, removed = pob.trial_stats([{}, {"remove": [51101]}], keys, mode=mode)
        assert kept["stats"]["ManaRegenRecovery"] == base
        assert removed["stats"]["ManaRegenRecovery"] < 0.2 * base, f"{mode}: the flask is out of the trial's calc"
        assert pob.flask_uptimes()["Flask 5"]["active"] is True, "the trial left the live flag alone"
        assert pob.stats(keys)["ManaRegenRecovery"] == base
        # the same removal done for real gives the same number
        pob.remove_nodes([51101])
        assert pob.stats(keys)["ManaRegenRecovery"] == removed["stats"]["ManaRegenRecovery"]
        assert pob.flask_uptimes()["Flask 5"]["active"] is False


@pytest.mark.pob
@needs_pob
def test_a_cached_read_state_before_a_stats_read_does_not_go_stale_on_a_derived_flip(tmp_path: Path) -> None:
    """Review of #575: the stats read derives (writes) the flags, so the state cached before it must be dropped."""

    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-flask-uptime-d", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(STORMBRAND))
        before = pob.read_state()["items_state"]["flasks_active"]  # cached, as saved
        assert before == dict.fromkeys(FLASKS, True)
        epoch = pob.build_epoch
        pob.stats(["FullDPS"])  # derives: all five flip off
        state = pob.read_state()
        assert state["items_state"]["flasks_active"] == dict.fromkeys(FLASKS, False)
        assert pob.build_epoch == epoch, "a derived flag is no new build"
        assert pob.stats(["FullDPS"]) and pob.read_state() == state  # nothing changed: the cached one is returned


@pytest.mark.pob
@needs_pob
def test_active_skill_stats_derives_and_agrees_with_stats_on_the_main_skill(tmp_path: Path) -> None:
    from junkroan.optimizer.castability import _skill_entries
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-flask-uptime-e", artifacts_root=tmp_path) as pob:
        pob.load_xml(_xml(STORMBRAND))
        pob.read_state()
        keys = ("FullDPS", "CombinedDPS")
        ids = [entry[2] for entry in _skill_entries(pob)]
        assert ids
        rows = pob.active_skill_stats(ids, keys)  # first thing after the load: derives for each skill itself
        derived = pob.stats(list(keys))
        assert pob.read_state()["items_state"]["flasks_active"] == dict.fromkeys(FLASKS, False)
        assert any(row.get("CombinedDPS") == derived["CombinedDPS"] and row.get("FullDPS") == derived["FullDPS"] for row in rows.values()), (rows, derived)
        assert round(derived["FullDPS"]) == 1_552_665
