"""#553 rule 3 in the replay bench: the loop's end gets the pipeline's final floor repair."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from replay_bench import final_repair_after_loop, render_report  # noqa: E402


class FakePipeline:
    def __init__(self, scores, view, note="final floor repair: 1 round(s) kept"):
        self.scores, self.note = list(scores), note
        self.judging = SimpleNamespace(view=lambda name: view, relane=lambda sk: self.relaned.append(sk))
        self.relaned, self.repairs = [], 0

    def _delivered_score(self):
        score = self.scores[0] if len(self.scores) == 1 else self.scores.pop(0)
        return score

    def _final_floor_repair(self, result, skeleton):
        self.repairs += 1
        return self.note


def score(value, violation):
    return SimpleNamespace(value=value, violation=violation, feasible=violation == 0)


def test_infeasible_loop_end_is_repaired_and_loop_end_numbers_kept() -> None:
    # after the loop (read twice only if it ran), then after the repair
    pipe = FakePipeline([score(1000.0, 0.1676), score(900.0, 0.0)], view=object())
    out = final_repair_after_loop(pipe, object(), "sk")
    assert pipe.repairs == 1 and pipe.relaned == ["sk"]
    assert out["violation_after_loop"] == 0.1676 and out["value_after_loop"] == 1000.0
    assert out["violation_final"] == 0.0 and out["ran"] and out["note"]


def test_feasible_build_makes_no_repair_call() -> None:
    pipe = FakePipeline([score(1000.0, 0.0)], view=object())
    out = final_repair_after_loop(pipe, object(), "sk")
    assert pipe.repairs == 0 and not out["ran"] and out["violation_after_loop"] == 0.0


def test_no_tree_view_makes_no_repair_call() -> None:
    pipe = FakePipeline([score(1000.0, 0.3)], view=None)
    out = final_repair_after_loop(pipe, object(), "sk")
    assert pipe.repairs == 0 and not out["ran"] and out["violation_after_loop"] == 0.3


def test_report_has_one_line_only_when_a_repair_ran() -> None:
    row = {"ok": True, "reference": "bleed_bow", "source": "s", "value_before": 1.0, "value_after": 900.0, "gain_percent": 1.0, "seconds": 1.0,
           "kept": 1, "not_kept": 0, "violation_before": 0.0, "violation_after": 0.0, "audit_errors": 0, "damage_kind": "attack",
           "final_repair_ran": True, "value_after_loop": 12345.0, "violation_after_loop": 0.1676}
    text = render_report([row], stamp="t", move="loop", passes=1, workers=1, seconds=1.0)
    assert "final floor repair: bleed_bow violation 0.1676 -> 0.0000, value 12,345 -> 900" in text
    row["final_repair_ran"] = False
    assert "final floor repair" not in render_report([row], stamp="t", move="loop", passes=1, workers=1, seconds=1.0)
