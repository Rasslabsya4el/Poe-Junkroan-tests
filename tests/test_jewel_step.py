"""#434 unit 3: the jewel step against a fake probe with known scores (rows 3 and 4 of the issue). No PoB."""

from __future__ import annotations

from dataclasses import dataclass
from junkroan.report_format import human_duration

from junkroan.optimizer.jewel_step import (
    PlacedJewel,
    SocketOption,
    jewel_log_line,
    repick_jewels,
    run_jewel_step,
)


@dataclass(frozen=True)
class Line:
    id: str


class FakeProbe:
    """A tree of parent links; score = node values + jewel gains (a jewel counts only in an allocated socket).

    `gain[line.id]` is a number or a function of the set of OTHER line ids already socketed.
    """

    def __init__(self, parents, values, sockets, gain, allocated, budget):
        self.parents = dict(parents)  # node -> parent (root 0 has none)
        self.values = dict(values)
        self.socket_paths = dict(sockets)  # socket id -> path tuple (socket last)
        self.socket_costs = {}
        self.gain = gain
        self.allocated = set(allocated) | {0}
        self.budget = budget
        self.jewels: dict[int, Line] = {}
        self.score_calls = 0
        for sid, path in self.socket_paths.items():
            for a, b in zip((0,) + path, path):
                self.parents.setdefault(b, a)

    def score(self):
        self.score_calls += 1
        total = sum(self.values.get(n, 0.0) for n in self.allocated)
        for sid, line in self.jewels.items():
            if sid in self.allocated:
                g = self.gain[line.id]
                others = {l.id for k, l in self.jewels.items() if k != sid}
                total += g(others) if callable(g) else g
        return float(total)

    def snapshot(self):
        return (frozenset(self.allocated), tuple(sorted(self.jewels.items(), key=lambda kv: kv[0])))

    def restore(self, snap):
        self.allocated = set(snap[0])
        self.jewels = dict(snap[1])

    def sockets(self):
        out = []
        for sid, path in self.socket_paths.items():
            if sid in self.jewels:
                continue
            cost = len([n for n in path if n not in self.allocated])
            out.append(SocketOption(sid, path, cost))
        return out

    def allocate(self, nodes):
        self.allocated |= set(nodes)

    def put_jewel(self, socket_id, candidate):
        assert socket_id in self.allocated and socket_id not in self.jewels
        self.jewels[socket_id] = candidate

    def remove_jewel(self, socket_id):
        self.jewels.pop(socket_id, None)

    def removable_leaves(self):
        parents_in_use = {self.parents[n] for n in self.allocated if n != 0}
        return sorted(n for n in self.allocated if n != 0 and n not in parents_in_use)

    def remove(self, node_id):
        self.allocated.discard(node_id)
        self.jewels.pop(node_id, None)  # a removed socket drops its jewel
        return 1  # the nodes the build lost (#1164)

    def points_over(self):
        return len(self.allocated) - 1 - self.budget  # root is free


# tree: root 0; chain 1-2-3, chain 4-5, single 6 (values: what removing them costs); sockets via 7-100 and 8-9-101
BASE_PARENTS = {1: 0, 2: 1, 3: 2, 4: 0, 5: 4, 6: 0}
BASE_VALUES = {1: 10, 2: 10, 3: 5, 4: 10, 5: 2, 6: 8, 7: 0, 100: 0, 8: 0, 9: 0, 101: 0}
BASE_NODES = {1, 2, 3, 4, 5, 6}
SOCKETS = {100: (7, 100), 101: (8, 9, 101)}
LINES = [Line("a"), Line("b"), Line("c")]


def make(gain, *, values=None, sockets=None, budget=6, allocated=None):
    return FakeProbe(
        BASE_PARENTS, values or BASE_VALUES, sockets or SOCKETS, gain, allocated or BASE_NODES, budget
    )


def test_pick_takes_the_highest_line():
    probe = make({"a": 3.0, "b": 9.0, "c": 5.0}, budget=8)
    result = run_jewel_step(probe, LINES, count_max=1)
    assert [j.candidate.id for j in result.jewels] == ["b"]
    # the ranking of the pick is remembered, best first (scores are absolute: the build plus the line)
    ranking = result.jewels[0].ranking
    assert [c.id for c, _s in ranking] == ["b", "c", "a"]
    assert ranking[0][1] - ranking[1][1] == 4.0 and ranking[1][1] - ranking[2][1] == 2.0


def test_no_jewel_when_every_line_is_at_or_below_the_empty_socket():
    probe = make({"a": 0.0, "b": -2.0, "c": 0.0}, budget=8)
    before = probe.snapshot()
    score = probe.score()
    result = run_jewel_step(probe, LINES)
    assert result.jewels == []
    assert probe.snapshot() == before and probe.score() == score  # nothing left behind


def test_restore_is_exact_after_the_pick():
    # the pick allocates the cheapest socket (100); the placement then lands on 101 only: 100 must be gone
    probe = make({"a": 30.0, "b": 1.0, "c": 1.0}, values={**BASE_VALUES, 8: 0, 9: 0, 101: 50}, budget=9)
    run_jewel_step(probe, LINES, count_max=1)
    assert 100 not in probe.allocated and 7 not in probe.allocated
    assert probe.jewels == {101: LINES[0]}


def test_best_socket_that_beats_the_build_is_taken():
    # socket 100 (cost 2) gives nothing extra; socket 101 (cost 3) carries a +20 node: 101 wins even though dearer
    probe = make({"a": 5.0, "b": 1.0, "c": 1.0}, values={**BASE_VALUES, 101: 20}, budget=9)
    result = run_jewel_step(probe, LINES, count_max=1)
    (jewel,) = result.jewels
    assert jewel.socket_id == 101
    assert jewel.score_after > jewel.score_before
    assert probe.jewels == {101: LINES[0]}


def test_none_when_no_socket_beats_the_build():
    # budget is full: every path costs leaves worth more than the jewel's +5
    probe = make({"a": 5.0, "b": 1.0, "c": 1.0}, budget=6)
    before = probe.snapshot()
    score = probe.score()
    result = run_jewel_step(probe, LINES)
    assert result.jewels == []
    assert "no socket beats" in result.stopped_reason
    assert probe.snapshot() == before and probe.score() == score


def test_never_more_than_count_max():
    sockets = {100: (7, 100), 101: (8, 101), 102: (10, 102), 103: (11, 103)}
    probe = make({"a": 5.0, "b": 4.0, "c": 3.0}, sockets=sockets, budget=20)
    assert len(run_jewel_step(probe, LINES).jewels) == 2  # the default rail
    probe = make({"a": 5.0, "b": 4.0, "c": 3.0}, sockets=sockets, budget=20)
    assert len(run_jewel_step(probe, LINES, count_max=1).jewels) == 1
    probe = make({"a": 5.0, "b": 4.0, "c": 3.0}, sockets=sockets, budget=20)
    assert len(run_jewel_step(probe, LINES, count_max=3).jewels) == 3


def test_second_line_is_picked_with_the_first_jewel_in_place():
    # alone: a=9 > b=6 > c=1. With a already in: a gives 0 (unique), c rises to 7 (> b=6).
    gain = {"a": lambda others: 0.0 if "a" in others else 9.0, "b": 6.0, "c": lambda others: 7.0 if "a" in others else 1.0}
    sockets = {100: (7, 100), 101: (8, 101)}
    probe = make(gain, sockets=sockets, budget=20)
    result = run_jewel_step(probe, LINES)
    assert [j.candidate.id for j in result.jewels] == ["a", "c"]
    # the second pick's own ranking saw the first jewel
    assert dict((c.id, s) for c, s in result.jewels[1].ranking)["a"] < dict((c.id, s) for c, s in result.jewels[1].ranking)["c"]


def test_freed_leaves_are_the_least_loss_and_never_on_the_new_path():
    # budget 6, 6 nodes in: socket 100's path (7, 100) needs 2 leaves freed. Leaves: 3 (5), 5 (2), 6 (8).
    # Least loss first: 5; then 4 becomes a leaf (10) so next is 3 (5), never 7/100 although they are leaves worth 0.
    probe = make({"a": 40.0, "b": 1.0, "c": 1.0}, budget=6, sockets={100: (7, 100)})
    result = run_jewel_step(probe, LINES, count_max=1)
    (jewel,) = result.jewels
    assert jewel.removed_leaves == (5, 3)
    assert not set(jewel.removed_leaves) & set(jewel.path)
    assert probe.allocated == {0, 1, 2, 4, 6, 7, 100}
    assert probe.points_over() == 0


def test_placed_jewel_socket_is_never_freed_for_the_second_jewel():
    # a cheap-to-lose jewel socket must stay although it is a leaf worth nothing
    sockets = {100: (7, 100), 101: (8, 101)}
    probe = make({"a": 40.0, "b": 39.0, "c": 38.0}, sockets=sockets, budget=7)
    result = run_jewel_step(probe, LINES)
    for jewel in result.jewels:
        assert jewel.socket_id in probe.allocated and jewel.socket_id in probe.jewels
        assert not set(jewel.removed_leaves) & {j.socket_id for j in result.jewels}


def test_repick_keeps_the_best_of_top10_and_current():
    lines = [Line(f"l{i}") for i in range(12)]
    gain = {l.id: float(i) for i, l in enumerate(lines)}  # on the pick l11 is best
    probe = make(gain, sockets={100: (7, 100)}, budget=20)
    result = run_jewel_step(probe, lines, count_max=1)
    (jewel,) = result.jewels
    assert jewel.candidate.id == "l11"
    # the build changes after the pick: now l5 is the best of everything, l0 is outside the top 10 and also huge
    gain.update({"l11": 1.0, "l5": 50.0, "l0": 99.0})
    (kept,) = repick_jewels(probe, [jewel])
    assert kept.candidate.id == "l5"  # l0 is rank 12 of the pick: never measured
    assert probe.jewels[100].id == "l5"
    assert kept.score_after > kept.score_before
    # when the current line is the best it stays
    (again,) = repick_jewels(probe, [kept])
    assert again.candidate.id == "l5"
    assert probe.jewels[100].id == "l5"


def test_log_line_and_measurement_count():
    probe = make({"a": 5.0, "b": 1.0, "c": 1.0}, budget=8)
    calls_before = probe.score_calls
    result = run_jewel_step(probe, LINES, count_max=1)
    assert result.measured == probe.score_calls - calls_before
    (jewel,) = result.jewels
    line = jewel_log_line(jewel, 4.0)
    assert line.startswith(f"jewel: socket {jewel.socket_id} 'a', score ")
    assert f"{jewel.measured} measured" in line and line.endswith(human_duration(4.0))
    assert isinstance(jewel, PlacedJewel)
