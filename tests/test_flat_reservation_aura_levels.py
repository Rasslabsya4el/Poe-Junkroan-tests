"""Flat-reservation aura levels are a PoB-scored build decision, not a gem rail."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.judging import Judging
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.pob.skill_facts import flat_reservation_aura_effect_ids
from junkroan.search.skeleton import Skeleton, SocketGroup

from conftest import needs_skill_source
from judging_fakes import _Lanes, _Reads, pob_judging

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


def test_flat_reservation_auras_are_derived_from_skill_data_not_names() -> None:
    blocks = {
        "FlatAura": 'skillTypes = { [SkillType.HasReservation] = true, [SkillType.Aura] = true, },\nlevels = { [1] = { manaReservationFlat = 22, }, }',
        "RemoteMine": 'skillTypes = { [SkillType.HasReservation] = true, [SkillType.RemoteMined] = true, },\nlevels = { [1] = { manaReservationFlat = 22, }, }',
        "PercentageAura": 'skillTypes = { [SkillType.HasReservation] = true, },\nlevels = { [1] = { manaMultiplier = 5000, }, }',
        "SupportOnly": 'levels = { [1] = { manaReservationFlat = 22, }, }',
    }

    assert flat_reservation_aura_effect_ids(blocks) == frozenset({"FlatAura"})


def test_level_search_keeps_the_last_level_before_an_objective_floor_breaks() -> None:
    class _Pob:
        def __init__(self) -> None:
            self.levels: list[int] = []

        def stats(self, keys):
            level = skeleton.aura_levels["Precision"]
            self.levels.append(level)
            return {key: 0.0 for key in keys} | {"CombinedDPS": float(level), "ManaUnreserved": float(100 - 10 * level)}

    class _Skeleton:
        aura_levels: dict[str, int]

        def __init__(self) -> None:
            self.aura_levels = {}

        def flat_reservation_auras(self) -> list[str]:
            return ["Precision"]

        def apply_skills(self, *_args, **_kwargs) -> None:
            pass

    skeleton = _Skeleton()
    pob = _Pob()
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob = pob
    pipeline.rails = SimpleNamespace(gems=SimpleNamespace(level=10, quality=0, main_quality=0))
    pipeline.judging = pob_judging(pipeline)
    pipeline.objective = Objective(maximize="CombinedDPS", floors={"ManaUnreserved": 50.0})

    assert pipeline._tune_flat_reservation_aura_levels(skeleton) == {"Precision": 5}
    assert pob.levels == [*range(1, 11)]


def test_chosen_aura_levels_round_trip_and_use_the_unified_skill_payload() -> None:
    skeleton = Skeleton(
        class_name="Duelist",
        ascendancy="Slayer",
        main_link=["Cyclone"],
        extra_groups=[SocketGroup(gems=["Precision"], slot="Helmet")],
        aura_levels={"Precision": 9},
    )

    restored = Skeleton.from_json(skeleton.to_json())
    payload = restored.skill_payload(gem_level=18, gem_quality=0, main_quality=0)

    assert restored.aura_levels == {"Precision": 9}
    assert payload["gem_levels"] == {"Precision": 9}
    assert payload["extra_groups"][0]["gems"][0]["level"] == 9


def test_level_search_forgets_an_override_when_the_aura_is_no_longer_enabled() -> None:
    class _Skeleton:
        def __init__(self) -> None:
            self.aura_levels = {"Precision": 9}

        def flat_reservation_auras(self) -> list[str]:
            return []

    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.judging = Judging(_Lanes([]), _Reads([]))  # no session: the search must not reach one
    skeleton = _Skeleton()

    assert pipeline._tune_flat_reservation_aura_levels(skeleton) == {}
    assert skeleton.aura_levels == {}


@needs_skill_source
def test_author_normalization_keeps_low_precision_but_raises_damage_gems() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from benchmark import normalize_author_gems
    from junkroan.optimizer.rails import Rails

    xml = ('<PathOfBuilding><Build level="70" className="Duelist" ascendClassName="Slayer" mainSocketGroup="1"/>'
           '<Skills activeSkillSet="1"><SkillSet id="1">'
           '<Skill slot="Body Armour" mainActiveSkill="1"><Gem nameSpec="Cyclone" level="14" quality="20"/></Skill>'
           '<Skill slot="Helmet" mainActiveSkill="1"><Gem nameSpec="Precision" level="1" quality="20"/></Skill>'
           '</SkillSet></Skills><Items activeItemSet="1"><ItemSet id="1"/></Items></PathOfBuilding>')

    normalized, report = normalize_author_gems(xml, Rails.load())
    levels = {gem.get("nameSpec"): gem.get("level") for gem in ET.fromstring(normalized).iter("Gem")}

    assert levels == {"Cyclone": "18", "Precision": "1"}
    assert report["kept_low"] == 1


@pytest.mark.pob
@needs_pob
def test_precision_reserves_its_pob_flat_mana_values_on_a_bare_duelist(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-flat-reservation-aura", artifacts_root=tmp_path) as pob:
        pob.set_identity(level=70)
        pob.set_tree(class_id="Duelist", ascendancy_id="Slayer")
        pob.set_skills(main_link=["Precision"], level=1, quality=0)
        low = pob.stats(("Mana", "ManaUnreserved"))
        pob.set_skills(main_link=["Precision"], level=18, quality=0)
        high = pob.stats(("Mana", "ManaUnreserved"))

    assert low["Mana"] - low["ManaUnreserved"] == 22
    assert high["Mana"] - high["ManaUnreserved"] == 167
