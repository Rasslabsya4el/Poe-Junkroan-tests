"""#898 row 9: the dispatcher holds a NEW ORCH start while the PC is busy."""

from __future__ import annotations

from junkroan.pob.slot_budget import admission_now
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue


def _setup(tmp_path, level):
    claude, clock = FakeClaude(), FakeClock()
    d = _dispatcher(tmp_path, claude=claude, gh=FakeGh(candidates=[_issue(1)]), clock=clock)
    lines: list[str] = []
    d.log = lines.append
    box = {"mean": level}
    d.admission = lambda prev: admission_now(
        now=1000.0, samples=[(1000.0 - 10 * i, box["mean"]) for i in range(8)],
        previous_wait=prev, cores=12, mode="day")
    return d, claude, clock, lines, box


def _run(d, clock, n):
    d.run(ticks=n, sleep=lambda s: clock.advance(30))


def test_busy_pc_holds_start_one_line_per_5_min(tmp_path):
    d, claude, clock, lines, _ = _setup(tmp_path, 9.2)
    _run(d, clock, 2)
    held = [l for l in lines if "start held" in l]
    assert not claude.started and len(held) == 1
    assert "9.2" in held[0] and "9.0" in held[0]
    _run(d, clock, 12)  # past 5 min: one more line
    assert len([l for l in lines if "start held" in l]) == 2


def test_quiet_pc_starts(tmp_path):
    d, claude, clock, lines, _ = _setup(tmp_path, 7.9)
    _run(d, clock, 1)
    assert len(claude.started) == 1


def test_wait_lifts_when_mean_falls(tmp_path):
    d, claude, clock, lines, box = _setup(tmp_path, 9.2)
    _run(d, clock, 1)
    assert not claude.started
    box["mean"] = 7.9
    _run(d, clock, 1)
    assert len(claude.started) == 1


def test_check_failure_is_go(tmp_path):
    d, claude, clock, lines, _ = _setup(tmp_path, 9.2)
    def boom(prev):
        raise OSError("x")
    d.admission = boom
    _run(d, clock, 1)
    assert len(claude.started) == 1
