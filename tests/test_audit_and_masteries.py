"""Build audit (D31) and the one-effect-per-mastery rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from junkroan.optimizer.audit import Finding, audit_average_damage, audit_skeleton_uniques, audit_stats, audit_xml, worn_unique_names
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.tree_graph import Candidate, TreeGraph
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.pob.session import decode_import_code

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "tuadh_329"


def test_audit_flags_duplicate_mastery_effects_and_legacy_uniques() -> None:
    xml = """<PathOfBuilding><Build level="77"/><Tree><Spec masteryEffects="{4492,5356},{5726,17942},{44298,17942}" nodes="1"/></Tree>
    <Items activeItemSet="1"><Item id="1">Rarity: UNIQUE\nMalachai's Awakening\nIron Mask\n</Item><Item id="2">Rarity: UNIQUE\nJiquani's Potential\nImperial Staff\n</Item>
    <ItemSet id="1"><Slot name="Helmet" itemId="1"/><Slot name="Weapon 1" itemId="2"/></ItemSet></Items><Skills/></PathOfBuilding>"""
    findings = audit_xml(xml, Rails.load())
    text = "\n".join(str(f) for f in findings)
    assert "[error] duplicate mastery effect: effect 17942 selected on 2" in text
    assert "[error] legacy unique: Helmet: Malachai's Awakening" in text
    assert "[warning] unique outside the rails: Weapon 1: Jiquani's Potential is boss" in text


def test_audit_reports_missed_relations_with_numbers() -> None:
    obj = Rails.load().objective()
    stats = {"CombinedDPS": 1, "Life": 4000, "TotalEHP": 12000, "PhysicalMaximumHitTaken": 9000, "FireMaximumHitTaken": 30000, "ColdMaximumHitTaken": 30000, "LightningMaximumHitTaken": 30000, "FireResist": 75, "ColdResist": 75, "LightningResist": 75, "EffectiveMovementSpeedMod": 1.25,
             "Str": 100, "ReqStr": 50, "Dex": 100, "ReqDex": 50, "Int": 100, "ReqInt": 50, "ManaUnreserved": 100, "ManaCost": 30,
             "LifeUnreserved": 4000, "LifeCost": 100, "LifePerSecondCost": 255.3, "LifeRegenRecovery": 37.4, "LifeLeechGainRate": 0, "ManaPerSecondCost": 0}
    findings = audit_stats(stats, obj)
    assert any(f.severity == "error" and "LifeSustainPerSecondCost = 255.3" in f.detail for f in findings), findings
    assert not any("ManaSustainPerSecondCost" in f.detail for f in findings)


def test_summed_relations_in_objective() -> None:
    obj = Objective(maximize="x", relations=(("A+B", "C", 0.85),))
    assert obj.score({"x": 1, "A": 50, "B": 40, "C": 100}).feasible
    assert not obj.score({"x": 1, "A": 50, "C": 100}).feasible  # missing B counts as 0: 50 < 85
    assert obj.score({"x": 1, "A": 50, "B": 40}).feasible  # no cost stat at all: relation not applicable
    assert "A" in obj.stat_keys and "B" in obj.stat_keys and "C" in obj.stat_keys


class _FakePob:
    def __init__(self, taken: list[str]) -> None:
        self._taken = taken

    def read_state(self) -> dict:
        return {"tree_state": {"mastery_effect_ids": self._taken}}


def test_tree_optimizer_never_proposes_a_mastery_effect_twice() -> None:
    graph = TreeGraph.load()
    mastery = next(n for n in graph.nodes.values() if n.kind == "mastery" and len(n.mastery_effects) >= 2)
    other = next(n for n in graph.nodes.values() if n.kind == "mastery" and n.name == mastery.name and n.node_id != mastery.node_id)
    taken_effect = mastery.mastery_effects[0][0]
    opt = TreeOptimizer(_FakePob([f"{mastery.node_id}:{taken_effect}"]), Objective(maximize="CombinedDPS"))
    cand = Candidate(node_id=other.node_id, name=other.name, kind="mastery", cost=1, path=(other.node_id,))
    effects = [t["trial"]["mastery"].get(other.node_id) for t in opt._trials_for([cand])]
    assert effects and taken_effect not in effects
    assert set(effects) == {e for e, _s in other.mastery_effects} - {taken_effect}


def test_audit_flags_more_ascendancy_points_than_the_rails_allow() -> None:
    from junkroan.search.hypothesis import ascendancies

    glad = [int(n["node_id"]) for n in ascendancies()["gladiator"]["nodes"] if not n.get("is_ascendancy_start")][:10]
    xml = f"""<PathOfBuilding><Build level="80"/><Tree><Spec nodes="{','.join(str(n) for n in glad)}"/></Tree><Items activeItemSet="1"><ItemSet id="1"/></Items><Skills/></PathOfBuilding>"""
    findings = audit_xml(xml, Rails.load())
    assert any(f.check == "ascendancy points" and f.severity == "error" for f in findings), findings


def test_audit_warns_when_pob_shows_average_damage_instead_of_dps() -> None:
    blade_trap = {"CombinedDPS": 85353.2, "AverageDamage": 85353.2, "TotalDPS": 0}
    assert any(f.check == "average damage" and "one hit" in f.detail for f in audit_average_damage(blade_trap))
    assert audit_average_damage({"CombinedDPS": 400000.0, "AverageDamage": 90000.0, "TotalDPS": 380000.0}) == []


def test_over_reserved_pool_violation_is_bounded() -> None:
    obj = Objective(maximize="x", relations=(("ManaUnreserved", "ManaCost", 1.0, "Mana"), ("LifeUnreserved", "LifeCost", 1.0, "Life")))
    assert "Mana" in obj.stat_keys and "Life" in obj.stat_keys
    over = obj.score({"x": 1, "ManaUnreserved": -300, "ManaCost": 0, "Mana": 900, "LifeUnreserved": 4000, "LifeCost": 100, "Life": 4000}).violation
    less = obj.score({"x": 1, "ManaUnreserved": -200, "ManaCost": 0, "Mana": 900, "LifeUnreserved": 4000, "LifeCost": 100, "Life": 4000}).violation
    short = obj.score({"x": 1, "ManaUnreserved": 500, "ManaCost": 0, "Mana": 900, "LifeUnreserved": 136, "LifeCost": 786, "Life": 4000}).violation
    assert abs(over - 300 / 900) < 1e-9 and less < over and abs(short - (786 - 136) / 786) < 1e-9  # 0.33 -> 0.22: a gradient; not 300 vs 0.83


def test_audit_flags_a_skeleton_unique_the_build_does_not_wear() -> None:
    """The unequipped quiver: in the list, no slot. PoB's Populate cleared Weapon 2 when Weapon 1 went
    empty (ItemSlotControl.lua:94) and the fill never put it back; the item text stays behind."""

    quiver = "Rarity: UNIQUE\nThe Poised Prism\nBlunt Arrow Quiver"
    worn = ("<PathOfBuilding><Build level=\"80\"/><Tree/>"
            f"<Items activeItemSet=\"1\"><Item id=\"1\">{quiver}</Item>"
            "<ItemSet id=\"1\"><Slot name=\"Weapon 1\" itemId=\"2\"/><Slot name=\"Weapon 2\" itemId=\"0\"/></ItemSet></Items>"
            "<Skills/></PathOfBuilding>")
    uniques = {"Weapon 2": "The Poised Prism"}
    assert [f.detail for f in audit_skeleton_uniques(worn, uniques)] == ["Weapon 2: The Poised Prism"]
    assert all(f.severity == "error" and f.check == "skeleton unique not equipped" for f in audit_skeleton_uniques(worn, uniques))

    equipped = worn.replace('name="Weapon 2" itemId="0"', 'name="Weapon 2" itemId="1"')
    assert audit_skeleton_uniques(equipped, uniques) == []
    assert worn_unique_names(equipped) == {"The Poised Prism"}
    swap = worn.replace('name="Weapon 2" itemId="0"', 'name="Weapon 2 Swap" itemId="1"')
    assert audit_skeleton_uniques(swap, uniques) == []  # an alternate weapon set still counts as equipped
    assert audit_skeleton_uniques(equipped, {}) == []
    assert audit_skeleton_uniques(equipped, {"Belt": "Prismweave"})[0].detail == "Belt: Prismweave"


def test_worn_unique_names_reads_the_escaped_apostrophe() -> None:
    xml = ("<PathOfBuilding><Items activeItemSet=\"1\">"
           "<Item id=\"1\">Rarity: UNIQUE\nAtziri&apos;s Acuity\nVaal Gauntlets</Item>"
           "<ItemSet id=\"1\"><Slot name=\"Gloves\" itemId=\"1\"/></ItemSet></Items></PathOfBuilding>")
    assert worn_unique_names(xml) == {"Atziri's Acuity"}
    assert audit_skeleton_uniques(xml, {"Gloves": "Atziri's Acuity"}) == []
