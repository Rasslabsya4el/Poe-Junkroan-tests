"""#1147 unit 6: another class's start is no connectivity root (PoB-free).

The stand spark-s4 (a Templar) holds 57264, a neighbour of the Witch start. `TreeGraph.roots` took every class start
adjacent to the allocation as a root, so the Templar trunk node 14151 (Intelligence) looked like a removable leaf:
the 92 nodes past it were "connected" through the Witch start. PoB connects a tree from its own class start only, so
the repair's weakest-leaf trim removed 14151 and PoB cascaded the whole tree away with it, the forced bundle included
(both acceptance bundles ended on the same 14-node tree: CombinedDPS 1,053,483 -> 55,607)."""

from __future__ import annotations

from junkroan.optimizer.tree_graph import TreeGraph

# `<Spec nodes=...>` of artifacts/stands-1124/spark-s4.pob.txt (class Templar, 61525 is its start)
SPARK_S4_NODES = frozenset({
    739, 1203, 1957, 2292, 2913, 3167, 4184, 4367, 4397, 5348, 5726, 5743, 6237, 6764, 7153, 7335, 7555, 7938, 9386, 9432,
    10575, 10635, 11420, 11645, 12379, 14021, 14057, 14151, 14936, 15405, 15599, 16775, 17352, 17579, 17735, 18866, 20228,
    21262, 21413, 21934, 21958, 22088, 23456, 26866, 27203, 27564, 30225, 31875, 32431, 32455, 32816, 33296, 33435, 33479,
    33631, 33740, 33755, 33923, 34157, 35724, 36121, 36678, 39790, 39841, 40059, 40351, 40366, 41472, 42760, 44183, 44184,
    44529, 44908, 45317, 46469, 46910, 47312, 48362, 49254, 49588, 50288, 50862, 54657, 54694, 55332, 55485, 55647, 55866,
    56029, 56716, 57222, 57264, 57362, 58218, 58402, 58604, 58763, 60769, 61217, 61264, 61471, 61525, 61871, 63447, 63965,
    63976, 65034,
})
TEMPLAR_TRUNK_INTELLIGENCE = 14151


def test_the_witch_start_is_no_root_of_a_templar_tree():
    graph = TreeGraph.load()
    witch, templar = graph.class_starts["Witch"], graph.class_starts["Templar"]
    assert 57264 in SPARK_S4_NODES and witch in graph.neighbours(57264)  # the premise: the tree touches the Witch start
    roots = graph.roots(SPARK_S4_NODES)
    assert templar in roots
    assert witch not in roots


def test_a_trunk_node_of_the_templar_tree_is_not_a_removable_leaf():
    graph = TreeGraph.load()
    assert TEMPLAR_TRUNK_INTELLIGENCE not in graph.removable_leaves(SPARK_S4_NODES)


def test_every_removable_leaf_of_the_stand_leaves_the_rest_connected_to_its_own_start():
    graph = TreeGraph.load()
    templar = graph.class_starts["Templar"]
    ascendancy = {n for n in SPARK_S4_NODES if n not in graph.allocatable and n != templar}  # the Inquisitor's own nodes
    for leaf in graph.removable_leaves(SPARK_S4_NODES):
        rest = SPARK_S4_NODES - {leaf}
        reached = graph._connected_from({templar} | ascendancy, set(rest))
        assert rest <= reached, (leaf, len(rest - reached))


def test_a_trim_removal_whose_cascade_takes_a_forced_node_is_refused_and_raises_when_no_leaf_is_left(monkeypatch):
    """The repair's trim never goes on with a forced node PoB cascaded away (the rail failure: {10115, 14813} not held):
    since #1164 each such cut is refused and put back, so a trim whose every leaf cascades the forced path ends with no leaf."""

    import pytest

    from junkroan.optimizer.repair import RepairChoice
    from test_issue1064_repair import FORCED, G, K, _force

    rig = _force(monkeypatch, [0.005])
    plain = rig.pob.remove_nodes

    def cascading(ids):  # PoB's connectivity is not the graph's: the leaf's removal takes the forced path with it
        return plain(list(ids) + [G, K])

    rig.pob.remove_nodes = cascading
    with pytest.raises(RuntimeError, match="no leaf to remove"):
        rig.run(RepairChoice(FORCED, "force"))


def test_a_readback_without_the_class_start_still_finds_it_by_adjacency():
    graph = TreeGraph.load()
    templar = graph.class_starts["Templar"]
    assert templar in graph.roots(SPARK_S4_NODES - {templar})  # the old fallback stays for a readback that omits the start
