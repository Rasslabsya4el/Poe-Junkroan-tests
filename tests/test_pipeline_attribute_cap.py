"""#430: the pipeline's TreeOptimizers carry the rails' +30 attribute node cap (rulebook t-nodes), no PoB."""

import json
from types import SimpleNamespace

from junkroan.optimizer import pipeline
from junkroan.optimizer.rails import DEFAULT_RAILS_PATH, Rails


class _Objective:
    def without(self, *_a):
        return self

    def without_sustain(self):
        return self


class _Judging:
    def cut(self, _role):
        return _Objective()

    def attach(self, _role, _view):
        pass


class _Recorder:
    def __init__(self, pob, objective, **kw):
        self.kw = kw


def _caps(rails, monkeypatch):
    monkeypatch.setattr(pipeline, "TreeOptimizer", _Recorder)
    stub = SimpleNamespace(rails=rails, judging=_Judging(), log=None)
    trees = pipeline.BuildPipeline._tree_optimizers(stub, object(), 3, 100, False, False)
    return [t.kw["attribute_requirement_nodes_max"] for t in trees]


def test_day1_tree_optimizers_carry_cap_one(monkeypatch):
    rails = Rails.load()
    assert rails.attribute_plus30_nodes_max == 1
    assert _caps(rails, monkeypatch) == [1, 1]


def test_other_loadout_carries_its_rail_value(monkeypatch, tmp_path):
    raw = json.loads(DEFAULT_RAILS_PATH.read_text(encoding="utf-8"))
    del raw["tree"]["attribute_plus30_nodes_max"]
    path = tmp_path / "other.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert _caps(Rails.load(path), monkeypatch) == [None, None]
    raw["tree"]["attribute_plus30_nodes_max"] = 3
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert _caps(Rails.load(path), monkeypatch) == [3, 3]
