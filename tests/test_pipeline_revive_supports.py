"""D52 follow-up: a skeleton whose skill has no number with the supports it inherited (a weapon
variant with Close Combat on a staff) gets its supports chosen again on the rig before any tree."""

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_close_combat_on_a_staff_is_replaced_before_the_tree() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.loot_gear import LootGear
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.pipeline import BuildPipeline, BuildResult
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code

    rails = Rails.load()
    sk = skeleton_from_xml(decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "smite.pob.txt").read_text(encoding="utf-8").strip()))
    sk.main_link = ["Smite", "Close Combat", "Multistrike"]
    sk.rare_bases["Weapon 1"] = "Judgement Staff"
    sk.rare_bases.pop("Weapon 2", None)
    sk.sockets.pop("Weapon 1", None)
    sk.sockets.pop("Weapon 2", None)
    with PobSession(run_id="test_revive_supports") as pob:
        pipeline = BuildPipeline(pob, rails, objective=objective_for(rails, "Smite"))
        sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        LootGear(pob, pipeline.objective, rails).fill({"Weapon 1": "Judgement Staff"}, passes=1, n=5, seed=1)
        dead = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys)).value
        assert dead == 0 and pipeline._revivable_supports(sk)
        result = BuildResult(skeleton=sk)
        note = pipeline._revive_supports(sk, result)
        alive = pipeline.objective.score(pob.stats(pipeline.objective.stat_keys)).value
    assert alive > 0 and "Close Combat" not in sk.main_link and len(sk.main_link) == 3 and "->" in note
