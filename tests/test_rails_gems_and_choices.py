"""Day-1 gem rails (D23) and PoB-judged list options (D24). PoB-backed."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import derive_config
from junkroan.optimizer.rails import Rails
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")]
def test_gem_rails_are_day1_not_20_20() -> None:
    rails = Rails.load()
    assert rails.gems.level <= 19 and rails.gems.quality == 0


def test_skeleton_applies_rail_gem_levels_and_pob_judges_stance(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml  # noqa: E402

    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    rails = Rails.load()
    with PobSession(run_id="test-gem-rails", artifacts_root=tmp_path) as pob:
        skeleton.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        skills = pob.read_state()["skills_state"]
        gems = [g for ss in skills.get("skill_sets", []) for grp in ss.get("socket_groups", []) for g in grp.get("gems", [])]
        assert gems and all(int(g["level"]) == rails.gems.level and int(g["quality"]) == rails.gems.quality for g in gems), gems[:3]

        derived = derive_config(pob)
        # Flesh and Stone is in the skeleton, the fresh build has no stance yet -> a choice for PoB to judge
        assert derived.choices.get("bloodSandStance") == ["BLOOD", "SAND"]
        # Cold Snap chills by itself (PoB applies it); Vortex / Creeping Frost are second cold skills -> checkbox on
        assert derived.conservative.inputs.get("conditionEnemyChilled") is True
        assert "ColdSnapBypassCD" not in derived.conservative.inputs  # an assumption, optimistic lane only
        assert derived.optimistic.inputs.get("ColdSnapBypassCD") is True


def test_pick_utilities_adds_a_movement_skill_and_only_gains(tmp_path: Path) -> None:
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.search.generator import SkeletonGenerator

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml  # noqa: E402

    xml = decode_import_code((FIXTURES / "cold_dot.pob.txt").read_text(encoding="utf-8").strip())
    skeleton = skeleton_from_xml(xml)
    skeleton.extra_groups = []  # strip the author's utilities; the generator must find its own
    rails = Rails.load()
    with PobSession(run_id="test-utilities", artifacts_root=tmp_path) as pob:
        skeleton.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        gen = SkeletonGenerator(pob, rails)
        before = pob.stats(("CombinedDPS",))["CombinedDPS"]
        added = gen.pick_utilities(skeleton, max_groups=2)
        names = [g.gems[0] for g in added]
        assert len(added) == 2
        from junkroan.search.hypothesis import active_gems
        assert any({"travel", "blink"} & set(active_gems()[n.lower()]["tag_keys"]) for n in names), names  # a movement skill is always there
        assert pob.stats(("CombinedDPS",))["CombinedDPS"] >= before
        assert skeleton.extra_groups == added
