"""#907: a hold longer than the cap becomes a go (day and night); play never caps."""

from __future__ import annotations

import json

from junkroan.pob.slot_budget import admission_now
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue
from tests.test_issue690_full_run import env, STUB  # noqa: F401  (the fixture)
from tools.agentops import full_run as fr

MIN = 60.0


def _adm(mean, mode, waited_s, cap):
    return admission_now(now=1000.0, samples=[(1000.0 - 10 * i, mean) for i in range(8)],
                         previous_wait=True, cores=12, mode=mode, waited_s=waited_s, hold_cap_s=cap)


def test_row1_day_29_min_still_waits():
    adm = _adm(9.5, "day", 29 * MIN, 1800)
    assert not adm.go and adm.reason != "hold cap"


def test_row2_orch_30_min_goes_by_cap():
    adm = _adm(9.5, "day", 30 * MIN, 1800)
    assert adm.go and adm.reason == "hold cap"
    line = adm.line()
    assert "hold cap" in line and "9.5" in line and "30 min" in line


def test_row3_play_never_caps():
    adm = _adm(0.5, "play", 5 * 3600, 1800)
    assert not adm.go


def test_row4_full_run_59_waits_60_goes():
    assert not _adm(9.5, "normal", 59 * MIN, 3600).go
    adm = _adm(9.5, "normal", 60 * MIN, 3600)
    assert adm.go and adm.reason == "hold cap"


def test_row5_dispatcher_holds_30_min_then_starts_once_with_one_cap_line(tmp_path):
    claude, clock = FakeClaude(), FakeClock()
    d = _dispatcher(tmp_path, claude=claude, gh=FakeGh(candidates=[_issue(1)]), clock=clock)
    lines: list[str] = []
    d.log = lines.append
    d.admission = lambda prev, waited_s=0.0, hold_cap_s=None: admission_now(
        now=1000.0, samples=[(1000.0 - 10 * i, 9.2) for i in range(8)], previous_wait=prev, cores=12,
        mode="day", waited_s=waited_s, hold_cap_s=hold_cap_s)
    d.run(ticks=59, sleep=lambda s: clock.advance(30))  # ticks at 0 .. 29 min
    assert not claude.started
    d.run(ticks=3, sleep=lambda s: clock.advance(30))  # reaches 30 min
    assert len(claude.started) == 1
    assert len([l for l in lines if "hold cap" in l]) == 1


def test_full_run_hold_state_is_rewritten_never_removed(env, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(fr, "_one_run", lambda *a, **k: calls.append(1) or 0)
    t = {"now": 5_000_000.0}

    def gate(waited_s=0.0, hold_cap_s=None):
        return admission_now(now=1000.0, samples=[(1000.0 - 60 * i, 9.5) for i in range(10)], cores=12,
                             mode="normal", waited_s=waited_s, hold_cap_s=hold_cap_s)

    def go():
        return fr.run_full(env.c1, root=env.repo, suite_cmd=env.cmd, suite_env=env.suite_env,
                           gh=lambda a: None, resolve_head=lambda: env.c3, admission=gate, clock=lambda: t["now"])

    hold = fr.hold_path(env.repo)
    assert go() == 0 and calls == []
    assert json.loads(hold.read_text())["since"] == t["now"]
    t["now"] += 59 * MIN
    assert go() == 0 and calls == []
    t["now"] += 1 * MIN
    assert go() == 0 and calls == [1]  # 60 min: by the cap
    assert hold.exists() and json.loads(hold.read_text())["since"] is None
