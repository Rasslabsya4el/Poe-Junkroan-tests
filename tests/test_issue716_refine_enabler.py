"""#716: `TreeOptimizer.refine` judges a Rage-on-hit node with the Rage it grants, as the greedy pass does (#632).

PoB hides the `multiplierRage` option until a Rage source is allocated, so a refine add or swap trial of node
55420 ("Gain 1 Rage on Melee Hit") measured under the config of the build before the node was scored with no
Rage at all. `refine` had no enabler-hook call (the gate lived inline in `allocate`); it now goes through the
same `TreeOptimizer._judge_with_enablers`, and a swap trial's `remove` reaches `_value_with_enabled`, so the
hook judges the tree the swap leaves.

PoB-free: a fake session whose DPS is worth 100 per point of `multiplierRage`, whose lanes derive
`multiplierRage` 5 (the 632 formula value) once the node is allocated, under the production
`BuildPipeline._value_with_enabled`.
"""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.judging import PobLanes
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

from judging_fakes import BASE, _lanes, pob_judging
from test_tree_optimizer_speed import ALL_ON, S, _Pob

P_N, N = 20, 21
LEAF = 22  # a plain node worth nothing: the leaf the swap drops
R = 55420
RAGE = 5  # floor(min(hits/s, 1 / 0.5 s) x 2.5 s): the value the 632 ramp derives for the node
SKELETON = SimpleNamespace(bandit="None", pantheon_major="Lunaris", pantheon_minor="None", user_config={}, tuned_choices={})


def _graph() -> TreeGraph:
    def node(node_id: int, name: str, kind: str, stats: tuple[str, ...] = ()) -> TreeNode:
        return TreeNode(node_id=node_id, name=name, kind=kind, stats=stats, ascendancy_name=None,
                        class_start_index=3 if kind == "class_start" else None)

    nodes = {
        S: node(S, "Witch", "class_start"),
        P_N: node(P_N, "pN", "normal"), N: node(N, "N", "notable", ("10% increased Spell Damage",)),
        LEAF: node(LEAF, "Leaf", "normal", ("+5 to Strength",)),
        R: node(R, "Rage on Hit", "normal", ("Gain 1 Rage on Melee Hit",)),
    }
    edges = [(S, P_N), (P_N, N), (S, LEAF), (S, R)]
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    return TreeGraph(tree_version="synthetic", nodes=nodes, adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=frozenset({P_N, N, LEAF, R}), class_starts={"Witch": S})


class _RagePob(_Pob):
    """Value 1000 + 10 per notable + 100 per point of `multiplierRage` the config holds; the config holds none
    until the lanes are written (PoB hides the option while no source is allocated)."""

    def __init__(self, graph: TreeGraph, **kwargs) -> None:
        super().__init__(graph, **kwargs)
        self.rage = 0
        self.rage_trials: list[int] = []  # the multiplierRage every trial_stats call measured under

    def config_inputs(self) -> dict:
        return {**self.toggles, "multiplierRage": self.rage}

    def _value(self, nodes) -> float:
        return 1000.0 + 10.0 * len({n for n in nodes if n == N}) + 100.0 * self.rage

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        self.rage_trials.append(self.rage)
        return super().trial_stats(trials, keys, mode)

    def export_xml(self) -> str:
        token = super().export_xml()
        self._snapshots[token] = (*self._snapshots[token], self.rage)
        return token

    def load_xml(self, token: str) -> None:
        super().load_xml(token)
        self.rage = self._snapshots[token][2]


class _RageLanes(PobLanes):
    """The lane read derives `multiplierRage` 5 with the node allocated, 0 without; the write puts it on the session."""

    def read(self):
        return _lanes({**self.pob.toggles, "multiplierRage": RAGE if R in self.pob.allocated else 0})

    def write(self, _skeleton, lanes) -> None:
        self.pob.rage = lanes.conservative.inputs.get("multiplierRage") or 0


def _rig(allocated: set[int]):
    graph = _graph()
    pob = _RagePob(graph, toggles=ALL_ON, allocated=allocated)
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph)
    logged: list[str] = []
    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.log = pob, logged.append
    p.judging = pob_judging(p, lanes=_RageLanes(pob))
    p.objective = BASE
    p.judging.attach("tree_construction", opt)
    opt.enabler_hook = lambda cand, trial: p._value_with_enabled(SKELETON, opt, cand, trial)
    opt.after_apply_hook = lambda _cand: p.judging.lanes.write(SKELETON, p.judging.lanes.read())
    return pob, opt, logged


def test_a_refine_swap_to_the_rage_node_is_judged_with_the_rage_it_grants() -> None:
    pob, opt, logged = _rig({S, P_N, N, LEAF})
    assert pob.rage == 0 and opt.generator_effects(R) == {None}

    result = opt.refine(max_rounds=1)

    # the plain trial of the swap is worth nothing (the config before the node holds no Rage): only the hook buys it
    assert [(s.node_id, s.removed_node_ids) for s in result.steps] == [(R, [LEAF])]
    assert opt.hook_calls >= 1
    assert f"generator Rage on Hit: judged with multiplierRage 0 -> {RAGE}: 1,510" in " ".join(logged)
    assert pob.rage == RAGE  # bought: the lanes now hold the Rage the node derives
    assert result.final_score.value == 1010.0 + 100.0 * RAGE


def test_the_hook_of_a_swap_trial_judges_the_tree_the_swap_leaves() -> None:
    """`remove` of the swap trial reaches the session: the leaf it drops is gone when the lanes are read."""

    pob, opt, logged = _rig({S, P_N, N, LEAF})
    mutations = pob.mutations
    plain = opt.objective.score({"CombinedDPS": 1010.0})

    judged = opt.enabler_hook(SimpleNamespace(node_id=R, name="Rage on Hit"), {"add": [R], "remove": [LEAF]})

    assert judged is not None and judged.value == plain.value + 100.0 * RAGE
    assert mutations[0] == ((R,), (LEAF,))  # added and dropped in one mutation, as the swap does
    assert pob.allocated == {S, P_N, N, LEAF} and pob.rage == 0  # the trial context is given back
