"""#400: "N% increased Effect of Cruelty" above PoB's clamp of 40, carried by one custom mod.

Fixture: zizaran_325/early/gladiator_lacerate (Cruelty Support linked to Lacerate; overrideCruelty is not
set in the build, so the value the lane holds is PoB's own 40). Mastery node 22067 (Damage Over Time
Mastery, effect 2459 = "30% increased Effect of Cruelty")."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import derive_config
from junkroan.optimizer.ramp_inputs import _more_lines_for, apply_custom_mods
from junkroan.pob.session import PobSession, decode_import_code

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "zizaran_325" / "early" / "gladiator_lacerate.pob.txt"
MASTERY, EFFECT = 22067, 2459
OUTPUTS = ("BleedDPS", "TotalDotDPS", "CombinedDPS")


def _load(pob: PobSession, *, mastery: bool, strip_cruelty: bool = False) -> None:
    xml = decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())
    if strip_cruelty:
        xml = re.sub(r'<Gem [^>]*nameSpec="Cruelty"[^>]*?(/>|>.*?</Gem>)', "", xml, flags=re.S)
        assert 'nameSpec="Cruelty"' not in xml
    pob.load_xml(xml)
    if mastery:
        pob.add_nodes([MASTERY], mastery_effects={MASTERY: EFFECT})


def _derived(pob: PobSession):
    pob.set_config(enemy_state={"is_boss": "Pinnacle"}, inputs={}, preserve="numeric")  # the pipeline's Baseline config set
    return derive_config(pob, cap_ailment_stacks=False)


def _cruelty_blocks(pob: PobSession) -> list[str]:
    return re.findall(r'<CustomModifierBlock[^>]*title="junkroan: Cruelty[^"]*"[^>]*>.*?</CustomModifierBlock>', pob.export_xml(), re.S)


@pytest.mark.parametrize("v,n", [(40, 30), (40, 90), (25, 30), (10, 60)])
def test_whole_percent_lines_land_within_a_tenth_of_a_percent(v: int, n: int) -> None:
    factor = (1 + v * (1 + n / 100) / 100) / (1 + v / 100)
    values, product = _more_lines_for(factor)
    assert len(values) == 1
    assert abs(product / factor - 1) < 0.0055  # whole percents only


@pytest.mark.pob
def test_row1_mastery_raises_damage_over_time_by_the_clamp_excess(tmp_path) -> None:
    with PobSession(run_id="test-cruelty-excess-1", artifacts_root=tmp_path) as pob:
        _load(pob, mastery=True)
        derived = _derived(pob)
        assert len(derived.custom_mods) == 1
        line, _title, why = derived.custom_mods[0]
        assert "Damage Over Time Mastery" in why and "30% increased Effect of Cruelty" in why
        assert derived.conservative.inputs.get("overrideCruelty") is None  # PoB's own 40 stays: nothing typed above the clamp
        without = pob.stats()
        apply_custom_mods(pob, derived.custom_mods)
        assert len(_cruelty_blocks(pob)) == 1
        with_mod = pob.stats()
    expected = (1 + 1.3 * 40 / 100) / (1 + 40 / 100)  # v = 40: PoB's default Cruelty when overrideCruelty is not set
    for key in ("BleedDPS", "TotalDotDPS"):
        ratio = with_mod[key] / without[key]
        assert abs(ratio / expected - 1) < 0.0055, (key, ratio, expected)


@pytest.mark.pob
def test_row2_without_the_mastery_nothing_changes(tmp_path) -> None:
    with PobSession(run_id="test-cruelty-excess-2", artifacts_root=tmp_path) as pob:
        _load(pob, mastery=False)
        derived = _derived(pob)
        before = {k: pob.stats().get(k) for k in OUTPUTS}
        assert derived.custom_mods == []
        apply_custom_mods(pob, derived.custom_mods)
        assert _cruelty_blocks(pob) == []
        assert {k: pob.stats().get(k) for k in OUTPUTS} == before


@pytest.mark.pob
def test_row3_without_cruelty_support_no_custom_mod(tmp_path) -> None:
    with PobSession(run_id="test-cruelty-excess-3", artifacts_root=tmp_path) as pob:
        _load(pob, mastery=True, strip_cruelty=True)
        derived = _derived(pob)
        assert all("Cruelty" not in str(m[1]) for m in derived.custom_mods)
        assert _cruelty_blocks(pob) == []


@pytest.mark.pob
def test_audit_lists_the_line_as_a_zero_only_without_the_custom_mod(tmp_path) -> None:
    from junkroan.optimizer.audit import audit_unsupported_mods

    with PobSession(run_id="test-cruelty-excess-audit", artifacts_root=tmp_path) as pob:
        _load(pob, mastery=True)
        listed = [f for f in audit_unsupported_mods(pob) if "Effect of Cruelty" in f.detail]
        derived = _derived(pob)
        apply_custom_mods(pob, derived.custom_mods)
        after = [f for f in audit_unsupported_mods(pob) if "Effect of Cruelty" in f.detail]
    assert listed and not after
