"""#1147 unit 4: a unique part of a bundle goes through the forced-unique path (PoB-free parts + one `pob` rail test).

The PoB-free parts run on the real tree data (the split) and on the rig of test_issue1064_repair (a fake PoB over a
synthetic graph) for the order of the forcing steps. The rail test opens one PobSession on a stand and reads the
build XML the PoB boundary last saw.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.repair import RepairChoice, split_bundle
from junkroan.optimizer.tree_graph import TreeGraph

from test_issue1064_repair import G, K, _force
from test_tree_plan_b import _node

ROOT = Path(__file__).resolve().parents[1]
GRAPH_JSON = ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "bundle_graph_day1.json"

NOTABLE = "notable:10016"  # Executioner
GLOVES = "unique:Admiral's Arrogance, Antique Gauntlets"  # type Gloves -> slot Gloves
WAND = "unique:Abberath's Horn, Goat's Horn"  # type Wand -> Weapon 1 or Weapon 2
CLAW = "unique:Advancing Fortress, Gut Ripper"  # type Claw -> Weapon 1 or Weapon 2


def _skeleton(**kw):
    base = dict(class_name="Witch", ascendancy="Elementalist", forced_uniques={}, forced_bases={}, forced_affixes={}, uniques={}, rare_bases={})
    return SimpleNamespace(**{**base, **kw})


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph.load()


# -- the split ------------------------------------------------------------------------------------------------------

def test_a_unique_goes_to_the_unique_list_and_a_tree_id_to_the_tree_parts(graph):
    parts = split_bundle(RepairChoice(direction="force", bundle=(NOTABLE, GLOVES)), graph, _skeleton())
    assert parts.forced_ids == (10016,)
    assert parts.uniques == (("Gloves", "Admiral's Arrogance"),)  # slot, the name without its base
    assert parts.label == "Executioner + Admiral's Arrogance"


def test_a_bundle_without_a_unique_has_no_unique_part(graph):
    parts = split_bundle(RepairChoice(direction="force", bundle=(NOTABLE,)), graph, _skeleton())
    assert parts.uniques == ()


def test_two_uniques_of_one_bundle_take_two_slots(graph):
    parts = split_bundle(RepairChoice(direction="force", bundle=tuple(sorted((CLAW, WAND)))), graph, _skeleton())
    assert sorted(slot for slot, _ in parts.uniques) == ["Weapon 1", "Weapon 2"]


def test_a_slot_with_a_unique_of_the_skeleton_is_taken_last(graph):
    parts = split_bundle(RepairChoice(direction="force", bundle=(WAND,)), graph, _skeleton(uniques={"Weapon 1": "Some Wand"}))
    assert parts.uniques == (("Weapon 2", "Abberath's Horn"),)


def test_a_unique_whose_slot_the_request_fixed_has_no_slot_and_raises_clearly(graph):
    sk = _skeleton(forced_uniques={"Gloves": "Some Gloves"})
    with pytest.raises(ValueError, match=r"no slot .*Admiral's Arrogance"):
        split_bundle(RepairChoice(direction="force", bundle=(GLOVES,)), graph, sk)


def test_a_unique_with_no_slot_in_the_gear_raises_clearly(graph):
    with pytest.raises(ValueError, match="no slot"):
        split_bundle(RepairChoice(direction="force", bundle=("unique:No Such Unique, Nothing",)), graph, _skeleton())


# -- the repair step: both kinds forced before the loop ---------------------------------------------------------------

def _unique_rig(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.opt.graph.nodes[G] = _node(G, "g", "notable")
    sk = rig.skeleton
    for name, value in dict(forced_uniques={}, forced_bases={}, forced_affixes={}, uniques={}, rare_bases={"Gloves": "Gauntlets"}).items():
        setattr(sk, name, value)
    rig.build.gear = SimpleNamespace(uniques={}, current_raw={"Gloves": "rare gloves"})
    calls: list[tuple] = []
    pob = rig.pob
    pob.unique_item = lambda name: calls.append(("unique_item", name)) or {"raw": f"RAW {name}"}
    pob.equip = lambda items: calls.append(("equip", dict(items)))
    add = pob.add_nodes
    pob.add_nodes = lambda ids, **kw: calls.append(("add_nodes", list(ids))) or add(ids, **kw)
    pass_run = rig.p._run_loop
    rig.p._run_loop = lambda *a: calls.append(("loop",)) or pass_run(*a)
    return rig, calls


def test_tree_parts_and_uniques_are_both_forced_before_the_loop(monkeypatch):
    rig, calls = _unique_rig(monkeypatch)
    rig.run(RepairChoice(direction="force", bundle=tuple(sorted((GLOVES, f"notable:{G}")))))
    names = [c[0] for c in calls]
    assert ("equip", {"Gloves": "RAW Admiral's Arrogance"}) in calls
    assert ("add_nodes", [G]) in calls
    loop = names.index("loop")
    assert names.index("equip") < loop and names.index("add_nodes") < loop


def test_the_unique_is_held_by_the_skeleton_and_the_gear_the_way_a_requested_unique_is(monkeypatch):
    rig, _ = _unique_rig(monkeypatch)
    rig.run(RepairChoice(direction="force", bundle=(GLOVES,)))
    sk = rig.skeleton
    assert sk.uniques == {"Gloves": "Admiral's Arrogance"} and sk.forced_uniques == {"Gloves": "Admiral's Arrogance"}
    assert "Gloves" not in sk.rare_bases  # the loop's gear move refills rare slots only
    assert rig.build.gear.uniques == {"Gloves": "RAW Admiral's Arrogance"}
    assert "Gloves" not in rig.build.gear.current_raw


def test_a_bundle_without_a_unique_makes_no_gear_call(monkeypatch):
    rig, calls = _unique_rig(monkeypatch)
    rig.run(RepairChoice(direction="force", bundle=(f"notable:{G}",)))
    assert [c for c in calls if c[0] in ("equip", "unique_item")] == []
    assert rig.skeleton.forced_uniques == {}


def test_a_unique_only_bundle_makes_no_tree_call(monkeypatch):
    rig, calls = _unique_rig(monkeypatch)
    rig.run(RepairChoice(direction="force", bundle=(GLOVES,)))
    assert [c for c in calls if c[0] == "add_nodes"] == []


# -- the rail test: one stand, the unique worn in the evaluated build -------------------------------------------------

STAND = ROOT / "artifacts" / "stands-1124" / "spark-s4.pob.txt"
needs_pob = pytest.mark.skipif(not ((ROOT / "var" / "cache" / "pob").is_dir() and STAND.is_file()), reason="PoB runtime or the stand file not present")


def _worn(xml: str) -> dict[str, str]:
    """slot -> name line of the item worn in the active item set."""

    items = ET.fromstring(xml).find("Items")
    by_id = {i.get("id"): [line.strip() for line in (i.text or "").splitlines() if line.strip()] for i in items.findall("Item")}
    active = next(s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1"))
    return {s.get("name"): (by_id.get(s.get("itemId")) or ["", ""])[1] for s in active.findall("Slot") if by_id.get(s.get("itemId"))}


def _first_unique_edge(allocated: set[int], skeleton) -> tuple[str, ...]:
    """The first edge sorted by (from, to) with one unique end that fits the stand and one on-tree notable / keystone end
    (#1147 unit 5a: the one rule is `bundle_select.first_unique_bundle`)."""

    from junkroan.optimizer.bundle_fit import load_bundle_graph, stand_from_skeleton
    from junkroan.optimizer.bundle_select import first_unique_bundle

    pick = first_unique_bundle(GRAPH_JSON, load_bundle_graph(), stand_from_skeleton(skeleton), allocated, TreeGraph.load().allocatable)
    if pick is None:
        raise AssertionError("no unique edge fits the stand")
    return pick.ids


@needs_pob
@pytest.mark.pob
def test_rail_a_unique_part_is_worn_in_the_evaluated_build():
    import os
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import replay_bench  # noqa: E402
    from junkroan.optimizer.build_result import BuildResult
    from junkroan.optimizer.improvement_loop import WorkingBuild
    from junkroan.pob.session import PobSession

    info = replay_bench.source_info(STAND)
    logs: list[str] = []
    with PobSession(run_id=f"issue1147-unique-rail-{os.getpid()}") as pob:
        prepared = replay_bench._prepared_author(pob, info["slug"], info["stat"], logs.append)
        pob.load_import_code(STAND.read_text(encoding="utf-8").strip())
        before = {int(n) for n in pob.tree_light()["user_allocated_node_ids"]}
        pipeline, skeleton, gear, tree = replay_bench._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
        bundle = _first_unique_edge(before, skeleton)
        working = WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree)
        result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=info["gear_mode"])
        parts = split_bundle(RepairChoice(direction="force", bundle=bundle), tree.graph, skeleton)  # before the repair: the repair fills the slot
        (slot, name), = parts.uniques
        outcome = pipeline.repair(working, result, RepairChoice(direction="force", bundle=bundle))
        worn = _worn(pob.export_xml())
        print(f"RAIL bundle={bundle} slot={slot} worn={worn.get(slot)!r} verdict={outcome.verdict} start={outcome.start:.0f} values={outcome.values}")
        assert worn.get(slot) == name
        assert outcome.values  # the loop passes ran on the build that wears it
