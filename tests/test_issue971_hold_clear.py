"""#971: the busy-PC hold counts its wait from the start that is held now, never from an old one.

`_admission_wait_since` is cleared by an admission check that fails (a go) and, since #1083, by a "wait"
older than the hold cap; the early returns of `_maybe_start` no longer clear it (a skipped tick keeps the
count). Row 1 is the red run on unchanged main (the new tests fail); rows 2-3 are the spec's tick sequences."""

from __future__ import annotations

import pytest

from junkroan.pob.slot_budget import admission_now
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue

MIN = 60.0


def _busy_admission(waits: list):
    """A busy PC at 9.2 (day cap 9.0): every check is a hold until the hold cap. Records `waited_s`."""

    def adm(prev, waited_s=0.0, hold_cap_s=None):
        waits.append(waited_s)
        return admission_now(now=1000.0, samples=[(1000.0 - 10 * i, 9.2) for i in range(8)],
                             previous_wait=prev, cores=12, mode="day", waited_s=waited_s,
                             hold_cap_s=hold_cap_s)

    return adm


@pytest.mark.parametrize("early", ["no candidates", "outage"])
def test_row2_early_return_clears_the_count_so_a_new_start_waits_from_40_min(tmp_path, early):
    claude, clock = FakeClaude(), FakeClock()
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh, clock=clock)
    lines: list[str] = []
    d.log = lines.append
    waits: list[float] = []
    d.admission = _busy_admission(waits)

    d.tick()  # tick 1, t = 0: held by the busy PC
    assert not claude.started and waits == [0.0]

    clock.advance(10 * MIN)  # tick 2, t = 10 min: the early return (nothing to start)
    if early == "no candidates":
        gh._candidates = []
    else:
        d._outage_until = clock() + 20 * MIN  # #931: an API-error ending, over by t = 30 min
    d.tick()
    assert not claude.started and waits == [0.0]

    clock.advance(30 * MIN)  # tick 3, t = 40 min: a new start, PC still busy
    gh._candidates = [_issue(1)]
    d.tick()
    assert not claude.started, "held by the busy PC, not started by the hold cap"
    assert waits == [0.0, 0.0], "the wait of tick 3 counts from t = 40 min, not from t = 0"
    assert not [l for l in lines if "hold cap" in l]


def test_row3_same_start_held_every_tick_starts_by_cap_at_30_min(tmp_path):
    claude, clock = FakeClaude(), FakeClock()
    d = _dispatcher(tmp_path, claude=claude, gh=FakeGh(candidates=[_issue(1)]), clock=clock)
    lines: list[str] = []
    d.log = lines.append
    waits: list[float] = []
    d.admission = _busy_admission(waits)

    for minute in (0, 10, 20):
        clock.value = minute * MIN
        d.tick()
        assert not claude.started
    clock.value = 30 * MIN
    d.tick()
    assert len(claude.started) == 1
    assert len([l for l in lines if "hold cap" in l]) == 1
    assert waits == [0.0, 600.0, 1200.0, 1800.0]


def test_admission_error_is_a_go_and_clears_the_count(tmp_path):
    claude, clock = FakeClaude(), FakeClock()
    d = _dispatcher(tmp_path, claude=claude, gh=FakeGh(candidates=[_issue(1)]), clock=clock)
    waits: list[float] = []
    d.admission = _busy_admission(waits)

    d.tick()  # t = 0: held
    assert d._admission_wait_since == 0.0

    def broken(prev, waited_s=0.0, hold_cap_s=None):
        raise RuntimeError("load check down")

    clock.advance(10 * MIN)  # t = 10 min: the check raises, which is a go: the start is made
    d.admission = broken
    d.tick()
    assert len(claude.started) == 1
    assert d._admission_wait_since is None, "a start that went through leaves no count behind"
