"""Minion instances at PoB's limit and the minion-skill choice (D49); Snipe stages rule."""

from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import _numeric_rule
from junkroan.pob.skill_facts import minion_limit_stat

from conftest import needs_skill_source

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@needs_skill_source
def test_minion_limit_stats_come_from_pob_skill_data() -> None:
    assert minion_limit_stat("RaiseZombie") == "ActiveZombieLimit"
    assert minion_limit_stat("Absolution") == "ActiveSentinelOfAbsolutionLimit"
    assert minion_limit_stat("SummonRagingSpirit") == "ActiveRagingSpiritLimit"
    assert minion_limit_stat("Fireball") is None and minion_limit_stat("NoSuchSkill") is None


def test_snipe_stages_are_a_rails_assumption_when_snipe_is_linked() -> None:
    assert _numeric_rule("configSnipeStages", {}, "", ["Puncture", "Snipe"], {"snipe_stages": 6}) == (6, "Snipe linked: channelled to full stages before release (rails)")
    assert _numeric_rule("configSnipeStages", {}, "", ["Puncture"], {})[0] is None


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_counts_and_minion_skill_choice_raise_full_dps_on_absolution() -> None:
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code

    rails = Rails.load()
    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "absolution_minions.pob.txt").read_text(encoding="utf-8").strip())
    sk = skeleton_from_xml(xml)
    obj = objective_for(rails, sk.main_link[0])
    assert obj.maximize == "FullDPS"
    with PobSession(run_id="test_minion_counts") as pob:
        sk.apply(pob, gem_level=18)
        bare = pob.stats(("FullDPS",))["FullDPS"]
        counts = sk.refresh_minion_counts(pob, gem_level=18)
        counted = pob.stats(("FullDPS",))["FullDPS"]
        chosen = sk.tune_minion_skills(pob, lambda: obj.score(pob.stats(obj.stat_keys)), gem_level=18)
        tuned = pob.stats(("FullDPS",))["FullDPS"]
    assert counts["Absolution"] == 3 and counts["Raise Zombie"] >= 3
    assert counted > 2 * bare and tuned > counted and chosen["Absolution"] == 2


@pytest.mark.skipif(not (PROJECT_ROOT / "var" / "cache" / "pob").is_dir(), reason="PoB runtime not present")
@pytest.mark.pob
def test_generator_setters_keep_minion_counts_and_skill_choice() -> None:
    """The generator's raw setter (support trials, the re-judge) must write the skeleton's minion
    counts and minion-skill choice: it wrote count 1 and Summon Raging Spirits fell to 8% of the
    author (runs D and E), and `refresh_minion_counts` saw nothing to re-apply."""

    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.objective_select import objective_for
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code
    from junkroan.search.generator import SkeletonGenerator

    rails = Rails.load()
    xml = decode_import_code((PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "absolution_minions.pob.txt").read_text(encoding="utf-8").strip())
    sk = skeleton_from_xml(xml)
    obj = objective_for(rails, sk.main_link[0])
    with PobSession(run_id="test_minion_setters") as pob:
        sk.apply(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        sk.refresh_minion_counts(pob, gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        sk.tune_minion_skills(pob, lambda: obj.score(pob.stats(obj.stat_keys)), gem_level=rails.gems.level, gem_quality=rails.gems.quality, main_quality=rails.gems.main_quality)
        tuned = pob.stats(("FullDPS",))["FullDPS"]
        gen = SkeletonGenerator(pob, rails, objective=obj)
        gen._set_main_link_raw(sk, sk.main_link)
        after_raw = pob.stats(("FullDPS",))["FullDPS"]
        gen._set_main_link(sk, sk.main_link)
        after_full = pob.stats(("FullDPS",))["FullDPS"]
    assert tuned > 0 and abs(after_raw - tuned) < 1e-6 * tuned and abs(after_full - tuned) < 1e-6 * tuned


def test_totem_skills_maximize_full_dps_like_minions() -> None:
    from junkroan.optimizer.objective_select import counts_instances, is_minion_skill, objective_for
    from junkroan.optimizer.rails import Rails

    rails = Rails.load()
    assert counts_instances("Shrapnel Ballista") and not is_minion_skill("Shrapnel Ballista")
    assert objective_for(rails, "Shrapnel Ballista").maximize == "FullDPS"
    assert objective_for(rails, "Summon Raging Spirit").maximize == "FullDPS"
    assert objective_for(rails, "Spark").maximize == "CombinedDPS"
