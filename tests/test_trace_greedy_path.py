"""A greedy trial carries its path to the trace counter, never to PoB (#511, row 2). PoB-free."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from junkroan.optimizer import trace
from junkroan.optimizer.trace import TRACE, classify
from junkroan.optimizer.tree_graph import Candidate
from junkroan.optimizer.tree_optimizer import TreeOptimizer
from junkroan.pob.session import PobSession

P, E = 501, 502  # an attribute+30 node in the middle of the path, the small endpoint


class _Adapter:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def trial_stats(self, handle, payload):
        self.payloads.append(payload)
        return [{"ok": True, "stats": {}} for _t in payload["trials"]]


@pytest.fixture(autouse=True)
def _kinds(monkeypatch):
    monkeypatch.setattr(trace, "default_node_kind", lambda nid: {P: "attribute+30", E: "small"}.get(int(nid), "unknown"))
    TRACE.reset()
    yield
    TRACE.reset()


def _trial() -> dict:
    opt = TreeOptimizer.__new__(TreeOptimizer)
    opt.excluded_nodes = set()
    opt.excluded_mastery_effects = set()
    opt.graph = SimpleNamespace(node=lambda nid: None)
    metas = opt._trials_for([Candidate(E, 2, (P, E), "small", "e")])
    assert len(metas) == 1
    return metas[0]["trial"]


def test_trial_carries_path_and_classes_hold_the_middle_node():
    trial = _trial()
    assert trial["path"] == [P, E] and trial["add"] == [E]
    classes = classify(trial)
    assert {"node-kind:attribute+30", f"node:{E}", "node-kind:small"} <= classes


def test_evaluated_side_counts_path_and_payload_stays_as_main():
    trial = _trial()
    adapter = _Adapter()
    pob = PobSession.__new__(PobSession)
    pob._adapter, pob._handle, pob.fulldps_shortcut, pob.mean_parts = adapter, object(), False, ()
    TRACE.count_candidates([trial])
    pob.trial_stats([trial], ("CombinedDPS",), mode="fast")
    TRACE.flush("picks")
    cells = TRACE.considered()["picks"]
    for cls in ("node-kind:attribute+30", f"node:{E}"):
        assert cells[cls] == {"generated": 1, "evaluated": 1}, cls
    assert adapter.payloads[0]["trials"] == [{"add": [E], "remove": [], "mastery": {}, "item": None}]
