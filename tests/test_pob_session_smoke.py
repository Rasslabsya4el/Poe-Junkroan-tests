"""End-to-end smoke test of PobSession against the pinned PoB runtime.

Skipped when the runtime is not present locally (var/cache/pob/<tag>/app), so
unit test runs stay fast on machines without PoB.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import audit_castability
from junkroan.optimizer.castability import costed_skills, with_castability_floors
from junkroan.optimizer.rails import Rails
from junkroan.pob.headless_runtime_worker import WorkerContractError, check_jit_guard
from junkroan.pob.session import PobSession, decode_import_code, encode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

pytestmark = [pytest.mark.pob, pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)]

BOOTS = """Rarity: Rare
Smoke Boots
Titan Greaves
Item Level: 70
Quality: 0
Sockets: R-R-R-R
LevelReq: 68
Implicits: 0
+80 to maximum Life
30% increased Movement Speed
+35% to Fire Resistance
"""


def test_session_builds_fireball_witch_and_round_trips_import_code(tmp_path: Path) -> None:
    with PobSession(run_id="test-smoke", artifacts_root=tmp_path) as pob:
        pob.set_identity(level=90)
        pob.set_tree(class_id="Witch", ascendancy_id="Elementalist")
        pob.set_skills(main_link=["Fireball", "Spell Echo", "Controlled Destruction"])
        pob.set_items({"Boots": BOOTS})
        pob.set_config(enemy_state={"is_boss": "Pinnacle"})

        stats = pob.calc()
        assert stats["Life"] > 1000
        assert stats["FullDPS"] > 0
        assert stats["FireResist"] == -25  # -60 base + 35 from boots
        assert stats["ColdResist"] == -60
        assert pob.stats(("FireResistMax", "ColdResistMax", "LightningResistMax")) == {
            "FireResistMax": 75,
            "ColdResistMax": 75,
            "LightningResistMax": 75,
        }
        trial = pob.trial_stats([{"add": [], "remove": []}], ("FireResistMax", "ColdResistMax", "LightningResistMax"), mode="fast")[0]
        assert trial["ok"] and trial["stats"] == {"FireResistMax": 75, "ColdResistMax": 75, "LightningResistMax": 75}
        active = pob.read_state()["skills_state"]["socket_groups"][0]["active_skill_entries"][0]
        assert active["granted_effect_id"] == "Fireball" and active["enabled"] is True

        conditional = pob.calc(lane="conditional")
        assert conditional["FullDPS"] == stats["FullDPS"]

        # Hextouch links the manual projectile and its triggered curse. This
        # bare synthetic group has no observed cost for the child, so only the
        # known parent cost enters the floor.
        pob.set_skills(main_link=["Fireball", "Hextouch", "Flammability"])
        assert [(skill.name, skill.mana_cost, skill.triggered) for skill in costed_skills(pob)] == [
            ("Fireball", pytest.approx(26), False),
        ]

        xml = pob.export_xml()
        code = encode_import_code(xml)
        assert decode_import_code(code) == xml
        assert pob.verify_import_code(code)["status"] == "accepted"

        power = pob.node_power()
        assert isinstance(power, dict)


def test_energy_shield_protects_mana_is_read_for_main_and_fast_trial_stats(tmp_path: Path) -> None:
    fixtures = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
    with PobSession(run_id="test-eb", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((fixtures / "soulrend_chaos_dot.pob.txt").read_text(encoding="utf-8")))
        assert pob.stats(("EnergyShieldProtectsMana",))["EnergyShieldProtectsMana"] == 1
        trial = pob.trial_stats([{"add": [], "remove": []}], ("EnergyShieldProtectsMana",), mode="fast")[0]
        assert trial["ok"] and trial["stats"]["EnergyShieldProtectsMana"] == 1
        trial = pob.trial_stats([{"add": [], "remove": []}], ("EnergyShieldProtectsMana",), mode="full")[0]
        assert trial["ok"] and trial["stats"]["EnergyShieldProtectsMana"] == 1
        objective = with_castability_floors(pob, Rails.load().objective())
        stats = pob.stats(objective.stat_keys)
        assert pob.mana_cost_warnings() == ()
        assert audit_castability(pob) == []
        assert not any(key.startswith("ManaCostPool>=") for key in objective.violations(stats))
        assert objective.violations({**stats, "EnergyShieldProtectsMana": 0})["ManaCostPool>=CostedManaCost"] == 1

        pob.load_xml(decode_import_code((fixtures / "physical_dot.pob.txt").read_text(encoding="utf-8")))
        assert pob.stats(("EnergyShieldProtectsMana",))["EnergyShieldProtectsMana"] == 0
        trial = pob.trial_stats([{"add": [], "remove": []}], ("EnergyShieldProtectsMana",), mode="fast")[0]
        assert trial["ok"] and trial["stats"]["EnergyShieldProtectsMana"] == 0
        trial = pob.trial_stats([{"add": [], "remove": []}], ("EnergyShieldProtectsMana",), mode="full")[0]
        assert trial["ok"] and trial["stats"]["EnergyShieldProtectsMana"] == 0


def test_srs_eb_fixture_reports_recharge_after_tree_conversion(tmp_path: Path) -> None:
    from junkroan.optimizer.keystone_floors import ES_RECHARGE_FOR_COSTS_KEYS

    fixtures = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"
    with PobSession(run_id="test-srs-eb-recharge", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code((fixtures / "summon_raging_spirits.pob.txt").read_text(encoding="utf-8")))
        pob.convert_tree()
        stats = pob.stats(ES_RECHARGE_FOR_COSTS_KEYS)
        assert stats["EnergyShieldRecharge"] > 0
        assert stats["EnergyShieldProtectsMana"] == 1
        assert all(stats[key] == 0 for key in ES_RECHARGE_FOR_COSTS_KEYS[2:])


def test_renamed_ascendancy_nodes_materialize_and_read_back(tmp_path: Path) -> None:
    """Ranger's Warden is `id = "Raider", name = "Warden"` in PoB's tree data, and its nodes
    carry the id in `node.ascendancyName` while `PassiveSpec.curAscendClassName` holds the name
    (PassiveSpec.lua:605-606). Matching the two made every ascendancy readback empty for the
    Warden and set_tree raised "ascendancy_node_ids did not materialize". Both spellings of the
    ascendancy must work, and a renamed one must read back like a never-renamed one (Deadeye).
    """

    warden = [4849, 11597]  # Mother's Teachings, Lesson of the Seasons
    deadeye = [24848, 26067]  # Gathering Winds, Endless Munitions
    with PobSession(run_id="test-warden", artifacts_root=tmp_path) as pob:
        pob.set_tree(class_id="Ranger", ascendancy_id="Deadeye", ascendancy_nodes=deadeye)
        control = pob.read_state()["tree_state"]
        assert set(deadeye) <= set(control["allocated_ascendancy_node_ids"])
        assert {"Gathering Winds", "Endless Munitions"} <= set(control["allocated_ascendancy_notables"])

        for spelling in ("Warden", "Raider"):  # display name and PoB id both select it
            pob.set_tree(class_id="Ranger", ascendancy_id=spelling, ascendancy_nodes=warden)
            state = pob.read_state()["tree_state"]
            assert state["ascendancy_id"] == "Warden", spelling
            assert set(warden) <= set(state["allocated_ascendancy_node_ids"]), spelling
            assert {"Mother's Teachings", "Lesson of the Seasons"} <= set(state["allocated_ascendancy_notables"]), spelling
            assert state["allocated_ascendancy_points"] == len(state["allocated_ascendancy_node_ids"]) > 0, spelling

        # the ascendancy-node report walks the whole tree with the same filter
        report = pob._adapter.read_ascendancy_node_report(pob._handle)
        listed = {int(row["node_id"]) for row in report["rows"]}
        assert set(warden) <= listed and len(listed) > 10


def test_boot_refuses_a_runtime_whose_luajit_trace_cache_is_not_the_pinned_one(tmp_path: Path) -> None:
    """The worker reads LuaJIT's state back at boot: a fast trial is 5.2-5.4 ms under
    Launch.lua's maxtrace=4000/maxmcode=8192 and 12.4-13.8 ms under LuaJIT's defaults
    (measured 2026-09-18), so a PoB bump that drops those settings has to fail the boot
    instead of costing +140% per trial in silence. A session that boots proves it passed."""

    with PobSession(run_id="test-jit-guard", artifacts_root=tmp_path) as pob:
        pob.set_identity(level=90)
        assert pob.stats(["Life"])["Life"] > 0

    assert check_jit_guard("true|LuaJIT 2.1.1784580905|4000|8192") == {
        "status": True,
        "version": "LuaJIT 2.1.1784580905",
        "maxtrace": 4000,
        "maxmcode": 8192,
    }
    for raw in (
        "false|LuaJIT 2.1|4000|8192",  # the JIT is off
        "true|LuaJIT 2.1|1000|8192",  # LuaJIT's default trace cache: it thrashes
        "true|LuaJIT 2.1|4000|512",  # LuaJIT's default mcode area
        "true|LuaJIT 2.1||8192",  # Launch.lua applied no jit.opt at all
        "",  # no readback from the wrapper
    ):
        with pytest.raises(WorkerContractError):
            check_jit_guard(raw)
