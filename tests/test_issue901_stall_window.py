"""#901: the "no test finished" window opens at the later of the first progress character and the moment the plan
is complete (fake clock, as in test_issue829_stall)."""
import json
from pathlib import Path

from junkroan.report_format import human_duration  # noqa: F401  (import check only)
from tools.agentops.merge import StallWatch
from tools.agentops.suite_plan import plan_path


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _watch(tmp_path: Path):
    out = tmp_path / "s.out"
    clock = Clock()
    return StallWatch(out, interval=1, factor=3, min_share=0.05, clock=clock, expected=3), clock, out


def _write_plan(out: Path, longest: float) -> None:
    plan_path(out).write_text(json.dumps({"seconds": [1.0, longest, 0.5]}), encoding="utf-8")


def _tick(w, clock, t, text=""):
    clock.t = t
    return w.tick(text, cpu_now=t)  # one full core


def test_row1_no_dot_plan_at_290_is_no_stall_at_300(tmp_path):
    # #1020: the window needs a first dot too; the first dot at 280 is before the plan, the plan completes at 290
    w, clock, out = _watch(tmp_path)
    assert _tick(w, clock, 280.0, ".") == ""
    _write_plan(out, 79.0)
    assert _tick(w, clock, 290.0, ".") == ""
    assert _tick(w, clock, 300.0, ".") == ""
    assert _tick(w, clock, 290.0 + 236.0, ".") == ""
    assert _tick(w, clock, 290.0 + 237.0, ".").startswith("stalled: no test finished for")


def test_row2_first_dot_at_300_then_none_fires_237_s_later(tmp_path):
    w, clock, out = _watch(tmp_path)
    _write_plan(out, 79.0)
    assert _tick(w, clock, 290.0) == ""
    assert _tick(w, clock, 300.0, ".") == ""
    assert _tick(w, clock, 300.0 + 236.0, ".") == ""
    line = _tick(w, clock, 300.0 + 237.0, ".")
    assert line.startswith("stalled: no test finished for 3.9 min") or line.startswith("stalled: no test finished for")


def test_row3_501_test_shape(tmp_path):
    # #1020: the first dot at 40 (before the plan); the plan completes at 44 and the window opens there
    w, clock, out = _watch(tmp_path)
    assert _tick(w, clock, 40.0, ".") == ""
    _write_plan(out, 12.0)
    assert _tick(w, clock, 44.0, ".") == ""
    assert _tick(w, clock, 45.0, ".") == ""
    assert _tick(w, clock, 79.0, ".") == ""
    assert _tick(w, clock, 80.0, ".").startswith("stalled: no test finished for 36 s")


def test_row4_quiet_limit_still_fires_without_any_dot(tmp_path):
    out = tmp_path / "s.out"
    clock = Clock()
    w = StallWatch(out, interval=1, clock=clock, expected=3, quiet_limit=900.0)
    # a silent tree (no CPU gained, #63): the quiet window stalls at its limit; a busy tree would only log "suite slow"
    assert w.tick("", cpu_now=0.0) == ""
    clock.t = 899.0
    assert w.tick("", cpu_now=0.0) == ""
    clock.t = 900.0
    assert "merge_suite_quiet_limit" in w.tick("", cpu_now=0.0)
