"""#699: every live job's estimate and the queue's end.

    python -m pytest -q bin/test_queue_eta.py   (from the repo root, like the other bin tests)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402,F401  (the generic collector loads the add-on)

addon = collect.addon()  # the project's add-on: the subject of this file
from junkroan.runs.store import Job  # noqa: E402


def job(id_, state="queued", cmd="python x.py", tag="t", **kw) -> Job:
    return Job(id=id_, host="pc", priority="P1", issue=None, submitter="t", tag=tag, pin=None, cmd=cmd,
               resumable=False, state=state, submit_ts="2026-10-10T00:00:00+00:00", **kw)


def q(id_, workers, takes, after=()):
    return {"id": id_, "host": "pc", "workers": workers, "takes_s": takes, "after": list(after)}


def test_queued_jobs_start_when_their_slots_free():
    running = [{"id": "A", "host": "pc", "workers": 1, "locks": 4, "left_s": 600}]
    queued = [q("X", 1, 300), q("Y", 2, 100)]
    end, partial = addon.plan_queue(running, queued, {"pc": 5})
    # X takes the one free slot now; Y needs 2: X frees 1 at 300 s, A frees 4 at 600 s -> starts 600 s, ends 700 s
    assert (queued[0]["start_s"], queued[1]["start_s"]) == (0.0, 600)
    assert (end, partial) == (700, False)


def test_a_job_after_another_waits_for_its_end():
    running = [{"id": "A", "host": "pc", "workers": 1, "locks": 1, "left_s": 400}]
    queued = [q("Z", 1, 50, after=["A"]), q("W", 1, 30, after=["gone"])]  # "gone" ended: no wait
    end, partial = addon.plan_queue(running, queued, {"pc": 5})
    assert queued[0]["start_s"] == 400 and queued[1]["start_s"] == 0.0
    assert (end, partial) == (450, False)


def test_a_job_without_estimate_makes_the_end_partial():
    running = [{"id": "A", "host": "pc", "workers": 1, "locks": 1, "left_s": None}]
    queued = [q("X", 1, None), q("Y", 1, 100)]
    end, partial = addon.plan_queue(running, queued, {"pc": 1})
    assert partial is True and "start_s" not in queued[1]


def test_replay_estimate_from_its_own_finished_builds(tmp_path):
    for i in range(6):
        (tmp_path / f"b{i}-s4.pob.txt").write_text("x")
    out = tmp_path / "run.out"
    out.write_text("  smite                          1,000 -> 1,100 +10.00% 9.4 min\n"
                   "  stormbrand                     FAILED boom\n", encoding="utf-8")
    now = time.time()
    os.utime(out, (now, now))
    j = job("R", state="running", cmd=f"python scripts/replay_bench.py --builds {tmp_path}/*-s4.pob.txt --move loop --workers 2",
            start_ts=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(now - 120)), out=str(out))
    left, how = addon._replay_est(j, 2, addon._Memo())
    # #985: 2 workers, 2 finished (smite 9.4 min, one FAILED = 0 s); the next build started 2 min ago (9.4 - 2 = 7.4 min
    # left), the one after it just started (9.4 min); the last two wait: 7.4 + 9.4 = 16.8 and 9.4 + 9.4 = 18.8 min
    assert how == "rate" and abs(left - (564 + 564)) < 10


def test_queued_replay_estimate_from_against(tmp_path):
    for i in range(6):
        (tmp_path / f"b{i}-s4.pob.txt").write_text("x")
    res = tmp_path / "base" / "results.json"
    res.parent.mkdir()
    res.write_text(json.dumps({"rows": [{"ok": True, "seconds": 300}, {"ok": True, "seconds": 500}, {"ok": False, "seconds": 9}]}))
    j = job("Q", cmd=f"python scripts/replay_bench.py --builds {tmp_path}/*-s4.pob.txt --move gear --against {res.parent}")
    takes, how = addon._replay_est(j, 1, addon._Memo())
    assert (takes, how) == (6 * 400, "against")


def test_other_commands_from_past_runs_of_the_same_command():
    past = [job(f"p{i}", state="done", cmd=f"python -m pytest tests/a.py --tag T{i}", start_ts="2026-10-09T10:00:00+00:00",
                end_ts=f"2026-10-09T10:{m:02d}:00+00:00") for i, m in enumerate((10, 20, 50))]
    other = job("o", state="done", cmd="python -m pytest tests/b.py", start_ts="2026-10-09T10:00:00+00:00", end_ts="2026-10-09T11:00:00+00:00")
    j = job("n", cmd="python -m pytest tests/a.py --tag NEW")
    assert addon.estimate(j, past + [other, j], None, 1, addon._Memo()) == (1200, "history")
    assert addon.estimate(job("m", cmd="python never_ran.py"), past, None, 1, addon._Memo()) == (None, None)


def test_daemon_waits_reads_the_reason_per_job(tmp_path, monkeypatch):
    # #706: the daemon's `waits` per queued job; entries without text and a daemon without `waits` give nothing
    runs = tmp_path / "artifacts" / "runs"
    runs.mkdir(parents=True)
    (runs / "daemon-pc.json").write_text(json.dumps({"host": "pc", "waits": {
        "j-1": {"kind": "ram", "text": "RAM: свободно 4.4 из 8 GB", "host_fixed": True},
        "j-2": {"kind": "after", "text": "ждёт конца P1-#553-8"},
        "j-3": {"kind": "slots"}}}), encoding="utf-8")
    (runs / "daemon-laptop.json").write_text("", encoding="utf-8")
    monkeypatch.setattr(addon, "REPO", tmp_path)
    w = addon.daemon_waits("pc")
    assert sorted(w) == ["j-1", "j-2"]
    assert "4.4" in w["j-1"]["text"] and "8" in w["j-1"]["text"] and w["j-1"]["host_fixed"] is True
    assert addon.daemon_waits("laptop") == {} and addon.daemon_waits("nohost") == {}


# ---- #985: the estimate against the real end, on three recorded runs (fixtures/estimate_985.json) ----
# Two replays (`.out` finished-build lines) and one benchmark (its rows with their end times), cut at 50 % of their run
# time by the harness `estimate_table_985.py`: only what existed then, the run's own history cut away (no earlier run in
# the fixture), so the numbers here are lower in quality than the table's, which also had the earlier runs. The old
# formulas are the ones removed by #985, written out below from the code of that day.

def _case_at(run_id, tmp_path, monkeypatch):
    import estimate_table_985 as h
    run = json.loads((HERE / "fixtures" / "estimate_985.json").read_text(encoding="utf-8"))[run_id]
    monkeypatch.setattr(addon, "BENCH_ROOT", tmp_path / "no-history")
    (tmp_path / "no-history").mkdir()
    monkeypatch.setattr(h, "SCRATCH", tmp_path / "scratch")
    for name in ("time", "NOW", "glob"):
        monkeypatch.setattr(addon, name, getattr(addon, name))
    from junkroan.runs import build_estimate
    monkeypatch.setattr(build_estimate, "_runs_newest_first", build_estimate._runs_newest_first)
    cmd = run["cmd"]
    if run.get("against"):  # the base replay the run named: its results.json, in a folder of the test
        (tmp_path / "base").mkdir()
        (tmp_path / "base" / "results.json").write_text(json.dumps({"rows": run["against"]}), encoding="utf-8")
        cmd = re.sub(r"--against \S+", lambda _: f"--against {(tmp_path / 'base').as_posix()}", cmd)
    j = job(run_id, state="done", cmd=cmd, tag=run["tag"], start_ts=run["start_ts"], end_ts=run["end_ts"],
            workers=run["workers"])
    if run["kind"] == "replay":
        out = tmp_path / "run.out"
        out.write_text("".join(ln + "\n" for ln in run["lines"]), encoding="utf-8")
        case = h.replay_case(dataclasses.replace(j, out=str(out)))
    else:
        rows = [{**r, "start": r["end"] - r["seconds"]} for r in run["rows"]]
        case = {"kind": "bench", "job": j, "t0": h._ts(j.start_ts), "t1": h._ts(j.end_ts), "n": len(rows), "rows": rows,
                "dir": tmp_path / "bench-run", "args": run["args"], "planned": run["planned"], "par": j.workers or 1}
    t = case["t0"] + 0.5 * (case["t1"] - case["t0"])
    (left, _), _, _ = h.predict(case, t, [j])
    return h, case, t, left, case["t1"] - t


def _old_replay_left(h, case, t):
    """The formula #985 removed: the median of this run's finished builds, in waves of `par`."""
    import math
    done = [i for i, e in case["ends"].items() if e <= t]
    mine = [case["lines"][i][2] for i in done]
    left = case["n"] - len(done)
    per = statistics.median(mine)
    waves = math.ceil(left / min(case["par"], left))
    since = max(0.0, t - max(case["t0"], max(case["ends"][i] for i in done)))
    return max(per - since, per * 0.05) + per * (waves - 1)


def _old_bench_left(h, case, t):
    """`run_cells`' removed eta: the mean of the finished rows times the cells left over the workers."""
    cells = h.bench_cells(case, t)
    took = [c["took"] for c in cells if c["state"] in ("done", "failed")]
    left = [c for c in cells if c["state"] not in ("done", "failed")]
    running = sum(c["state"] == "running" for c in cells)
    return statistics.mean(took) * (len(left) - running * 0.5) / max(1, case["par"])


import dataclasses  # noqa: E402
import statistics  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.parametrize("run_id,bound", [("j-20261007-0151-e422", 0.10), ("j-20261006-2240-9479", 0.25),
                                          ("j-20260927-1526-72cb", 0.15)])
def test_estimate_at_half_a_recorded_run_beats_the_old_formula(run_id, bound, tmp_path, monkeypatch):
    h, case, t, left, actual = _case_at(run_id, tmp_path, monkeypatch)
    old = _old_replay_left(h, case, t) if case["kind"] == "replay" else _old_bench_left(h, case, t)
    new_err, old_err = abs(left - actual) / actual, abs(old - actual) / actual
    print(run_id, f"actual {actual / 60:.0f} min, new {left / 60:.0f} min ({new_err:.0%}), old {old / 60:.0f} min ({old_err:.0%})")
    assert new_err < bound and old_err > 0.5 and new_err < old_err / 2
