"""Pure-Python passive tree graph over the canonical PoB tree corpus.

No PoB process needed. Used by the optimizer to enumerate candidates (what can
be reached from the current allocation and at what point cost) so PoB is only
asked to *evaluate* candidates, never to *find* them.

    graph = TreeGraph.load()
    costs = graph.bfs_costs(allocated, max_depth=6)      # node -> (cost, path)
    for cand in graph.candidates(allocated, max_depth=6): ...
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Collection, Iterable, Mapping, Sequence

from junkroan.pob.tree_payload_normalization import canonical_active_tree_corpus

CORPUS_ROOT = Path(__file__).resolve().parents[1] / "pob" / "corpus_data"
CLASS_NAMES_BY_INDEX = ("Scion", "Marauder", "Ranger", "Witch", "Duelist", "Templar", "Shadow")  # PoB class ids


Links = Mapping[int, frozenset[int]]  # extra undirected edges the static graph lacks (`links_from_edges`)


@dataclass(frozen=True, slots=True)
class TreeNode:
    node_id: int
    name: str
    kind: str  # "normal" | "notable" | "keystone" | "mastery" | "jewel" | "class_start" | "ascendancy"
    stats: tuple[str, ...]
    ascendancy_name: str | None
    class_start_index: int | None
    mastery_effects: tuple[tuple[int, tuple[str, ...]], ...] = ()  # (effect_id, stats)
    expansion_size: int | None = None  # cluster socket size 0 Small / 1 Medium / 2 Large; None for any other node
    expansion_parent: int | None = None  # outer cluster socket this inner socket belongs to; PoB has it only once that cluster is socketed

    @property
    def is_payoff(self) -> bool:
        return self.kind in {"notable", "keystone", "mastery"}


def cluster_socket_size(node: TreeNode) -> int | None:
    """Cluster socket size (2 Large, 1 Medium, 0 Small); None for a plain jewel socket or any other node.

    Size 2 takes Large or Medium cluster jewels, size 1 Medium only, None none.
    """
    return node.expansion_size


@dataclass(frozen=True, slots=True)
class Candidate:
    node_id: int
    cost: int  # points needed including the node itself
    path: tuple[int, ...]  # unallocated nodes to allocate, target last
    kind: str
    name: str


@dataclass
class TreeGraph:
    tree_version: str
    nodes: dict[int, TreeNode]
    adjacency: dict[int, frozenset[int]]
    allocatable: frozenset[int]  # user-allocatable, non-ascendancy, non-start
    class_starts: dict[str, int] = field(default_factory=dict)  # class name -> start node id

    # -- construction --------------------------------------------------------

    @classmethod
    @lru_cache(maxsize=1)
    def load(cls) -> "TreeGraph":
        corpus = canonical_active_tree_corpus()
        records = _load_records("passives.json") + _load_records("keystones.json") + _load_records("masteries.json")
        ascendancy_ids = set(corpus["ascendancy_node_ids"])
        start_proxy_ids = set(corpus["start_root_proxy_node_ids"])
        mastery_ids = set(corpus["mastery_node_ids"])

        nodes: dict[int, TreeNode] = {}
        class_starts: dict[str, int] = {}
        for rec in records:
            node_id = int(rec["node_id"])
            if node_id in nodes:
                continue
            if rec.get("class_start_index") is not None:
                kind = "class_start"
                index = int(rec["class_start_index"])
                class_name = CLASS_NAMES_BY_INDEX[index] if 0 <= index < len(CLASS_NAMES_BY_INDEX) else str(rec["name"]).title()
                class_starts[class_name] = node_id
            elif node_id in ascendancy_ids or rec.get("ascendancy_name"):
                kind = "ascendancy"
            elif rec.get("is_keystone"):
                kind = "keystone"
            elif rec.get("is_mastery") or node_id in mastery_ids:
                kind = "mastery"
            elif rec.get("is_notable"):
                kind = "notable"
            elif "Jewel" in str(rec.get("name", "")) and not rec.get("stats"):
                kind = "jewel"
            else:
                kind = "normal"
            effects = tuple(
                (int(e["effect_id"]), tuple(str(s) for s in e.get("stats", [])))
                for e in rec.get("mastery_effects", [])
                if isinstance(e, dict) and "effect_id" in e
            )
            nodes[node_id] = TreeNode(
                node_id=node_id,
                name=str(rec.get("name") or ""),
                kind=kind,
                stats=tuple(str(s) for s in rec.get("stats", [])),
                ascendancy_name=rec.get("ascendancy_name"),
                class_start_index=rec.get("class_start_index"),
                mastery_effects=effects,
                expansion_size=rec.get("expansion_size"),
                expansion_parent=rec.get("expansion_parent"),
            )

        adjacency: dict[int, set[int]] = {}
        for key, neighbours in corpus["adjacency"].items():
            a = int(key)
            for b in neighbours:
                b = int(b)
                adjacency.setdefault(a, set()).add(b)
                adjacency.setdefault(b, set()).add(a)

        # A mastery is allocated through any notable of its cluster but is not a path: it expands
        # to nothing, while the notables keep the edge to it (so it stays allocatable from them).
        for m in mastery_ids:
            adjacency[int(m)] = set()

        # The corpus's active_allocatable list omits masteries and keystones; both are
        # user-allocatable in PoB, so add them back (still excluding ascendancy/start nodes).
        keystone_ids = {node_id for node_id, node in nodes.items() if node.kind == "keystone"}
        allocatable = frozenset(
            int(n)
            for n in (*corpus["active_allocatable_node_ids"], *corpus["mastery_node_ids"], *keystone_ids)
            if int(n) not in ascendancy_ids
            and int(n) not in start_proxy_ids
            and int(n) in adjacency
            # PoB keeps an inner cluster socket only after its cluster is socketed in the parent.
            and not (int(n) in nodes and nodes[int(n)].expansion_parent is not None)
        )
        return cls(
            tree_version=str(corpus["canonical_tree_version"]),
            nodes=nodes,
            adjacency={k: frozenset(v) for k, v in adjacency.items()},
            allocatable=allocatable,
            class_starts=class_starts,
        )

    # -- queries -------------------------------------------------------------

    def node(self, node_id: int) -> TreeNode | None:
        return self.nodes.get(int(node_id))

    def neighbours(self, node_id: int) -> frozenset[int]:
        return self.adjacency.get(int(node_id), frozenset())

    def frontier(self, allocated: Iterable[int]) -> set[int]:
        """Unallocated allocatable nodes adjacent to the allocated set."""

        allocated_set = {int(n) for n in allocated}
        out: set[int] = set()
        for node_id in allocated_set:
            for nb in self.neighbours(node_id):
                if nb not in allocated_set and nb in self.allocatable:
                    out.add(nb)
        return out

    def bfs_costs(self, allocated: Iterable[int], *, max_depth: int = 6) -> dict[int, tuple[int, tuple[int, ...]]]:
        """Shortest path (in points) from the allocated set to every reachable
        allocatable node within max_depth, walking only through unallocated
        allocatable nodes. Returns node -> (cost, path) with path ending at node.
        """

        allocated_set = {int(n) for n in allocated}
        result: dict[int, tuple[int, tuple[int, ...]]] = {}
        queue: deque[tuple[int, tuple[int, ...]]] = deque()
        seen: set[int] = set(allocated_set)
        for node_id in allocated_set:
            for nb in self.neighbours(node_id):
                if nb not in seen and nb in self.allocatable:
                    seen.add(nb)
                    queue.append((nb, (nb,)))
        while queue:
            node_id, path = queue.popleft()
            result[node_id] = (len(path), path)
            if len(path) >= max_depth:
                continue
            for nb in self.neighbours(node_id):
                if nb not in seen and nb in self.allocatable:
                    seen.add(nb)
                    queue.append((nb, path + (nb,)))
        return result

    def candidates(
        self,
        allocated: Iterable[int],
        *,
        max_depth: int = 6,
        include_normal_beyond_frontier: bool = False,
        payoff_ids: Collection[int] = (),
    ) -> list[Candidate]:
        """Candidate allocations: every frontier node (cost 1) plus payoff nodes
        (notable / keystone / mastery) reachable within max_depth, plus the nodes in `payoff_ids`
        (ordinary nodes whose text pays only once allocated, e.g. "Gain 1 Rage on Melee Hit")."""

        out: list[Candidate] = []
        for node_id, (cost, path) in self.bfs_costs(allocated, max_depth=max_depth).items():
            node = self.nodes.get(node_id)
            kind = node.kind if node else "normal"
            name = node.name if node else str(node_id)
            if cost == 1 or kind in {"notable", "keystone", "mastery"} or include_normal_beyond_frontier or node_id in payoff_ids:
                out.append(Candidate(node_id=node_id, cost=cost, path=path, kind=kind, name=name))
        out.sort(key=lambda c: (c.cost, c.node_id))
        return out

    def removable_leaves(
        self, allocated: Iterable[int], *, protected: Iterable[int] = (), links: Links | None = None
    ) -> list[int]:
        """Allocated nodes whose removal keeps every other allocated node connected
        to the class start (i.e. leaves of the allocated subgraph). `links`: the extra edges of
        socketed cluster jewels (`links_from_edges`, #433); none = the static graph alone."""

        allocated_set = {int(n) for n in allocated}
        protected_set = {int(n) for n in protected}
        roots = self.roots(allocated_set, links=links)
        if not roots:
            return []
        leaves: list[int] = []
        for node_id in allocated_set:
            if node_id in protected_set or node_id in roots:
                continue
            remaining = allocated_set - {node_id}
            if self._connected_from(roots, remaining, links) == remaining:
                leaves.append(node_id)
        return sorted(leaves)

    def keeps_connected(
        self, allocated: Iterable[int], remove: Iterable[int], protected: Iterable[int], links: Links | None = None
    ) -> bool:
        """Whether removing `remove` leaves every allocated protected node allocated and still
        connected to the class start (#510: a forced node and the path to it survive every move)."""

        allocated_set = {int(n) for n in allocated}
        keep = {int(n) for n in protected} & allocated_set
        if not keep:
            return True
        gone = {int(n) for n in remove}
        if keep & gone:
            return False
        roots = self.roots(allocated_set, links=links)
        if not roots:
            return True
        return keep <= self._connected_from(roots, allocated_set - gone, links)

    def mastery_effect_holders(self, effect_id: int) -> list[int]:
        """Mastery nodes that offer the effect, ascending."""

        return sorted(n.node_id for n in self.nodes.values() if any(e == int(effect_id) for e, _ in n.mastery_effects))

    def resolve_forced(self, ids: Iterable[int], *, class_name: str | None = None) -> tuple[list[int], dict[int, int]]:
        """Split the request's forced ids (#510) into (passive node ids, {mastery node: effect id}).

        An id that is a tree node is that node (a mastery node needs its effect, so a bare mastery
        node id raises); any other id must be a mastery effect id, and its mastery node is the
        holder cheapest to reach from the class start (ties: the lowest node id). A mastery effect
        id equal to some node's id reads as that node: the id space is shared (16 of 353 collide)."""

        plain: list[int] = []
        masteries: dict[int, int] = {}
        costs: dict[int, tuple[int, tuple[int, ...]]] | None = None
        for raw in ids:
            i = int(raw)
            node = self.nodes.get(i)
            if node is not None:
                if node.kind == "mastery":
                    raise ValueError(f"forced id {i} is a mastery node ({node.name}); name its effect id instead")
                if i not in plain:
                    plain.append(i)
                continue
            holders = self.mastery_effect_holders(i)
            if not holders:
                raise ValueError(f"forced id {i} is neither a passive node nor a mastery effect")
            if costs is None:
                start = self.class_starts.get(class_name or "")
                costs = self.bfs_costs({start}, max_depth=80) if start is not None else {}
            holder = min(holders, key=lambda h: (costs[h][0] if h in costs else 10**6, h))
            masteries[holder] = i
        return plain, masteries

    def protected_nodes(self, forced_ids: Iterable[int], selected_effects: Mapping[int, int] | None = None) -> frozenset[int]:
        """Node ids the forced ids pin: each tree node by its id, each forced mastery effect by the
        allocated mastery node (`selected_effects`: node -> effect) that carries it."""

        forced = {int(n) for n in forced_ids}
        out = {i for i in forced if i in self.nodes}
        for node_id, effect in (selected_effects or {}).items():
            if int(effect) in forced and int(effect) not in self.nodes:
                out.add(int(node_id))
        return frozenset(out)

    def cascade_if_removed(self, allocated: Iterable[int], node_id: int, links: Links | None = None) -> set[int]:
        """Allocated nodes that would be disconnected (and thus dropped by PoB) if node_id is removed."""

        allocated_set = {int(n) for n in allocated}
        roots = self.roots(allocated_set, links=links)
        remaining = allocated_set - {int(node_id)}
        return remaining - self._connected_from(roots, remaining, links) | {int(node_id)}

    def is_connected(self, allocated: Iterable[int], links: Links | None = None) -> bool:
        """Does every allocated node still hang off a root? The corridor exchange builds its
        final set itself (PoB's fast what-if does not cascade), so connectivity is ours to prove
        before the mutation is handed to PoB."""

        allocated_set = {int(n) for n in allocated}
        roots = self.roots(allocated_set, links=links)
        if not roots:
            return not allocated_set
        return self._connected_from(roots, allocated_set, links) == allocated_set

    def bypass_paths(
        self,
        source: int,
        target: int,
        *,
        allowed: Iterable[int],
        max_inner: int,
        limit: int,
        max_expansions: int = 20_000,
    ) -> list[tuple[int, ...]]:
        """Up to `limit` shortest simple paths from `source` to `target` whose inner nodes all lie
        in `allowed` and number at most `max_inner`; each result is the inner nodes only, in walk
        order, shortest first.

        Used by the corridor exchange to propose another way between two key nodes. The walk is a
        BFS over paths (so the order is by length) pruned by the distance to the target through the
        same `allowed` set, which is what keeps it linear in the paths returned instead of
        exponential in the branching factor; `max_expansions` is the last-resort guard.
        """

        source, target = int(source), int(target)
        allowed_set = {int(n) for n in allowed} - {source, target}
        if max_inner < 0 or limit <= 0:
            return []
        # distance from every allowed node back to the target, so a partial path that can no longer
        # reach the target inside the budget is never extended
        distance: dict[int, int] = {target: 0}
        queue: deque[int] = deque([target])
        while queue:
            node_id = queue.popleft()
            if distance[node_id] > max_inner:
                continue
            for nb in sorted(self.neighbours(node_id)):
                if nb in allowed_set and nb not in distance:
                    distance[nb] = distance[node_id] + 1
                    queue.append(nb)

        out: list[tuple[int, ...]] = []
        seen: set[tuple[int, ...]] = set()
        paths: deque[tuple[int, tuple[int, ...]]] = deque([(source, ())])
        expansions = 0
        while paths and len(out) < limit and expansions < max_expansions:
            node_id, inner = paths.popleft()
            expansions += 1
            remaining = max_inner - len(inner)
            for nb in sorted(self.neighbours(node_id)):
                if nb == target:
                    if inner not in seen:
                        seen.add(inner)
                        out.append(inner)
                        if len(out) >= limit:
                            break
                    continue
                if nb not in allowed_set or nb in inner or remaining <= 0:
                    continue
                if distance.get(nb, max_inner + 1) > remaining:
                    continue  # cannot reach the target from here inside the point budget
                paths.append((nb, inner + (nb,)))
        return out

    def is_inner_socket(self, node_id: int) -> bool:
        """A socket inside a cluster's template: not allocatable by itself, but it can be held once its cluster is socketed."""

        node = self.nodes.get(int(node_id))
        return node is not None and node.expansion_parent is not None

    def roots(self, allocated: Iterable[int], links: Links | None = None) -> set[int]:
        """Connectivity anchors: allocated non-allocatable nodes (class start, ascendancy)
        plus, only when no class start is allocated (PoB state readbacks may omit it), any class
        start adjacent to the allocation. PoB connects a tree from its own class start alone: with
        the own start allocated, another class's start next to the tree is no anchor (#1147: the
        Witch start made a Templar trunk node look like a leaf, and its removal cascaded 92 nodes).
        A node the `links` carry (a cluster jewel's inner node, unknown to the static graph) is
        no anchor: it hangs off its outer socket."""

        allocated_set = {int(n) for n in allocated}
        roots = {n for n in allocated_set if n not in self.allocatable and not (links and n in links) and not self.is_inner_socket(n)}
        if roots & set(self.class_starts.values()):
            return roots
        for start in self.class_starts.values():
            if self.neighbours(start) & allocated_set:
                roots.add(start)
        return roots

    def _connected_from(self, roots: set[int], allowed: set[int], links: Links | None = None) -> set[int]:
        seen: set[int] = set()
        queue = deque(roots)
        seen.update(queue)
        while queue:
            node_id = queue.popleft()
            neighbours = self.neighbours(node_id)
            if links and node_id in links:
                neighbours = neighbours | links[node_id]
            for nb in neighbours:
                if nb in allowed and nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return seen & allowed


def links_from_edges(edges: Iterable[tuple[int, int]]) -> Links:
    """An undirected adjacency of extra edges (a cluster jewel's subgraph, read from PoB) to hand to the
    connectivity methods; each edge is entered both ways. No edges = no links."""

    out: dict[int, set[int]] = {}
    for a, b in edges:
        out.setdefault(int(a), set()).add(int(b))
        out.setdefault(int(b), set()).add(int(a))
    return {node: frozenset(nbs) for node, nbs in out.items()}


def _load_records(file_name: str) -> list[Mapping]:
    payload = json.loads((CORPUS_ROOT / file_name).read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    return [r for r in (records or []) if isinstance(r, Mapping)]


@lru_cache(maxsize=1)
def ascendancy_node_owners() -> dict[int, tuple[str, str, str, bool]]:
    """Every node of `ascendancies.json` (the static `TreeGraph` holds none): node id -> (ascendancy id, display name,
    node name, is the ascendancy start). #1147: a forced ascendancy node is told from a passive node by this map."""

    out: dict[int, tuple[str, str, str, bool]] = {}
    for rec in _load_records("ascendancies.json"):
        for node in rec.get("nodes") or ():
            out[int(node["node_id"])] = (str(rec["ascendancy_id"]), str(rec.get("display_name") or rec["ascendancy_id"]),
                                         str(node.get("name") or ""), bool(node.get("is_ascendancy_start")))
    return out


def parse_allocated_from_xml(xml_text: str) -> list[int]:
    """Node ids allocated in a PoB build XML (active spec), ascendancy nodes included."""

    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml_text)
    tree = root.find("Tree")
    if tree is None:
        return []
    active = int(tree.get("activeSpec") or 1)
    specs = tree.findall("Spec")
    spec = specs[active - 1] if 0 < active <= len(specs) else (specs[0] if specs else None)
    if spec is None:
        return []
    return [int(n) for n in (spec.get("nodes") or "").split(",") if n.strip()]


__all__ = ["TreeGraph", "TreeNode", "Candidate", "parse_allocated_from_xml"]
