"""#1038 unit 2 (kind: search-space rule, D113): the seeder's TreeOptimizer carries the main optimizers' rails.

`BuildPipeline._seed_scaling` used to hand-build its TreeOptimizer without the forbidden node text and the +30
attribute cap. PoB-free: a synthetic tree, a fake PoB behind the real `PobSession.trial_stats` (so the trace counters
`forbidden_node_text` / `attribute_cap_exceeded` are counted where the pipeline counts them), and the trace table of
the seed stage. `evaluated(forbidden) = 0` after the fix; the same tree with the rails left off shows the counters count.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer import pipeline
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.pipeline import BuildPipeline, build_tree_optimizer
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.optimizer.tree_trace import ATTRIBUTE_CAP_EXCEEDED, FORBIDDEN_NODE_TEXT, SEED_MOVE
from junkroan.pob.session import PobSession

S, A, P, B, F = 1, 2, 3, 4, 5  # A: +30 Strength, P: plain, B: +30 Dexterity, F: forbidden accuracy line
GAIN = {F: 100.0, A: 50.0, B: 40.0, P: 10.0}  # the forbidden node is the best pick, so an unwired seeder takes it first
FORBIDDEN_LINE = "50% more Accuracy Rating against Unique Enemies"
PLUS30 = {A, B}


def _graph() -> TreeGraph:
    nodes = {
        S: TreeNode(S, "Witch", "class_start", (), None, 3),
        A: TreeNode(A, "Might", "notable", ("+30 to Strength",), None, None),
        P: TreeNode(P, "Plain", "notable", ("10% increased Damage",), None, None),
        B: TreeNode(B, "Agility", "notable", ("+30 to Dexterity",), None, None),
        F: TreeNode(F, "Sniper", "notable", (FORBIDDEN_LINE,), None, None),
    }
    adjacency = {S: frozenset({A, P, B, F}), **{n: frozenset({S}) for n in (A, P, B, F)}}
    return TreeGraph(tree_version="synthetic", nodes=nodes, adjacency=adjacency, allocatable=frozenset({A, P, B, F}), class_starts={"Witch": S})


class _Synthetic(TreeOptimizer):
    """The pipeline's TreeOptimizer over the synthetic tree; every instance is kept for the asserts."""

    built: list["_Synthetic"] = []

    def __init__(self, pob, objective, **kw):
        super().__init__(pob, objective, graph=_graph(), **kw)
        _Synthetic.built.append(self)


class _Model:
    def __init__(self):
        self.allocated = {S}
        self._snaps = {}

    def value(self, nodes):
        return 1000.0 + sum(GAIN[n] for n in nodes if n in GAIN)

    def outcomes(self, trials):
        out = []
        for t in trials:
            added = [int(n) for n in (t.get("add") or ()) if int(n) not in self.allocated]
            removed = [int(n) for n in (t.get("remove") or ()) if int(n) in self.allocated]
            nodes = (self.allocated | set(added)) - set(removed)
            out.append({"ok": True, "stats": {"CombinedDPS": self.value(nodes)}, "added_node_ids": added, "removed_node_ids": removed})
        return out


class _Adapter:
    def __init__(self, model):
        self.model, self.payloads = model, []

    def trial_stats(self, _handle, payload):
        self.payloads.append(payload)
        return self.model.outcomes(payload["trials"])


class _Pob(PobSession):
    """A PobSession whose PoB boundary is a fake: `trial_stats` is the real method, so the trace is counted as in a run."""

    def __init__(self):  # no PoB: the session's own constructor is not called
        self.model = _Model()
        self._adapter = _Adapter(self.model)
        self._handle, self.fulldps_shortcut, self.mean_parts = object(), False, ()

    def config_inputs(self):
        return {}

    def tree_light(self):
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.model.allocated - {S}), "mastery_effect_ids": []}

    def mutate_nodes(self, add=None, remove=None, mastery_effects=None):
        m = self.model
        gone = {int(n) for n in (remove or ()) if int(n) in m.allocated}
        m.allocated -= gone
        added = [int(n) for n in (add or ()) if int(n) not in m.allocated]
        m.allocated |= set(added)
        return {"added_node_ids": added, "removed_node_ids": sorted(gone), "allocated_node_ids": sorted(m.allocated - {S}),
                "removed_mastery_effects": [], "points_used": len(m.allocated) - 1}

    def stats(self, keys):
        return {"CombinedDPS": self.model.value(self.model.allocated)}

    def export_xml(self):
        token = f"x{len(self.model._snaps)}"
        self.model._snaps[token] = set(self.model.allocated)
        return token

    def load_xml(self, token):
        self.model.allocated = set(self.model._snaps[token])

    def sent_adds(self) -> set[int]:
        return {int(n) for payload in self._adapter.payloads for t in payload["trials"] for n in t["add"]}


@pytest.fixture(autouse=True)
def _synthetic(monkeypatch):
    _Synthetic.built = []
    monkeypatch.setattr(pipeline, "TreeOptimizer", _Synthetic)
    TRACE.reset()
    yield
    TRACE.reset()


def _rails() -> SimpleNamespace:
    real = Rails.load()
    return SimpleNamespace(attribute_plus30_nodes_max=real.attribute_plus30_nodes_max, forbidden_node_text=real.forbidden_node_text)


def _skeleton() -> SimpleNamespace:
    return SimpleNamespace(forbid_keystones=(), forced_nodes=(), scaling={"stat": "CombinedDPS", "seed_points": 1.0})


def _pipeline(pob) -> SimpleNamespace:
    return SimpleNamespace(pob=pob, rails=_rails(), log=lambda _m: None, judging=SimpleNamespace(cut=lambda _r: Objective(maximize="CombinedDPS"), attach=lambda *_a: None),
                           _points_used=lambda: len(pob.model.allocated) - 1, _protected_nodes=lambda _sk: frozenset())


def _seed(pipe, points=4):
    return BuildPipeline._seed_scaling(pipe, _skeleton(), points)


def _cells() -> dict:
    return TRACE.considered().get(SEED_MOVE, {})


def test_the_rails_in_the_fake_are_what_the_test_assumes():
    assert Rails.load().attribute_plus30_nodes_max == 1
    assert Rails.load().forbidden_node_text
    opt = TreeOptimizer(_Pob(), Objective(maximize="CombinedDPS"), graph=_graph())
    assert opt._text_matches(Rails.load().forbidden_node_text)[0] == [F]


def test_the_seeder_carries_the_main_optimizers_forbidden_text_and_attribute_cap():
    pob = _Pob()
    pipe = _pipeline(pob)
    skeleton = _skeleton()
    main, main_full = BuildPipeline._tree_optimizers(pipe, pob, 6, 300, False, False)
    self_cost = ("self cost line",)
    for opt in (main, main_full):
        BuildPipeline.wire_tree(pipe, opt, skeleton, forbidden_text=(*pipe.rails.forbidden_node_text, *self_cost), protected=frozenset())
    _seed(pipe)
    seeder = _Synthetic.built[-1]
    assert seeder is not main and seeder is not main_full and seeder.objective.maximize == "CombinedDPS"
    assert seeder.attribute_requirement_nodes_max == main.attribute_requirement_nodes_max == main_full.attribute_requirement_nodes_max == 1
    assert seeder.audit_attribute_cap == main.audit_attribute_cap == 1
    assert seeder.excluded_nodes == main.excluded_nodes == main_full.excluded_nodes
    assert F in seeder.excluded_nodes
    assert seeder.excluded_mastery_effects == main.excluded_mastery_effects
    assert seeder.audit_forbidden_text == main.audit_forbidden_text == (*pipe.rails.forbidden_node_text, *self_cost)


def test_a_seeder_before_any_run_wired_the_main_trees_still_gets_the_rails_text():
    pob = _Pob()
    _seed(_pipeline(pob))
    seeder = _Synthetic.built[-1]
    assert F in seeder.excluded_nodes and seeder.attribute_requirement_nodes_max == 1


def test_the_seed_sends_no_forbidden_node_and_exceeds_no_cap_to_pob():
    pob = _Pob()
    note = _seed(_pipeline(pob))
    assert F not in pob.sent_adds() and F not in pob.model.allocated
    assert len(pob.model.allocated & PLUS30) == 1  # the cap: one +30 node, the second is never asked
    cells = _cells()
    for cls in (FORBIDDEN_NODE_TEXT, ATTRIBUTE_CAP_EXCEEDED):
        assert cells[cls]["evaluated"] == 0, cls
    assert cells["node:" + str(P)]["evaluated"] > 0  # the stage did run and was counted
    assert note.startswith("2 points")


def test_without_the_rails_the_same_tree_shows_the_counters_above_zero():
    """The counters are armed apart from the enforcement: a seeder built the old hand-made way is seen."""

    pob = _Pob()
    old = _Synthetic(pob, Objective(maximize="CombinedDPS"))
    old.audit_forbidden_text, old.audit_attribute_cap = tuple(Rails.load().forbidden_node_text), 1
    with TRACE.move(SEED_MOVE):
        old.allocate(4)
    cells = _cells()
    assert F in pob.model.allocated and PLUS30 <= pob.model.allocated
    assert cells[FORBIDDEN_NODE_TEXT]["evaluated"] > 0
    assert cells[ATTRIBUTE_CAP_EXCEEDED]["evaluated"] > 0


def test_a_candidate_with_a_forbidden_node_is_never_evaluated_by_a_builder_made_optimizer():
    pob = _Pob()
    tree = build_tree_optimizer(pob, Objective(maximize="CombinedDPS"), _rails(), log=lambda _m: None, skeleton=_skeleton(),
                                forbidden_text=_rails().forbidden_node_text)
    with TRACE.move(SEED_MOVE):
        tree.allocate(4)
        # a trial naming the forbidden node, handed to the PoB boundary directly, is what the counter would show
        tree._measure([{"add": [F]}], ("CombinedDPS",), None)
    assert _cells()[FORBIDDEN_NODE_TEXT]["evaluated"] == 1  # only the hand-made probe; `allocate` itself sent none
    assert sum(1 for p in pob._adapter.payloads for t in p["trials"] if F in t["add"]) == 1


def test_the_stamps_never_reach_the_pob_payload():
    pob = _Pob()
    tree = build_tree_optimizer(pob, Objective(maximize="CombinedDPS"), _rails(), log=lambda _m: None, skeleton=_skeleton(),
                                forbidden_text=_rails().forbidden_node_text)
    tree._measure([{"add": [F]}, {"add": [A]}, {"add": [B]}], ("CombinedDPS",), None)
    sent = [t for p in pob._adapter.payloads for t in p["trials"]]
    assert sent and all(set(t) == {"add", "remove", "mastery", "item"} for t in sent)


def test_the_seed_stage_writes_both_counters_as_zero_even_when_nothing_is_allocated():
    pob = _Pob()
    pipe = _pipeline(pob)
    pipe._points_used = lambda: 99  # no points left: the seeder allocates nothing
    _seed(pipe, points=3)
    cells = _cells()
    assert cells[FORBIDDEN_NODE_TEXT] == {"generated": 0, "evaluated": 0}
    assert cells[ATTRIBUTE_CAP_EXCEEDED] == {"generated": 0, "evaluated": 0}


def test_the_seeder_keeps_the_cheap_defaults_and_none_of_the_judging():
    pob = _Pob()
    _seed(_pipeline(pob))
    seeder = _Synthetic.built[-1]
    assert (seeder.max_depth, seeder.max_trials, seeder.skip_inert) == (6, 300, False)
    assert seeder.enabler_hook is None and seeder.after_apply_hook is None and seeder.after_proof_removal_hook is None
    assert seeder.snapshot_context_hook is None and seeder.restore_context_hook is None and seeder.cluster_links is None
