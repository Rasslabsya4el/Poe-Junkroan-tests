"""#1044: with Chaos Inoculation forced, the defence-pool floor is `EnergyShield` at the author's Life
(benchmark) or at the rails' life floor (request), and there is no `Life` floor; every other floor stays
as it is. Without it the floors are unchanged, field for field."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import FIXTURES, author_floors, resolve_keystone_name  # noqa: E402

from junkroan.optimizer.objective import max_hit_floors  # noqa: E402
from junkroan.optimizer.objective_select import forced_keystones_of, objective_for  # noqa: E402
from junkroan.optimizer.rails import Rails, life_floor_key  # noqa: E402
from junkroan.optimizer.tree_graph import TreeGraph  # noqa: E402


def _author() -> tuple[dict, dict]:
    author = next(r for r in json.loads((FIXTURES / "stats.json").read_text(encoding="utf-8")) if r["slug"] == "stormbrand")
    raw = {**author, "EffectiveMovementSpeedMod": 1.24, "PhysicalMaximumHitTaken": 5000.0}
    lane = {**raw, "TotalEHP": raw["TotalEHP"] * 1.08, "FireResistMax": 80, "ColdResistMax": 76, "LightningResistMax": 75}
    return raw, lane


def test_with_chaos_inoculation_forced_the_author_life_becomes_the_energy_shield_floor() -> None:
    rails = Rails.load()
    objective = rails.objective()
    raw, lane = _author()

    plain = author_floors(objective, raw, lane, rails)
    forced = author_floors(objective, raw, lane, rails, forced_keystones=["Chaos Inoculation"])

    assert forced["EnergyShield"] == raw["Life"] == 4156
    assert "Life" not in forced
    assert {k: v for k, v in forced.items() if k != "EnergyShield"} == {k: v for k, v in plain.items() if k != "Life"}
    assert forced["TotalEHP"] == plain["TotalEHP"] == float(lane["TotalEHP"])
    assert forced["PhysicalMaximumHitTaken"] == plain["PhysicalMaximumHitTaken"] == 5000.0 * 0.95
    assert forced["EffectiveMovementSpeedMod"] == plain["EffectiveMovementSpeedMod"] == min(1.24, 1.2) * 0.97
    assert "Life" in plain and "EnergyShield" not in plain


def test_the_keystone_name_is_matched_case_insensitively() -> None:
    rails = Rails.load()
    raw, lane = _author()
    objective = rails.objective()
    assert author_floors(objective, raw, lane, rails, forced_keystones=("chaos inoculation",))["EnergyShield"] == raw["Life"]
    assert "Life" not in author_floors(objective, raw, lane, rails, forced_keystones=["CHAOS INOCULATION"])


def test_without_chaos_inoculation_the_floors_are_the_old_dict_exactly() -> None:
    rails = Rails.load()
    objective = rails.objective()
    raw, lane = _author()
    expected = {k: v for k, v in objective.floors.items() if not k.endswith("MaximumHitTaken")}
    expected["Life"] = raw["Life"]
    expected["TotalEHP"] = float(lane["TotalEHP"])
    expected.update(max_hit_floors(raw))
    expected["EffectiveMovementSpeedMod"] = min(float(lane["EffectiveMovementSpeedMod"]), rails.movement_speed_floor or 1.0) * 0.97

    assert author_floors(objective, raw, lane, rails) == expected
    assert author_floors(objective, raw, lane, rails, forced_keystones=["Blood Magic"]) == expected
    assert author_floors(objective, raw, lane, rails, forced_keystones=()) == expected


def test_request_rails_objective_swaps_life_for_energy_shield_only_when_forced() -> None:
    rails = Rails.load()
    plain = rails.objective()
    forced = rails.objective(forced_keystones=["Chaos Inoculation"])

    assert plain.floors["Life"] == rails.life_floor and "EnergyShield" not in plain.floors
    assert forced.floors["EnergyShield"] == rails.life_floor and "Life" not in forced.floors
    assert {k: v for k, v in forced.floors.items() if k != "EnergyShield"} == {k: v for k, v in plain.floors.items() if k != "Life"}
    assert life_floor_key([]) == "Life" and life_floor_key(["Blood Magic"]) == "Life" and life_floor_key(["Chaos Inoculation"]) == "EnergyShield"


def test_objective_for_on_a_built_base_moves_the_life_floor_too() -> None:
    """The request pipeline hands `objective_for` the base it built without the keystone (pipeline.run)."""

    rails = Rails.load()
    base = rails.objective()
    assert objective_for(rails, "Spark", base).floors["Life"] == rails.life_floor
    swapped = objective_for(rails, "Spark", base, forced_keystones=("Chaos Inoculation",))
    assert swapped.floors["EnergyShield"] == rails.life_floor and "Life" not in swapped.floors
    assert objective_for(rails, "Spark", forced_keystones=("Chaos Inoculation",)).floors.get("EnergyShield") == rails.life_floor


def test_forced_keystone_names_come_from_the_skeleton_node_ids() -> None:
    graph = TreeGraph.load()
    node_id = resolve_keystone_name(graph, "Chaos Inoculation")[0]
    assert forced_keystones_of(SimpleNamespace(forced_nodes=[node_id])) == ("Chaos Inoculation",)
    assert forced_keystones_of(SimpleNamespace(forced_nodes=[])) == ()
    assert forced_keystones_of(SimpleNamespace()) == ()
