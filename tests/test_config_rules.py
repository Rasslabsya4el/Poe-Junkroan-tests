"""Phase 4: config lanes derived from PoB's predicates plus source proof. PoB-backed."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from junkroan.optimizer.audit import audit_build
from junkroan.optimizer.config_rules import derive_config
from junkroan.pob.session import PobSession, decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
REGRESSIONS = PROJECT_ROOT / "tests" / "fixtures" / "regressions"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]


def _load(pob: PobSession, slug: str) -> None:
    pob.load_xml(decode_import_code((FIXTURES / f"{slug}.pob.txt").read_text(encoding="utf-8").strip()))


def _apply(pob: PobSession, derived) -> None:
    state = pob.read_state()["config_state"]
    pob.set_config(
        bandit=state.get("bandit") or "None",
        pantheon_major=state.get("pantheon_major") or "None",
        pantheon_minor=state.get("pantheon_minor") or "None",
        enemy_state={"is_boss": "Pinnacle"},
        inputs={k: v for k, v in derived.conservative.inputs.items() if k != "enemyIsBoss"},
        conditional={"inputs": {k: v for k, v in derived.optimistic.inputs.items() if k != "enemyIsBoss"}},
    )


def test_ignite_build_gets_ignite_but_not_unproven_shock(tmp_path: Path) -> None:
    with PobSession(run_id="test-config-ignite", artifacts_root=tmp_path) as pob:
        _load(pob, "ignite_penance_brand")
        author = pob.stats(("CombinedDPS",))["CombinedDPS"]
        derived = derive_config(pob)
        cons, opti = derived.conservative.inputs, derived.optimistic.inputs
        assert cons.get("conditionEnemyIgnited") is True
        # the build's hits always shock and chill; own_hit_ailments types those from the
        # main skill's hits when they earn it (uptime bar, minimum effect); the checkboxes of other sources need a second skill
        assert "conditionEnemyChilled" not in cons  # no second cold skill
        # Wave of Conviction and Smite are second lightning skills, so "enemy shocked" is a real source
        assert cons.get("conditionEnemyShocked") is True and "second lightning skill" in derived.conservative.reasons["conditionEnemyShocked"]
        assert "conditionEnemyScorched" not in cons  # no scorch source
        assert cons.get("BrandsAttachedToEnemy") == 2 and cons.get("ActiveBrands") == 2  # numeric inputs kept
        assert not any(v.startswith("use") and v.endswith("Charges") for v in cons)  # no charge generator in the build
        _apply(pob, derived)
        c, o = pob.calc("baseline")["CombinedDPS"], pob.calc("conditional")["CombinedDPS"]
        assert 0.9 * author <= c <= 1.05 * author  # PoB's own shock from the hits vs the author's checkbox; small difference
        assert o > author


def test_poison_build_keeps_stacks_and_charges_need_generators(tmp_path: Path) -> None:
    with PobSession(run_id="test-config-poison", artifacts_root=tmp_path) as pob:
        _load(pob, "poison_spectral_throw")
        author = pob.stats(("CombinedDPS",))["CombinedDPS"]
        derived = derive_config(pob)
        cons = derived.conservative.inputs
        assert cons.get("multiplierPoisonOnEnemy") == 5  # author's value kept
        # Deflection's "25% chance to gain an Endurance Charge when you Block" is the build's only generator: block is
        # not a source on a boss (mechanics/unsupported_lines.json), so the boss lane leaves the charges off
        assert cons.get("useEnduranceCharges") is not True and "block" in derived.conservative.reasons["useEnduranceCharges"]
        assert derived.optimistic.inputs.get("useEnduranceCharges") is True
        assert "usePowerCharges" not in cons and "useFrenzyCharges" not in cons
        _apply(pob, derived)
        c = pob.calc("baseline")["CombinedDPS"]
        assert abs(c - author) <= 1e-6 * author  # same numbers as the author's own config


def test_every_conservative_toggle_has_a_reason(tmp_path: Path) -> None:
    with PobSession(run_id="test-config-reasons", artifacts_root=tmp_path) as pob:
        _load(pob, "stormbrand")
        derived = derive_config(pob)
        for var, value in derived.conservative.inputs.items():
            assert var in derived.conservative.reasons and not derived.conservative.reasons[var].startswith("off:"), var
        # everything the conservative lane enables, the optimistic lane enables too
        for var, value in derived.conservative.inputs.items():
            assert derived.optimistic.inputs.get(var) == value, var


def _load_stormbrand_regression(pob: PobSession) -> None:
    pob.load_xml(decode_import_code((REGRESSIONS / "stormbrand-gearloot-s2.pob.txt").read_text(encoding="utf-8").strip()))


def _without_baseline_power_charges(xml: str) -> str:
    root = ET.fromstring(xml)
    config = root.find("Config")
    baseline = next(s for s in config.findall("ConfigSet") if s.get("title") == "Baseline")
    baseline.remove(next(i for i in baseline.findall("Input") if i.get("name") == "usePowerCharges"))
    return ET.tostring(root, encoding="unicode")


def test_stormbrand_gearloot_channelling_generator_is_off_and_isolated_toggle_is_measured(tmp_path: Path) -> None:
    """The isolated mutation keeps every original config input except Power Charges.

    The pinned runtime measures 1,831,645 here. The historical 1,611,848 target also
    needs `conditionEnemyOnConsecratedGround` off; this test intentionally preserves it.
    """

    with PobSession(run_id="test-config-stormbrand-gearloot", artifacts_root=tmp_path) as pob:
        _load_stormbrand_regression(pob)
        derived = derive_config(pob)
        assert "usePowerCharges" not in derived.conservative.inputs

        original = pob.export_xml()
        inputs = pob.config_inputs()
        assert inputs.get("usePowerCharges") is True
        pob.load_xml(_without_baseline_power_charges(original))
        assert pob.config_inputs() == {key: value for key, value in inputs.items() if key != "usePowerCharges"}
        full_dps = pob.calc("baseline")["FullDPS"]
        assert full_dps == pytest.approx(1_831_645, rel=0.005)


def test_stormbrand_gearloot_original_baseline_fails_generator_audit(tmp_path: Path) -> None:
    with PobSession(run_id="test-audit-stormbrand-gearloot", artifacts_root=tmp_path) as pob:
        _load_stormbrand_regression(pob)
        findings = audit_build(pob)
        assert any(f.severity == "error" and f.check == "conservative generator proof" and "usePowerCharges" in f.detail for f in findings)
