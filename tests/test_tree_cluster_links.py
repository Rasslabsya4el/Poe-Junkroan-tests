"""#433 unit 10: a socketed cluster jewel's nodes are connected through its outer socket (kind: refactor of connectivity).

The case is the unit-8 witness' shape without PoB: a real `TreeGraph.load()`, a Shadow path of the real tree to the
Large Jewel Socket 32763, the cluster's inner nodes (ids >= 65536, unknown to the static graph) and the inner
"Medium Jewel Socket" 6910 (a real tree id PoB links only through the inner nodes). The links are PoB's own
`cluster_graph(32763)` of that fixture (id, linked), unit 8's measurement.
"""

from __future__ import annotations

from junkroan.optimizer.jewel_probe import PobJewelProbe, cluster_links_of
from junkroan.optimizer.tree_graph import TreeGraph, links_from_edges

OUTER = 32763
INNER_SOCKET = 6910
START = "Shadow"
# PoB's cluster subgraph of the author's Large cluster (unit 8): (id, linked)
CLUSTER = {
    6910: (65827, 65829), 33753: (65831, 65833), 65824: (32763, 65825, 65835), 65825: (65824, 65826),
    65826: (65825, 65827), 65827: (6910, 65826), 65829: (6910, 65830), 65830: (65829, 65831),
    65831: (33753, 65830), 65833: (33753, 65834), 65834: (65833, 65835), 65835: (65824, 65834),
}
RAW = "Rarity: Rare\nWrath Fall\nLarge Cluster Jewel\n"


def _edges():
    return [(node, other) for node, linked in CLUSTER.items() for other in linked]


def _case(graph: TreeGraph):
    start = graph.class_starts[START]
    path = graph.bfs_costs({start}, max_depth=80)[OUTER][1]
    spare = next(n for n in sorted(graph.neighbours(path[0])) if n not in path and n in graph.allocatable and graph.node(n).kind == "normal")
    inner = {65824, 65825, 65826, 65827, INNER_SOCKET}  # the entry, a path of the cluster to its inner socket
    allocated = {start, *path, *inner, spare}
    return start, tuple(path), spare, inner, allocated


def test_without_links_no_real_leaf_with_links_the_true_leaves() -> None:
    graph = TreeGraph.load()
    start, path, spare, inner, allocated = _case(graph)
    links = links_from_edges(_edges())

    old = [n for n in graph.removable_leaves(allocated) if n in graph.allocatable or graph.is_inner_socket(n)]
    assert spare not in old and path[-1] not in old  # the defect: the inner socket 6910 hangs off nothing the static graph knows
    new = [n for n in graph.removable_leaves(allocated, links=links) if n in graph.allocatable or graph.is_inner_socket(n)]
    assert spare in new  # a real tree leaf (name: the spare node hanging off the path)
    assert INNER_SOCKET in new  # the inner socket at the end of the cluster's inner path is a true leaf
    assert OUTER not in new  # the outer socket carries the cluster
    assert not set(path[:-1]) & set(new) - {spare}  # the trunk of the path is never a leaf


def test_the_outer_socket_is_never_a_leaf_while_inner_nodes_stay() -> None:
    graph = TreeGraph.load()
    start, path, spare, inner, allocated = _case(graph)
    links = links_from_edges(_edges())
    assert OUTER not in graph.removable_leaves(allocated, links=links)
    # take the inner nodes away: the socket is the tip of the path again
    bare = allocated - inner
    assert OUTER in graph.removable_leaves(bare, links=links)
    assert graph.cascade_if_removed(allocated, OUTER, links) == {OUTER, *inner}
    assert graph.cascade_if_removed(allocated, spare, links) == {spare}


def test_the_inner_nodes_are_no_roots_with_links() -> None:
    graph = TreeGraph.load()
    start, path, spare, inner, allocated = _case(graph)
    links = links_from_edges(_edges())
    assert graph.roots(allocated, links) == {start} | (set() if graph.neighbours(start) & allocated else set())
    assert graph.is_connected(allocated, links)
    assert not graph.is_connected(allocated - {OUTER}, links)  # the cluster hangs off the outer socket


def test_keeps_connected_agrees() -> None:
    graph = TreeGraph.load()
    start, path, spare, inner, allocated = _case(graph)
    links = links_from_edges(_edges())
    protected = {INNER_SOCKET}
    assert not graph.keeps_connected(allocated, [spare], protected)  # the defect: 6910 looks cut off
    assert graph.keeps_connected(allocated, [spare], protected, links)
    assert not graph.keeps_connected(allocated, [OUTER], protected, links)  # the socket carries the protected inner socket
    assert not graph.keeps_connected(allocated, [path[3]], protected, links)  # so does the path to it
    assert not graph.keeps_connected(allocated, [INNER_SOCKET], protected, links)


def test_no_cluster_nothing_changes() -> None:
    graph = TreeGraph.load()
    start = graph.class_starts[START]
    path = graph.bfs_costs({start}, max_depth=80)[OUTER][1]
    spare = next(n for n in sorted(graph.neighbours(path[0])) if n not in path and n in graph.allocatable)
    allocated = {start, *path, spare}
    plain = graph.removable_leaves(allocated)
    assert plain and spare in plain and OUTER in plain
    for none in (None, {}, links_from_edges([])):
        assert graph.removable_leaves(allocated, links=none) == plain
        assert graph.roots(allocated, none) == graph.roots(allocated)
        assert graph.is_connected(allocated, none) is graph.is_connected(allocated) is True
        assert graph.cascade_if_removed(allocated, path[3], none) == graph.cascade_if_removed(allocated, path[3])
        assert graph.keeps_connected(allocated, [spare], {OUTER}, none) is graph.keeps_connected(allocated, [spare], {OUTER}) is True
    assert not graph.keeps_connected(allocated, [path[3]], {OUTER}, None)


class _Pob:
    """The reads the probe makes; counts the cluster_graph calls."""

    def __init__(self, jewels: dict[int, str], allocated: set[int], start: int) -> None:
        self.jewels, self.allocated, self.start = jewels, allocated, start
        self.graph_calls: list[int] = []

    def socketed_jewels(self) -> dict[int, str]:
        return dict(self.jewels)

    def tree_light(self) -> dict:
        return {"user_allocated_node_ids": sorted(self.allocated), "class_id": "Shadow"}

    def cluster_graph(self, socket: int) -> list[dict]:
        self.graph_calls.append(socket)
        return [{"id": n, "kind": "small", "name": "", "linked": list(linked)} for n, linked in CLUSTER.items()] if socket == OUTER else []


def test_the_probe_reads_one_cluster_graph_per_cluster_and_none_without() -> None:
    graph = TreeGraph.load()
    start, path, spare, inner, allocated = _case(graph)
    pob = _Pob({OUTER: RAW, 12345: "Rarity: Rare\nHate Shard\nCobalt Jewel\n"}, allocated - {start}, start)
    pob.start = start
    probe = PobJewelProbe(pob, lambda: None, graph, points=100)
    leaves = probe.removable_leaves()
    assert pob.graph_calls == [OUTER]  # one read for the one cluster; the plain jewel is no cluster
    assert spare in leaves and INNER_SOCKET in leaves and OUTER not in leaves
    assert all(n < 65536 for n in leaves)  # no inner node is offered

    plain = _Pob({12345: "Rarity: Rare\nHate Shard\nCobalt Jewel\n"}, {*path, spare}, start)
    PobJewelProbe(plain, lambda: None, graph, points=100).removable_leaves()
    assert plain.graph_calls == []  # no cluster, no extra read
    assert cluster_links_of(plain, []) is None
