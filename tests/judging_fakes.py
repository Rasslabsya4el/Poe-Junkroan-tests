"""Shared fakes for the judging context (#35, #42): a `LaneSource` and a `ContextReads` that record
their calls, a view, and a `Judging` over them with both trees and the gear filler attached.

Imported by the tests as `from judging_fakes import ...` (pytest's default import mode puts
`tests/` on `sys.path`)."""

from __future__ import annotations

from types import SimpleNamespace

from junkroan.optimizer.judging import UNSET, VIEWS, ContextReads, Judging, LaneSource, PobLanes, PobReads
from junkroan.optimizer.objective import Objective

BASE = Objective(maximize="dps", floors={"Life": 1.0, "EffectiveMovementSpeedMod": 1.2})


def _lanes(conservative: dict, optimistic: dict | None = None, **extra) -> SimpleNamespace:
    return SimpleNamespace(conservative=SimpleNamespace(inputs=dict(conservative), reasons={}),
                           optimistic=SimpleNamespace(inputs=dict(conservative if optimistic is None else optimistic), reasons={}),
                           **extra)


class _Graph:
    def __init__(self, nodes: dict) -> None:
        self.nodes = nodes

    def node(self, node_id: int):
        return self.nodes.get(node_id)


class _Lanes(LaneSource):
    def __init__(self, calls: list) -> None:
        self.calls = calls
        self.lanes = _lanes({"usePowerCharges": True})

    def read(self):
        self.calls.append("read")
        return self.lanes

    def write(self, skeleton, lanes) -> None:
        self.calls.append("write")

    def snapshot(self):
        self.calls.append("snapshot")
        return "xml"

    def restore(self, snapshot) -> None:
        self.calls.append(f"restore {snapshot}")


class _Reads(ContextReads):
    def __init__(self, calls: list, *, counts_changed: bool = False) -> None:
        self.calls, self.counts_changed = calls, counts_changed

    def minion_counts(self, skeleton) -> bool:
        self.calls.append("minion_counts")
        return self.counts_changed

    def main_group(self):
        self.calls.append("main_group")
        return ["Soulrend"], False, (("Soulrend", 18),)

    def self_cost(self, main_tags, triggered, gems, gem_levels):
        self.calls.append("self_cost")
        return SimpleNamespace(gem_levels=gem_levels)

    def castability(self):
        self.calls.append("castability")
        return SimpleNamespace(read=True)

    def ramp(self, skeleton, lanes):
        self.calls.append("ramp")
        return {}

    def holders(self, lanes, graph):
        self.calls.append("holders")
        return {7: {"usePowerCharges": (True, None)}}, {}


def _view(objective: Objective, *, graph=None) -> SimpleNamespace:
    return SimpleNamespace(objective=objective, proof_holders={}, graph=graph)


def _judging(calls: list, *, counts_changed: bool = False) -> tuple[Judging, tuple, SimpleNamespace]:
    judging = Judging(_Lanes(calls), _Reads(calls, counts_changed=counts_changed))
    judging.objective = BASE
    trees = (_view(VIEWS["tree_construction"].cut(BASE), graph=_Graph({})), _view(VIEWS["tree"].cut(BASE)))
    gear = _view(BASE)
    judging.attach("tree_construction", trees[0])
    judging.attach("tree", trees[1])
    judging.attach("gear", gear)
    judging.main_tags = frozenset({"chaos"})
    return judging, trees, gear


def _pob_adapters(pipeline) -> tuple[PobLanes, PobReads]:
    def log(message: str) -> None:
        pipeline.log(message)

    rails = getattr(pipeline, "rails", None)
    return (PobLanes(pipeline.pob, log=log),
            PobReads(pipeline.pob, gems=getattr(rails, "gems", None), log=log, metrics=pipeline.castability_metrics))


def pob_judging(pipeline, *, lanes: LaneSource | None = None, objective=UNSET) -> Judging:
    """The production judging context over a unit harness's pipeline, as `BuildPipeline.__init__`
    builds it: the production adapters over the pipeline's session, its rails' gem levels and its
    castability metrics, bound NOW (set `pob`, `rails`, `log` and `castability_metrics` first).
    `lanes` replaces the lane source (a harness's stub of the lane read or write)."""

    pob_lanes, reads = _pob_adapters(pipeline)
    return Judging(lanes if lanes is not None else pob_lanes, reads, objective=objective,
                   log=lambda message: pipeline.log(message))


def rebind_session(pipeline) -> None:
    """A harness that swaps `pipeline.pob` (or its rails / metrics) mid-test: the judging context
    keeps its state (objective, views, main tags) and reads and writes the new session from now on,
    as a `Judging` built over it would."""

    pipeline.judging.lanes, pipeline.judging.reads = _pob_adapters(pipeline)
