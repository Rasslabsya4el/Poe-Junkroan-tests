"""#1147 unit 3: a bundle of tree parts is forced by `BuildPipeline.repair` (PoB-free parts + one `pob` rail test).

The PoB-free parts run on the real tree data (the resolver per surface, the split) and on the rig of
test_issue1064_repair (a fake PoB over a synthetic graph) for the routing and the force steps. The rail test at the end
opens one PobSession on a stand and counts the nodes at the PoB boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.repair import RepairChoice, resolve_keystone_id, resolve_part_id, split_bundle
from junkroan.optimizer.tree_graph import TreeGraph

from test_issue1064_repair import FORCED, G, K, L1, L2, _Rig, _force
from test_tree_plan_b import _node

ROOT = Path(__file__).resolve().parents[1]
GRAPH_JSON = ROOT / "src" / "junkroan" / "pob" / "corpus_data" / "bundle_graph_day1.json"

NOTABLE = "notable:10016"  # Executioner
KEYSTONE = "keystone:10661"  # Iron Reflexes
MASTERY = "mastery:10141"  # Recovery Mastery
MASTERY_LINE = "3% chance to Recover all Life when you Kill an Enemy"
MASTERY_EFFECT = 19002  # the effect of that line on that node (masteries.json)
ELEMENTALIST_NODE = "ascendancy:53123"  # Shaper of Flames
NECROMANCER_NODE = "ascendancy:54159"  # Mindless Aggression
ELEMENTALIST_START = "ascendancy:16023"
SKELETON = SimpleNamespace(class_name="Witch", ascendancy="Elementalist")


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph.load()


# -- the choice -------------------------------------------------------------------------------------------------

def test_a_keystone_choice_is_what_it_was():
    choice = RepairChoice("Iron Reflexes", "force")
    assert choice.keystone == "Iron Reflexes" and choice.bundle == ()


def test_a_bundle_choice_needs_force_a_sorted_unique_list_and_no_keystone_name():
    RepairChoice(direction="force", bundle=(KEYSTONE, NOTABLE))  # keystone: < notable:
    with pytest.raises(ValueError, match="forbid"):
        RepairChoice(direction="forbid", bundle=(NOTABLE,))
    with pytest.raises(ValueError, match="sorted"):
        RepairChoice(direction="force", bundle=(NOTABLE, KEYSTONE))
    with pytest.raises(ValueError, match="sorted"):
        RepairChoice(direction="force", bundle=(NOTABLE, NOTABLE))
    with pytest.raises(ValueError, match="either"):
        RepairChoice("Iron Reflexes", "force", bundle=(NOTABLE,))
    with pytest.raises(ValueError, match="names nothing"):
        RepairChoice(direction="force")


# -- the resolver per surface -----------------------------------------------------------------------------------

def test_the_keystone_resolver_is_untouched(graph):
    assert resolve_keystone_id(graph, "iron reflexes") == 10661


def test_notable_and_keystone_ids_resolve_to_the_tree_node(graph):
    assert resolve_part_id(graph, NOTABLE) == 10016
    assert resolve_part_id(graph, KEYSTONE) == 10661


def test_a_notable_id_that_is_a_keystone_in_the_tree_raises(graph):
    with pytest.raises(ValueError, match="not a notable"):
        resolve_part_id(graph, "notable:10661")


@pytest.mark.parametrize("bad", ["notable:99999999", "keystone:99999999", "mastery:99999999", "ascendancy:99999999", "notable:x"])
def test_an_unknown_id_raises(graph, bad):
    with pytest.raises(ValueError, match="no "):
        resolve_part_id(graph, bad, line="x")


def test_a_notable_in_the_corpus_but_off_the_active_tree_raises(graph):
    assert 40828 not in graph.allocatable  # Dark Ideation: PoB's worker answers "unknown node id" for it
    with pytest.raises(ValueError, match="active tree"):
        resolve_part_id(graph, "notable:40828")


def test_a_mastery_resolves_to_the_effect_whose_line_equals_the_given_line(graph):
    assert resolve_part_id(graph, MASTERY, line=MASTERY_LINE) == MASTERY_EFFECT


def test_a_mastery_without_a_line_or_with_a_foreign_line_raises(graph):
    with pytest.raises(ValueError, match="needs the line"):
        resolve_part_id(graph, MASTERY)
    with pytest.raises(ValueError, match="no effect"):
        resolve_part_id(graph, MASTERY, line="Regenerate 5000 Life per second")


def test_a_mastery_effect_id_that_is_also_a_node_id_raises(graph):
    node = next(n for n in graph.nodes.values() if any(e in graph.nodes for e, _ in n.mastery_effects))
    effect, stats = next((e, s) for e, s in node.mastery_effects if e in graph.nodes)
    with pytest.raises(ValueError, match="also a node id"):
        resolve_part_id(graph, f"mastery:{node.node_id}", line=stats[0])


def test_an_ascendancy_node_resolves_when_it_is_the_skeletons_own(graph):
    assert resolve_part_id(graph, ELEMENTALIST_NODE, ascendancy="Elementalist") == 53123
    assert resolve_part_id(graph, ELEMENTALIST_NODE, ascendancy="elementalist") == 53123


def test_an_ascendancy_node_of_another_ascendancy_or_a_start_raises(graph):
    with pytest.raises(ValueError, match="belongs to Necromancer"):
        resolve_part_id(graph, NECROMANCER_NODE, ascendancy="Elementalist")
    with pytest.raises(ValueError, match="start"):
        resolve_part_id(graph, ELEMENTALIST_START, ascendancy="Elementalist")


def test_a_surface_this_change_does_not_force_raises(graph):
    for part in ("gear_affix:Whatever", "flask:Whatever", "unique_jewel:Whatever", "nonsense:1", "10016"):
        with pytest.raises(ValueError, match="cannot be forced|not a graph node id"):
            resolve_part_id(graph, part)


# -- the split (its unique part is in test_issue1147_unique.py) ----------------------------------------------------

def test_split_keeps_the_bundle_order_and_names_the_parts(graph):
    choice = RepairChoice(direction="force", bundle=(ELEMENTALIST_NODE, KEYSTONE, MASTERY, NOTABLE),
                          mastery_lines={MASTERY: MASTERY_LINE})
    parts = split_bundle(choice, graph, SKELETON)
    assert parts.forced_ids == (53123, 10661, MASTERY_EFFECT, 10016)
    assert parts.ascendancy_ids == frozenset({53123})
    assert parts.keystone_names == ("Iron Reflexes",)
    assert parts.label == "Shaper of Flames + Iron Reflexes + Recovery Mastery + Executioner"


# -- routing in `repair` -------------------------------------------------------------------------------------------

def _record_calls(rig: _Rig) -> list[tuple]:
    calls: list[tuple] = []
    for name in ("_repair_force", "_repair_force_bundle", "_repair_forbid"):
        original = getattr(rig.p, name, None)
        if original is None:
            continue

        def wrapped(*args, _name=name, _original=original):
            calls.append((_name, *args[1:]))
            return _original(*args)

        setattr(rig.p, name, wrapped)
    return calls


def test_a_keystone_alone_routes_to_the_old_path_with_the_node_id(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    calls = _record_calls(rig)
    rig.run(RepairChoice(FORCED, "force"))
    assert calls == [("_repair_force", K)]  # the old method, called with the keystone's node id, and nothing else


def test_a_bundle_routes_to_the_bundle_path_and_holds_every_part(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.opt.graph.nodes[G] = _node(G, "g", "notable")  # the path node becomes a notable of the synthetic tree
    calls = _record_calls(rig)
    rig.p._run_loop = lambda build, result, plan, flags: (_ for _ in ()).throw(RuntimeError("stop before the passes"))
    with pytest.raises(RuntimeError, match="stop before"):
        rig.run(RepairChoice(direction="force", bundle=(f"keystone:{K}", f"notable:{G}")))
    assert [name for name, *_ in calls] == ["_repair_force_bundle"]
    assert rig.skeleton.forced_nodes == [K, G]
    assert {K, G} <= rig.pob.allocated and len(rig.pob.allocated) == 7  # the budget again, the leaves paid
    assert not {L1, L2} & rig.pob.allocated  # the two weakest leaves left, as for the keystone alone
    for opt in (rig.opt, rig.construction):
        assert {K, G} <= opt.protected


def test_a_bundle_runs_the_passes_by_the_same_rule(monkeypatch):
    rig = _force(monkeypatch, [0.05, 0.005])
    rig.opt.graph.nodes[G] = _node(G, "g", "notable")
    outcome = rig.run(RepairChoice(direction="force", bundle=(f"keystone:{K}", f"notable:{G}")))
    assert len(outcome.values) == 2 and outcome.verdict == "take"
    assert rig.result.stages[0].name == "repair pass 0"
    assert "force Test Forced Keystone + g" in rig.result.stages[0].notes


def test_a_bundle_with_a_keystone_the_skeleton_forbids_raises(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    rig.skeleton.forbid_keystones.append(FORCED)
    with pytest.raises(ValueError, match="forbids"):
        rig.run(RepairChoice(direction="force", bundle=(f"keystone:{K}",)))


def test_a_bundle_asking_more_ascendancy_points_than_the_rails_allow_raises(monkeypatch):
    rig = _force(monkeypatch, [0.005])
    plain = rig.pob.mutate_nodes
    rig.pob.mutate_nodes = lambda **kw: {**plain(**kw), "ascendancy_points_used": 9}
    rig.p.rails = SimpleNamespace(ascendancy_points=8)
    rig.skeleton.apply_forced_nodes = lambda pob: None  # the fake session knows no ascendancy node
    with pytest.raises(ValueError, match="ascendancy points"):
        rig.run(RepairChoice(direction="force", bundle=(ELEMENTALIST_NODE,)))


# -- the real skeleton puts an ascendancy node through add_nodes ---------------------------------------------------

class _StubPob:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": []}

    def add_nodes(self, ids, *, mastery_effects=None) -> dict:
        self.calls.append(("add_nodes", list(ids), dict(mastery_effects or {})))
        return {"allocated_node_ids": [i for i in ids if i not in (53123,)], "added_node_ids": list(ids)}


def _real_skeleton(forced):
    from junkroan.search.skeleton import Skeleton

    sk = Skeleton.__new__(Skeleton)
    sk.class_name, sk.forced_nodes = "Witch", list(forced)
    return sk


def test_an_ascendancy_forced_node_is_added_after_the_plain_ones_and_not_counted_as_missing():
    pob = _StubPob()
    _real_skeleton([10661, 53123])._apply_forced_nodes(pob)
    assert pob.calls == [("add_nodes", [10661], {}), ("add_nodes", [53123], {})]


def test_without_an_ascendancy_node_the_forced_nodes_call_is_the_old_one():
    pob = _StubPob()
    _real_skeleton([10661])._apply_forced_nodes(pob)
    assert pob.calls == [("add_nodes", [10661], {})]


# -- the rail test: two notables on a stand, counted at the PoB boundary -------------------------------------------

STAND = ROOT / "artifacts" / "stands-1124" / "spark-s4.pob.txt"


def _first_notable_edge(allocated: set[int]) -> tuple[str, str]:
    data = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
    on_tree = TreeGraph.load().allocatable  # the graph also holds notables that are not on the active tree (PoB: unknown node id)
    for edge in sorted(data["edges"], key=lambda e: (e["from"], e["to"])):
        ends = (edge["from"], edge["to"])
        if all(e.startswith("notable:") and int(e.split(":")[1]) not in allocated and int(e.split(":")[1]) in on_tree for e in ends) and ends[0] != ends[1]:
            return tuple(sorted(ends))
    raise AssertionError("no notable edge off the stand")


@pytest.mark.skipif(not ((ROOT / "var" / "cache" / "pob").is_dir() and STAND.is_file()), reason="PoB runtime or the stand file not present")
@pytest.mark.pob
def test_rail_a_two_notable_bundle_is_forced_on_a_stand_and_evaluated():
    """Both notables are allocated in the build the PoB boundary last saw, and each was evaluated (> 0)."""

    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    import replay_bench  # noqa: E402
    from junkroan.optimizer.build_result import BuildResult
    from junkroan.optimizer.improvement_loop import WorkingBuild
    from junkroan.pob.session import PobSession

    info = replay_bench.source_info(STAND)
    logs: list[str] = []
    with PobSession(run_id=f"issue1147-rail-{__import__('os').getpid()}") as pob:
        prepared = replay_bench._prepared_author(pob, info["slug"], info["stat"], logs.append)
        pob.load_import_code(STAND.read_text(encoding="utf-8").strip())
        before = {int(n) for n in pob.tree_light()["user_allocated_node_ids"]}
        bundle = _first_notable_edge(before)
        pipeline, skeleton, gear, tree = replay_bench._pipeline_state(pob, prepared, gear_mode=info["gear_mode"], log=logs.append)
        working = WorkingBuild(pob=pob, judging=pipeline.judging, skeleton=skeleton, gear=gear, tree=tree)
        result = BuildResult(skeleton=skeleton, objective_stat=pipeline.objective.maximize, gear_mode=info["gear_mode"])
        seen: dict[int, int] = {}  # node id -> evaluations whose build held it, counted at the session boundary
        original = pob.stats

        def counting(*args, **kwargs):
            for node in pob.tree_light()["user_allocated_node_ids"]:
                seen[int(node)] = seen.get(int(node), 0) + 1
            return original(*args, **kwargs)

        pob.stats = counting
        outcome = pipeline.repair(working, result, RepairChoice(direction="force", bundle=bundle))
        parts = [int(b.split(":")[1]) for b in bundle]
        held = {int(n) for n in pob.tree_light()["user_allocated_node_ids"]}
        counters = {part: seen.get(part, 0) for part in parts}
        print(f"RAIL bundle={bundle} verdict={outcome.verdict} start={outcome.start:.0f} values={outcome.values} evaluated={counters}")
        assert set(parts) <= held
        assert all(counters[part] > 0 for part in parts)
