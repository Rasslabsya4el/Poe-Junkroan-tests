"""The day-1 rare jewel step (#434): pick a 1-line jewel, find the socket it pays for, up to `count_max` times.

Pure Python. The step drives the build only through an injected `JewelProbe`; the pipeline (unit 4) implements
the probe against a PobSession, the tests implement it with a fake that holds known scores. Every judgement of
strength is `probe.score()`: the step never reasons about a line or a socket (principle 1).

The probe (all methods act on the one build the probe holds):

- `score() -> float`: the objective of the build as it stands now. One call = one measurement.
- `snapshot() -> object` / `restore(snap)`: `restore` brings the build back EXACTLY (tree, jewels, same score).
- `sockets() -> list[SocketOption]`: the jewel sockets the tree search reaches within `max_depth` that hold no
  jewel now. `SocketOption.path` is every node to allocate, the socket included (nodes already allocated may be
  listed; allocating them again is a no-op); `cost` = points the path adds (0 when it is all allocated).
- `allocate(nodes)`: allocate the nodes.
- `put_jewel(socket_id, candidate)` / `remove_jewel(socket_id)`: socket a candidate line (a real item) into an
  ALLOCATED socket / take it out. `put_jewel` into a socket that holds one is not asked of the probe.
- `removable_leaves() -> list[int]` / `remove(node_id) -> int | None`: allocated nodes whose removal leaves the tree
  connected, and the removal of one, answering how many nodes the build really lost (1 = the leaf alone; more = a
  cascade the leaf estimate missed; None = not known, taken as a refusal: #1164). The step puts a refused leaf back
  with `restore`, never tries it again in that call, and takes the next. It never removes a node of the new path nor
  the socket of a jewel it placed.
- `points_over() -> int`: passive points used beyond the budget (0 or less = inside).
- optional `leaf_scores(leaves) -> list[float]`: the score without each leaf, measured as one batch; a probe
  without it is measured leaf by leaf (`remove`, `score`, `restore`).

A candidate is an opaque object with a stable `id`; unit 1 builds them. The step puts each one into a socket and
reads the score, nothing else.

`run_jewel_step` does the pick and the placement for jewel 1..count_max and returns one `PlacedJewel` per jewel
(socket, line, score before -> after, number of measurements) for the pipeline's log line
`jewel: socket <node id> '<line>', score before -> after, N measured, time` (`jewel_log_line`).
`repick_jewels` is the end re-pick: the 10 best lines of each jewel's own pick plus its current line, measured on
the final build; the best stays.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from typing import Any, Protocol, Sequence

from junkroan.report_format import human_duration

DEFAULT_COUNT_MAX = 2
REPICK_TOP = 10


class JewelCandidate(Protocol):
    """A line to socket: opaque to the step, identified by `id`."""

    id: str


@dataclass(frozen=True)
class SocketOption:
    node_id: int
    path: tuple[int, ...]  # every node to allocate, the socket included
    cost: int  # points the path adds


class JewelProbe(Protocol):
    def score(self) -> float: ...
    def snapshot(self) -> Any: ...
    def restore(self, snap: Any) -> None: ...
    def sockets(self) -> list[SocketOption]: ...
    def allocate(self, nodes: Sequence[int]) -> None: ...
    def put_jewel(self, socket_id: int, candidate: JewelCandidate) -> None: ...
    def remove_jewel(self, socket_id: int) -> None: ...
    def removable_leaves(self) -> list[int]: ...
    def remove(self, node_id: int) -> int | None: ...  # the nodes the build lost; None = not known (#1164)
    def points_over(self) -> int: ...


@dataclass(frozen=True)
class PlacedJewel:
    socket_id: int
    candidate: JewelCandidate
    score_before: float  # the build before this jewel (its path and freed leaves included in "after")
    score_after: float
    measured: int  # score() calls this jewel took (line pick + placement)
    ranking: tuple[tuple[JewelCandidate, float], ...]  # every line of its pick, best first
    path: tuple[int, ...] = ()
    removed_leaves: tuple[int, ...] = ()  # the leaves freed for the path, in order
    seconds: float = 0.0  # wall clock of this jewel's pick and placement (the log line's time)


@dataclass
class JewelStepResult:
    jewels: list[PlacedJewel] = field(default_factory=list)
    measured: int = 0
    stopped_reason: str = ""


class _Counter:
    """`probe.score()` with a count: the number the log line reports."""

    def __init__(self, probe: JewelProbe) -> None:
        self.probe = probe
        self.n = 0

    def score(self) -> float:
        self.n += 1
        return self.probe.score()


def _cheapest(options: Sequence[SocketOption]) -> SocketOption:
    return min(options, key=lambda o: (o.cost, o.node_id))


def pick_line(
    probe: JewelProbe, candidates: Sequence[JewelCandidate], counter: _Counter | None = None
) -> tuple[JewelCandidate | None, list[tuple[JewelCandidate, float]], float | None]:
    """Line pick: every candidate measured as a socketed jewel in the cheapest reachable socket.

    Returns (best line or None, ranking best first, score of that socket allocated empty). None when no socket is
    reachable or no line scores above the empty socket. The build is restored exactly before returning.
    """

    counter = counter or _Counter(probe)
    options = probe.sockets()
    if not options or not candidates:
        return None, [], None
    socket = _cheapest(options)
    snap = probe.snapshot()
    try:
        probe.allocate(socket.path)
        empty = counter.score()
        ranking: list[tuple[JewelCandidate, float]] = []
        for candidate in candidates:
            probe.put_jewel(socket.node_id, candidate)
            ranking.append((candidate, counter.score()))
            probe.remove_jewel(socket.node_id)
    finally:
        probe.restore(snap)
    ranking.sort(key=lambda item: item[1], reverse=True)  # stable: ties keep the candidates' order
    best, best_score = ranking[0]
    if not best_score > empty:
        return None, ranking, empty
    return best, ranking, empty


def _alone(took: int | None) -> bool:
    """Whether a removal that took `took` nodes took the leaf alone; a count PoB did not give (None) is not known to be."""

    return took == 1


def _removes_alone(probe: JewelProbe, leaf: int) -> bool:
    """Remove `leaf` for real; True when the build lost that node alone. A removal that took more (PoB connects the tree
    from its own class start, the graph's leaf estimate can disagree: 92 nodes once, #1164) or whose count is not known
    is undone with the probe's restore and refused."""

    snap = probe.snapshot()
    if _alone(probe.remove(leaf)):
        return True
    probe.restore(snap)
    return False


def _free_points(
    probe: JewelProbe, counter: _Counter, keep: set[int]
) -> list[int] | None:
    """Remove leaves one at a time, each the leaf whose measured removal loses least, until inside the budget.

    `keep` = nodes never removed (the new path, the placed jewels' sockets). A leaf whose real removal takes more than
    itself is put back and refused for the rest of this call (never scored or removed again); the next-best leaf is
    taken (#1164). Returns the removed leaves in order, or None when the budget cannot be met (no removable leaf
    left, or every one refused).
    """

    removed: list[int] = []
    refused: set[int] = set()
    while probe.points_over() > 0:
        leaves = [leaf for leaf in probe.removable_leaves() if leaf not in keep and leaf not in refused]
        if not leaves:
            return None
        batch = getattr(probe, "leaf_scores", None)
        if callable(batch):
            # a probe that can measure every removal in one batch (PoB trials leave the build as it was)
            scored = list(zip(batch(leaves), leaves))
            counter.n += len(leaves)
        else:
            snap = probe.snapshot()
            scored = []
            for leaf in leaves:
                if _alone(probe.remove(leaf)):
                    scored.append((counter.score(), leaf))
                else:
                    refused.add(leaf)  # the measuring removal was real: this leaf is not tried again
                probe.restore(snap)
        # highest score after removal = least loss; ties go to the lowest node id
        for _score, leaf in sorted(scored, key=lambda item: (-item[0], item[1])):
            if _removes_alone(probe, leaf):
                removed.append(leaf)
                break
            refused.add(leaf)
        else:
            return None
    return removed


def _apply(probe: JewelProbe, socket: SocketOption, candidate: JewelCandidate, removed: Sequence[int]) -> None:
    probe.allocate(socket.path)
    probe.put_jewel(socket.node_id, candidate)
    for leaf in removed:
        probe.remove(leaf)


def place_jewel(
    probe: JewelProbe,
    candidate: JewelCandidate,
    score_before: float,
    counter: _Counter,
    placed_sockets: Sequence[int] = (),
) -> tuple[SocketOption, float, list[int]] | None:
    """Placement: the best reachable socket for `candidate`, kept only when it beats `score_before`.

    Each socket is tried (path + socket + jewel, points freed by least-loss leaves) and the build restored. The
    best one is re-applied and returned as (socket, score after, freed leaves); None when none beats the build,
    in which case the build is as it was.
    """

    options = sorted(probe.sockets(), key=lambda o: (o.cost, o.node_id))
    base = probe.snapshot()
    best: tuple[float, SocketOption, list[int]] | None = None
    for option in options:
        keep = set(option.path) | {option.node_id} | set(placed_sockets)
        probe.allocate(option.path)
        probe.put_jewel(option.node_id, candidate)
        removed = _free_points(probe, counter, keep)
        if removed is not None:
            after = counter.score()
            if best is None or after > best[0]:
                best = (after, option, removed)
        probe.restore(base)
    if best is None or not best[0] > score_before:
        return None
    after, option, removed = best
    _apply(probe, option, candidate, removed)
    return option, after, removed


def run_jewel_step(
    probe: JewelProbe,
    candidates: Sequence[JewelCandidate],
    *,
    count_max: int = DEFAULT_COUNT_MAX,
) -> JewelStepResult:
    """Jewel i = 1..count_max: line pick, then placement; stops at the first jewel that does not pay."""

    result = JewelStepResult()
    total = _Counter(probe)
    for i in range(count_max):
        started = time.perf_counter()
        counter = _Counter(probe)
        before = counter.score()
        line, ranking, _empty = pick_line(probe, candidates, counter)
        if line is None:
            result.stopped_reason = f"jewel {i + 1}: no line beats the empty socket" if ranking else f"jewel {i + 1}: no socket"
            total.n += counter.n
            break
        socket_ids = [j.socket_id for j in result.jewels]
        placement = place_jewel(probe, line, before, counter, socket_ids)
        total.n += counter.n
        if placement is None:
            result.stopped_reason = f"jewel {i + 1}: no socket beats the build"
            break
        option, after, removed = placement
        result.jewels.append(
            PlacedJewel(
                socket_id=option.node_id,
                candidate=line,
                score_before=before,
                score_after=after,
                measured=counter.n,
                ranking=tuple(ranking),
                path=tuple(option.path),
                removed_leaves=tuple(removed),
                seconds=time.perf_counter() - started,
            )
        )
    else:
        result.stopped_reason = f"count_max {count_max} reached"
    result.measured = total.n
    return result


def repick_jewels(
    probe: JewelProbe, placed: Sequence[PlacedJewel], *, top: int = REPICK_TOP
) -> list[PlacedJewel]:
    """End re-pick: per jewel, its `top` best lines plus the current line on the current build; the best stays.

    `placed` = the jewels the build still holds (a jewel whose socket a later step removed is the pipeline's to
    drop before). The current line wins ties. Returns the jewels with the kept line, score after and measured
    count updated (`score_before` is the score with the current line).
    """

    out: list[PlacedJewel] = []
    for jewel in placed:
        counter = _Counter(probe)
        current = counter.score()
        options: list[JewelCandidate] = []
        seen = {jewel.candidate.id}
        for candidate, _score in jewel.ranking[:top]:
            if candidate.id not in seen:
                seen.add(candidate.id)
                options.append(candidate)
        best_candidate, best_score = jewel.candidate, current
        for candidate in options:
            probe.remove_jewel(jewel.socket_id)
            probe.put_jewel(jewel.socket_id, candidate)
            s = counter.score()
            if s > best_score:
                best_candidate, best_score = candidate, s
        probe.remove_jewel(jewel.socket_id)
        probe.put_jewel(jewel.socket_id, best_candidate)
        out.append(
            replace(
                jewel,
                candidate=best_candidate,
                score_before=current,
                score_after=best_score,
                measured=jewel.measured + counter.n,
            )
        )
    return out


def jewel_log_line(jewel: PlacedJewel, seconds: float) -> str:
    return (
        f"jewel: socket {jewel.socket_id} '{jewel.candidate.id}', score {jewel.score_before:.6g} -> "
        f"{jewel.score_after:.6g}, {jewel.measured} measured, {human_duration(seconds)}"
    )
