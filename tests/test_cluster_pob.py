"""#433 unit 3: a cluster jewel in an allocated tree socket, through `PobSession` and `PobJewelProbe`, counted by PoB.

Build: the Zizaran Trickster "blight of contagion" fixture; its author's Large Cluster L10 (10 passives) sits in
socket 32763 and is replaced by a generated Large-12 with the same enchant and notables (`CLUSTER`).

Row 2: `read_state` holds the cluster in `cluster_jewel_items`; `cluster_graph(32763)` is the subgraph PoB built
(12 inner nodes, read from PoB, every node linked); allocating the entry-to-both-notables path moves `CombinedDPS`;
`export_xml` -> `load_xml` round-trips `CombinedDPS` / `Life` / `TotalEHP` to the digit.
Row 3: `snapshot` / `put_jewel` + `allocate` / `restore` bring `CombinedDPS` / `Life` / `TotalEHP` back to the digit;
a second `put_jewel` on the socket replaces, never stacks.
Plus `set_tree(jewels={socket: cluster})`: the cluster is applied before the nodes, so its inner node ids resolve.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from junkroan.optimizer.jewel_probe import ClusterNode, PobJewelProbe
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph
from junkroan.pob.session import PobSession, decode_import_code, is_cluster_jewel_raw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "zizaran_326" / "early" / "trickster_blight_of_contagion.pob.txt"
LOCK = json.loads((PROJECT_ROOT / "locks" / "pob.lock.json").read_text(encoding="utf-8"))
RUNTIME_ROOT = PROJECT_ROOT / "var" / "cache" / "pob" / LOCK["tag"] / LOCK["extract_subdir"]

SOCKET = 32763
KEYS = ("CombinedDPS", "Life", "TotalEHP")
CLUSTER = "\n".join([
    "Rarity: RARE",
    "Day-1 Large Cluster",
    "Large Cluster Jewel",
    "Item Level: 72",
    "Cluster Jewel Skill: affliction_chaos_damage",
    "Cluster Jewel Node Count: 12",
    "Implicits: 3",
    "{crafted}Adds 12 Passive Skills",
    "{crafted}2 Added Passive Skills are Jewel Sockets",
    "{crafted}Added Small Passive Skills grant: 12% increased Chaos Damage",
    "1 Added Passive Skill is Unwaveringly Evil",
    "1 Added Passive Skill is Wicked Pall",
])
PLAIN = "\n".join(["Rarity: RARE", "Doom Eye", "Crimson Jewel", "Item Level: 84", "Implicits: 0", "8% increased maximum Life"])

_RUNTIME_MISSING = pytest.mark.skipif(
    not (RUNTIME_ROOT / "lua51.dll").is_file(),
    reason=f"pinned PoB runtime not present at {RUNTIME_ROOT}",
)


def needs_pob(test):
    """The `pob` mark plus the skip when the pinned runtime is absent."""

    return pytest.mark.pob(_RUNTIME_MISSING(test))


def _fixture_xml_with_generated_cluster() -> str:
    xml = decode_import_code(FIXTURE.read_text(encoding="utf-8").strip())
    item = re.search(r'<Item id="14">.*?</Item>', xml, re.S)
    assert item and "Large Cluster Jewel" in item.group(0)
    return xml.replace(item.group(0), '<Item id="14">\n' + CLUSTER + "\n</Item>")


@pytest.fixture()
def pob():
    with PobSession(run_id="test-cluster-pob", artifacts_root=PROJECT_ROOT / "artifacts" / "test-runs") as session:
        session.load_xml(_fixture_xml_with_generated_cluster())
        yield session


def _stats(pob: PobSession) -> dict[str, float]:
    return {k: pob.stats(KEYS)[k] for k in KEYS}


def _probe(pob: PobSession) -> PobJewelProbe:
    objective = Objective(maximize="CombinedDPS")
    return PobJewelProbe(pob, lambda: objective, TreeGraph.load(), points=999)


def _path_to_both_notables(graph: list[ClusterNode]) -> list[int]:
    """Entry -> ... -> both notables along the ring PoB linked (read from `linked`, the shortest way through inner nodes)."""

    by_id = {n.id: n for n in graph}
    entry = next(n for n in graph if n.kind == "entry")
    notables = {n.id for n in graph if n.kind == "notable"}
    best: list[int] | None = None
    for first in sorted(notables):
        # shortest entry -> first notable -> other notable by BFS over inner links
        legs: list[int] = []
        here = entry.id
        for target in (first, next(iter(notables - {first}))):
            prev = {here: None}
            queue = [here]
            while queue and target not in prev:
                cur = queue.pop(0)
                for nxt in by_id[cur].linked:
                    if nxt in by_id and nxt not in prev:
                        prev[nxt] = cur
                        queue.append(nxt)
            walk = []
            cur = target
            while cur is not None and cur != here:
                walk.append(cur)
                cur = prev[cur]
            legs += walk[::-1]
            here = target
        if best is None or len(set(legs)) < len(set(best)):
            best = legs
    assert best is not None
    return [entry.id] + [n for n in dict.fromkeys(best) if n != entry.id]


@needs_pob
def test_row2_cluster_graph_is_read_from_pob_and_moves_the_build(pob: PobSession) -> None:
    state = pob.read_state()["tree_state"]
    held = state.get("cluster_jewel_items") or []
    assert [e["node_id"] for e in held] == [SOCKET], held
    dumped = json.dumps(held[0])
    assert "Unwaveringly Evil" in dumped and "Wicked Pall" in dumped, dumped
    assert "Cluster Jewel Node Count: 12" in pob.socketed_jewels()[SOCKET]

    probe = _probe(pob)
    graph = probe.cluster_graph(SOCKET)
    kinds = sorted(n.kind for n in graph)
    print("\nrow 2 cluster_graph:", [(n.id, n.kind, n.name, n.linked) for n in graph])
    print("row 2 kinds:", {k: kinds.count(k) for k in sorted(set(kinds))})
    assert len(graph) == 12, kinds
    assert kinds.count("notable") == 2 and kinds.count("socket") == 2, kinds
    assert kinds.count("entry") == 1 and kinds.count("small") == 7, kinds  # the entry node (index 0) is one of the 12 and is a small
    assert all(n.linked for n in graph), [n for n in graph if not n.linked]
    assert {n.name for n in graph if n.kind == "notable"} == {"Unwaveringly Evil", "Wicked Pall"}

    without = None
    pob.remove_jewel(SOCKET)
    assert probe.cluster_graph(SOCKET) == []
    without = _stats(pob)
    probe.put_jewel(SOCKET, CLUSTER)
    path = _path_to_both_notables(probe.cluster_graph(SOCKET))
    probe.allocate(path)
    with_cluster = _stats(pob)
    print(f"row 2 path {path}: CombinedDPS {without['CombinedDPS']} -> {with_cluster['CombinedDPS']}  Life {without['Life']} -> {with_cluster['Life']}")
    assert with_cluster["CombinedDPS"] != without["CombinedDPS"], f"CombinedDPS unchanged: without {without['CombinedDPS']} with {with_cluster['CombinedDPS']}"

    xml = pob.export_xml()
    pob.load_xml(xml)
    again = _stats(pob)
    print(f"row 2 round trip: {with_cluster} -> {again}")
    assert again == with_cluster


@needs_pob
def test_row3_snapshot_put_allocate_restore_is_exact_and_a_second_put_replaces(pob: PobSession) -> None:
    probe = _probe(pob)
    pob.remove_jewel(SOCKET)
    base = _stats(pob)
    snap = probe.snapshot()
    probe.put_jewel(SOCKET, CLUSTER)
    probe.allocate(_path_to_both_notables(probe.cluster_graph(SOCKET)))
    moved = _stats(pob)
    assert moved != base
    probe.restore(snap)
    back = _stats(pob)
    print(f"\nrow 3 base {base}\nrow 3 moved {moved}\nrow 3 restored {back}  (fast {probe.restore_fast}, fallback {probe.restore_fallback})")
    assert back == base
    assert probe.cluster_graph(SOCKET) == []

    probe.put_jewel(SOCKET, CLUSTER)
    probe.put_jewel(SOCKET, CLUSTER.replace("Node Count: 12", "Node Count: 10").replace("Adds 12", "Adds 10"))
    items = pob.read_state()["tree_state"]["cluster_jewel_items"]
    assert [e["node_id"] for e in items] == [SOCKET], items
    assert len(probe.cluster_graph(SOCKET)) == 10
    probe.remove_jewel(SOCKET)
    assert probe.cluster_graph(SOCKET) == [] and _stats(pob) == base


@needs_pob
def test_set_tree_routes_a_cluster_raw_and_resolves_its_inner_nodes(pob: PobSession) -> None:
    probe = _probe(pob)
    path = _path_to_both_notables(probe.cluster_graph(SOCKET))
    probe.allocate(path)
    expected = _stats(pob)
    state = pob.read_state()["tree_state"]
    inner = {n.id for n in probe.cluster_graph(SOCKET)}
    nodes = state["user_allocated_node_ids"]
    assert set(path) <= {int(n) for n in nodes}, "the readback lists the allocated inner nodes"
    tree = dict(
        class_id=state["class_id"],
        ascendancy_id=state["ascendancy_id"],
        nodes=nodes,
        ascendancy_nodes=state["allocated_ascendancy_node_ids"],
        keystones=state["keystone_node_ids"],
        masteries=state["mastery_effect_ids"],
    )
    allocated = {int(n) for n in nodes}
    # the cluster jewel and the plain jewels of the allocated sockets (`set_tree` allocates every socket it is given a jewel for)
    jewels = {socket: raw for socket, raw in pob.socketed_jewels().items() if socket in allocated}
    assert is_cluster_jewel_raw(jewels[SOCKET]) and any(not is_cluster_jewel_raw(raw) for raw in jewels.values())
    pob.set_tree(**tree, jewels=jewels)
    assert {s: r for s, r in pob.socketed_jewels().items() if s in allocated} == jewels
    assert {n.id for n in probe.cluster_graph(SOCKET)} == inner
    again = _stats(pob)
    print(f"\nset_tree with {len(jewels)} jewels: {expected} -> {again}")
    assert again == expected
    assert [e["node_id"] for e in pob.read_state()["tree_state"]["cluster_jewel_items"]] == [SOCKET]
    assert set(path) <= {int(n) for n in pob.read_state()["tree_state"]["user_allocated_node_ids"]}


def test_is_cluster_jewel_raw_tells_the_cluster_base_from_a_plain_jewel() -> None:
    assert is_cluster_jewel_raw(CLUSTER) and not is_cluster_jewel_raw(PLAIN)
    assert is_cluster_jewel_raw(CLUSTER.replace("Large", "Medium", 2))
