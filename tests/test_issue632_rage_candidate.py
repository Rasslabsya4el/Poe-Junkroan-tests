"""#632 unit 3: a candidate node that gains Rage on hit is judged with the Rage the ramp derives for it.

PoB hides the `multiplierRage` option until a Rage source is allocated, so a greedy trial scored under
the stage's config (made before the node existed) saw no Rage at all. The node is now routed through
the enabler hook like a charge generator (`_value_with_enabled` re-derives the lanes with the node
allocated), and once bought the lanes are re-judged (`after_apply_hook`).

Without PoB: the one regex (`ramp_inputs.grants_rage_on_hit`), the routing, the rejudge, the gate.
With PoB (mark `pob`): the derived `multiplierRage` of smite-s4 + candidate 55420.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.ramp_inputs import grants_rage_on_hit
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

from judging_fakes import BASE, _lanes, pob_judging
from judging_fakes import PobLanes
from test_tree_optimizer_speed import ALL_ON, S, _Pob

PROJECT_ROOT = Path(__file__).resolve().parents[1]

P_N, N = 20, 21
R = 55420


def test_the_helper_matches_the_rage_on_hit_lines_rage_stacks_counts_by_hits() -> None:
    graph = TreeGraph.load()
    assert grants_rage_on_hit("\n".join(graph.node(55420).stats))  # "Gain 1 Rage on Melee Hit"
    assert grants_rage_on_hit("\n".join(graph.node(50842).stats))  # "Gain 2 Rage on Melee Hit" + "Inherent Rage Loss starts 1 second later"
    assert grants_rage_on_hit("Gain 1 Rage on Hit with Axes")
    # the lines rage_stacks counts by something else, or not at all, are not enablers
    assert not grants_rage_on_hit("Gain 3 Rage when Hit by an Enemy")
    assert not grants_rage_on_hit("Gain 5 Rage on Hit with Retaliation Skills")
    assert not grants_rage_on_hit("Gain 1 Rage on Kill")
    assert not grants_rage_on_hit("10% increased Spell Damage")
    assert not grants_rage_on_hit("Every Rage also grants 1% increased Armour")


def _graph() -> TreeGraph:
    def node(node_id: int, name: str, kind: str, stats: tuple[str, ...] = ()) -> TreeNode:
        return TreeNode(node_id=node_id, name=name, kind=kind, stats=stats, ascendancy_name=None,
                        class_start_index=3 if kind == "class_start" else None)

    nodes = {
        S: node(S, "Witch", "class_start"),
        P_N: node(P_N, "pN", "normal"), N: node(N, "N", "notable", ("10% increased Spell Damage",)),
        R: node(R, "Rage on Hit", "normal", ("Gain 1 Rage on Melee Hit",)),
    }
    edges = [(S, P_N), (P_N, N), (S, R)]
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    return TreeGraph(tree_version="synthetic", nodes=nodes, adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=frozenset({P_N, N, R}), class_starts={"Witch": S})


class _RagePob(_Pob):
    """The speed rig's PoB with the Rage node worth the same as a notable."""

    def _value(self, nodes) -> float:
        return 1000.0 + 10.0 * len({n for n in nodes if n in (N, R)})


def test_a_rage_on_hit_candidate_reaches_the_enabler_and_the_rejudge_a_plain_node_does_not() -> None:
    graph = _graph()
    pob = _RagePob(graph, toggles=ALL_ON)  # every charge toggle on: only the Rage node can still enable anything
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph)
    asked: list[int] = []
    rejudged: list[int] = []
    opt.enabler_hook = lambda cand, trial: asked.append(cand.node_id)  # None: "nothing was enabled"
    opt.after_apply_hook = lambda cand: rejudged.append(cand.node_id)

    assert opt.generator_effects(R) == {None} and opt.generator_kinds([R]) == {"Rage"}
    assert opt.generator_effects(N) == set() and opt.generator_kinds([N]) == set()

    result = opt.allocate(3, allocated={S})

    assert asked == [R] and opt.hook_calls == 1  # N never reaches the hook: its PoB calls are the ones it had
    assert rejudged == [R]  # bought once; the lanes are re-derived with the Rage on the build
    assert {step.node_id for step in result.steps} == {N, R}


def test_a_rage_on_hit_node_a_step_behind_the_frontier_is_a_candidate_and_reaches_the_enabler() -> None:
    """The loop miss of #632: "Rage on Hit" sits behind a "Strength" (cost 2), and `TreeGraph.candidates` offers an
    ordinary node only on the frontier, so the node was never tried on its own; node:55420 in the trace counted
    the notable 15543 whose path runs through it. The same graph with the Rage node a step behind."""

    graph = _graph()
    behind = 22
    graph.nodes[behind] = TreeNode(node_id=behind, name="Strength", kind="normal", stats=("+10 to Strength",), ascendancy_name=None, class_start_index=None)
    graph.adjacency.clear()
    for a, b in [(S, P_N), (P_N, N), (S, behind), (behind, R)]:
        graph.adjacency[a] = frozenset(graph.adjacency.get(a, frozenset()) | {b})
        graph.adjacency[b] = frozenset(graph.adjacency.get(b, frozenset()) | {a})
    graph = TreeGraph(tree_version="synthetic", nodes=graph.nodes, adjacency=graph.adjacency,
                      allocatable=frozenset({P_N, N, R, behind}), class_starts={"Witch": S})
    assert R not in {c.node_id for c in graph.candidates({S}, max_depth=6)}  # the old rule: not on the frontier, not a payoff kind
    pob = _RagePob(graph, toggles=ALL_ON)
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph)
    assert opt.rage_source_nodes() == {R}
    asked: list[int] = []
    opt.enabler_hook = lambda cand, trial: asked.append(cand.node_id)
    opt.after_apply_hook = lambda cand: None

    opt.allocate(3, allocated={S})

    assert asked == [R]  # offered at cost 2 and judged by the hook; before: never asked


def _pipeline(calls: list[str], config: dict, lanes_inputs: dict, kinds: set[str]):
    class _Pob:
        def config_inputs(self):
            calls.append("config_inputs")
            return dict(config)

        def export_xml(self):
            calls.append("export_xml")
            return "xml"

        def mutate_nodes(self, add=None, mastery_effects=None):
            calls.append("mutate_nodes")
            return {"added_node_ids": list(add or ())}

        def stats(self, keys):
            calls.append("stats")
            return {key: 0.0 for key in keys} | {"dps": 321.0}

        def load_xml(self, xml):
            calls.append("load_xml")

    derived = _lanes(lanes_inputs)

    class _RecordingLanes(PobLanes):
        def read(self):
            calls.append("derive_config")
            return derived

        def write(self, _skeleton, _lanes) -> None:
            calls.append("apply_config")

    p = BuildPipeline.__new__(BuildPipeline)
    p.pob, p.log = _Pob(), lambda _m: None
    p.judging = pob_judging(p, lanes=_RecordingLanes(p.pob))
    tree = SimpleNamespace(objective=Objective(maximize="dps"), CHARGE_KINDS=("Power",), proof_holders={},
                           generator_kinds=lambda nodes, mastery: kinds)
    p.objective = BASE
    p.judging.attach("tree_construction", tree)
    return p, tree


SKELETON = SimpleNamespace(bandit="None", pantheon_major="Lunaris", pantheon_minor="None", user_config={}, tuned_choices={})
CAND = SimpleNamespace(node_id=R, name="Rage on Hit")


def test_the_enabler_scores_a_rage_node_under_the_rage_the_lanes_derive_with_it() -> None:
    calls: list[str] = []
    p, tree = _pipeline(calls, config={"usePowerCharges": True}, lanes_inputs={"usePowerCharges": True, "multiplierRage": 5}, kinds={"Rage"})
    score = p._value_with_enabled(SKELETON, tree, CAND, {})
    assert score.value == 321.0
    assert calls == ["config_inputs", "export_xml", "mutate_nodes", "derive_config", "apply_config", "stats", "load_xml"]


def test_a_rage_node_that_changes_nothing_in_the_lanes_is_not_rewritten() -> None:
    calls: list[str] = []
    p, tree = _pipeline(calls, config={"multiplierRage": 5}, lanes_inputs={"multiplierRage": 5}, kinds={"Rage"})
    assert p._value_with_enabled(SKELETON, tree, CAND, {}) is None
    assert calls == ["config_inputs", "export_xml", "mutate_nodes", "derive_config", "load_xml"]


def test_a_plain_node_takes_the_calls_it_took_before_and_never_derives() -> None:
    calls: list[str] = []
    p, tree = _pipeline(calls, config={}, lanes_inputs={"multiplierRage": 5}, kinds=set())
    assert p._value_with_enabled(SKELETON, tree, CAND, {}) is None
    assert calls == ["config_inputs", "export_xml", "mutate_nodes", "load_xml"]


# -- the bug-specific number (PoB) ---------------------------------------------

SMITE_S4 = PROJECT_ROOT / "artifacts" / "benchmark" / "20261005-1220-gate-20261005" / "smite-s4.pob.txt"


@pytest.mark.pob
@pytest.mark.skipif(not SMITE_S4.is_file(), reason="the smite-s4 gate build is not present")
def test_smite_s4_without_a_rage_source_plus_node_55420_derives_multiplier_rage_5(tmp_path: Path) -> None:
    from junkroan.optimizer.config_rules import derive_config
    from junkroan.optimizer.ramp_inputs import grants_rage_on_hit as rage_on_hit
    from junkroan.pob.session import PobSession, decode_import_code

    seen: dict[str, object] = {}
    with PobSession(run_id="test-632-rage-candidate", artifacts_root=tmp_path) as pob:
        pob.load_xml(decode_import_code(SMITE_S4.read_text(encoding="utf-8").strip()))
        graph = TreeGraph.load()
        owned = [int(n) for n in pob.read_state()["tree_state"]["user_allocated_node_ids"]]
        sources = [n for n in owned if graph.node(n) and rage_on_hit("\n".join(graph.node(n).stats))]
        if sources:
            pob.mutate_nodes(remove=sources)
        assert 55420 not in [int(n) for n in pob.read_state()["tree_state"]["user_allocated_node_ids"]]
        seen["without"] = derive_config(pob).conservative.inputs.get("multiplierRage")
        assert seen["without"] in (None, 0)  # the option is hidden, the stage's config holds no Rage

        tree = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph)
        tree.enabler_hook = lambda cand, trial: None
        pipeline = BuildPipeline.__new__(BuildPipeline)
        pipeline.pob, pipeline.log = pob, lambda _m: None
        pipeline.judging = pob_judging(pipeline, lanes=_Capturing(pob, seen))
        pipeline.objective = tree.objective
        pipeline.judging.attach("tree_construction", tree)
        plain = tree.objective.score(pob.trial_stats([{"add": [55420]}], tree.objective.stat_keys)[0]["stats"])
        enabled = pipeline._value_with_enabled(SKELETON, tree, SimpleNamespace(node_id=55420, name="Rage on Hit"), {})

    print(f"smite-s4 without Rage: multiplierRage {seen['without']}; candidate 55420 derived {seen['with']}; "
          f"CombinedDPS plain trial {plain.value:,.2f} vs judged with the Rage {enabled.value:,.2f}")
    assert seen["with"] == 5  # floor(min(5.04 hits/s, 1 / 0.5 s) x 2.5 s)
    assert enabled is not None and enabled.value > plain.value


class _Capturing(PobLanes):
    """The real lanes, the derived `multiplierRage` kept."""

    def __init__(self, pob, seen: dict) -> None:
        super().__init__(pob)
        self._seen = seen

    def read(self):
        derived = super().read()
        self._seen["with"] = derived.conservative.inputs.get("multiplierRage")
        return derived
