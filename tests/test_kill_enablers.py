"""On-kill enablers on the boss lane (#401): The Writhing Jar spawns adds per flask use (rate read from PoB's own
flask outputs), The Hateful Accuser's Penance Mark has no spawn rate in PoB's skill data (stays 0)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from junkroan.optimizer.config_rules import ADD_KILLS_STAT, build_text, charge_rule, derive_config, flask_add_kills_per_second
from junkroan.pob.skill_facts import constant_stats_matching

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]
needs_pob = pytest.mark.skipif(not (RUNTIME_ROOT / "lua51.dll").is_file(), reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}")
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329" / "exsanguinate_mines.pob.txt"  # slots: Flask 5, Ring 1
ON_KILL = "gain a frenzy charge on kill"
TREE_STATS = {"FrenzyChargesMax": 3, "FrenzyChargesDuration": 10, "Speed": 4.0}


def _open(pob) -> None:
    from junkroan.pob.session import decode_import_code

    pob.load_xml(decode_import_code(FIXTURE.read_text(encoding="utf-8").strip()))


def _boss_rate(pob, extra: str = "") -> tuple[float, str]:
    """The boss lane's on-kill value (frenzy charges gained per second) as derive_config feeds it to charge_rule."""

    derive_config(pob, prefer_rules=True)  # the real path must run on the fixture
    stats = pob.stats()
    text = build_text(pob)
    kills, notes = flask_add_kills_per_second(pob, text)
    if kills > 0:
        stats[ADD_KILLS_STAT] = kills
    _use, why, _override, rate = charge_rule("useFrenzyCharges", stats, text + "\n" + ON_KILL + extra, frozenset(), ramp_seconds=10.0)
    return rate, why


@pytest.mark.pob
@needs_pob
def test_writhing_jar_kills_per_second_come_from_pob_flask_outputs(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    with PobSession(run_id="test-kill-enablers-jar", artifacts_root=tmp_path) as pob:
        _open(pob)
        rate, why = _boss_rate(pob)
        assert rate == 0.0 and "no kills on a boss" in why  # without the item: as on main

        pob.equip({"Flask 5": pob.unique_item("The Writhing Jar")["raw"]})  # exsanguinate_mines, Flask 5 (a Divine Life Flask)
        out = pob.calc_raw()["baseline"]["calcs_output"]
        charges_per_second = out["LifeFlaskChargeGen"] + out["ManaFlaskChargeGen"] - out["FlaskChargeGen"]  # a Hybrid flask: both
        slot = pob.read_state()["gear_slots"]["slots"]["Flask 5"]["item"]
        assert slot["base_type"] == "Hallowed Hybrid Flask" and "15% reduced Charges per use" in slot["explicit_affixes"]
        per_use = math.floor(20 * (1 - 0.15))  # Data/Bases/flask.lua chargesUsed = 20, the item's own line
        expected_kills = 2 * charges_per_second / per_use
        assert expected_kills > 0
        rate, why = _boss_rate(pob)
        print(f"LifeFlaskChargeGen {out['LifeFlaskChargeGen']}, ManaFlaskChargeGen {out['ManaFlaskChargeGen']}, FlaskChargeGen {out['FlaskChargeGen']}: {expected_kills:.4f} kills/s; {why}")
        assert rate == pytest.approx(expected_kills)
        assert "kills/s from adds" in why

        pob.equip({"Flask 5": None})  # the item out again: back to 0
        assert _boss_rate(pob)[0] == 0.0


@pytest.mark.pob
@needs_pob
def test_hateful_accuser_has_no_rate_in_pob_data_and_stays_zero(tmp_path: Path) -> None:
    from junkroan.pob.session import PobSession

    stats = dict(constant_stats_matching("PenanceMark", r"."))
    assert stats == {"base_skill_effect_duration": 3000.0, "penance_mark_summon_phantasms_when_hit": 2.0}  # a count per hit, no interval

    with PobSession(run_id="test-kill-enablers-accuser", artifacts_root=tmp_path) as pob:
        _open(pob)
        pob.equip({"Ring 1": pob.unique_item("The Hateful Accuser")["raw"]})  # exsanguinate_mines, Ring 1
        assert "grants level 20 penance mark" in build_text(pob)  # build_text is lowercased
        rate, why = _boss_rate(pob)
        assert rate == 0.0 and "no kills on a boss" in why


def test_squirming_terror_text_still_counts_one_kill_per_two_seconds() -> None:
    use, why, _o, rate = charge_rule("useFrenzyCharges", TREE_STATS, "an enemy writhing worm spawns every 2 seconds\n" + ON_KILL, frozenset(), ramp_seconds=10.0)
    assert use and "0.50 kills/s from adds" in why and rate == pytest.approx(0.5)
