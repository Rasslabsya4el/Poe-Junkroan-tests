"""#516 (kind A, D113): the +30 attribute-requirement cap holds on every allocation path, before PoB.

refine's add-probe and repair_target_first used to ask PoB about +30 nodes the cap forbids. PoB-free:
a fake PoB records every trial batch it receives."""

from junkroan.optimizer.objective import Objective
from junkroan.optimizer.tree_graph import TreeGraph, TreeNode
from junkroan.optimizer.tree_optimizer import TreeOptimizer

S, A, P, B = 1, 2, 3, 4  # A: +30 Strength (allocated), P: plain notable, B: +30 Dexterity (candidate)
GAIN = {A: 50.0, P: 10.0, B: 30.0}
PLUS30 = {A, B}


def _graph() -> TreeGraph:
    nodes = {
        S: TreeNode(S, "Witch", "class_start", (), None, 3),
        A: TreeNode(A, "Might", "notable", ("+30 to Strength",), None, None),
        P: TreeNode(P, "Plain", "notable", ("10% increased Damage",), None, None),
        B: TreeNode(B, "Agility", "notable", ("+30 to Dexterity",), None, None),
    }
    return TreeGraph(tree_version="synthetic", nodes=nodes,
                     adjacency={S: frozenset({A, P, B}), A: frozenset({S}), P: frozenset({S}), B: frozenset({S})},
                     allocatable=frozenset({A, P, B}), class_starts={"Witch": S})


class _Pob:
    def __init__(self):
        self.allocated = {S, A}
        self._snaps = {}
        self.batches: list[list[dict]] = []

    def config_inputs(self):
        return {}

    def tree_light(self):
        return {"class_id": "Witch", "user_allocated_node_ids": sorted(self.allocated - {S}), "mastery_effect_ids": []}

    def _value(self, nodes):
        return 1000.0 + sum(GAIN[n] for n in nodes if n in GAIN)

    def trial_stats(self, trials, keys, mode="fast"):
        self.batches.append([dict(t) for t in trials])
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


def _opt(cap):
    pob = _Pob()
    opt = TreeOptimizer(pob, Objective(maximize="CombinedDPS"), graph=_graph(), attribute_requirement_nodes_max=cap)
    return opt, pob


def _touched(trial) -> set[int]:
    return {int(n) for n in (*(trial.get("add") or ()), *(trial.get("path") or ()))}


def _add_probe(pob):
    """The batch refine's add-probe sent: trials that add and do not remove."""
    batches = [b for b in pob.batches if b and all("add" in t and not t.get("remove") for t in b)]
    assert len(batches) == 1, pob.batches
    return batches[0]


def test_refine_add_probe_holds_no_plus30_trial_under_the_cap():
    opt, pob = _opt(1)
    opt.refine(max_rounds=1)
    probe = _add_probe(pob)
    assert {tuple(sorted(_touched(t))) for t in probe} == {(P,)}
    assert not any(_touched(t) & PLUS30 for t in probe)


def test_refine_add_probe_holds_both_without_the_cap():
    opt, pob = _opt(None)
    opt.refine(max_rounds=1)
    probe = _add_probe(pob)
    assert {tuple(sorted(_touched(t))) for t in probe} == {(P,), (B,)}


def test_repair_target_first_adds_no_plus30_node_under_the_cap():
    opt, pob = _opt(1)
    opt.repair_target_first(1)
    trials = [t for b in pob.batches for t in b]
    assert trials and not any(_touched(t) & PLUS30 for t in trials)
    assert pob.allocated - {S} == {A, P}


def test_repair_target_first_considers_the_plus30_notable_without_the_cap():
    opt, pob = _opt(None)
    opt.repair_target_first(1)
    trials = [t for b in pob.batches for t in b]
    assert any(B in _touched(t) for t in trials)


def test_no_swap_trial_is_built_for_a_plus30_candidate_when_the_allocated_one_is_the_cheapest_leaf():
    opt, pob = _opt(1)
    opt.refine(max_rounds=1)
    trials = [t for b in pob.batches for t in b]
    assert trials
    assert not any(B in _touched(t) for t in trials)


# -- the counter (u2): `node-kind:attribute+30` counts every +30 add; only an add beyond the cap is forbidden ----

import pytest

from junkroan.optimizer import trace
from junkroan.optimizer.trace import TRACE, classify
from junkroan.pob.session import PobSession


@pytest.fixture
def _trace(monkeypatch):
    monkeypatch.setattr(trace, "default_node_kind", lambda nid: "attribute+30" if int(nid) in PLUS30 else "notable")
    TRACE.reset()
    yield
    TRACE.reset()


def _measure_one(opt, trial):
    opt._measure([trial], ("CombinedDPS",), {"CombinedDPS": 1000.0})


def _sent(pob):
    return pob.batches[-1][0]


def test_an_add_beyond_the_cap_is_stamped_and_classed_over(_trace):
    opt, pob = _opt(1)  # the tree holds A (+30), the cap is 1
    _measure_one(opt, {"add": [B], "mastery": {}})
    assert _sent(pob)["attribute_cap_over"] is True
    assert "attribute-cap:over" in classify(_sent(pob))


def test_a_plain_add_and_a_swap_of_the_held_node_are_not_over(_trace):
    opt, pob = _opt(1)
    _measure_one(opt, {"add": [P], "mastery": {}})
    assert "attribute_cap_over" not in _sent(pob)
    _measure_one(opt, {"add": [B], "remove": [A], "mastery": {}})  # one +30 out, one in: still one
    assert "attribute_cap_over" not in _sent(pob)


def test_a_plus30_add_when_the_ruin_cut_the_held_node_is_legal_and_not_over(_trace):
    """trace-516b, bleed_bow: the kick's ruin removed the one +30 node, so every +30 candidate was legal again
    (held=[]): 60 `node-kind:attribute+30` generated and evaluated, none of them over the cap."""

    opt, pob = _opt(1)
    pob.allocated = {S}
    opt.allocate(1)
    trials = [t for b in pob.batches for t in b]
    assert any(B in _touched(t) for t in trials)
    assert not any(t.get("attribute_cap_over") for t in trials)
    TRACE.flush("kick tree")
    cells = TRACE.considered()["kick tree"]
    assert cells["node-kind:attribute+30"]["generated"] > 0
    assert "attribute-cap:over" not in cells


def test_no_cap_stamps_nothing(_trace):
    opt, pob = _opt(None)
    _measure_one(opt, {"add": [B], "mastery": {}})
    assert "attribute_cap_over" not in _sent(pob)


def test_the_over_stamp_reaches_the_evaluated_count_and_never_the_payload(_trace):
    class _Adapter:
        def __init__(self):
            self.payloads = []

        def trial_stats(self, handle, payload):
            self.payloads.append(payload)
            return [{"ok": True, "stats": {}} for _t in payload["trials"]]

    adapter = _Adapter()
    pob = PobSession.__new__(PobSession)
    pob._adapter, pob._handle, pob.fulldps_shortcut, pob.mean_parts = adapter, object(), False, ()
    pob.trial_stats([{"add": [B], "mastery": {}, "attribute_cap_over": True}, {"add": [B], "mastery": {}}], ("CombinedDPS",), mode="fast")
    TRACE.flush("kick tree")
    cells = TRACE.considered()["kick tree"]
    assert cells["attribute-cap:over"] == {"generated": 0, "evaluated": 1}
    assert cells["node-kind:attribute+30"]["evaluated"] == 2
    assert all("attribute_cap_over" not in t for t in adapter.payloads[0]["trials"])
