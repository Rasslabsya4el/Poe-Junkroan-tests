"""The stall bound of a full run (PoB-free): a run in which no test finishes for longer than a bound derived from
the plan's longest test and the share of a core the child got ends with one reason line, frees the lock and lets
the pending commit's run start; a run that keeps moving, even slowly or starved, is never cut.

No fixed seconds: the real-child tests scale every wait by ``unit`` (one measured start of a bare python child)."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

from tools.agentops import full_run, merge
from tools.agentops.merge import StallWatch
from tools.agentops.suite_plan import plan_path
from tests.timing_bound import bound


def _unit() -> float:
    best = []
    for _ in range(3):
        t = time.monotonic()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        best.append(time.monotonic() - t)
    return max(max(best), bound(0.25, 2))   # #858: a load spike during a child start must stay under 10 units


def _plan(out: Path, longest: float) -> None:
    plan_path(out).write_text(json.dumps({"seconds": [1.0, longest, 0.5]}), encoding="utf-8")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# merge_suite_total_limit of the fake clocks: far past their hours, so the 4 h ceiling without a limit (#63) never cuts them
FAR = 10 ** 12


def _watch(tmp_path: Path, longest: float = 10.0) -> tuple[StallWatch, Clock]:
    out = tmp_path / "s.out"
    _plan(out, longest)
    clock = Clock()
    return StallWatch(out, interval=1, factor=3, min_share=0.05, clock=clock, total_limit=FAR), clock


# -- the rule, read on fixed readings (fake clock and CPU) ------------------------------------------

def test_a_run_with_no_new_dot_is_cut_at_factor_x_longest_over_share(tmp_path):
    w, clock = _watch(tmp_path)               # longest 10 s, factor 3
    assert w.tick(".", cpu_now=0.0) == ""      # #1020: the first test finished; the window opens here
    clock.t = 29.0
    assert w.tick(".", cpu_now=29.0) == ""     # one full core: bound 30 s
    clock.t = 30.0
    line = w.tick(".", cpu_now=30.0)
    assert line.startswith("stalled: no test finished for 30 s") and "\n" not in line
    assert "3 x longest test 10 s / 1.00 of a core" in line


def test_a_starved_run_gets_a_longer_bound(tmp_path):
    w, clock = _watch(tmp_path)
    assert w.tick(".", cpu_now=0.0) == ""      # #1020: the first test finished; the window opens here
    for wall in (30.0, 100.0, 299.0):          # a tenth of a core: bound 300 s
        clock.t = wall
        assert w.tick(".", cpu_now=wall * 0.1) == ""
    clock.t = 300.0
    assert "0.10 of a core" in w.tick(".", cpu_now=30.0)


def test_a_hung_test_burning_no_cpu_is_cut_at_the_share_floor(tmp_path):
    w, clock = _watch(tmp_path)               # share held at 0.05: bound 3 x 10 / 0.05 = 600 s
    assert w.tick(".", cpu_now=0.0) == ""      # #1020: the first test finished; the window opens here
    clock.t = 599.0
    assert w.tick(".", cpu_now=0.0) == ""
    clock.t = 600.0
    assert "0.05 of a core" in w.tick(".", cpu_now=0.0)


def test_a_moving_run_is_never_cut_however_long_it_takes(tmp_path):
    w, clock = _watch(tmp_path)
    dots = ""
    for i in range(1, 200):                    # a dot every 25 s (bound 30 s at a full core): 5000 s in all
        clock.t = i * 25.0
        assert w.tick(dots, cpu_now=clock.t) == ""   # 25 s since the last dot
        dots += "."


def test_a_starved_run_that_moves_is_never_cut(tmp_path):
    w, clock = _watch(tmp_path)
    dots = ""
    for i in range(1, 100):                    # a dot every 200 s at a twentieth of a core: bound 600 s
        clock.t = i * 200.0
        assert w.tick(dots, cpu_now=clock.t * 0.05) == ""
        dots += "."


def test_a_dot_arriving_just_before_the_bound_resets_the_window(tmp_path):
    w, clock = _watch(tmp_path)
    clock.t = 29.0
    assert w.tick("", cpu_now=29.0) == ""
    clock.t = 30.0
    assert w.tick(".", cpu_now=30.0) == ""     # a new dot: the window restarts here
    clock.t = 59.0
    assert w.tick(".", cpu_now=59.0) == ""
    clock.t = 60.0
    assert w.tick(".", cpu_now=60.0) != ""


def test_without_a_plan_there_is_no_bound(tmp_path):
    w = StallWatch(tmp_path / "none.out", interval=1, factor=3, min_share=0.05, clock=Clock(), total_limit=FAR)
    assert w.tick("", cpu_now=0.0, now=10 ** 9) == ""


# -- real children ----------------------------------------------------------------------------------

def _script(tmp_path: Path, body: str) -> str:
    p = tmp_path / "fake_suite.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return f'"{sys.executable}" "{p}"'


def test_a_fake_suite_that_never_finishes_a_test_ends_with_one_reason_line(tmp_path):
    unit = _unit()
    longest = 10 * unit
    out = tmp_path / "s.out"
    _plan(out, longest)
    # one test finishes (a dot, #1020: the window opens at the first dot), then no test ever finishes
    cmd = _script(tmp_path, f"import sys, time\nsys.stdout.write('.')\nsys.stdout.flush()\ntime.sleep({60 * longest})\n")
    watch = StallWatch(out, interval=unit / 2, factor=1, min_share=1.0)       # bound = the longest test
    ok, output = merge._run_suite(cmd, tmp_path, None, out, stall=watch)   # the child sleeps 60 x longest: only a cut ends it with a reason
    assert not ok
    lines = [l for l in out.read_text(encoding="utf-8").splitlines() if l]
    assert len(lines) == 2 and lines[0] == "." and lines[1].startswith("stalled: no test finished for ") and "longest test" in lines[1]
    assert output == ".\n" + lines[1] + "\n" and watch.reason == lines[1]


def test_a_real_run_that_moves_slowly_is_not_cut(tmp_path):
    unit = _unit()
    longest = 20 * unit                        # #858: the child start inside the first window can take many units under load
    out = tmp_path / "s.out"
    _plan(out, longest)
    gap = 2 * unit                             # a tenth of the bound; twelve dots take more than the bound in all
    cmd = _script(tmp_path, f"""
        import sys, time
        for i in range(12):
            end = time.monotonic() + {gap}
            while time.monotonic() < end:    # #858: spins, so a starved child shows a small share and gets the longer bound
                pass
            sys.stdout.write(".")
            sys.stdout.flush()
    """)
    watch = StallWatch(out, interval=unit / 2, factor=1, min_share=0.1)
    ok, output = merge._run_suite(cmd, tmp_path, None, out, stall=watch)
    assert ok and output == "............" and watch.reason == "", (ok, output, watch.reason)


# -- the whole path: lock freed, the pending commit's run starts ------------------------------------

def test_a_stalled_full_run_frees_the_lock_and_the_pending_commit_runs(tmp_path, monkeypatch, capsys):
    unit = _unit()
    longest = 10 * unit
    wt = tmp_path / "wt"
    wt.mkdir()
    monkeypatch.setattr(full_run, "ensure_suite_worktree", lambda *a, **k: wt)
    monkeypatch.setattr(full_run._merge, "_augmented_suite_cmd", lambda c: c)
    monkeypatch.setattr(full_run._merge, "_with_workers", lambda c, p, w: (c, 1, ""))
    monkeypatch.setattr(full_run._merge, "resolve_suite_shared", lambda: None)
    monkeypatch.setattr(merge, "STALL_POLL_SECONDS", unit / 2)
    monkeypatch.setattr(merge, "STALL_FACTOR", 1)
    monkeypatch.setattr(merge, "STALL_MIN_SHARE", 1.0)
    marks = tmp_path / "marks"
    marks.mkdir()
    suite = _script(tmp_path, f"""
        import json, os, sys, time
        from pathlib import Path
        marks = Path({str(marks)!r})
        Path(os.environ["SUITE_PLAN_FILE"]).write_text(json.dumps({{"seconds": [{longest}]}}))
        if not (marks / "first").exists():
            (marks / "first").write_text("x")
            sys.stdout.write(".")       # #1020: one test finishes, then none does
            sys.stdout.flush()
            time.sleep({60 * longest})
        (marks / "second").write_text(os.environ["SUITE_PLAN_FILE"])
        sys.stdout.write(".")
    """)
    first, second = "a" * 40, "b" * 40
    full_run.write_pending(tmp_path, second)    # a call during the run asked for the next commit
    rc = full_run.run_full(first, root=tmp_path, suite_cmd=suite, suite_env={}, gh=lambda args: None,
                           resolve_head=lambda: second)
    assert not full_run.lock_path(tmp_path).exists()
    assert not full_run.pending_path(tmp_path).exists()
    assert (marks / "second").read_text().endswith("bbbbbbbb.out.plan.json")   # the pending commit's run started
    out = capsys.readouterr().out
    assert sum("stalled:" in l for l in out.splitlines() if "full run aaaaaaaa" in l) == 1  # #1020: a dot may precede the line
    assert rc == 0 and "full run bbbbbbbb: green" in out
