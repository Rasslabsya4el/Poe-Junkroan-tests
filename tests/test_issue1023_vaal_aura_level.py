"""#1023: a Vaal reservation aura (Vaal Clarity) counts as the aura of its plain name in `flat_reservation_auras`,
so its saved level survives the first skills write. Row 1 on PoB (the saved absolution_minions s4 build through the
replay's `_pipeline_state`), row 2 and the unit tests without PoB."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from build_from_skeleton import skeleton_from_xml  # noqa: E402
from test_skeleton_from_xml import _synthetic, _with_vitality, _written_levels  # noqa: E402

from junkroan.optimizer.rails import Rails  # noqa: E402

SAVED = ROOT / "artifacts" / "benchmark" / "20261013-0101-P2-core-3" / "absolution_minions-s4.pob.txt"
RUNTIME = ROOT / "var" / "cache" / "pob"


def _with_aura(name: str, level: int):
    xml = _synthetic([("Fireball", True), ("Added Fire Damage", True)])
    group = f'<Skill slot="Helmet" enabled="true" mainActiveSkill="1"><Gem nameSpec="{name}" level="{level}" quality="0" enabled="true"/></Skill>'
    return skeleton_from_xml(xml.replace("</Skill></SkillSet>", "</Skill>" + group + "</SkillSet>"))


def test_a_vaal_reservation_aura_is_listed_under_its_own_name_and_keeps_its_saved_level() -> None:
    skeleton = _with_aura("Vaal Clarity", 1)

    assert skeleton.flat_reservation_auras() == ["Vaal Clarity"]
    assert skeleton.aura_levels == {"Vaal Clarity": 1}
    assert _written_levels(skeleton)["Vaal Clarity"] == 1


def test_a_vaal_aura_at_the_rail_level_is_written_at_the_rail_as_before() -> None:
    rail = Rails.load().gems.level
    skeleton = _with_aura("Vaal Clarity", rail)

    assert skeleton.flat_reservation_auras() == ["Vaal Clarity"]
    assert skeleton.aura_levels == {}
    assert _written_levels(skeleton)["Vaal Clarity"] == rail


def test_row2_a_plain_aura_is_unchanged() -> None:
    skeleton = _with_vitality(1)

    assert skeleton.flat_reservation_auras() == ["Vitality"]
    assert skeleton.aura_levels == {"Vitality": 1}
    assert _written_levels(skeleton)["Vitality"] == 1


def test_a_vaal_gem_that_is_not_a_reservation_aura_is_still_not_one() -> None:
    skeleton = _with_aura("Vaal Spark", 1)

    assert skeleton.flat_reservation_auras() == []
    assert skeleton.aura_levels == {}


@pytest.mark.pob
@pytest.mark.skipif(not SAVED.is_file() or not RUNTIME.is_dir(), reason="saved build or pinned PoB runtime not present")
def test_row1_the_saved_absolution_s4_build_keeps_its_mana_after_the_replay_pipeline_state() -> None:
    import replay_bench as rb
    from junkroan.pob.session import PobSession

    info = rb.source_info(SAVED)
    logs: list[str] = []
    keys = ("ManaUnreserved", "ManaReserved", "ManaOverReserved")
    with PobSession(run_id="test-1023") as pob:
        prepared = rb._prepared_author(pob, info["slug"], info["stat"], logs.append)
        pob.load_import_code(SAVED.read_text(encoding="utf-8").strip())
        before = pob.stats(keys)
        pipeline, skeleton, _gear, _tree = rb._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
        objective = pipeline.objective
        stats = pob.stats(tuple(dict.fromkeys((*objective.stat_keys, *keys))))
        violations = objective.violations(stats)

    assert skeleton.aura_levels == {"Vaal Clarity": 1}
    assert before["ManaUnreserved"] == pytest.approx(43, abs=1)
    assert stats["ManaUnreserved"] == pytest.approx(43, abs=1), (stats["ManaUnreserved"], stats["ManaReserved"])
    assert violations == {}
