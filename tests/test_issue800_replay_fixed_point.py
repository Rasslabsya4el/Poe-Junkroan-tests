"""#800: the replay bench's `fixed-point` move calls the finishing check on a delivered build and reports its table."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from replay_bench import LEGAL_MOVES, fixed_point_lines, fixed_point_replay, render_report, validate_move  # noqa: E402


class FakePipeline:
    """The check keeps a move once, then nothing."""

    def __init__(self):
        self.calls = []

    def _delivered_score(self):
        return SimpleNamespace(value=1000.0)

    def _fixed_point_check(self, result, skeleton, loot, tree, *, loot_n, seed, min_gain, max_seconds, enabled=True, loop_outcome=None):
        self.calls.append(dict(loot=loot, tree=tree, loot_n=loot_n, seed=seed, min_gain=min_gain, max_seconds=max_seconds, enabled=enabled, loop_outcome=loop_outcome))
        result.stages.append(SimpleNamespace(name="fixed point check", score_value=1008.0, notes="swap Elemental Damage with Attacks -> Deadly Ailments"))
        result.stages.append(SimpleNamespace(name="fixed point check", score_value=1008.0, notes=""))
        result.fixed_point_gain, result.fixed_point_note = 0.008, "swap"
        return ["warning: fixed point: one more pass gained +0.8%"]


def test_move_is_legal() -> None:
    assert "fixed-point" in LEGAL_MOVES and validate_move("fixed-point") == "fixed-point"


def test_check_called_once_with_finish_argument_shape_and_table_read() -> None:
    pipe, result = FakePipeline(), SimpleNamespace(stages=[], fixed_point_gain=0.0, fixed_point_note="")
    out = fixed_point_replay(pipe, result, "sk", "gear", "tree", seed=3)
    assert len(pipe.calls) == 1
    call = pipe.calls[0]
    assert set(call) == {"loot", "tree", "loot_n", "seed", "min_gain", "max_seconds", "enabled", "loop_outcome"}
    assert call["loot"] == "gear" and call["tree"] == "tree" and call["seed"] == 3 and call["enabled"] is True and call["loop_outcome"] is None
    assert out["passes"] == 2 and out["reading"] == "+0.8%"
    assert [step["kept"] for step in out["steps"]] == ["", "swap Elemental Damage with Attacks -> Deadly Ailments", "kept nothing"]
    assert out["findings"]


def test_nothing_kept_reads_kept_nothing() -> None:
    pipe = FakePipeline()
    pipe._fixed_point_check = lambda result, *a, **k: setattr(result, "fixed_point_gain", 0.0) or []
    out = fixed_point_replay(pipe, SimpleNamespace(stages=[], fixed_point_gain=0.0, fixed_point_note=""), "sk", "g", "t", seed=1)
    assert out["reading"] == "kept nothing" and out["passes"] == 0


def test_report_holds_table_pass_count_and_time() -> None:
    pipe, result = FakePipeline(), SimpleNamespace(stages=[], fixed_point_gain=0.0, fixed_point_note="")
    row = {"ok": True, "reference": "burning_arrow_snipe", "source": "s", "value_before": 1000.0, "value_after": 1008.0, "gain_percent": 0.8,
           "seconds": 1020.0, "kept": 1, "not_kept": 0, "violation_before": 0.0, "violation_after": 0.0, "audit_errors": 0, "damage_kind": "attack",
           "fixed_point": fixed_point_replay(pipe, result, "sk", "g", "t", seed=1)}
    text = render_report([row], stamp="t", move="fixed-point", passes=1, workers=1, seconds=1020.0)
    assert "| step | value after | kept |" in text and "| extra pass 2 | 1,008 | kept nothing |" in text
    assert "2 extra pass(es)" in text and "17 min" in text
    assert fixed_point_lines({"reference": "x"}) == []
