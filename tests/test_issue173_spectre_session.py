"""#173 unit 2: the harness writes the build's spectre list and the Raise Spectre gem's `skillMinion`.

PoB computes a spectre only while `build.spectreList` holds its id and the gem's `skillMinion` names it
(CalcActiveSkill.lua:661-666, :685-691). `PobSession.set_skills(spectres=[...], main_skill_minion={...})`
writes both; a call without them sends the payload it always sent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.pob import headless_runtime_worker as worker  # noqa: E402
from junkroan.pob.session import PobSession, decode_import_code  # noqa: E402

LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}"
)

PYROMANIAC = "Metadata/Monsters/LeagueCrucible/Cold/Pyromaniac"
SECOND = "Metadata/Monsters/BloodChieftain/MonkeyChiefBloodEnrage"  # the fixture's own second spectre


def _session_capturing() -> tuple[PobSession, dict]:
    captured: dict = {}
    pob = PobSession.__new__(PobSession)
    pob._fulldps_last_ratio = None
    pob._handle = object()
    pob._adapter = SimpleNamespace(apply_skill_state=lambda _handle, payload: captured.update(payload=payload))
    return pob, captured


def test_a_payload_without_the_new_fields_is_unchanged() -> None:
    pob, captured = _session_capturing()
    pob.set_skills(main_link=["Cyclone", "Melee Physical Damage"], main_counts={"Cyclone": 2}, main_minion_skills={"Cyclone": 3})
    assert captured["payload"] == {
        "active_skill_set_id": "skills.main",
        "main_socket_group_id": "skills.main.socket_group.1",
        "keep_main_active_skill": True,  # #1022
        "skill_sets": [
            {
                "skill_set_id": "skills.main",
                "title": "Main",
                "socket_groups": [
                    {
                        "label": "Main",
                        "slot": "Body Armour",
                        "enabled": True,
                        "include_in_full_dps": True,
                        "group_count": 1,
                        "main_active_skill_index": 1,
                        "gems": [
                            {"gem_name": "Cyclone", "level": 20, "quality": 20, "enabled": True, "count": 2, "skill_minion_skill_index": 3},
                            {"gem_name": "Melee Physical Damage", "level": 20, "quality": 20, "enabled": True, "count": 1},
                        ],
                    }
                ],
            }
        ],
    }
    assert "spectre_list" not in captured["payload"]


def test_the_new_fields_reach_the_payload() -> None:
    pob, captured = _session_capturing()
    pob.set_skills(main_link=["Raise Spectre"], main_skill_minion={"Raise Spectre": PYROMANIAC}, spectres=[PYROMANIAC, SECOND])
    payload = captured["payload"]
    assert payload["spectre_list"] == [PYROMANIAC, SECOND]
    assert payload["skill_sets"][0]["socket_groups"][0]["gems"][0]["skill_minion"] == PYROMANIAC
    pob.set_skills(main_link=["Raise Spectre"], spectres=[])
    assert captured["payload"]["spectre_list"] == []  # an empty list is a write, not "unused"


def test_the_worker_normalizer_keeps_the_field_only_when_given() -> None:
    runtime = object.__new__(worker.HeadlessLuaRuntime)
    base = {
        "active_skill_set_id": "skills.main",
        "main_socket_group_id": "skills.main.socket_group.1",
        "skill_sets": [{"skill_set_id": "skills.main", "socket_groups": [{"gems": [{"gem_name": "Raise Spectre", "skill_minion": PYROMANIAC}]}]}],
    }
    without = runtime._normalize_skill_payload(dict(base))
    assert "spectre_list" not in without
    with_list = runtime._normalize_skill_payload({**base, "spectre_list": [PYROMANIAC]})
    assert with_list["spectre_list"] == [PYROMANIAC]
    assert {k: v for k, v in with_list.items() if k != "spectre_list"} == without
    with pytest.raises(worker.WorkerContractError):
        runtime._normalize_skill_payload({**base, "spectre_list": [""]})


def _fixture_xml() -> str:
    from benchmark import fixture_path

    return decode_import_code(fixture_path("z327_necromancer_raise_spectre").read_text(encoding="utf-8").strip())


def _spectre_numbers(pob: PobSession) -> tuple[float, float]:
    stats = pob.stats(["TotalDPS", "FullDPS", "Minion.TotalDPS"])
    # the main skill is Raise Spectre: its DPS is the minion's (PobSession._FULLDPS_BASES reads both)
    return float(stats.get("Minion.TotalDPS") or stats.get("TotalDPS") or 0.0), float(stats.get("FullDPS") or 0.0)


def _write_spectre(pob: PobSession, spectre_id: str) -> None:
    pob.set_skills(
        main_link=["Raise Spectre"],
        slot="Body Armour",
        main_skill_minion={"Raise Spectre": spectre_id},
        main_minion_skills={"Raise Spectre": 1},
        spectres=[spectre_id],
    )


@pytest.mark.pob
@needs_pob
def test_the_spectre_list_and_skill_minion_reach_the_exported_xml_and_the_calc(tmp_path: Path) -> None:
    with PobSession(run_id="test-173-spectre-session", artifacts_root=tmp_path) as pob:
        pob.load_xml(_fixture_xml())

        # the list empty: PoB has no spectre to compute, the gem names an id the list does not hold
        pob.set_skills(main_link=["Raise Spectre"], main_skill_minion={"Raise Spectre": PYROMANIAC}, main_minion_skills={"Raise Spectre": 1}, spectres=[])
        assert ET.fromstring(pob.export_xml()).find("Build").findall("Spectre") == []

        _write_spectre(pob, PYROMANIAC)
        first = _spectre_numbers(pob)
        build = ET.fromstring(pob.export_xml())
        assert [s.get("id") for s in build.find("Build").findall("Spectre")] == [PYROMANIAC]
        gems = [g for g in build.iter("Gem") if g.get("nameSpec") == "Raise Spectre"]
        assert gems and all(g.get("skillMinion") == PYROMANIAC for g in gems)
        assert first[0] > 0 and first[1] > 0, first

        _write_spectre(pob, SECOND)
        second = _spectre_numbers(pob)
        assert [s.get("id") for s in ET.fromstring(pob.export_xml()).find("Build").findall("Spectre")] == [SECOND]
        assert second[0] > 0 and second[1] > 0, second
        assert second[0] != first[0]

        # the round trip: export, load again, the list survives and the numbers read the same
        pob.load_xml(pob.export_xml())
        assert [s.get("id") for s in ET.fromstring(pob.export_xml()).find("Build").findall("Spectre")] == [SECOND]
        assert _spectre_numbers(pob) == second

        # an id PoB does not know is an error, never a silent drop
        with pytest.raises(Exception, match="unknown spectre id"):
            pob.set_skills(main_link=["Raise Spectre"], spectres=["Metadata/Monsters/Nonsense"])
    print(f"\nPYROMANIAC TotalDPS={first[0]:,.0f} FullDPS={first[1]:,.0f}; {SECOND} TotalDPS={second[0]:,.0f} FullDPS={second[1]:,.0f}")
