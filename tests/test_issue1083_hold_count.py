"""#1083: the busy-PC hold keeps its wait count across a skipped tick while the last "wait" answer is
younger than the hold cap; the count restarts at 0 only after a go, or when the last "wait" answer is
older than the cap. Row 1 is the red run on unchanged main (it fails); row 2 and the #971 / #907 tests
stay green. Fake clock, no PoB."""

from __future__ import annotations

from junkroan.pob.slot_budget import admission_now
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue
from tools.agentops.worktree import ROOT

MIN = 60.0


def _busy(waits: list):
    """A busy PC at 9.2 (day cap 9.0): every check is a hold until the hold cap. Records `waited_s`."""

    def adm(prev, waited_s=0.0, hold_cap_s=None):
        waits.append(waited_s)
        return admission_now(now=1000.0, samples=[(1000.0 - 10 * i, 9.2) for i in range(8)],
                             previous_wait=prev, cores=12, mode="day", waited_s=waited_s,
                             hold_cap_s=hold_cap_s)

    return adm


def _live_orch(claude: FakeClaude) -> None:
    """A live ORCH of this root, working (not finishing): the admission is skipped while it lives."""
    claude.add_session("live-1", name="orch #100", state="working", status="busy", startedAt=1, cwd=str(ROOT))


def _no_live_orch(claude: FakeClaude, d) -> None:
    """The live ORCH has ended: gone from the listing and from the dispatcher's own sessions."""
    claude._sessions.pop("live-1", None)
    d.sessions.clear()


def test_row1_skipped_ticks_keep_the_count_so_the_cap_fires_at_30_min(tmp_path):
    """Today's log replayed on a fake clock: wait at T, a skipped tick (a live ORCH showing a watch) at
    T+5, waits at T+10..T+22, an outage tick at T+27, a wait at T+29; the start comes at T+30 by the cap.
    Main clears the count on the skipped tick, so the cap never fires here: that is the red."""
    claude, clock = FakeClaude(), FakeClock()
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh, clock=clock)
    lines: list[str] = []
    d.log = lines.append
    waits: list[float] = []
    d.admission = _busy(waits)

    clock.value = 0 * MIN  # T: held by the busy PC
    d.tick()
    assert waits == [0.0]

    clock.value = 5 * MIN  # skipped: a live ORCH is not finishing
    _live_orch(claude)
    d.tick()
    assert waits == [0.0], "a live ORCH that is not finishing skips the admission"

    for minute in (10, 15, 22):  # held again: no live ORCH
        clock.value = minute * MIN
        _no_live_orch(claude, d)
        d.tick()
    assert waits == [0.0, 600.0, 900.0, 1320.0], "the count runs from T, through the skipped tick"
    assert not claude.started

    clock.value = 27 * MIN  # skipped: an API-error ending (#931) holds the tick
    d._outage_until = 28 * MIN
    d.tick()
    assert waits[-1] == 1320.0 and len(waits) == 4

    clock.value = 29 * MIN  # held: 29 min since T, under the 30 min cap
    d.tick()
    assert waits[-1] == 1740.0 and not claude.started

    clock.value = 30 * MIN  # 30 min since T: the hold cap fires
    d.tick()
    assert waits[-1] >= 1800.0
    assert len(claude.started) == 1
    assert len([l for l in lines if "start by hold cap" in l]) == 1


def test_row2_last_wait_older_than_cap_restarts_the_count_at_zero(tmp_path):
    """A hold from 8 h ago never counts: the next wait starts its count at 0 (#971's intent)."""
    claude, clock = FakeClaude(), FakeClock()
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh, clock=clock)
    waits: list[float] = []
    d.admission = _busy(waits)

    clock.value = 0.0
    d.tick()  # t = 0: held
    assert waits == [0.0]

    clock.value = 8 * 60 * MIN  # 8 h later, the last "wait" answer is old
    d.tick()
    assert waits == [0.0, 0.0], "the count restarts at 0, it does not carry the 8 h"
    assert not claude.started, "held by the busy PC, not started by the hold cap"
