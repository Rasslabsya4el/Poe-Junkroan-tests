"""The day-1 rare cluster jewel step (#433): pick a cluster jewel (size, enchant, notables) and its socket.

Pure Python, driven only through an injected `ClusterProbe` (a `JewelProbe` plus `cluster_graph`); PoB judges
every trial through `probe.score()` (principle 1). Algorithm: screen every (socket, enchant) with no notables,
keep the best `screen_keep`, try each notable of the kept ones and pairs of the top `pair_top`, then pay the
best candidate's points like `place_jewel` does and keep it only when the score beats the build before it.

`cluster_graph(socket_id)` lists the nodes of the cluster jewel socketed in that socket: `id`, `kind`
("entry"|"small"|"notable"|"socket"), `name`, `linked` (ids). A socket option carries `expansion_size`
(2 = Large socket, 1 = Medium, 0 = Small, None = plain); a Large cluster goes only to 2, a Medium to 1 or 2.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from junkroan.optimizer import yield_probe
from junkroan.optimizer.jewel_step import JewelProbe, SocketOption, _Counter, _free_points
from junkroan.report_format import human_duration

DEFAULT_COUNT_MAX = 2
DEFAULT_NOTABLES_MAX = 2
DEFAULT_SCREEN_KEEP = 6
DEFAULT_PAIR_TOP = 5
SMALL_IN_SCREEN = 2

_SIZE_OK = {"large": (2,), "medium": (1, 2)}


@dataclass(frozen=True)
class ClusterSocket(SocketOption):
    expansion_size: int | None = None


class ClusterProbe(JewelProbe, Protocol):
    def cluster_graph(self, socket_id: int) -> list[Any]: ...


@dataclass(frozen=True)
class PlacedCluster:
    socket_id: int
    candidate: Any
    score_before: float
    score_after: float
    measured: int
    path: tuple[int, ...] = ()
    removed_leaves: tuple[int, ...] = ()
    seconds: float = 0.0


@dataclass
class ClusterStepResult:
    placed: list[PlacedCluster] = field(default_factory=list)
    score_before: float = 0.0
    score_after: float = 0.0
    trials: int = 0
    seconds: float = 0.0
    stopped_reason: str = ""
    inner_skipped: list[int] = field(default_factory=list)


def _bfs(graph: Sequence[Any], start: int) -> tuple[list[int], dict[int, int | None]]:
    adj: dict[int, set[int]] = {}
    for n in graph:
        for m in n.linked:
            adj.setdefault(n.id, set()).add(m)
            adj.setdefault(m, set()).add(n.id)
    order: list[int] = []
    parent: dict[int, int | None] = {start: None}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for nxt in sorted(adj.get(cur, ())):
            if nxt not in parent:
                parent[nxt] = cur
                queue.append(nxt)
    return order, parent


def _path_to(parent: Mapping[int, int | None], node: int) -> list[int]:
    out: list[int] = []
    cur: int | None = node
    while cur is not None:
        out.append(cur)
        cur = parent[cur]
    return out[::-1]


def _entry(graph: Sequence[Any]) -> Any | None:
    return next((n for n in graph if n.kind == "entry"), None)


def screen_nodes(graph: Sequence[Any]) -> list[int]:
    """Entry plus its 2 nearest small nodes (and the nodes between)."""

    entry = _entry(graph)
    if entry is None:
        return []
    order, parent = _bfs(graph, entry.id)
    kind = {n.id: n.kind for n in graph}
    nodes = [entry.id]
    smalls = [i for i in order if kind.get(i) == "small"][:SMALL_IN_SCREEN]
    for s in smalls:
        nodes += [n for n in _path_to(parent, s) if n not in nodes]
    return nodes


def notable_nodes(graph: Sequence[Any], names: Sequence[str]) -> list[int] | None:
    """Shortest inner path entry -> each named notable, united; None when a name is not in the graph."""

    entry = _entry(graph)
    if entry is None:
        return None
    _order, parent = _bfs(graph, entry.id)
    by_name = {n.name: n.id for n in graph if n.kind == "notable"}
    nodes: list[int] = []
    for name in names:
        nid = by_name.get(name)
        if nid is None or nid not in parent:
            return None
        nodes += [n for n in _path_to(parent, nid) if n not in nodes]
    return nodes


def _size_of(option: Any, socket_size: Callable[[int], int | None] | None) -> int | None:
    if socket_size is not None:
        return socket_size(option.node_id)
    return getattr(option, "expansion_size", None)


def _trial(probe, counter, option, make, size, enchant, names):
    """Put the candidate, allocate socket path + inner path, score, restore. (score, candidate, inner) or None."""

    base = probe.snapshot()
    try:
        candidate = make(size, enchant, tuple(names))
        probe.allocate(option.path)
        probe.put_jewel(option.node_id, candidate)
        graph = probe.cluster_graph(option.node_id)
        inner = screen_nodes(graph) if not names else notable_nodes(graph, names)
        if inner is None:
            return None
        probe.allocate(inner)
        return counter.score(), candidate, inner
    finally:
        probe.restore(base)


def run_cluster_step(
    probe: Any,
    enchants_by_size: Mapping[str, Sequence[Any]],
    notables_for: Callable[[Any, str], Sequence[str]],
    make_candidate: Callable[[str, Any, tuple[str, ...]], Any],
    *,
    count_max: int = DEFAULT_COUNT_MAX,
    notables_max: int = DEFAULT_NOTABLES_MAX,
    screen_keep: int = DEFAULT_SCREEN_KEEP,
    pair_top: int = DEFAULT_PAIR_TOP,
    socket_size: Callable[[int], int | None] | None = None,
    is_inner: Callable[[int], bool] | None = None,
) -> ClusterStepResult:
    """Cluster 1..count_max; the round stops at the first cluster that does not pay."""

    started_all = time.perf_counter()
    result = ClusterStepResult()
    total = _Counter(probe)
    result.score_before = result.score_after = total.score()
    placed_sockets: list[int] = []
    for i in range(count_max):
        yield_probe.check("clusters")  # #621
        started = time.perf_counter()
        counter = _Counter(probe)
        before = counter.score()
        base = probe.snapshot()
        options = sorted(probe.sockets(), key=lambda o: (o.cost, o.node_id))
        if is_inner is not None:
            result.inner_skipped += [o.node_id for o in options if is_inner(o.node_id)]
            options = [o for o in options if not is_inner(o.node_id)]
        screened = []
        for option in options:
            yield_probe.check("clusters")  # #621
            sz = _size_of(option, socket_size)
            for size, allowed in _SIZE_OK.items():
                if sz not in allowed:
                    continue
                for enchant in enchants_by_size.get(size, ()):
                    t = _trial(probe, counter, option, make_candidate, size, enchant, ())
                    if t is not None:
                        screened.append((t[0], option, size, enchant, t[1], t[2]))
        screened.sort(key=lambda x: x[0], reverse=True)
        ranking = []  # (score, option, candidate, inner)
        for score, option, size, enchant, cand0, inner0 in screened[:screen_keep]:
            ranking.append((score, option, cand0, inner0))
            singles = []
            for name in list(notables_for(enchant, size)):
                t = _trial(probe, counter, option, make_candidate, size, enchant, (name,))
                if t is not None:
                    singles.append((t[0], name))
                    ranking.append((t[0], option, t[1], t[2]))
            if notables_max >= 2:
                top = [n for _s, n in sorted(singles, key=lambda x: x[0], reverse=True)[:pair_top]]
                for a in range(len(top)):
                    for b in range(a + 1, len(top)):
                        t = _trial(probe, counter, option, make_candidate, size, enchant, (top[a], top[b]))
                        if t is not None:
                            ranking.append((t[0], option, t[1], t[2]))
        total.n += counter.n
        if not ranking:
            result.stopped_reason = f"cluster {i + 1}: no cluster option"
            break
        ranking.sort(key=lambda x: x[0], reverse=True)
        _s, option, candidate, inner = ranking[0]
        keep = set(option.path) | {option.node_id} | set(inner) | set(placed_sockets)
        probe.allocate(option.path)
        probe.put_jewel(option.node_id, candidate)
        probe.allocate(inner)
        pay = _Counter(probe)
        removed = _free_points(probe, pay, keep)
        after = pay.score() if removed is not None else None
        total.n += pay.n
        counter.n += pay.n
        if after is None or not after > before:
            probe.restore(base)
            paid = "no leaf to free" if after is None else f"{after:.6g} after paying its points"
            result.stopped_reason = f"cluster {i + 1}: best option does not beat the build (best trial {_s:.6g}, {paid}, build {before:.6g})"
            break
        result.placed.append(
            PlacedCluster(
                socket_id=option.node_id,
                candidate=candidate,
                score_before=before,
                score_after=after,
                measured=counter.n,
                path=tuple(option.path) + tuple(inner),
                removed_leaves=tuple(removed),
                seconds=time.perf_counter() - started,
            )
        )
        placed_sockets.extend([option.node_id, *inner])
        result.score_after = after
    else:
        result.stopped_reason = f"count_max {count_max} reached"
    result.trials = total.n
    result.seconds = time.perf_counter() - started_all
    return result


def cluster_log_line(placed: PlacedCluster, seconds: float) -> str:
    c = placed.candidate
    return (
        f"cluster: socket {placed.socket_id} {c.size} '{c.enchant.id}' + {', '.join(c.notables)}, "
        f"score {placed.score_before:.6g} -> {placed.score_after:.6g}, {placed.measured} measured, "
        f"{len(placed.path)} points, removed {', '.join(str(n) for n in placed.removed_leaves) or 'none'}, "
        f"{human_duration(seconds)}"
    )
