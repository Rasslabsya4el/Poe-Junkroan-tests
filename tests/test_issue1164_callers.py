"""#1164 rule 2: every caller that removes a `removable_leaves` pick FOR REAL checks the real `removed_node_ids`.

`TreeGraph.removable_leaves` is the graph's estimate; PoB's `remove_nodes` cascades by its own connectivity (from the
build's own class start). When they disagree a "leaf" takes more than itself away (92 nodes once, #1164). The callers:

* `jewel_step._free_points` (the jewel step frees points leaf by leaf) over `PobJewelProbe.remove`: refuses a removal
  of more than one node, puts the tree back, takes the next leaf;
* `TracingJewelProbe.remove` (jewel_trace.py) forwards the probe's answer, so the step above sees it;
* `TreeOptimizer.refine` removes the leaves of a swap for real and already refuses a cascade (`cascaded`,
  tree_optimizer.py): pinned here, green on main.

No PoB: fake sessions whose removal reports 2+ nodes while the graph names a single leaf.
"""

from __future__ import annotations

from junkroan.optimizer.jewel_probe import PobJewelProbe
from junkroan.optimizer.jewel_step import _Counter, _free_points
from junkroan.optimizer.jewel_trace import TracingJewelProbe
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

START = 1
TRUNK, LEAF_A, LEAF_B = 20, 21, 22  # START - TRUNK - LEAF_A ; START - LEAF_B
LEAF_C = 23  # START - LEAF_C
VALUE = {TRUNK: 5.0, LEAF_A: 9.0, LEAF_B: 1.0, LEAF_C: 3.0}  # what each node is worth: LEAF_B is the cheapest to lose


def _node(node_id: int, kind: str = "normal") -> TreeNode:
    return TreeNode(node_id=node_id, name=str(node_id), kind=kind, stats=(), ascendancy_name=None,
                    class_start_index=3 if kind == "class_start" else None)


def _graph(edges: list[tuple[int, int]], allocatable: set[int]) -> TreeGraph:
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    nodes = {n: _node(n, "class_start" if n == START else "normal") for n in adjacency}
    return TreeGraph(tree_version="synthetic", nodes=nodes, adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=frozenset(allocatable), class_starts={"Templar": START})


class _Session:
    """A session the jewel probe talks to. Removing a node in `cascade` takes its dependants with it, as PoB's own
    connectivity does where the graph's estimate was wrong. `trial_sees_cascade`: whether a PoB trial of a removal
    reports the dependants too (a full-mode trial does; a fast one does not)."""

    def __init__(self, allocated: set[int], cascade: dict[int, tuple[int, ...]], *, trial_sees_cascade: bool = False) -> None:
        self.allocated = set(allocated)
        self.cascade = cascade
        self.trial_sees_cascade = trial_sees_cascade
        self.removals: list[list[int]] = []  # every remove_nodes call
        self.loaded: list[str] = []
        self._xml: dict[str, set[int]] = {}

    def _removed_by(self, node_id: int) -> list[int]:
        return sorted(({node_id} | set(self.cascade.get(node_id, ()))) & self.allocated)

    def tree_light(self) -> dict:
        return {"class_id": "Templar", "user_allocated_node_ids": sorted(self.allocated - {START}), "mastery_effect_ids": []}

    def socketed_jewels(self) -> dict:
        return {}

    def stats(self, keys) -> dict:
        return {"CombinedDPS": sum(VALUE[n] for n in self.allocated if n in VALUE)}

    def export_xml(self) -> str:
        token = f"xml{len(self._xml)}"
        self._xml[token] = set(self.allocated)
        return token

    def load_xml(self, token: str) -> None:
        self.loaded.append(token)
        self.allocated = set(self._xml[token])

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        out = []
        for trial in trials:
            node_id = int(trial["remove"][0])
            gone = self._removed_by(node_id) if self.trial_sees_cascade else [node_id]
            out.append({"ok": True, "stats": {"CombinedDPS": sum(VALUE[n] for n in self.allocated - set(gone) if n in VALUE)},
                        "removed_node_ids": gone, "added_node_ids": []})
        return out

    def remove_nodes(self, node_ids) -> dict:
        self.removals.append([int(n) for n in node_ids])
        gone = sorted({g for n in node_ids for g in self._removed_by(int(n))})
        self.allocated -= set(gone)
        return {"removed_node_ids": gone, "added_node_ids": [], "allocated_node_ids": sorted(self.allocated - {START}),
                "removed_mastery_effects": [], "points_used": len(self.allocated) - 1}

    def mutate_nodes(self, add=(), remove=(), mastery_effects=None) -> dict:
        self.allocated -= {int(n) for n in remove}
        self.allocated |= {int(n) for n in add}
        return {"removed_node_ids": [], "added_node_ids": [int(n) for n in add],
                "allocated_node_ids": sorted(self.allocated - {START}), "points_used": len(self.allocated) - 1}

    def cluster_graph(self, socket: int) -> list:
        return []


def _probe(session: _Session, graph: TreeGraph, *, budget: int) -> PobJewelProbe:
    return PobJewelProbe(session, lambda: Objective(maximize="CombinedDPS"), graph, points=budget)


def _jewel_graph() -> TreeGraph:
    return _graph([(START, TRUNK), (TRUNK, LEAF_A), (START, LEAF_B)], {TRUNK, LEAF_A, LEAF_B})


def test_jewel_step_refuses_a_leaf_whose_real_removal_takes_more_than_itself() -> None:
    """LEAF_B is the cheapest leaf by the trial, but PoB's real removal of it also takes LEAF_A (the trial did not see
    it): the step puts the tree back and frees the next leaf alone."""

    session = _Session({START, TRUNK, LEAF_A, LEAF_B}, {LEAF_B: (LEAF_A,)})
    probe = _probe(session, _jewel_graph(), budget=2)  # 3 points held, 2 allowed: one point to free
    assert probe.removable_leaves() == [LEAF_A, LEAF_B]

    removed = _free_points(probe, _Counter(probe), keep=set())

    assert session.removals == [[LEAF_B], [LEAF_A]]  # LEAF_B tried first (cheapest), refused, then LEAF_A alone
    assert removed == [LEAF_A]
    assert session.allocated == {START, TRUNK, LEAF_B}  # LEAF_B is back, only LEAF_A is gone


def test_jewel_step_stops_when_every_leaf_cascades() -> None:
    """The one leaf the graph names takes the trunk with it in PoB: nothing can be freed, the answer is 'budget cannot
    be met' (None) and the build is as it was."""

    graph = _graph([(START, TRUNK), (TRUNK, LEAF_A)], {TRUNK, LEAF_A})
    session = _Session({START, TRUNK, LEAF_A}, {LEAF_A: (TRUNK,)}, trial_sees_cascade=True)
    probe = _probe(session, graph, budget=1)
    assert probe.removable_leaves() == [LEAF_A]

    assert _free_points(probe, _Counter(probe), keep=set()) is None
    assert session.allocated == {START, TRUNK, LEAF_A}


def test_the_probe_reports_how_many_nodes_the_real_removal_took() -> None:
    session = _Session({START, TRUNK, LEAF_A, LEAF_B}, {LEAF_B: (LEAF_A,)})
    probe = _probe(session, _jewel_graph(), budget=2)
    assert probe.remove(LEAF_A) == 1
    assert probe.remove(LEAF_B) == 1  # LEAF_A is already gone: PoB takes only what is still there


def test_a_reply_without_the_removed_list_is_not_known_not_one_node() -> None:
    session = _Session({START, TRUNK, LEAF_A, LEAF_B}, {})
    session.remove_nodes = lambda node_ids: {"allocated_node_ids": []}  # no `removed_node_ids` key
    assert _probe(session, _jewel_graph(), budget=2).remove(LEAF_A) is None


def test_jewel_step_refuses_a_removal_whose_count_is_not_known() -> None:
    """The probe cannot say what PoB took: the leaf is put back and refused like a cascade, never read as one node."""

    probe = _CountingProbe({})
    real_remove = probe.remove
    probe.remove = lambda node_id: (real_remove(node_id), None)[1] if node_id == 1 else real_remove(node_id)
    assert _free_points(probe, _Counter(probe), keep=set()) == [3]
    assert probe.allocated == {1, 2}


def test_a_cascading_leaf_is_removed_for_real_at_most_once_per_call() -> None:
    """Two points to free; LEAF_B (the cheapest) cascades. The batch path never tries it again after its refusal."""

    graph = _graph([(START, TRUNK), (TRUNK, LEAF_A), (START, LEAF_B), (START, LEAF_C)], {TRUNK, LEAF_A, LEAF_B, LEAF_C})
    session = _Session({START, TRUNK, LEAF_A, LEAF_B, LEAF_C}, {LEAF_B: (TRUNK,)})
    probe = _probe(session, graph, budget=2)  # 4 points held, 2 allowed: two to free

    removed = _free_points(probe, _Counter(probe), keep=set())

    assert [call[0] for call in session.removals].count(LEAF_B) == 1
    assert removed == [LEAF_C, LEAF_A] and session.allocated == {START, TRUNK, LEAF_B}


def test_one_by_one_path_removes_a_cascading_leaf_at_most_once_per_call() -> None:
    probe = _CountingProbe({1: 3})
    probe.scores = {1: 1.0, 2: 9.0, 3: 5.0, 4: 0.5}
    probe.allocated = {1, 2, 3, 4}  # budget 2: two to free
    removes: list[int] = []
    real_remove = probe.remove
    probe.remove = lambda node_id: (removes.append(node_id), real_remove(node_id))[1]

    freed = _free_points(probe, _Counter(probe), keep=set())

    assert freed == [4, 3]
    assert removes.count(1) == 1  # measured once while scoring (that removal was real), never again


def test_the_tracing_probe_forwards_the_removal_count() -> None:
    session = _Session({START, TRUNK, LEAF_A, LEAF_B}, {LEAF_B: (LEAF_A,)})
    traced = TracingJewelProbe(_probe(session, _jewel_graph(), budget=2))
    assert traced.remove(LEAF_B) == 2


def test_jewel_step_through_the_tracing_probe_also_refuses() -> None:
    session = _Session({START, TRUNK, LEAF_A, LEAF_B}, {LEAF_B: (LEAF_A,)})
    traced = TracingJewelProbe(_probe(session, _jewel_graph(), budget=2))

    assert _free_points(traced, _Counter(traced), keep=set()) == [LEAF_A]
    assert session.allocated == {START, TRUNK, LEAF_B}


class _CountingProbe:
    """A probe without `leaf_scores` (the one-by-one measure path): `remove` answers how many nodes it took."""

    def __init__(self, cascade: dict[int, int]) -> None:
        self.allocated = {1, 2, 3}
        self.cascade = cascade
        self.scores = {1: 1.0, 2: 9.0, 3: 5.0}

    def score(self) -> float:
        return sum(self.scores[n] for n in self.allocated)

    def snapshot(self):
        return frozenset(self.allocated)

    def restore(self, snap) -> None:
        self.allocated = set(snap)

    def removable_leaves(self) -> list[int]:
        return sorted(self.allocated)

    def remove(self, node_id: int) -> int:
        self.allocated.discard(node_id)
        return self.cascade.get(node_id, 1)

    def points_over(self) -> int:
        return len(self.allocated) - 2


def test_jewel_step_one_by_one_path_skips_a_cascading_leaf() -> None:
    probe = _CountingProbe({1: 3})  # removing 1 would take 3 nodes: the cheapest by score, yet never freed
    assert _free_points(probe, _Counter(probe), keep=set()) == [3]
    assert probe.allocated == {1, 2}


# -- refine: the swap's leaves are removed for real, a cascade is refused (already so on main) ------------------


def test_refine_restores_the_tree_and_drops_the_swap_when_the_real_removal_cascades() -> None:
    from test_tree_optimizer_speed import ALL_ON, F, N, P, P_F, P_N, P_P, S, _Pob
    from test_tree_optimizer_speed import _graph as speed_graph

    class _CascadingPob(_Pob):
        """F is worth 50, N and P 10 each. Removing N for real also takes its path node P_N (the graph said leaf)."""

        def _value(self, nodes) -> float:
            return 1000.0 + 10.0 * len({n for n in nodes if n in (N, P)}) + 50.0 * (F in nodes)

        def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
            if remove and N in remove:
                remove = [*remove, P_N]
            return super().mutate_nodes(add, remove, mastery_effects)

    graph = speed_graph()
    pob = _CascadingPob(graph, toggles=ALL_ON, allocated={S, P_N, N, P_P, P})
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph)

    result = opt.refine(max_rounds=2)

    assert result.steps == []  # the swap F for {N, P} was refused, not kept
    assert pob.allocated == {S, P_N, N, P_P, P}  # the tree is as it was
    assert opt.skipped_errors.get("swap did not verify", 0) >= 1
    assert F not in pob.allocated and P_F not in pob.allocated

