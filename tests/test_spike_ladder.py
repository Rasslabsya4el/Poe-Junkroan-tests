import pytest

from junkroan.runs.spike import Ladder, Lines

W = 300.0
LINES = Lines(ram_free_mb_hard=2000, cpu_pct_soft=90, window_s=W)
GROUPS = ("pob_counted", "pob_filler", "claude", "owner", "system", "other")


def snap(free=8000.0, cpu=20.0, **over):
    groups = {g: {"cpu_pct": 1.0, "rss_mb": 500.0, "count": 1} for g in GROUPS}
    for g, v in over.items():
        groups[g] = {**groups[g], **v}
    return {"ts": "t", "free_ram_mb": free, "total_ram_mb": 32000.0, "cpu_pct": cpu,
            "groups": groups, "whole_suite_pytest": 0, "merge_suite_pytest": 0}


def run(ladder, make, t0, t1, dt=60.0):
    out, t = [], t0
    while t <= t1:
        out.append(ladder.observe(make(t), t))
        t += dt
    return out


def hog(group):
    return lambda t: snap(free=1000.0, **{group: {"rss_mb": 4000.0 + t * 5}})


@pytest.mark.parametrize("group", ["claude", "owner", "system"])
def test_ram_hog_steps(group):
    d = run(Ladder(LINES), hog(group), 0, 2 * W)
    assert d[-1].step == 2 and d[-1].cause == group
    d = run(Ladder(LINES), hog(group), 0, 3 * W)
    assert d[-1].step == 3 and d[-1].cause == group
    assert "GB" in d[-1].reason


def test_pob_never_named():
    mk = lambda t: snap(free=1000.0, pob_counted={"rss_mb": 20000.0 + t * 50})
    d = run(Ladder(LINES), mk, 0, 2 * W)
    assert d[-1].cause in ("claude", "owner", "system", "other")


def test_cpu_only_caps_at_1():
    d = run(Ladder(LINES), lambda t: snap(cpu=97.0, owner={"cpu_pct": 60.0}), 0, 6 * W)
    assert d[-1].step == 1 and d[-1].cause == "owner"
    assert max(x.step for x in d) == 1


def test_blip():
    mk = lambda t: snap(free=1000.0 if t < W - 60 else 8000.0)
    d = run(Ladder(LINES), mk, 0, 4 * W)
    assert all(x.step == 0 and not x.changed for x in d)


def test_recovery():
    ladder = Ladder(LINES)
    run(ladder, hog("claude"), 0, 3 * W)
    assert ladder.step == 3
    d = run(ladder, lambda t: snap(), 3 * W + 60, 8 * W)
    assert [x.step for x in d if x.changed] == [2, 1, 0]
    assert d[-1].step == 0


def test_from_config_missing():
    assert Lines.from_config({}) is None
    assert Lines.from_config({"ram_free_mb_hard": 1, "cpu_pct_soft": 2}) is None
    assert Lines.from_config({"ram_free_mb_hard": 1, "cpu_pct_soft": 2, "window_s": 3}) == Lines(1, 2, 3)
