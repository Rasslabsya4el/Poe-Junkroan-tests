"""The tree optimizer's repeated-work rules (speed audit 2026-09-18), without PoB.

Five behaviours, each of which must not change a single PoB number:

* the enabler hook is asked once per (config generation, node, effect), and never at all for a
  candidate that cannot turn a charge toggle from off to on;
* a hanging subtree already proven not to pay on this exact tree is not tried again;
* a tree-only revert goes through the inverse mutation and falls back to the XML reload whenever
  the tree does not come back node for node;
* the path-swap pass refuses to start a candidate that would overrun its budget;
* a trial PoB answered on the build as it stands is not asked again, and a refine round that
  measured the whole neighbourhood and found no swap is not bought twice.

The synthetic tree: class start S, a plain notable N, a notable P that grants power charges and a
notable F that grants frenzy charges, each behind its own one-point path node.
"""

from __future__ import annotations

import pytest

from junkroan.optimizer.objective import Objective, Score
from junkroan.optimizer.pipeline import BuildPipeline
from junkroan.optimizer.tree_graph import Candidate, TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer, attribute_requirement_node_ids

from judging_fakes import pob_judging

S = 1
P_N, N = 20, 21
P_P, P = 30, 31
P_F, F = 40, 41
ALL_ON = {"usePowerCharges": True, "useFrenzyCharges": True, "useEnduranceCharges": True}
POWER_ON = {"usePowerCharges": True, "useFrenzyCharges": False, "useEnduranceCharges": False}


def _graph() -> TreeGraph:
    def node(node_id: int, name: str, kind: str, stats: tuple[str, ...] = ()) -> TreeNode:
        return TreeNode(node_id=node_id, name=name, kind=kind, stats=stats, ascendancy_name=None,
                        class_start_index=3 if kind == "class_start" else None)

    nodes = {
        S: node(S, "Witch", "class_start"),
        P_N: node(P_N, "pN", "normal"), N: node(N, "N", "notable", ("10% increased Spell Damage",)),
        P_P: node(P_P, "pP", "normal"), P: node(P, "P", "notable", ("Gain a Power Charge on Critical Strike",)),
        P_F: node(P_F, "pF", "normal"), F: node(F, "F", "notable", ("Gain a Frenzy Charge on Kill",)),
    }
    edges = [(S, P_N), (P_N, N), (S, P_P), (P_P, P), (S, P_F), (P_F, F)]
    adjacency: dict[int, set[int]] = {}
    for a, b in edges:
        adjacency.setdefault(a, set()).add(b)
        adjacency.setdefault(b, set()).add(a)
    return TreeGraph(tree_version="synthetic", nodes=nodes,
                     adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=frozenset({P_N, N, P_P, P, P_F, F}), class_starts={"Witch": S})


class _Pob:
    """Value: 1000 + 10 per allocated notable. Records every call that costs PoB time."""

    def __init__(self, graph: TreeGraph, *, toggles: dict | None = None, allocated: set[int] | None = None) -> None:
        self.graph = graph
        self.allocated = set(allocated or {S})
        self.toggles = dict(toggles if toggles is not None else ALL_ON)
        self.masteries: dict[int, int] = {}
        self.loaded: list[str] = []
        self.mutations: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
        self.trials: list[int] = []  # the size of every batch PoB was actually asked for
        self._snapshots: dict[str, tuple[set[int], dict[int, int]]] = {}

    # -- surfaces the optimizer uses -------------------------------------
    def config_inputs(self) -> dict:
        return dict(self.toggles)

    def tree_light(self) -> dict:
        return {"class_id": "Witch",
                "user_allocated_node_ids": sorted(self.allocated - {S}),
                "mastery_effect_ids": [f"{n}:{e}" for n, e in sorted(self.masteries.items())]}

    def _added(self, targets) -> list[int]:
        costs = self.graph.bfs_costs(self.allocated, max_depth=6)
        added: list[int] = []
        for target in targets:
            if int(target) in self.allocated:
                continue
            for node_id in costs[int(target)][1]:
                if node_id not in self.allocated and node_id not in added:
                    added.append(node_id)
        return added

    def _value(self, nodes) -> float:
        return 1000.0 + 10.0 * len({n for n in nodes if n in (N, P, F)})

    def trial_stats(self, trials, keys, mode="fast") -> list[dict]:
        self.trials.append(len(trials))
        out = []
        for trial in trials:
            added = self._added(trial.get("add") or ())
            removed = [int(n) for n in (trial.get("remove") or ()) if int(n) in self.allocated]
            nodes = (self.allocated | set(added)) - set(removed)
            out.append({"ok": True, "stats": {"CombinedDPS": self._value(nodes)},
                        "added_node_ids": list(added), "removed_node_ids": removed})
        return out

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None) -> dict:
        self.mutations.append((tuple(add or ()), tuple(remove or ())))
        gone = {int(n) for n in (remove or ()) if int(n) in self.allocated}
        self.allocated -= gone
        for n in gone:
            self.masteries.pop(n, None)
        added = self._added(add or ())
        self.allocated |= set(added)
        for node_id, effect in (mastery_effects or {}).items():
            self.masteries[int(node_id)] = int(effect)
        return {"added_node_ids": list(added), "removed_node_ids": sorted(gone),
                "allocated_node_ids": sorted(self.allocated - {S}), "removed_mastery_effects": [], "points_used": len(added)}

    def stats(self, keys) -> dict:
        return {"CombinedDPS": self._value(self.allocated)}

    def export_xml(self) -> str:
        token = f"xml{len(self._snapshots) + 1}"
        self._snapshots[token] = (set(self.allocated), dict(self.masteries))
        return token

    def load_xml(self, token: str) -> None:
        self.loaded.append(token)
        self.allocated, self.masteries = set(self._snapshots[token][0]), dict(self._snapshots[token][1])


def _opt(pob: _Pob, graph: TreeGraph, **kwargs) -> TreeOptimizer:
    return TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=graph, **kwargs)


def test_attribute_requirement_nodes_are_identified_and_uncapped_unless_a_caller_asks() -> None:
    nodes = {
        S: TreeNode(S, "Witch", "class_start", (), None, 3),
        2: TreeNode(2, "Might", "notable", ("+30 to Strength",), None, None),
        3: TreeNode(3, "Agility", "notable", ("+30 to Dexterity",), None, None),
        4: TreeNode(4, "Life", "notable", ("+10 to maximum Life",), None, None),
    }
    graph = TreeGraph(
        tree_version="synthetic",
        nodes=nodes,
        adjacency={S: frozenset({2, 3, 4}), 2: frozenset({S}), 3: frozenset({S}), 4: frozenset({S})},
        allocatable=frozenset({2, 3, 4}),
        class_starts={"Witch": S},
    )
    uncapped = TreeOptimizer(None, Objective(maximize="CombinedDPS"), graph=graph)
    capped = TreeOptimizer(None, Objective(maximize="CombinedDPS"), graph=graph, attribute_requirement_nodes_max=1)

    assert attribute_requirement_node_ids(graph) == {2, 3}
    # D79 rule 7: the one-node cap was never measured, so the default is no cap.
    assert uncapped.attribute_requirement_nodes_max is None
    assert not uncapped._attribute_cap_blocks(Candidate(3, 1, (3,), "notable", "Agility"), {S, 2})
    # The knob is still there for a caller that asks for it.
    assert not capped._attribute_cap_blocks(Candidate(2, 1, (2,), "notable", "Might"), {S})
    assert capped._attribute_cap_blocks(Candidate(3, 1, (3,), "notable", "Agility"), {S, 2})
    assert not capped._attribute_cap_blocks(Candidate(4, 1, (4,), "notable", "Life"), {S, 2})
    assert not capped._attribute_cap_blocks(Candidate(4, 1, (4,), "notable", "Life"), {S, 2, 3})


def _hooking(opt: TreeOptimizer, seen: list) -> None:
    def hook(cand, trial):
        seen.append((cand.node_id, (trial.get("mastery") or {}).get(cand.node_id)))
        return None  # "nothing was enabled": the answer 86% of real calls give

    opt.enabler_hook = hook


# -- finding 2: the enabler hook -----------------------------------------


def test_generator_kinds_names_the_kind_each_node_grants() -> None:
    graph = _graph()
    opt = _opt(_Pob(graph), graph)
    assert opt.generator_kinds([P]) == {"Power"}
    assert opt.generator_kinds([F]) == {"Frenzy"}
    assert opt.generator_kinds([N]) == set()
    assert opt.generator_kinds([P, F]) == {"Power", "Frenzy"}
    assert opt.generator_effects(P) == {None} and opt.generator_effects(N) == set()


def test_the_hook_is_never_called_when_every_toggle_it_could_flip_is_already_on() -> None:
    graph = _graph()
    pob = _Pob(graph, toggles=ALL_ON)
    opt = _opt(pob, graph)
    seen: list = []
    _hooking(opt, seen)

    opt.allocate(6, allocated={S})

    assert seen == [] and opt.hook_calls == 0
    assert opt.hook_skipped_inert > 0


def test_only_the_kinds_that_are_off_reach_the_hook() -> None:
    """Power is on, Frenzy is off: the power-charge notable cannot flip anything and is skipped;
    the frenzy one still has to be judged."""

    graph = _graph()
    pob = _Pob(graph, toggles=POWER_ON)
    opt = _opt(pob, graph)
    seen: list = []
    _hooking(opt, seen)

    opt.allocate(6, allocated={S})

    assert {node for node, _e in seen} == {F}
    assert opt.hook_calls == 1 and opt.hook_skipped_inert >= 1


def test_the_hook_answer_is_reused_by_the_next_allocate_call_under_the_same_lanes() -> None:
    graph = _graph()
    pob = _Pob(graph, toggles=POWER_ON)
    opt = _opt(pob, graph)
    seen: list = []
    _hooking(opt, seen)

    opt.allocate(2, allocated={S})
    calls_after_first = opt.hook_calls
    opt.allocate(2, allocated=set(pob.allocated))

    assert calls_after_first == 1 and opt.hook_calls == 1, "the second call re-judged a node the lanes had not changed for"
    assert opt.hook_skipped_cached >= 1


def test_a_change_in_the_lanes_drops_the_hook_answers() -> None:
    graph = _graph()
    pob = _Pob(graph, toggles=POWER_ON)
    opt = _opt(pob, graph)
    seen: list = []
    _hooking(opt, seen)

    opt.allocate(2, allocated={S})
    pob.toggles = {"usePowerCharges": False, "useFrenzyCharges": False, "useEnduranceCharges": False}
    opt.allocate(2, allocated=set(pob.allocated))

    assert opt.hook_calls >= 2, "answers derived under the old lanes must not survive a config change"


def test_without_a_config_surface_every_generator_still_reaches_the_hook(monkeypatch) -> None:
    """A session (or a test double) that cannot report its config inputs keeps the old behaviour:
    the skip is an optimisation, never a silent change of who gets judged."""

    graph = _graph()
    pob = _Pob(graph, toggles=ALL_ON)
    monkeypatch.delattr(_Pob, "config_inputs")
    opt = _opt(pob, graph)
    seen: list = []
    _hooking(opt, seen)

    opt.allocate(6, allocated={S})

    assert {node for node, _e in seen} == {P, F}


# -- finding 7: the restore ----------------------------------------------


def test_a_tree_only_revert_goes_through_the_inverse_mutation() -> None:
    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    opt = _opt(pob, graph)
    expected, _ = opt.current_score()

    snapshot = opt._snapshot()
    pob.mutate_nodes(add=[P], remove=[N])
    opt._restore(snapshot, expected, "test")

    assert pob.allocated == {S, P_N, N} and pob.loaded == []
    assert opt.restore_fast == 1 and opt.restore_fallback == 0 and opt.restore_failures == 0


def test_a_revert_the_mutation_cannot_do_falls_back_to_the_xml() -> None:
    """A mastery effect re-selected on a node that stays allocated cannot be put back by a
    mutation, so the reload does it."""

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    pob.masteries[N] = 100
    opt = _opt(pob, graph)
    expected, _ = opt.current_score()

    snapshot = opt._snapshot()
    pob.masteries[N] = 200
    opt._restore(snapshot, expected, "test")

    assert pob.masteries == {N: 100} and pob.loaded == ["xml1"]
    assert opt.restore_fast == 0 and opt.restore_fallback == 1


def test_a_config_change_since_the_snapshot_forces_the_xml_reload() -> None:
    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    opt = _opt(pob, graph)
    expected, _ = opt.current_score()

    snapshot = opt._snapshot()
    pob.mutate_nodes(add=[P])
    opt.note_config_change()  # the lanes moved: the tree is not the only thing to put back
    opt._restore(snapshot, expected, "test")

    assert pob.loaded == ["xml1"] and opt.restore_fallback == 1


def test_only_a_sole_proof_removal_reconfigures_and_a_dead_leaf_still_swaps() -> None:
    """The expensive lane judgement is for the one mapped proof, not for every leaf."""

    proof, dead, payoff = 50, 51, 52

    def node(node_id: int, name: str, kind: str) -> TreeNode:
        return TreeNode(node_id=node_id, name=name, kind=kind, stats=(), ascendancy_name=None,
                        class_start_index=3 if kind == "class_start" else None)

    graph = TreeGraph(
        tree_version="proof-removal",
        nodes={S: node(S, "Witch", "class_start"), proof: node(proof, "Caster Mastery", "normal"),
               dead: node(dead, "Minion Life", "normal"), payoff: node(payoff, "Spell Damage", "notable")},
        adjacency={S: frozenset({proof, dead, payoff}), proof: frozenset({S}), dead: frozenset({S}), payoff: frozenset({S})},
        allocatable=frozenset({proof, dead, payoff}), class_starts={"Witch": S},
    )

    class _ProofPob(_Pob):
        def __init__(self) -> None:
            super().__init__(graph, allocated={S, proof, dead})
            self.power_on = True
            self.power_snapshots: dict[str, bool] = {}

        def export_xml(self) -> str:
            token = super().export_xml()
            self.power_snapshots[token] = self.power_on
            return token

        def load_xml(self, token: str) -> None:
            super().load_xml(token)
            self.power_on = self.power_snapshots[token]

        def _value(self, nodes) -> float:
            return 1000.0 + (100.0 if self.power_on else 0.0) + (30.0 if payoff in nodes else 0.0)

    pob = _ProofPob()
    opt = _opt(pob, graph)
    calls: list[list[int]] = []
    opt.proof_holders = {proof: {"usePowerCharges": True}}

    def reconfigure(applied) -> None:
        calls.append(list(applied["removed_node_ids"]))
        pob.power_on = proof in pob.allocated

    opt.after_proof_removal_hook = reconfigure
    result = opt.refine(max_rounds=2, top_candidates=8)

    assert calls == [[proof]], "the dead leaf must not pay for config derivation"
    assert proof in pob.allocated and dead not in pob.allocated and payoff in pob.allocated
    assert result.steps and result.steps[0].removed_node_ids == [dead]


def test_a_second_source_is_not_a_proof_holder() -> None:
    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    opt = _opt(pob, graph)
    opt.proof_holders = {}  # pipeline attribution omitted the node because an item has the same proof line
    reconfigured: list[object] = []
    opt.after_proof_removal_hook = reconfigured.append

    applied = pob.mutate_nodes(remove=[N])

    assert not opt.after_real_removal(applied) and reconfigured == []


def test_pipeline_does_not_mark_a_tree_line_held_again_by_an_item() -> None:
    """Proof attribution uses exact text ownership, not a list of passive names."""

    graph = _graph()

    class _SourcePob(_Pob):
        def read_state(self) -> dict:
            return {
                "tree_state": {"user_allocated_node_ids": [P], "mastery_effect_ids": []},
                "gear_slots": {"slots": {"Ring 1": {"item": {"raw_item_text": "Gain a Power Charge on Critical Strike"}}}},
                "skills_state": {},
            }

    pob = _SourcePob(graph, allocated={S, P_P, P})
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob, pipeline.log = pob, lambda _line: None
    pipeline.judging = pob_judging(pipeline)
    opt = _opt(pob, graph)
    derived = type("Derived", (), {"conservative": type("Lane", (), {
        "proof_lines": {"usePowerCharges": ("Gain a Power Charge on Critical Strike",)},
        "inputs": {"usePowerCharges": True},
    })()})()

    pipeline.judging.post_holders(derived, (opt,))

    assert opt.proof_holders == {}, "the same proof line on an item leaves the passive ordinary"


# -- the proof is NECESSARY, not sole (v3) --------------------------------
#
# winter_orb's `usePowerCharges` stands on the SUM of two lines: an Occultist ASCENDANCY node
# ("gain a power charge after spending a total of 200 mana") and the Caster Mastery ("gain a
# power charge each second while channelling a spell"). Neither is a sole proof, so the sole
# test left the map empty -- and the mastery's removal still cost 14% of the build.

MASTERY, EFFECT = 60, 33089
ASCENDANCY_LINE = "gain a power charge after spending a total of 200 mana"
MASTERY_LINE = "gain a power charge each second while channelling a spell"


def _mastery_graph() -> TreeGraph:
    graph = _graph()
    node = TreeNode(node_id=MASTERY, name="Caster Mastery", kind="mastery", stats=(), ascendancy_name=None,
                    class_start_index=None, mastery_effects=((EFFECT, (MASTERY_LINE,)), (99, ("something else",))))
    nodes = {**graph.nodes, MASTERY: node}
    adjacency = {**{k: set(v) for k, v in graph.adjacency.items()}}
    adjacency.setdefault(S, set()).add(MASTERY)
    adjacency[MASTERY] = {S}
    return TreeGraph(tree_version="synthetic", nodes=nodes,
                     adjacency={k: frozenset(v) for k, v in adjacency.items()},
                     allocatable=graph.allocatable | {MASTERY}, class_starts={"Witch": S})


class _MasteryPob(_Pob):
    """The allocated tree is the mastery alone; the ascendancy line is fixed evidence the tree
    cannot remove, exactly as `build_text` collects it beside the passives."""

    def read_state(self) -> dict:
        return {
            "tree_state": {"user_allocated_node_ids": [MASTERY], "mastery_effect_ids": [f"{MASTERY}:{EFFECT}"]},
            "gear_slots": {"slots": {}},
            "skills_state": {},
        }


def _derived(recheck) -> object:
    lane = type("Lane", (), {"proof_lines": {"usePowerCharges": (ASCENDANCY_LINE, MASTERY_LINE)},
                             "inputs": {"usePowerCharges": True, "overridePowerCharges": 3}})()
    return type("Derived", (), {"conservative": lane, "recheck": staticmethod(recheck)})()


def _pipeline_for(pob, logs: list[str]) -> BuildPipeline:
    pipeline = BuildPipeline.__new__(BuildPipeline)
    pipeline.pob, pipeline.log = pob, logs.append
    pipeline.judging = pob_judging(pipeline)
    return pipeline


def test_a_line_the_rule_needs_beside_an_unowned_one_makes_the_node_a_holder() -> None:
    """The rule wants both rates: without the mastery's the input goes off. That is the holder."""

    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        # the real shape of `charge_rule`: the sustained count is the SUM of the sources still
        # in the text, and one source alone does not hold a charge inside the ramp budget
        rates = {ASCENDANCY_LINE: 0.4, MASTERY_LINE: 1.0}
        left = sum(rate for line, rate in rates.items() if line not in dict(masked))
        keys = ("usePowerCharges", "overridePowerCharges")
        return ProofRecheck(rule="charge_rule", keys=keys, inputs={} if left < 1.2 else {keys[0]: True, keys[1]: 3})

    graph = _mastery_graph()
    pob = _MasteryPob(graph, allocated={S, MASTERY})
    opt = _opt(pob, graph)
    logs: list[str] = []

    _pipeline_for(pob, logs).judging.post_holders(_derived(recheck), (opt,))

    assert opt.proof_holders == {(MASTERY, EFFECT): {"usePowerCharges": (True, None), "overridePowerCharges": (3, None)}}
    assert any("proof holders: Caster Mastery [effect 33089] -> " in line for line in logs)
    assert any("usePowerCharges True -> None" in line for line in logs)


def test_a_lower_number_without_the_node_is_a_holder_too() -> None:
    """The input survives on the other source, but at a smaller count: the tree still paid for it."""

    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        keys = ("usePowerCharges", "overridePowerCharges")
        held = {keys[0]: True, keys[1]: 1 if MASTERY_LINE in dict(masked) else 3}
        return ProofRecheck(rule="charge_rule", keys=keys, inputs=held)

    graph = _mastery_graph()
    pob = _MasteryPob(graph, allocated={S, MASTERY})
    opt = _opt(pob, graph)

    _pipeline_for(pob, []).judging.post_holders(_derived(recheck), (opt,))

    assert opt.proof_holders == {(MASTERY, EFFECT): {"overridePowerCharges": (3, 1)}}


def test_a_node_whose_line_the_rule_can_do_without_is_not_a_holder() -> None:
    """Either line proves it on its own: the mastery is an ordinary fast removal."""

    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        keys = ("usePowerCharges", "overridePowerCharges")
        left = [line for line in (ASCENDANCY_LINE, MASTERY_LINE) if line not in dict(masked)]
        return ProofRecheck(rule="charge_rule", keys=keys, inputs={keys[0]: True, keys[1]: 3} if left else {})

    graph = _mastery_graph()
    pob = _MasteryPob(graph, allocated={S, MASTERY})
    opt = _opt(pob, graph)

    _pipeline_for(pob, []).judging.post_holders(_derived(recheck), (opt,))

    assert opt.proof_holders == {}


def test_a_line_an_item_repeats_is_never_masked_away() -> None:
    """Fixed evidence: `mask_text` withdraws only as many copies as the node itself carries."""

    from junkroan.optimizer.config_rules import mask_text

    text = "\n".join([MASTERY_LINE, MASTERY_LINE, ASCENDANCY_LINE])  # a ring and the mastery say the same thing
    assert mask_text(text, {MASTERY_LINE: 1}).splitlines() == [MASTERY_LINE, ASCENDANCY_LINE]
    assert mask_text(text, {ASCENDANCY_LINE: 1}).splitlines() == [MASTERY_LINE, MASTERY_LINE]
    assert mask_text(text, ()) == text


def test_an_input_whose_rule_needs_pob_falls_back_to_the_sole_proof_test() -> None:
    """A rule this derivation cannot re-run is named in the log and judged the v2 way."""

    from junkroan.optimizer.config_rules import ProofRecheck

    def recheck(var: str, masked) -> ProofRecheck:
        return ProofRecheck(rule="judge_stack_options", keys=(var,), inputs=None)

    graph = _mastery_graph()
    pob = _MasteryPob(graph, allocated={S, MASTERY})
    opt = _opt(pob, graph)
    logs: list[str] = []

    _pipeline_for(pob, logs).judging.post_holders(_derived(recheck), (opt,))

    # the ascendancy line has no allocated owner, so the sole-proof test refuses the mastery
    assert opt.proof_holders == {}
    assert any("usePowerCharges: not decidable without PoB (judge_stack_options)" in line for line in logs)


def test_only_a_contract_error_forgets_the_subtrees_already_proven_not_to_pay() -> None:
    """`_rejected_subtrees` is keyed by the allocated set it was measured on, so a plain revert --
    which puts that very set back -- may keep it; a contract error may not."""

    graph = _graph()
    opt = _opt(_Pob(graph), graph)
    opt._rejected_subtrees.add((frozenset({S, P}), frozenset({P})))
    opt._unswappable.add(P)

    opt.invalidate_after_recovery(keep_rejections=True)

    assert opt._rejected_subtrees and opt._unswappable
    assert opt._trial_memo == {} and opt._config_fp is None  # everything measured on the transient build is gone

    opt.invalidate_after_recovery()

    assert not opt._rejected_subtrees and not opt._unswappable


def test_a_plain_xml_snapshot_still_works() -> None:
    """`_restore` keeps taking a bare XML token, so nothing outside this module has to change."""

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    opt = _opt(pob, graph)
    expected, _ = opt.current_score()

    token = pob.export_xml()
    pob.mutate_nodes(add=[P])
    opt._restore(token, expected, "test")

    assert pob.allocated == {S, P_N, N} and pob.loaded == [token]


# -- findings 5 and 9: the path-swap pass --------------------------------


def test_a_subtree_rejected_on_this_tree_is_not_tried_again() -> None:
    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N, P_P, P, P_F, F})
    opt = _opt(pob, graph)

    first = opt.swap_subtrees(max_size=2, min_gain=0.002, max_seconds=240.0)
    tried_first = len(pob.mutations)
    assert first.steps == [] and opt._rejected_subtrees, "nothing pays on this tree: every subtree is rejected"

    pob.mutations.clear()
    second = opt.swap_subtrees(max_size=2, min_gain=0.002, max_seconds=240.0)

    assert second.steps == [] and pob.mutations == [], "the same tree was re-explored"
    assert opt.subtree_retries_skipped == len(opt._rejected_subtrees) > 0
    assert tried_first > 0


def test_a_different_tree_is_explored_again() -> None:
    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N, P_P, P, P_F, F})
    opt = _opt(pob, graph)
    opt.swap_subtrees(max_size=2, min_gain=0.002, max_seconds=240.0)

    pob.mutate_nodes(remove=[F])  # the tree is no longer the one those rejections were measured on
    pob.mutations.clear()
    opt.swap_subtrees(max_size=2, min_gain=0.002, max_seconds=240.0)

    assert pob.mutations, "a rejection must not carry over to a tree it was never measured on"


def test_the_budget_refuses_a_candidate_that_would_overrun(monkeypatch) -> None:
    """A path-swap candidate costs 25-58 s, so checking only "am I already over" let a 120 s pass
    run to 144 s. A candidate is started only when the longest one measured so far still fits."""

    from junkroan.optimizer import tree_optimizer as mod

    ticks = iter(range(0, 100_000))
    monkeypatch.setattr(mod.time, "perf_counter", lambda: float(next(ticks)) * 4.0)  # 4 s per clock read

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N, P_P, P, P_F, F})
    opt = _opt(pob, graph)
    result = opt.swap_subtrees(max_size=2, min_gain=0.002, max_seconds=40.0)

    assert result.stopped_reason == "time budget"
    assert len(pob.mutations) < 6, "the pass kept starting candidates it had no budget for"


def test_a_swaps_pass_without_a_clock_or_count_is_bounded_by_failures() -> None:
    """#569: `max_seconds=None` and no `max_candidates` is the loop's call; the pass stops on `max_failures` in a row
    or when the subtree list is done."""

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N, P_P, P, P_F, F})
    opt = _opt(pob, graph)

    bare = opt.swap_subtrees(max_size=2, max_seconds=None)
    assert bare.stopped_reason in ("consecutive failures", "all subtrees tried", "no small subtrees")
    opt = _opt(_Pob(graph, allocated={S, P_N, N, P_P, P, P_F, F}), graph)
    counted = opt.swap_subtrees(max_size=2, max_seconds=None, max_candidates=1)
    assert counted.stopped_reason in ("candidate budget", "consecutive failures", None)


# -- finding 1: inert candidates (skip_inert, approximate, default off) ---


def _pays(pob: _Pob, weights: dict[int, float]) -> None:
    """Only these nodes are worth anything; every other candidate comes back inert."""

    pob._value = lambda nodes: 1000.0 + sum(v for n, v in weights.items() if n in set(nodes))  # type: ignore[method-assign]


def _inert_opt(pob: _Pob, graph: TreeGraph, **kwargs) -> TreeOptimizer:
    """The N branch pays, one point at a time (pN is the better buy per point, so the greedy takes
    it first and N second); P and F are worth nothing and come back inert on every step."""

    _pays(pob, {P_N: 8.0, N: 2.0})
    return _opt(pob, graph, skip_inert=True, **kwargs)


def _sent_nodes(pob: _Pob, opt: TreeOptimizer) -> list[list[int]]:
    sent: list[list[int]] = []
    raw = pob.trial_stats

    def spy(trials, keys, mode="fast"):
        sent.append(sorted({int(n) for t in trials for n in (t.get("add") or ())}))
        return raw(trials, keys, mode=mode)

    pob.trial_stats = spy  # type: ignore[method-assign]
    return sent


def test_off_by_default_nothing_is_skipped() -> None:
    graph = _graph()
    pob = _Pob(graph)
    opt = _opt(pob, graph)
    sent = _sent_nodes(pob, opt)
    result = opt.allocate(4, allocated={S})

    assert opt.skip_inert is False and opt.inert_skipped == 0
    assert all(s.candidates_skipped == 0 for s in result.steps)
    assert all(P in batch and F in batch for batch in sent), "every candidate was offered on every step"


def test_an_inert_candidate_is_not_sent_again_next_step() -> None:
    graph = _graph()
    pob = _Pob(graph)
    opt = _inert_opt(pob, graph)
    sent = _sent_nodes(pob, opt)
    result = opt.allocate(4, allocated={S})

    assert P in sent[0] and F in sent[0], "the first step must measure everything"
    assert P not in sent[1] and F not in sent[1], "PoB was asked again about candidates it had called inert"
    assert opt.inert_skipped > 0 and result.steps[1].candidates_skipped > 0
    assert "skipped" in result.summary()


def test_a_candidate_whose_path_touches_the_new_allocation_is_measured_again() -> None:
    graph = _graph()
    pob = _Pob(graph)
    opt = _inert_opt(pob, graph)
    sent = _sent_nodes(pob, opt)
    opt.allocate(2, allocated={S})

    # step 1 allocated pN on the way to N; F sits behind pF and is untouched, P behind pP likewise,
    # but the notable N's own neighbour pN moved, so N's key is invalidated and re-offered
    assert N in sent[1] and P not in sent[1]


def test_a_new_violated_floor_wakes_every_inert_candidate() -> None:
    graph = _graph()
    pob = _Pob(graph)
    opt = _inert_opt(pob, graph)
    opt.objective = Objective(maximize="CombinedDPS", floors={"Life": 0.0})
    sent = _sent_nodes(pob, opt)
    opt.allocate(2, allocated={S})
    assert P not in sent[1]

    opt.objective = Objective(maximize="CombinedDPS", floors={"Life": 100.0})  # a floor is missed now
    pob.stats = lambda keys: {"CombinedDPS": pob._value(pob.allocated), "Life": 0.0}  # type: ignore[method-assign]
    opt.allocate(2, allocated=set(pob.allocated))

    assert P in sent[-1], "the violated-floor set changed: every inert verdict must be re-measured"


def test_the_verdict_expires_after_inert_refresh_steps() -> None:
    """The window is the backstop against an interaction the other triggers cannot see, so it is
    checked on the rule itself: a verdict older than `inert_refresh` steps stops being trusted."""

    graph = _graph()
    pob = _Pob(graph)
    opt = _inert_opt(pob, graph, inert_refresh=3)
    opt.allocate(1, allocated={S})
    assert opt._inert, "the first step recorded verdicts"
    trials = opt._trials_for(graph.candidates(pob.allocated, max_depth=6))
    violated = opt.violated_floors(pob.stats(("CombinedDPS",)))

    for age in (1, 2):
        opt._inert_step += 1
        _sent, skipped = opt._filter_inert(list(trials), violated)
        assert skipped > 0, f"a {age}-step-old verdict inside the window must still be trusted"
    opt._inert_step += 1  # now 3 steps old: at the window
    _sent, skipped = opt._filter_inert(list(trials), violated)
    assert skipped == 0, "a verdict at the refresh window must be measured again"


def test_a_restore_and_a_config_change_drop_every_verdict() -> None:
    graph = _graph()
    pob = _Pob(graph)
    opt = _inert_opt(pob, graph)
    opt.allocate(1, allocated={S})
    assert opt._inert

    opt.note_config_change()
    assert not opt._inert

    opt.allocate(1, allocated=set(pob.allocated))
    assert opt._inert
    opt._restore(opt._snapshot(), opt.current_score()[0], "test")
    assert not opt._inert


def test_a_charge_generator_drops_every_verdict() -> None:
    graph = _graph()
    pob = _Pob(graph)
    _pays(pob, {P_N: 8.0, P_P: 1.0, P: 5.0})  # step 1 takes pN, step 2 the generator P
    opt = _opt(pob, graph, skip_inert=True)
    opt.allocate(2, allocated={S})  # pN, then pP: P itself costs 2 and does not fit the last point
    assert opt._inert and P not in pob.allocated

    opt.allocate(1, allocated=set(pob.allocated))  # buys P with the last point and stops there

    assert P in pob.allocated
    assert not opt._inert, "a charge generator changes what every other node is worth"


# -- finding 5 (refine): the round it re-sends unchanged ------------------


def _refine_case(**kwargs) -> tuple[TreeGraph, _Pob, TreeOptimizer]:
    """A tree that has nothing left to swap: N is allocated behind pN, and neither of the two
    other branches is worth anything, so a refine round measures the whole neighbourhood
    (1 leaf + 4 candidates + 2 affordable swaps) and keeps nothing."""

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    return graph, pob, _opt(pob, graph, **kwargs)


def test_a_refine_round_measures_every_leaf_every_candidate_and_every_affordable_swap() -> None:
    _graph_, pob, opt = _refine_case()

    result = opt.refine()

    assert result.steps == [] and result.stopped_reason == "no improving swap"
    assert pob.trials == [1, 4, 2], "the round's three batches: the leaves, the candidates, the swaps"
    assert opt.trials_measured == 7 and opt.trials_reused == 0


def test_the_same_refine_on_the_same_build_costs_no_trial_at_all() -> None:
    """The improvement loop runs the move once per pass and reverts the whole pass when it lost,
    so the next pass asks the same question about the same build: 27 s a time in the campaign."""

    _graph_, pob, opt = _refine_case()
    first = opt.refine()
    pob.trials.clear()

    second = opt.refine()

    assert pob.trials == [], "PoB was asked again for a verdict it had already given on this build"
    assert opt.refine_skipped == 1
    assert second.steps == first.steps == []
    assert second.final_score == first.final_score and second.final_stats == first.final_stats


def test_a_tree_that_moved_is_measured_again() -> None:
    _graph_, pob, opt = _refine_case()
    opt.refine()
    pob.mutate_nodes(add=[P])  # a different build: the verdict was never measured on it
    pob.trials.clear()

    opt.refine()

    assert pob.trials and opt.refine_skipped == 0


def test_a_config_change_makes_the_verdict_be_measured_again() -> None:
    """A lane the pipeline rewrote between two passes can change what a swap is worth without
    moving a single objective stat, so the config the build carries is part of the key."""

    _graph_, pob, opt = _refine_case()
    opt.refine()
    pob.toggles = {"usePowerCharges": False, "useFrenzyCharges": False, "useEnduranceCharges": False}
    pob.trials.clear()

    opt.refine()

    assert pob.trials and opt.refine_skipped == 0


def test_a_verdict_reached_on_a_batch_skip_inert_thinned_is_not_remembered() -> None:
    """`skip_inert` hands the round less than the whole neighbourhood; "nothing here" then says
    less than it seems, and a later call (which starts with every verdict forgotten) must ask."""

    graph = _graph()
    pob = _Pob(graph, allocated={S, P_N, N})
    opt = _opt(pob, graph, skip_inert=True)
    offered = opt._trials_for(graph.candidates(pob.allocated, max_depth=6))
    opt._inert_step = 1
    opt._inert[opt._inert_key(offered[0])] = (opt.violated_floors(pob.stats(("CombinedDPS",))), 1)

    opt.refine()

    assert opt.inert_skipped == 1, "the round was thinned"
    assert not opt._barren, "a verdict about less than the whole neighbourhood must not be remembered"

    opt.refine()  # the next call asks the whole question again (its trials come from the memo, not from a verdict)

    assert opt.refine_skipped == 0 and not opt._barren


def test_the_batch_a_stage_ended_on_comes_back_after_a_pass_that_was_reverted() -> None:
    """A path-swap pass walks a hundred other builds between two tree moves, so the live memo is
    long gone when the loop's revert brings the first build back: the batch a stage ended on is
    kept for exactly that."""

    graph = _graph()
    pob = _Pob(graph)
    _pays(pob, {P_N: 8.0, N: 2.0, P_P: 1.0})
    opt = _opt(pob, graph)
    opt.allocate(1, allocated={S})
    snapshot = opt._snapshot()
    expected, _stats = opt.current_score()
    opt.allocate(1, allocated=set(pob.allocated))  # measures the batch at the snapshot's build
    opt.swap_subtrees(max_size=2, max_seconds=240.0)  # walks other builds; the live memo is thrown away
    opt._restore(snapshot, expected, "test")
    pob.trials.clear()
    reused = opt.trials_reused

    opt.allocate(1, allocated=set(pob.allocated))

    assert opt.trials_reused > reused, "the same question on the same build was sent to PoB again"


def test_neither_rule_changes_what_refine_does() -> None:
    """The whole proof: the same swaps in the same order with the same numbers, measured against
    a run whose state key answers "unknown", which is the code path before the change."""

    def run(rules: bool) -> tuple[list, object]:
        graph = _graph()
        pob = _Pob(graph, allocated={S, P_N, N})
        _pays(pob, {N: 2.0, P_P: 50.0, P: 5.0})
        opt = _opt(pob, graph)
        if not rules:
            opt._state_key = lambda *_a, **_kw: None  # type: ignore[method-assign]
        steps = [(s.node_id, s.cost, s.before.value, s.after.value) for s in opt.refine().steps]
        second = opt.refine()
        return steps + [(s.node_id, s.cost, s.before.value, s.after.value) for s in second.steps], opt.current_score()[0]

    assert run(True) == run(False)


@pytest.mark.parametrize("toggles", [ALL_ON, POWER_ON])
def test_the_skip_never_changes_what_the_greedy_takes(toggles) -> None:
    """The hook only ever raises a candidate's score, and a hook that enables nothing returns None,
    so skipping those calls must leave the kept steps identical to running every one of them."""

    graph = _graph()
    plain = _Pob(graph, toggles=toggles)
    reference = _opt(plain, graph)
    _hooking(reference, [])
    reference._hook_can_flip = lambda _c, _t: True  # judge every generator, as before the change
    before = [(s.node_id, s.cost, s.after.value) for s in reference.allocate(6, allocated={S}).steps]

    graph2 = _graph()
    fast = _opt(_Pob(graph2, toggles=toggles), graph2)
    _hooking(fast, [])
    after = [(s.node_id, s.cost, s.after.value) for s in fast.allocate(6, allocated={S}).steps]

    assert before == after
