"""Cluster candidates (ROADMAP 7.2 rule 5), without PoB.

A synthetic tree: the class start S, three notables A, B, C each behind their own one-point
path node, and one plain frontier node F. The fake PoB pays 10 per notable, 5 for F and a
synergy bonus of 100 once all three notables are allocated -- the payoff no single-node
greedy can see. The optimizer must take A, B and C as one cluster step when the bonus
exists, and never when the cluster only ties the singles per point.
"""

from __future__ import annotations

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

S, F = 1, 10
P_A, A = 20, 21
P_B, B = 30, 31
P_C, C = 40, 41
NOTABLES = (A, B, C)
IMPALE = ("ailment", "impale")


def _graph() -> TreeGraph:
    def node(node_id: int, name: str, kind: str) -> TreeNode:
        return TreeNode(node_id=node_id, name=name, kind=kind, stats=(), ascendancy_name=None, class_start_index=3 if kind == "class_start" else None)

    nodes = {
        S: node(S, "Witch", "class_start"),
        F: node(F, "F", "normal"),
        P_A: node(P_A, "pA", "normal"),
        A: node(A, "A", "notable"),
        P_B: node(P_B, "pB", "normal"),
        B: node(B, "B", "notable"),
        P_C: node(P_C, "pC", "normal"),
        C: node(C, "C", "notable"),
    }
    edges = [(S, F), (S, P_A), (P_A, A), (S, P_B), (P_B, B), (S, P_C), (P_C, C)]
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    return TreeGraph(
        tree_version="synthetic",
        nodes=nodes,
        adjacency={k: frozenset(v) for k, v in adjacency.items()},
        allocatable=frozenset({F, P_A, A, P_B, B, P_C, C}),
        class_starts={"Witch": S},
    )


class _Pob:
    """Values: 1000 + 10 per allocated notable + 5 for F + `synergy` once all three notables are in."""

    def __init__(self, graph: TreeGraph, *, synergy: float = 100.0) -> None:
        self.graph = graph
        self.allocated = {S}
        self.synergy = synergy
        self.rounds: list[list[dict]] = []  # the trial list of every trial_stats round trip

    def _added(self, targets) -> list[int]:
        costs = self.graph.bfs_costs(self.allocated, max_depth=6)
        added: list[int] = []
        for target in targets:
            for node_id in costs[int(target)][1]:
                if node_id not in self.allocated and node_id not in added:
                    added.append(node_id)
        return added

    def _value(self, nodes) -> float:
        nodes = set(nodes)
        value = 1000.0 + 10.0 * len(nodes & set(NOTABLES)) + (5.0 if F in nodes else 0.0)
        if self.synergy and set(NOTABLES) <= nodes:
            value += self.synergy
        return value

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        self.rounds.append([dict(t) for t in trials])
        out = []
        for trial in trials:
            added = self._added(trial.get("add") or ())
            out.append({"ok": True, "stats": {"CombinedDPS": self._value(self.allocated | set(added))}, "added_node_ids": list(added)})
        return out

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        added = self._added(add or ())
        self.allocated |= set(added)
        return {"added_node_ids": list(added), "points_used": len(added)}

    def stats(self, keys) -> dict:
        return {"CombinedDPS": self._value(self.allocated)}

    def read_state(self) -> dict:
        return {"tree_state": {"mastery_effect_ids": []}}


def _tags(node_id: int) -> set[tuple[str, str]]:
    return {IMPALE} if int(node_id) in NOTABLES else set()


def _optimizer(pob: _Pob, graph: TreeGraph, **kwargs) -> TreeOptimizer:
    return TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph, cluster_tags=_tags, **kwargs)


def _add_sizes(pob: _Pob) -> list[int]:
    return [len(trial.get("add") or ()) for round_ in pob.rounds for trial in round_]


def test_cluster_is_taken_as_one_step_when_it_beats_every_single() -> None:
    graph = _graph()
    pob = _Pob(graph)
    result = _optimizer(pob, graph, cluster_candidates=True).allocate(6, allocated={S})

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.kind == "cluster"
    assert step.name == "cluster ailment=impale: A + B + C"
    assert step.node_id == A  # the first member
    assert step.cost == 6 and sorted(step.added_node_ids) == [P_A, A, P_B, B, P_C, C]
    assert step.mastery_effect is None
    assert (step.before.value, step.after.value) == (1000.0, 1130.0)  # +130 for 6 points; a single is +10 for 2
    assert result.points_spent == 6
    assert pob.allocated == {S, P_A, A, P_B, B, P_C, C}


def test_no_cluster_trial_when_the_union_does_not_fit_the_budget() -> None:
    graph = _graph()
    pob = _Pob(graph)
    result = _optimizer(pob, graph, cluster_candidates=True).allocate(3, allocated={S})

    assert max(_add_sizes(pob)) == 1  # the union of A, B, C costs 6 > 3: never proposed
    assert not any(s.kind == "cluster" for s in result.steps)
    assert result.points_spent == 3

    plain = _Pob(graph)
    assert [(s.node_id, s.cost) for s in _optimizer(plain, graph).allocate(3, allocated={S}).steps] == [(s.node_id, s.cost) for s in result.steps]


def test_flag_off_is_the_greedy_of_today() -> None:
    graph = _graph()
    off = _Pob(graph)
    explicit = _optimizer(off, graph, cluster_candidates=False).allocate(6, allocated={S})
    assert max(_add_sizes(off)) == 1  # no trial ever carries more than one node

    graph2 = _graph()
    never_set = _Pob(graph2)
    default = _optimizer(never_set, graph2).allocate(6, allocated={S})
    fields = lambda r: [(s.node_id, s.name, s.kind, s.cost, tuple(s.added_node_ids), s.before.value, s.after.value) for s in r.steps]
    assert fields(explicit) == fields(default)
    assert not any(s.kind == "cluster" for s in explicit.steps)


def test_a_cluster_that_only_ties_the_singles_is_not_taken() -> None:
    graph = _graph()
    pob = _Pob(graph, synergy=0.0)  # 10 per notable and nothing for taking all three
    result = _optimizer(pob, graph, cluster_candidates=True).allocate(6, allocated={S})

    assert max(_add_sizes(pob)) == 3  # the cluster was proposed...
    assert not any(s.kind == "cluster" for s in result.steps)  # ...and lost the tie to the singles
    assert all(len(s.added_node_ids) <= 2 for s in result.steps)


def test_cluster_max_size_caps_the_members() -> None:
    graph = _graph()
    pob = _Pob(graph)
    _optimizer(pob, graph, cluster_candidates=True, cluster_max_size=2).allocate(6, allocated={S})

    clusters = [t["add"] for t in pob.rounds[0] if len(t["add"]) > 1]
    assert clusters == [[A, B]]  # the two cheapest by (cost, node_id)


def test_cluster_max_trials_zero_proposes_nothing() -> None:
    graph = _graph()
    pob = _Pob(graph)
    result = _optimizer(pob, graph, cluster_candidates=True, cluster_max_trials=0).allocate(6, allocated={S})

    assert max(_add_sizes(pob)) == 1
    assert not any(s.kind == "cluster" for s in result.steps)


def test_default_cluster_tags_come_from_the_passives_corpus() -> None:
    from junkroan.optimizer.tree_optimizer import corpus_cluster_tags

    skewering = next(n for n in TreeGraph.load().nodes.values() if n.name == "Merciless Skewering")
    tags = corpus_cluster_tags(skewering.node_id)
    assert ("ailment", "impale") in tags and ("mechanic", "attack") in tags
    assert all(facet in ("ailment", "charge", "mechanic", "scaling_stat") for facet, _v in tags)  # no node_kind / damage_type
    assert corpus_cluster_tags(-1) == set()
