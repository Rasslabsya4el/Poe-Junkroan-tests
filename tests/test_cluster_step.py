"""#433 unit 4: the cluster step against a fake probe with known scores. No PoB."""

from __future__ import annotations

from dataclasses import dataclass

from junkroan.optimizer.cluster_step import (
    ClusterSocket,
    cluster_log_line,
    run_cluster_step,
)
from junkroan.report_format import human_duration


@dataclass(frozen=True)
class Ench:
    id: str


@dataclass(frozen=True)
class Cand:
    size: str
    enchant: Ench
    notables: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.size}/{self.enchant.id}/{','.join(self.notables)}"


@dataclass(frozen=True)
class Node:
    id: int
    kind: str
    name: str
    linked: tuple[int, ...]


# inner graph of any cluster: entry 201 - small 202, 203; notable 204 (via 201), notable 205 (via 204)
GRAPH = [
    Node(201, "entry", "", (202, 204)),
    Node(202, "small", "s", (203,)),
    Node(203, "small", "s", ()),
    Node(204, "notable", "N1", (205,)),
    Node(205, "notable", "N2", ()),
]
INNER_VALUE = {202: 1.0, 203: 1.0, 204: 5.0, 205: 4.0}


class FakeProbe:
    """Allocated set + jewels; score = leaf values + inner values + gain[size] for a jewel in an allocated socket."""

    def __init__(self, socket_sizes, gain, budget=2):
        self.sizes = dict(socket_sizes)  # socket id -> expansion_size
        self.gain = gain  # size -> gain
        self.allocated = {0, 1, 2}
        self.budget = budget
        self.jewels = {}
        self.puts = []
        self.score_calls = 0

    def score(self):
        self.score_calls += 1
        total = float(sum({1: 1.0, 2: 1.0}.get(n, 0.0) + INNER_VALUE.get(n, 0.0) for n in self.allocated))
        for sid, c in self.jewels.items():
            if sid in self.allocated:
                total += self.gain[c.size]
        return total

    def snapshot(self):
        return (frozenset(self.allocated), tuple(self.jewels.items()))

    def restore(self, snap):
        self.allocated = set(snap[0])
        self.jewels = dict(snap[1])

    def sockets(self):
        return [ClusterSocket(sid, (sid,), 0 if sid in self.allocated else 1, size)
                for sid, size in self.sizes.items() if sid not in self.jewels]

    def allocate(self, nodes):
        self.allocated |= set(nodes)

    def put_jewel(self, socket_id, candidate):
        self.puts.append((socket_id, candidate))
        self.jewels[socket_id] = candidate

    def remove_jewel(self, socket_id):
        self.jewels.pop(socket_id, None)

    def cluster_graph(self, socket_id):
        return GRAPH

    def removable_leaves(self):
        return sorted(n for n in self.allocated if n != 0)

    def remove(self, node_id):
        self.allocated.discard(node_id)
        return 1  # the nodes the build lost (#1164)

    def points_over(self):
        return len(self.allocated) - 1 - self.budget


ENCH = {"large": [Ench("L")], "medium": [Ench("M")]}


def run(probe, **kw):
    return run_cluster_step(
        probe, ENCH, lambda e, s: ["N1", "N2"], lambda s, e, n: Cand(s, e, n), **kw
    )


def test_size_rules_never_plain_or_small():
    probe = FakeProbe({100: 2, 101: 1, 102: None, 103: 0}, {"large": 50.0, "medium": 40.0}, budget=20)
    run(probe)
    seen = {(sid, c.size) for sid, c in probe.puts}
    assert (100, "large") in seen and (100, "medium") in seen and (101, "medium") in seen
    assert (101, "large") not in seen
    assert not any(sid in (102, 103) for sid, _ in probe.puts)


def test_paying_cluster_kept_with_best_notables_and_log_line():
    probe = FakeProbe({100: 2}, {"large": 50.0, "medium": 10.0}, budget=4)
    res = run(probe, count_max=1)
    assert len(res.placed) == 1
    p = res.placed[0]
    assert (p.candidate.size, p.candidate.notables) == ("large", ("N2",))
    assert res.score_after > res.score_before and probe.score() == res.score_after
    assert probe.jewels[100] == p.candidate
    assert probe.points_over() <= 0
    line = cluster_log_line(p, 3.0)
    assert line == (
        f"cluster: socket 100 large 'L' + N2, score {p.score_before:.6g} -> {p.score_after:.6g}, "
        f"{p.measured} measured, {len(p.path)} points, removed {', '.join(str(n) for n in p.removed_leaves) or 'none'}, "
        f"{human_duration(3.0)}"
    )


def test_is_inner_none_trials_every_socket():
    probe = FakeProbe({100: 2, 8: 1}, {"large": 50.0, "medium": 40.0}, budget=20)
    res = run(probe)
    assert 8 in {sid for sid, _c in probe.puts}
    assert res.inner_skipped == []


def test_not_paying_is_reverted():
    # the jewel adds nothing; every path point costs two leaves worth 1 each at budget 2
    probe = FakeProbe({100: 2}, {"large": -100.0, "medium": -100.0}, budget=2)
    before = probe.score()
    snap = probe.snapshot()
    res = run(probe)
    assert res.placed == []
    assert probe.snapshot() == snap and probe.score() == before
    assert res.score_after == res.score_before


def test_count_max_ends_the_round_and_points_stay_inside():
    probe = FakeProbe({100: 2, 101: 2, 102: 2}, {"large": 50.0, "medium": 50.0}, budget=8)
    res = run(probe, count_max=2)
    assert len(res.placed) == 2
    assert res.stopped_reason == "count_max 2 reached"
    assert probe.points_over() <= 0
    assert len(probe.jewels) == 2
