"""Day-1 rulebook rails (#392): uniques of drop-rate tier T5 only, no bench craft that costs Exalted Orb."""

import json
from pathlib import Path

from junkroan.mechanics import bench_unlocks
from junkroan.optimizer.rails import Rails

CORPUS = Path(__file__).resolve().parents[1] / "src" / "junkroan" / "pob" / "corpus_data"


def _rec(name: str) -> dict:
    recs = json.loads((CORPUS / "uniques.json").read_text(encoding="utf-8"))["records"]
    return next(r for r in recs if r["name"].startswith(name + ","))


def test_only_tier_5_uniques_allowed() -> None:
    rails = Rails.load()
    assert rails.unique_allowed_tiers == (5,)
    assert _rec("Dyadian Dawn")["tier"] == 3 and not rails.unique_allowed(_rec("Dyadian Dawn"))
    assert _rec("Natural Hierarchy")["tier"] == 4 and not rails.unique_allowed(_rec("Natural Hierarchy"))
    assert _rec("Honourhome")["tier"] == 5 and rails.unique_allowed(_rec("Honourhome"))


def test_bench_row_with_exalted_orb_cost_refused() -> None:
    rails = Rails.load()
    assert rails.gear.bench.excluded_cost_currencies == ("Exalted Orb",)
    row = {"unlock": {"where": "start", "tier": None, "cost": ["4x Exalted Orb"]}}
    assert not rails.bench_allowed(row)
    assert rails.bench_allowed({"unlock": {"where": "start", "tier": None, "cost": ["1x Orb of Alteration"]}})


def test_real_exalted_craft_illegal_under_loaded_rail() -> None:
    bench = Rails.load().gear.bench
    unlock = bench_unlocks.data()["by_mod_id"]["EinharMasterIncreasedCastSpeed3"]
    assert "Exalted Orb" in " ".join(unlock["cost"])
    assert not bench_unlocks.legal(
        unlock,
        max_map_tier=bench.max_map_tier,
        unknown_tier_allowed=bench.unknown_tier_allowed,
        excluded_cost_currencies=bench.excluded_cost_currencies,
    )
