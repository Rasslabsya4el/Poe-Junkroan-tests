"""#430 witness (kind A, D113): with the rail's cap 1 the best +30 attribute node is kept and a second is refused; no PoB."""

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

S, A, B = 1, 2, 3  # A: +30 Strength (best), B: +30 Dexterity (second best)
GAIN = {A: 50.0, B: 30.0}


def _graph() -> TreeGraph:
    nodes = {
        S: TreeNode(S, "Witch", "class_start", (), None, 3),
        A: TreeNode(A, "Might", "notable", ("+30 to Strength",), None, None),
        B: TreeNode(B, "Agility", "notable", ("+30 to Dexterity",), None, None),
    }
    return TreeGraph(tree_version="synthetic", nodes=nodes,
                     adjacency={S: frozenset({A, B}), A: frozenset({S}), B: frozenset({S})},
                     allocatable=frozenset({A, B}), class_starts={"Witch": S})


class _Pob:
    def __init__(self):
        self.allocated = {S}
        self._snaps = {}

    def config_inputs(self):
        return {}

    def tree_light(self):
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.allocated - {S}), "mastery_effect_ids": []}

    def _value(self, nodes):
        return 1000.0 + sum(GAIN[n] for n in nodes if n in GAIN)

    def trial_stats(self, trials, keys, mode="fast"):
        out = []
        for t in trials:
            added = [int(n) for n in (t.get("add") or ()) if int(n) not in self.allocated]
            removed = [int(n) for n in (t.get("remove") or ()) if int(n) in self.allocated]
            nodes = (self.allocated | set(added)) - set(removed)
            out.append({"ok": True, "stats": {"CombinedDPS": self._value(nodes)}, "added_node_ids": added, "removed_node_ids": removed})
        return out

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None):
        gone = {int(n) for n in (remove or ()) if int(n) in self.allocated}
        self.allocated -= gone
        added = [int(n) for n in (add or ()) if int(n) not in self.allocated]
        self.allocated |= set(added)
        return {"added_node_ids": added, "removed_node_ids": sorted(gone), "allocated_node_ids": sorted(self.allocated - {S}),
                "removed_mastery_effects": [], "points_used": len(added)}

    def stats(self, keys):
        return {"CombinedDPS": self._value(self.allocated)}

    def export_xml(self):
        token = f"x{len(self._snaps)}"
        self._snaps[token] = set(self.allocated)
        return token

    def load_xml(self, token):
        self.allocated = set(self._snaps[token])


def _run(cap):
    graph, pob = _graph(), _Pob()
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph, attribute_requirement_nodes_max=cap)
    opt.allocate(2, allocated={S})
    return pob.allocated - {S}


def test_cap_one_keeps_the_best_attribute_node_and_refuses_the_second():
    assert _run(1) == {A}


def test_without_the_cap_both_are_taken():
    assert _run(None) == {A, B}
