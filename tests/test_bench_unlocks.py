"""Bench recipe unlock data and the day-1 crafting rail."""

from __future__ import annotations

import json
from pathlib import Path

from junkroan.mechanics.bench_unlocks import legal, lowest_requirement
from junkroan.optimizer.loot_gear import bench_candidates
from junkroan.optimizer.rails import Rails


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "junkroan" / "mechanics" / "bench_unlocks.json"


def _entries() -> list[dict]:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    return [*raw["by_mod_id"].values(), *raw["by_name"].values()]


def test_generated_index_pins_all_wiki_options_and_current_tier_split() -> None:
    entries = _entries()
    assert len(entries) == 829
    assert {entry["where"] for entry in entries} == {"start", "campaign", "labyrinth", "map"}
    assert {where: sum(entry["where"] == where for entry in entries) for where in ("start", "campaign", "labyrinth", "map")} == {
        "start": 79,
        "campaign": 187,
        "labyrinth": 18,
        "map": 545,
    }
    assert sum(entry["where"] == "map" and entry["tier"] is not None and entry["tier"] <= 10 for entry in entries) + sum(entry["where"] == "map" and entry["tier"] is None for entry in entries) == 422
    assert sum(entry["where"] == "map" and entry["tier"] is not None and 11 <= entry["tier"] <= 16 for entry in entries) == 123
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    assert raw["by_name"]["Two Sockets"]["cost"] == ["1x Jeweller's Orb"]


def test_flat_life_recipe_and_tier_twelve_recipe_follow_the_rail() -> None:
    raw = json.loads(DATA.read_text(encoding="utf-8"))
    life = raw["by_mod_id"]["EinharMasterIncreasedLife5_"]
    tier_twelve = raw["by_mod_id"]["JunMaster2MinimumFrenzyCharges1_"]
    assert legal(life, max_map_tier=10)
    assert not legal(life, max_map_tier=6)
    assert not legal(tier_twelve, max_map_tier=10)
    assert legal(tier_twelve, max_map_tier=None)


def test_the_pinned_pob_alias_still_resolves_to_the_current_wiki_recipe() -> None:
    from junkroan.mechanics.bench_unlocks import lookup

    unlock = lookup(mod_id="EinharMasterLocalLifeLeechPermyriad1__")
    assert unlock and unlock["location"] == "Flooded Mine" and unlock["tier"] == 4


def test_currency_exclusion_and_missing_data_rules() -> None:
    exalted = {"where": "campaign", "tier": None, "cost": ["4x Exalted Orb"]}
    assert legal(exalted, excluded_cost_currencies=())
    assert not legal(exalted, excluded_cost_currencies=("Exalted Orb",))
    assert legal(exalted, excluded_cost_currencies=("",))
    assert legal(None, max_map_tier=10, excluded_cost_currencies=("Exalted Orb",))


def test_loaded_rails_expose_the_bench_block_and_allow_an_override(tmp_path: Path) -> None:
    path = tmp_path / "rails.json"
    path.write_text(json.dumps({"gear": {"bench": {"max_map_tier": 6, "unknown_tier_allowed": True, "excluded_cost_currencies": ["Divine Orb"]}}}), encoding="utf-8")
    rails = Rails.load(path)
    assert rails.gear.bench.max_map_tier == 6
    assert rails.gear.bench.unknown_tier_allowed
    assert rails.gear.bench.excluded_cost_currencies == ("Divine Orb",)
    assert not rails.bench_allowed({"unlock": {"where": "map", "tier": 7, "cost": []}})


def test_unknown_map_tier_is_a_separate_rail_choice() -> None:
    unknown = {"where": "map", "tier": None, "cost": []}
    assert not legal(unknown, max_map_tier=10, unknown_tier_allowed=False)
    assert legal(unknown, max_map_tier=10, unknown_tier_allowed=True)


def test_multiple_candidate_ids_choose_the_lowest_requirement() -> None:
    entries = [
        {"where": "map", "tier": 12, "cost": []},
        {"where": "campaign", "tier": None, "cost": []},
    ]
    assert lowest_requirement(entries)["where"] == "campaign"


def test_bench_candidates_applies_the_rail_once_for_both_fillers() -> None:
    rails = Rails()
    rows = [
        {"type": "Suffix", "group": "high", "level": 90, "unlock": {"where": "map", "tier": 12, "cost": []}},
        {"type": "Suffix", "group": "low", "level": 80, "unlock": {"where": "map", "tier": 10, "cost": []}},
        {"type": "Suffix", "group": "gap", "level": 70, "unlock": None},
    ]
    kept = bench_candidates(rows, [], lambda _mod_id: frozenset(), 0, 0, rails)
    assert [row["group"] for row in kept] == ["low", "gap"]
