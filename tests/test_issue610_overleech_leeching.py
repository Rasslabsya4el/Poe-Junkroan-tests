"""#610: an overleech source plus any leech sets `conditionLeeching`; the source list comes from PoB's data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer import config_rules, overleech
from junkroan.optimizer.overleech import OFF_CLASS, SET_CLASS, overleech_leeching, overleech_source_lines
from junkroan.optimizer.trace import TRACE

SOURCE = "Life Leech effects are not removed when Unreserved Life is Filled"
LEECH = {"LifeLeechGainRate": 120.0}


def test_source_list_is_read_from_pob_data() -> None:
    lines = overleech_source_lines()
    print("overleech source lines:", len(lines), sorted(set(lines.values())))
    assert len(lines) >= 4
    assert {"CanLeechLifeOnFullLife", "CanLeechEnergyShieldOnFullEnergyShield"} <= set(lines.values())
    assert "energy shield leech effects are not removed when energy shield is filled" in lines  # Trickster's Soul Drinker
    assert "life leech effects are not removed when unreserved life is filled" in lines  # Slayer's Brutal Fervour


def test_source_and_leech_set_the_toggle() -> None:
    on, why = overleech_leeching(f"10% increased Damage\n{SOURCE}", LEECH)
    assert on and SOURCE in why and "LifeLeechGainRate" in why


def test_leech_without_source_keeps_todays_behaviour() -> None:
    assert overleech_leeching("10% increased Damage\n0.4% of Attack Damage Leeched as Life", LEECH) == (False, None)


def test_source_without_leech_does_not_set_it() -> None:
    assert overleech_leeching(SOURCE, {"LifeLeechGainRate": 0, "ManaLeechGainRate": 0}) == (False, None)


def test_trace_counts_set_and_off() -> None:
    TRACE.reset()
    overleech.count_overleech(True, True, True)
    overleech.count_overleech(False, False, False)
    with TRACE.move("t"):
        pass
    TRACE.flush("t")
    seen = TRACE.considered().get("t", {})
    assert seen.get(OFF_CLASS, {}).get("evaluated", 0) == 0
    assert seen.get(SET_CLASS, {}).get("evaluated", 0) == 1
    TRACE.reset()
    overleech.count_overleech(True, False, False)  # an overleech build left with Leeching off is counted
    TRACE.flush("t2")
    assert TRACE.considered()["t2"][OFF_CLASS]["evaluated"] == 1


ROOT = Path(__file__).resolve().parents[1]
_LOCK = json.loads((ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
_RUNTIME = ROOT / "var" / "cache" / "pob" / _LOCK["tag"] / _LOCK["extract_subdir"]


@pytest.mark.pob
@pytest.mark.skipif(not (_RUNTIME / "lua51.dll").is_file(), reason="pinned PoB runtime not present")
def test_derive_config_sets_conditionleeching_only_with_source_and_leech(tmp_path: Path, monkeypatch) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    code = (ROOT / "tests" / "fixtures" / "tuadh_329" / "ignite_penance_brand.pob.txt").read_text(encoding="utf-8").strip()
    real_text = config_rules.build_text
    with PobSession(run_id="test-610", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(code))
        real_stats = pob.stats

        def with_leech(rate: float):
            return lambda *a, **k: {**real_stats(*a, **k), "LifeLeechGainRate": rate, "ManaLeechGainRate": 0, "EnergyShieldLeechGainRate": 0}

        def derive(source: bool, rate: float):
            monkeypatch.setattr(pob, "stats", with_leech(rate), raising=False)
            monkeypatch.setattr(config_rules, "build_text", (lambda *a, **k: real_text(*a, **k) + chr(10) + SOURCE) if source else real_text)
            return config_rules.derive_config(pob)

        both = derive(True, 120.0)
        assert both.conservative.inputs.get("conditionLeeching") is True
        assert SOURCE in both.conservative.proof_lines["conditionLeeching"]
        no_source = derive(False, 120.0)  # leech alone: today's rule, no overleech proof
        assert SOURCE not in no_source.conservative.proof_lines.get("conditionLeeching", ())
        no_leech = derive(True, 0.0)  # a source without any leech sets nothing
        assert SOURCE not in no_leech.conservative.proof_lines.get("conditionLeeching", ())
        assert "overleech source" not in no_leech.conservative.reasons.get("conditionLeeching", "")


def test_item_granted_keystone_name_is_a_source() -> None:
    """Soul Tether / Mahuxotl's Machination write only "Immortal Ambition"; PoB's legion keystone data holds its leech line."""
    ks = overleech.overleech_keystones()
    print("overleech keystones:", ks)
    assert ks.get("immortal ambition") == "CanLeechLifeOnFullLife"
    assert "vaal pact" not in ks and "strength of blood" not in ks  # instant melee leech / no recovery: not overleech
    text = "Soul Tether\n{tags:resource,defences}Immortal Ambition\nVariant: Ahuana (Immortal Ambition)"
    assert [f for _l, f in overleech.overleech_sources_in(text)] == ["CanLeechLifeOnFullLife"]
    on, why = overleech_leeching(text, LEECH)
    assert on and "Immortal Ambition" in why
    assert overleech_leeching("Vaal Pact\nStrength of Blood", LEECH) == (False, None)
