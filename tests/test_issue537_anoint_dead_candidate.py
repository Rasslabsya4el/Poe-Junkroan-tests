"""#537: the anoint step ranks floats from `BuildPipeline._anoint_measurer`; the float must keep `Score`'s key
(`(value > 0, neg_violation, value)`, #15 / D88 amd 1, as #533 did at the jewel sites): a dead candidate (value 0) that
meets its floors never beats a live current with a small violation. PoB-free: the real `_anoint_measurer` and
`pick_anoint` over a fake pob and a fake objective that hand out a `Score` table."""

from __future__ import annotations

from types import SimpleNamespace

import junkroan.optimizer.pipeline as pipeline
from junkroan.optimizer.anoint_step import pick_anoint
from junkroan.optimizer.objective import Score
from junkroan.optimizer.pipeline import BuildPipeline

LIVE_INFEASIBLE = Score(neg_violation=-0.012, value=100.0)  # the current (plain amulet)
DEAD_FEASIBLE = Score(neg_violation=0.0, value=0.0)
LIVE_FEASIBLE = Score(neg_violation=0.0, value=90.0)


class FakePob:
    def equip(self, items) -> None:
        pass

    def stats(self, keys):
        return "plain"

    def trial_stats(self, trials, keys, mode="fast"):
        return [{"ok": True, "stats": trial["item"]["raw"]} for trial in trials]


def _pick(monkeypatch, table: dict[str, Score]):
    """`table` maps a notable name to its Score; the plain amulet scores LIVE_INFEASIBLE. `apply_anoint` is faked to
    return the notable's name, so the fake pob hands it back as the stats and the fake objective looks it up."""

    monkeypatch.setattr(pipeline, "apply_anoint", lambda raw, notable: notable)
    objective = SimpleNamespace(stat_keys=[], score=lambda stats: LIVE_INFEASIBLE if stats == "plain" else table[stats])
    fake = SimpleNamespace(pob=FakePob(), objective=objective)
    names = list(table)
    measure, _scores = BuildPipeline._anoint_measurer(fake, "plain raw", names)
    return pick_anoint(names, measure)


def test_dead_feasible_candidate_is_rejected_over_a_live_infeasible_current(monkeypatch):
    assert _pick(monkeypatch, {"dead": DEAD_FEASIBLE}).chosen is None


def test_live_feasible_candidate_beats_a_live_infeasible_current(monkeypatch):
    pick = _pick(monkeypatch, {"live": LIVE_FEASIBLE})
    assert pick.chosen == "live" and pick.score_after == 90.0


def test_larger_value_wins_between_two_live_feasible_candidates(monkeypatch):
    pick = _pick(monkeypatch, {"low": LIVE_FEASIBLE, "high": Score(neg_violation=0.0, value=110.0)})
    assert pick.chosen == "high"
