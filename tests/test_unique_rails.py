"""Unique availability + drop-rate tier rail (D31): PoB Source classes, wiki tiers, drop_enabled."""

import json
from pathlib import Path

from junkroan.optimizer.castability import MANA_COST_POOL_STAT
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails

CORPUS = Path(__file__).resolve().parents[1] / "src" / "junkroan" / "pob" / "corpus_data"


def _rec(name: str) -> dict:
    recs = json.loads((CORPUS / "uniques.json").read_text(encoding="utf-8"))["records"]
    return next(r for r in recs if r["name"].startswith(name + ","))


def test_reference_uniques_pass_and_rare_or_dead_ones_fail() -> None:
    rails = Rails.load()
    for name in ("Honourhome", "The Wasp Nest"):  # Tuadh's tier-5 uniques; day 1 is T5 only (#392)
        assert _rec(name)["tier"] == 5 and rails.unique_allowed(_rec(name)), name
    for name in ("Natural Hierarchy", "Blood of the Karui", "Dyadian Dawn"):  # Tuadh's tier 4 / 4 / 3: out under T5 only
        assert _rec(name)["tier"] in (3, 4) and not rails.unique_allowed(_rec(name)), name
    hh = _rec("Headhunter")
    assert hh["availability"] == "core" and hh["tier"] == 0 and not rails.unique_allowed(hh)
    dead = _rec("Malachai's Awakening")
    assert dead["availability"] == "legacy" and dead["drop_enabled_wiki"] is False
    assert _rec("Jiquani's Potential")["availability"] == "boss"
    assert _rec("Rathpith Globe")["tier"] == 2 and not rails.unique_allowed(_rec("Rathpith Globe"))


def test_without_sustain_keeps_legality_relations() -> None:
    obj = Rails.load().objective()
    lite = obj.without_sustain()
    assert any("PerSecond" in r[1] for r in obj.relations) and not any("PerSecond" in r[1] for r in lite.relations)
    assert ("Str", "ReqStr", 1.0) in lite.relations
    assert (MANA_COST_POOL_STAT, "ManaCost", 1.0, "Mana") in lite.relations
    assert ("LifeUnreserved", "LifeCost", 1.0, "Life") in lite.relations
    assert isinstance(lite, Objective) and lite.floors == obj.floors
