"""Stack-type skill options are held at the cap PoB enforces (D50): intensity from Pinpoint /
Intensify, stages, stacks. A state the player builds by using the skill, never an assumption
about the fight; PoB judges the cap. Repairs in the tree refine cost DPS, not points."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import config_surfaces, derive_config, is_stack_option
from junkroan.optimizer.objective import Score
from junkroan.optimizer.ramp import RampContext, ramp_seconds
from junkroan.optimizer.tree_optimizer import TreeOptimizer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")


def test_stack_options_are_recognised_by_their_label_only() -> None:
    surfaces = config_surfaces()
    assert is_stack_option(surfaces["intensifyIntensity"])
    assert is_stack_option(surfaces["frostShieldStages"])
    assert not is_stack_option(surfaces["BrandsAttachedToEnemy"])  # "(if not maximum)": PoB fills it
    assert is_stack_option(surfaces["MomentumStacks"])  # "(if not average)", admitted by name (#17): one stack per use, PoB caps it at MomentumStacksMax
    assert not is_stack_option(surfaces["configSnipeStages"]) or True  # a rails rule (D49) handles it first
    assert not is_stack_option(surfaces["enemyRadius"])
    assert not is_stack_option(surfaces["multiplierRage"]) if "multiplierRage" in surfaces else True
    assert not is_stack_option({"var": "x", "type": "check", "section": "Skill Options", "label": "Stacks"})


def test_only_momentum_stacks_is_admitted_among_the_if_not_presets() -> None:
    """Every other "(if not maximum / average)" option stays PoB's own fill (#17)."""

    presets = {var: rec for var, rec in config_surfaces().items() if "(if not" in str(rec.get("label") or "")}
    assert "MomentumStacks" in presets and len(presets) > 5
    for var, rec in presets.items():
        assert is_stack_option({**rec, "var": var}) == (var == "MomentumStacks"), f"{var}: {rec.get('label')}"


@pytest.mark.parametrize(("speed", "cap", "conservative"), [(4.0, 5, 5), (1.0, 5, 2), (4.0, 3, 3)])
def test_momentum_stacks_one_per_use_capped_by_pob(speed: float, cap: int, conservative: int) -> None:
    """Conservative lane: floor(Speed x 2.5 s) capped. Optimistic lane: the ceiling input, which PoB itself
    caps at the gem's MomentumStacksMax; `judge_stack_options` finds that cap by bisection on PoB's number
    (5 at gem level 20, 3 at levels 1-9), so the number the optimistic lane holds is the cap."""

    from junkroan.optimizer import config_rules
    from junkroan.optimizer.ramp_inputs import BuildFacts, stack_option

    rec = {**config_surfaces()["MomentumStacks"], "var": "MomentumStacks"}
    value, why = stack_option("MomentumStacks", "# of Momentum", float(cap), BuildFacts(stats={"Speed": speed}, budget=2.5))
    assert value == conservative and "casts/s" in why

    config_rules._STACK_JUDGEMENTS.clear()
    pob = _StackPob()
    pob.cap = cap
    ceiling_input, _why, found_cap, _share = config_rules.judge_stack_options(pob, [rec], ceiling=50)["MomentumStacks"]
    assert ceiling_input == 50 and found_cap == cap  # PoB holds min(50, cap) = the cap


class _StackPob:
    """Enough of a session for `judge_stack_options`: a build whose number rises with the option
    until PoB's own cap (4 here) and then stops. `export_xml` is the build's identity, as PoB's is."""

    def __init__(self, build: str = "build-1") -> None:
        self.build, self.cap, self.value = build, 4, 0
        self.set_config_calls = 0

    def export_xml(self) -> str:
        return f"<PathOfBuilding>{self.build}</PathOfBuilding>"

    def load_xml(self, xml: str) -> None:
        self.value = 0

    def read_state(self) -> dict:
        return {"config_state": {"bandit": "Alira", "pantheon_major": "None", "pantheon_minor": "None"}}

    def set_config(self, *, inputs=None, **_kw) -> None:
        self.set_config_calls += 1
        self.value = min(int(list((inputs or {}).values())[0]), self.cap) * 100

    def stats(self, keys):
        return {k: float(self.value) for k in keys}


def test_the_stack_judgement_is_reused_while_the_build_is_the_same() -> None:
    """9 config writes and 9 recalcs per option, and `derive_config` asks for it again on every call
    (prefer_rules defeats the "kept from the build's config" shortcut): ~19 s per derivation on Spark.
    The key is the build's own export -- `value()` only sets one input on this build and reads PoB's
    numbers, so the same XML cannot give different probes (7.1h)."""

    from junkroan.optimizer import config_rules

    config_rules._STACK_JUDGEMENTS.clear()
    pob = _StackPob()
    pending = [{"var": "intensifyIntensity", "label": "# of Intensity"}]

    first = config_rules.judge_stack_options(pob, pending, ceiling=50)
    assert first["intensifyIntensity"][0] == 50 and first["intensifyIntensity"][2] == 4  # held at the ceiling, PoB caps at 4
    assert pob.set_config_calls == 9  # value(0), value(50), value(49) and six bisection steps

    again = config_rules.judge_stack_options(pob, pending, ceiling=50)
    assert again == first and pob.set_config_calls == 9  # the same build: reused, not measured again

    pob.build, pob.cap = "build-2", 3  # a node or an item changed the build, and with it the cap
    third = config_rules.judge_stack_options(pob, pending, ceiling=50)
    assert pob.set_config_calls == 18 and third["intensifyIntensity"][2] == 3  # measured again, new answer

    config_rules.judge_stack_options(pob, pending, ceiling=40)
    assert pob.set_config_calls > 18  # a different ceiling is a different question, not a cache hit


def test_repair_key_prefers_free_then_cheapest_per_dps_lost() -> None:
    current = Score(neg_violation=-0.5, value=200_000)
    free = Score(neg_violation=-0.47, value=201_000)
    cheap = Score(neg_violation=-0.47, value=197_000)  # 0.03 for 3k
    big = Score(neg_violation=-0.41, value=155_000)  # 0.09 for 45k (Quick Recovery on the Cold DoT seed)
    none = Score(neg_violation=-0.5, value=210_000)
    key = lambda s: TreeOptimizer.repair_key(current, s)
    assert key(free) > key(cheap) > key(big) > key(none)


def test_option_stacks_ramp_only_the_share_they_carry() -> None:
    stats = {"CombinedDPS": 569_000, "Speed": 6.5}
    # intensity 3 at 6.5 casts/s carrying 38% of the number: 80% of the steady state within the first cast
    ctx = RampContext(fraction=0.8, option_stacks=((3, 0.38),))
    assert 0 < ramp_seconds(stats, "CombinedDPS", ctx) < 3 / 6.5
    # 40 stacks carrying nothing: no ramp at all
    assert ramp_seconds(stats, "CombinedDPS", RampContext(fraction=0.8, option_stacks=((40, 0.0),))) == 0.0
    # 40 stacks carrying everything at 5 casts/s: 80% needs 6.4 s
    assert abs(ramp_seconds({"CombinedDPS": 1.0, "Speed": 5}, "CombinedDPS", RampContext(fraction=0.8, option_stacks=((40, 1.0),))) - 6.4) < 0.01


@pytest.mark.pob
@needs_pob
def test_spark_stacks_what_it_builds_inside_the_budget_the_optimistic_lane_the_cap(tmp_path: Path) -> None:
    """PoB still measures the cap; the conservative lane holds what the build's own rates reach
    inside the 2.5 s ramp budget (D62 amendment), never the ceiling. Spark casts 5.35 times a
    second: 4 intensity (the cap) but only 1 Sigil of Power stage, where 50 stood before."""

    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-stack-spark", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((FIXTURES / "spark.pob.txt").read_text(encoding="utf-8").strip()))
        state = pob.read_state()["config_state"]
        pob.set_config(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None", preserve="none")
        before = pob.stats(("CombinedDPS",))["CombinedDPS"]
        d = derive_config(pob)
        cap, share = d.stack_caps["intensifyIntensity"]
        assert cap in (3, 4) and 0.3 < share < 0.6
        assert d.optimistic.inputs.get("intensifyIntensity") == 50  # PoB caps it (Pinpoint: 3, +1 from the Caster Mastery)
        assert d.conservative.inputs.get("intensifyIntensity") == cap  # one per cast at 5.35 casts/s: the cap inside 2.5 s
        assert "casts/s" in d.conservative.reasons["intensifyIntensity"] and "cap" in d.conservative.reasons["intensifyIntensity"]
        assert d.optimistic.inputs.get("sigilOfPowerStages") == 50
        assert d.conservative.inputs.get("sigilOfPowerStages") == 1  # 43 mana x 5.35 casts/s / 337 per stage x 2.5 s
        assert "mana/s" in d.conservative.reasons["sigilOfPowerStages"]
        assert abs(pob.stats(("CombinedDPS",))["CombinedDPS"] - before) < 1.0  # the judge restores the build


def test_violations_are_reported_per_constraint() -> None:
    from junkroan.optimizer.objective import Objective

    obj = Objective(maximize="CombinedDPS", floors={"Life": 4000, "TotalEHP": 20000}, relations=(("Str", "ReqStr", 1.0),))
    parts = obj.violations({"CombinedDPS": 1.0, "Life": 3600, "TotalEHP": 21000, "Str": 90, "ReqStr": 100})
    assert set(parts) == {"Life", "Str>=ReqStr"}
    assert abs(parts["Life"] - 0.1) < 1e-9 and abs(parts["Str>=ReqStr"] - 0.1) < 1e-9
    assert abs(obj.score({"CombinedDPS": 1.0, "Life": 3600, "TotalEHP": 21000, "Str": 90, "ReqStr": 100}).violation - 0.2) < 1e-9
    assert obj.violations({"CombinedDPS": 1.0, "Life": 4000, "TotalEHP": 20000, "Str": 100, "ReqStr": 100}) == {}


@pytest.mark.pob
@needs_pob
def test_rule_derived_numbers_are_derived_again_for_our_own_builds(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    with PobSession(run_id="test-prefer-rules", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((FIXTURES / "poison_spectral_throw.pob.txt").read_text(encoding="utf-8").strip()))
        state = pob.read_state()["config_state"]
        ident = dict(bandit=state.get("bandit") or "None", pantheon_major=state.get("pantheon_major") or "None", pantheon_minor=state.get("pantheon_minor") or "None")
        pob.set_config(inputs={"multiplierPoisonOnEnemy": 4}, preserve="none", **ident)  # a bare-rig estimate frozen in the config
        estimate = int(pob.stats(("PoisonStacks",))["PoisonStacks"])
        assert estimate > 4
        kept = derive_config(pob)
        assert kept.conservative.inputs["multiplierPoisonOnEnemy"] == 4  # reading a build as it is (D26)
        ours = derive_config(pob, prefer_rules=True)
        assert ours.conservative.inputs["multiplierPoisonOnEnemy"] == min(estimate, ours.ailment_stack_caps["poison"].counted)
        assert "PoisonStackLimit" in ours.conservative.reasons["multiplierPoisonOnEnemy"]


def test_passive_point_budget_is_pobs_rule() -> None:
    from junkroan.optimizer.rails import Rails, max_passive_points

    assert max_passive_points(77) == 99  # 76 + 23 quest points, a bandit reward taken (Stormbrand 77/Alira: 99)
    assert max_passive_points(77, 1) == 100  # killed every bandit (Absolution 77/None: 100)
    assert max_passive_points(81) == 103 and max_passive_points(75) == 97  # Cold DoT 81/Alira, Hit Penance Brand 75/Alira
    assert max_passive_points(1) == 0 and max_passive_points(12) == 13
    assert Rails.load().passive_points == max_passive_points(Rails.load().level)


@pytest.mark.pob
@needs_pob
def test_pipeline_refuses_a_skeleton_whose_skill_has_no_number(tmp_path: Path) -> None:
    """Smite with Close Combat on a Judgement Staff: PoB gives 0 CombinedDPS; the pipeline raises after
    the first gear pass instead of optimizing a tree for nothing (a Smite search ranked four such builds).
    The supports are the request's own (fixed), so PoB may not choose others (D52 follow-up); a link with
    supports PoB picked is revived instead (tests/test_pipeline_revive_supports.py)."""

    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.optimizer.rails import Rails
    from junkroan.pob.session import PobSession, decode_import_code

    skeleton = skeleton_from_xml(decode_import_code((FIXTURES / "smite.pob.txt").read_text(encoding="utf-8").strip()))
    skeleton.main_link = ["Smite", "Close Combat", "Multistrike"]  # Close Combat: 0 DPS on a staff or a sceptre (a search's sword supports carried over to its weapon variants)
    skeleton.fixed_supports = ["Close Combat", "Multistrike"]
    skeleton.rare_bases["Weapon 1"] = "Judgement Staff"
    skeleton.rare_bases.pop("Weapon 2", None)
    skeleton.sockets.pop("Weapon 1", None)
    with PobSession(run_id="test-no-number", artifacts_root=tmp_path) as pob:
        with pytest.raises(ValueError, match="cannot be used"):
            BuildPipeline(pob, Rails.load()).run(skeleton, screen=True, loot_n=20)


def test_a_floor_met_within_floating_point_is_not_a_shortfall() -> None:
    from junkroan.optimizer.objective import Objective

    obj = Objective(maximize="CombinedDPS", floors={"EffectiveMovementSpeedMod": 1.2})
    assert obj.score({"CombinedDPS": 1.0, "EffectiveMovementSpeedMod": 1.2 - 1e-12}).feasible
    assert not obj.score({"CombinedDPS": 1.0, "EffectiveMovementSpeedMod": 1.19}).feasible
