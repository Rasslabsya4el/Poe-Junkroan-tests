"""The jewel step's `JewelProbe` over a `PobSession` (#434 unit 4).

`jewel_step.run_jewel_step` drives the build only through the probe; this one answers every question with PoB:

- `score()` is the build's objective, one full PoB calc (a line is never measured by a fast path). PoB's `Score`
  is ordered `(value > 0, neg_violation, value)`; the step compares plain numbers, so the order is mapped
  monotonically onto one float (`scalar`): a live feasible build scores its value, a live infeasible one
  `-1 - violation`, a dead one (value <= 0) `DEAD_SCORE - violation` (#533).
- `sockets()` are the jewel sockets (`TreeNode.kind == "jewel"`) the tree search reaches within `max_depth` that
  hold no jewel, each with the path `TreeGraph` walks to it (cost = the nodes it adds); a path through a node the
  tree optimizer excludes (forbidden keystones, forbidden text) is not offered.
- `snapshot()` / `restore()` bring back the tree, the mastery selections and the socketed jewels; the XML is
  exported at the snapshot and loaded only when the inverse mutation did not give the same tree back.
- `removable_leaves()` are the allocated, non-ascendancy leaves whose removal keeps the tree connected
  (`TreeGraph.removable_leaves`, what `TreeOptimizer.refine` uses); `leaf_scores()` measures each removal as one
  batch of PoB trials, the build restored by PoB after each.
- `put_jewel()` takes a cluster jewel too (a raw string or anything with `.raw(item_level)`): PoB builds its
  subgraph and a second put on the socket replaces it; `cluster_graph()` reads that subgraph from PoB (#433).
- `points_over()` is the allocated points beyond the build's passive points.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from junkroan.optimizer.jewel_lines import JewelLine, rare_jewel_raw
from junkroan.optimizer.jewel_step import SocketOption
from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.tree_graph import Links, TreeGraph, links_from_edges
from junkroan.pob.session import PobSession, is_cluster_jewel_raw

LEAF_MEASURE_MODE = "full"  # a leaf's removal is measured by PoB's full calc as well; "fast" is the tree search's trial mode
NO_SCORE = -1e18  # a trial PoB refused: never the least-loss leaf
DEAD_SCORE = -1e9  # a dead build (value <= 0) ranks under every live one, D88 amd 1 / #533; above NO_SCORE


@dataclass(frozen=True)
class ClusterNode:
    """One node of the subgraph PoB built for a cluster jewel, as PoB reports it."""

    id: int
    kind: str  # "entry" (linked to the socket) | "small" | "notable" | "socket" (| "keystone")
    name: str
    linked: tuple[int, ...]


def scalar(score: Score) -> float:
    """`Score` as one float monotone in its key `(value > 0, neg_violation, value)` (D88 amd 1, #533):

    - live (value > 0) and feasible: `value` (> 0);
    - live and infeasible: `-1 - violation` (under every feasible live build, a smaller violation higher);
    - dead (value <= 0), feasible or not: `DEAD_SCORE - violation`, under every live build, above `NO_SCORE`.
    """

    if score.value <= 0.0:
        return DEAD_SCORE - score.violation
    return score.value if score.feasible else -1.0 - score.violation


def _effects(state: dict) -> dict[int, int]:
    out: dict[int, int] = {}
    for entry in state.get("mastery_effect_ids") or []:
        node, _, effect = str(entry).partition(":")
        if node.isdigit() and effect.isdigit():
            out[int(node)] = int(effect)
    return out


def _clusters(jewels: dict[int, str]) -> dict[int, str]:
    return {socket: raw for socket, raw in jewels.items() if is_cluster_jewel_raw(raw)}


def cluster_links_of(pob: PobSession, sockets: Iterable[int]) -> Links | None:
    """The extra edges of the cluster jewels in `sockets`: every `linked` field of PoB's subgraph for each (the entry's
    link to its outer socket included), one `cluster_graph` read per socket; None for no socket or no edge."""

    sockets = list(sockets)
    if not sockets:
        return None
    edges = [(int(n["id"]), int(other)) for socket in sockets for n in pob.cluster_graph(socket) for other in n.get("linked") or ()]
    return links_from_edges(edges) or None


class PobJewelProbe:
    def __init__(
        self,
        pob: PobSession,
        objective: Callable[[], Objective],
        graph: TreeGraph,
        *,
        points: int,
        max_depth: int = 6,
        excluded: Callable[[], Iterable[int]] = lambda: (),
        protected: Iterable[int] = (),
        item_level: int = 72,
    ) -> None:
        self.pob = pob
        self._objective = objective
        self.graph = graph
        self.points = int(points)
        self.max_depth = int(max_depth)
        self._excluded = excluded
        self.protected = frozenset(int(n) for n in protected)
        self.item_level = int(item_level)  # a cluster candidate is written at this item level (the lane's)
        self.restore_fast = 0
        self.restore_fallback = 0

    # -- the build ------------------------------------------------------------------------------------------

    def score(self) -> float:
        objective = self._objective()
        return scalar(objective.score(self.pob.stats(objective.stat_keys)))

    def _tree(self) -> dict:
        return dict(self.pob.tree_light())

    def allocated(self) -> set[int]:
        """Every allocated node id with the class start (the graph needs it as a root, PoB's readback omits it)."""

        state = self._tree()
        nodes = {int(n) for n in state.get("user_allocated_node_ids") or ()}
        start = self.graph.class_starts.get(str(state.get("class_id") or ""))
        if start is not None:
            nodes.add(start)
        return nodes

    def snapshot(self) -> dict[str, Any]:
        return {"xml": self.pob.export_xml(), "tree": self._tree(), "jewels": dict(self.pob.socketed_jewels())}

    def restore(self, snap: dict[str, Any]) -> None:
        if self._undo(snap):
            self.restore_fast += 1
        else:
            self.restore_fallback += 1
            self.pob.load_xml(snap["xml"])

    def _undo(self, snap: dict[str, Any]) -> bool:
        held = self.pob.socketed_jewels()
        if _clusters(held) != _clusters(snap["jewels"]):
            return False  # a cluster jewel's inner nodes exist only while it sits there: only a reload puts a changed set back
        before, now = snap["tree"], self._tree()
        if now.get("class_id") != before.get("class_id"):
            return False
        before_nodes = {int(n) for n in before.get("user_allocated_node_ids") or ()}
        now_nodes = {int(n) for n in now.get("user_allocated_node_ids") or ()}
        before_eff, now_eff = _effects(before), _effects(now)
        if any(before_eff.get(n) != now_eff.get(n) for n in before_nodes & now_nodes):
            return False  # a re-selected mastery effect: only a reload puts that back
        add, remove = sorted(before_nodes - now_nodes), sorted(now_nodes - before_nodes)
        if add or remove:
            self.pob.mutate_nodes(add=add, remove=remove, mastery_effects={n: before_eff[n] for n in add if n in before_eff} or None)
            after = self._tree()
            if {int(n) for n in after.get("user_allocated_node_ids") or ()} != before_nodes or _effects(after) != before_eff:
                return False
            held = self.pob.socketed_jewels()
        wanted: dict[int, str] = snap["jewels"]
        if held != wanted:
            allocated = before_nodes
            if any(socket not in allocated for socket in wanted):
                return False  # a jewel the snapshot held in a socket that is not allocated: only a reload puts that back
            for socket in held:
                if wanted.get(socket) != held[socket]:
                    self.pob.remove_jewel(socket)
            for socket, raw in wanted.items():
                if held.get(socket) != raw:
                    self.pob.put_jewel(socket, raw)
            if self.pob.socketed_jewels() != wanted:
                return False
        return True

    # -- sockets and points -----------------------------------------------------------------------------------

    def sockets(self) -> list[SocketOption]:
        allocated = self.allocated()
        held = set(self.pob.socketed_jewels())
        excluded = set(self._excluded())
        out: list[SocketOption] = []
        for node_id in allocated:
            node = self.graph.node(node_id)
            if node is not None and node.kind == "jewel" and node_id not in held:
                out.append(SocketOption(node_id, (node_id,), 0))
        for node_id, (cost, path) in self.graph.bfs_costs(allocated, max_depth=self.max_depth).items():
            node = self.graph.node(node_id)
            if node is None or node.kind != "jewel" or node_id in held or not excluded.isdisjoint(path):
                continue
            out.append(SocketOption(node_id, tuple(path), cost))
        out.sort(key=lambda o: (o.cost, o.node_id))
        return out

    def allocate(self, nodes: Sequence[int]) -> None:
        have = self.allocated()
        missing = [int(n) for n in nodes if int(n) not in have]
        if not missing:
            return
        self.pob.mutate_nodes(add=missing)
        still = [n for n in missing if n not in self.allocated()]
        if still:
            raise RuntimeError(f"PoB did not allocate {still}")

    def put_jewel(self, socket_id: int, candidate: JewelLine | str | Any, *, item_level: int | None = None) -> None:
        """A `JewelLine` as the one-mod rare jewel; a string as its own raw text; anything else through `.raw(item_level)`
        (a cluster candidate). A cluster jewel replaces what sat in the socket, an earlier cluster jewel with its inner nodes."""

        if isinstance(candidate, JewelLine):
            raw = rare_jewel_raw(candidate)
        elif isinstance(candidate, str):
            raw = candidate
        else:
            raw = candidate.raw(self.item_level if item_level is None else item_level)
        self.pob.put_jewel(socket_id, raw)

    def cluster_graph(self, socket_id: int) -> list[ClusterNode]:
        """The subgraph PoB built for the cluster jewel in `socket_id` (empty when it holds none), read from PoB."""

        return [
            ClusterNode(int(n["id"]), str(n["kind"]), str(n.get("name") or ""), tuple(int(x) for x in n.get("linked") or ()))
            for n in self.pob.cluster_graph(socket_id)
        ]

    def remove_jewel(self, socket_id: int) -> None:
        self.pob.remove_jewel(socket_id)

    def cluster_links(self, held: dict[int, str] | None = None) -> Links | None:
        """The extra edges of every socketed cluster jewel (its subgraph's `linked` fields, the entry to its outer socket
        included), one `cluster_graph` read per cluster; None when no cluster sits in a socket (no PoB read then)."""

        return cluster_links_of(self.pob, _clusters(self.pob.socketed_jewels() if held is None else held))

    def removable_leaves(self) -> list[int]:
        held = self.pob.socketed_jewels()
        leaves = self.graph.removable_leaves(self.allocated(), protected=self.protected, links=self.cluster_links(held))
        return [n for n in leaves if (n in self.graph.allocatable or self.graph.is_inner_socket(n)) and n not in held]

    def remove(self, node_id: int) -> int | None:
        """Remove the node in PoB and say how many nodes PoB took: more than one means its own connectivity disagreed with
        the graph's leaf estimate and the removal cascaded (#1164); the caller decides (`jewel_step._free_points` restores).
        None when PoB's reply carries no `removed_node_ids` (not known, never read as one node)."""

        removed = self.pob.remove_nodes([int(node_id)]).get("removed_node_ids")
        return None if removed is None else len(removed)

    def points_over(self) -> int:
        return int(self.pob.mutate_nodes()["points_used"]) - self.points

    def leaf_scores(self, leaves: Sequence[int]) -> list[float]:
        """The score of the build without each leaf, one PoB trial per leaf (the build is as it was after)."""

        objective = self._objective()
        outcomes = self.pob.trial_stats([{"remove": [int(leaf)]} for leaf in leaves], objective.stat_keys, mode=LEAF_MEASURE_MODE)
        scores: list[float] = []
        for outcome in outcomes:
            if outcome.get("ok") and outcome.get("stats") and len(outcome.get("removed_node_ids") or ()) == 1:
                scores.append(scalar(objective.score(outcome["stats"])))
            else:
                scores.append(NO_SCORE)
        return scores
