"""Azadi Crest on the boss lane (#401): an on-block charge line counts at half value without a retaliation skill
(Azadi's own line: lucky effects use three rolls), full with one, and 0 without Azadi Crest (as on main)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import build_text, charge_rule

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "exsanguinate_mines.pob.txt"

STATS = {"EnduranceChargesMax": 4, "EnduranceChargesDuration": 10, "Speed": 4.0, "CritChance": 50}
BLOCK = "25% chance to gain an endurance charge when you block"
AZADI = "Your Lucky or Unlucky effects use the best or\nworst from three rolls instead of two"


def _rule(text: str, tags: frozenset[str] = frozenset()):
    return charge_rule("useEnduranceCharges", STATS, text, tags, ramp_seconds=2.5)


def test_on_block_is_half_value_with_azadi_and_no_retaliation_skill() -> None:
    use, why, override, rate = _rule(BLOCK + "\n" + AZADI)
    # full rate = kmax / duration = 4 / 10 s = 0.4 per second; half = 0.2 per second = 2 held of 4
    assert use and abs(rate - 0.2) < 1e-9 and override == 2 and "half value" in why


def test_on_block_with_a_retaliation_skill_stays_full() -> None:
    use, why, override, rate = _rule(BLOCK + "\n" + AZADI, frozenset({"retaliation"}))
    assert use and override is None and rate == 0.0 and "retaliation" in why


def test_on_block_without_azadi_is_zero_as_on_main() -> None:
    use, why, override, rate = _rule(BLOCK)
    assert not use and override is None and rate == 0.0 and "not a source" in why


@pytest.mark.pob
@needs_pob
def test_azadi_crest_in_weapon_2_halves_the_on_block_line(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession, decode_import_code

    # exsanguinate_mines, slot "Weapon 2" (Azadi Crest is a shield); the fixture carries no on-block line, so the
    # line is appended to the build text as the other kill-enabler tests append theirs.
    with PobSession(run_id="test-azadi-block", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(FIXTURE.read_text(encoding="utf-8").strip()))
        stats = pob.stats()
        before = charge_rule("useEnduranceCharges", stats, build_text(pob) + "\n" + BLOCK, frozenset(), ramp_seconds=2.5)
        assert not before[0] and before[3] == 0.0
        pob.equip({"Weapon 2": pob.unique_item("Azadi Crest")["raw"]})
        stats = pob.stats()
        text = build_text(pob)
        assert "three rolls instead of two" in text
        use, _why, _override, rate = charge_rule("useEnduranceCharges", stats, text + "\n" + BLOCK, frozenset(), ramp_seconds=2.5)
        kmax, duration = float(stats["EnduranceChargesMax"]), float(stats["EnduranceChargesDuration"])
        assert use and abs(rate - 0.5 * kmax / duration) < 1e-9
