"""#750 unit 2: `runs.py weekly` and `runs.py recut` (rows 3-6). Temp git repos and store, no PoB, no daemon, no network."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import benchmark  # noqa: E402
import runs  # noqa: E402
from junkroan.runs import weekly_cut as wc  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

MONDAY = date(2026, 10, 12)


def sh(repo: Path, *args: str, when: str | None = None) -> str:
    env = dict(os.environ)
    if when:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = when
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=env).stdout.strip()


def make_commit(work: Path, name: str, when: str) -> str:
    (work / "f.txt").write_text(name)
    sh(work, "add", "-A")
    sh(work, "commit", "-q", "-m", name, when=when)
    return sh(work, "rev-parse", "HEAD")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A work repo (the cut at an old commit, origin/main one commit later), a store, host pc."""
    work = tmp_path / "work"
    work.mkdir()
    sh(work, "init", "-q", "-b", "main")
    sh(work, "config", "user.email", "t@t")
    sh(work, "config", "user.name", "t")
    old = make_commit(work, "old", "2026-10-02T12:00:00+03:00")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(work), str(origin)], check=True)
    sh(work, "remote", "add", "origin", str(origin))
    sh(work, "fetch", "-q", "origin")
    new = make_commit(work, "new", "2026-10-10T12:00:00+03:00")
    sh(work, "push", "-q", "origin", "main")
    sh(work, "reset", "-q", "--hard", old)  # the checkout is behind; recut fetches
    monkeypatch.setattr(runs, "ROOT", work)
    monkeypatch.setattr(runs, "_now", lambda: datetime(2026, 10, 10, 12, 0))  # Saturday -> week of 12.10
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: True)
    monkeypatch.setattr(runs.runs_pin_ref, "missing_script", lambda *a, **k: None)  # #877 rule 4 is not this test's subject: the fake work repo holds no scripts
    monkeypatch.setattr(runs, "_src_tree_hash", lambda pin: "h")
    store_path = tmp_path / "jobs.jsonl"
    return argparse.Namespace(work=work, origin=origin, old=old, new=new, store=store_path, tmp=tmp_path)


def run(env, *a) -> int:
    return runs.main(["--store", str(env.store), *a])


def switch(monkeypatch, on: bool):
    monkeypatch.setattr(runs, "_any_filler_switch", lambda: on)


def test_row4_switch_off_submits_todays_line(env, monkeypatch, capsys):
    switch(monkeypatch, False)
    monkeypatch.setenv("JUNKROAN_HOST", "laptop")  # #1165: the no-folder line is host laptop; run as the laptop so the submit is local
    assert run(env, "weekly") == 0
    jobs = Store(env.store).jobs()
    assert len(jobs) == 1
    j = jobs[0]
    assert j.host == "laptop" and j.priority == "P2" and j.issue is None and not j.pin
    assert "--resume" not in j.cmd
    assert "--set core14 --gear wishlist --seed 4 --seeds 3 --workers auto" in j.cmd
    assert "week-20261012" in j.note and "weekly core run" in j.note


def test_row3_switch_on_resumes_week_folder_at_the_cut(env, monkeypatch):
    switch(monkeypatch, True)
    assert run(env, "weekly") == 0
    j = Store(env.store).jobs()[0]
    folder = wc.find_week_folder(env.work, MONDAY)
    assert folder is not None and json.loads((folder / "args.json").read_text())["commit"] == env.old
    assert j.pin == env.old and j.host == "pc" and j.priority == "P2"
    assert f"--resume artifacts/benchmark/{folder.name}" in j.cmd and "week-20261012" in j.note
    # a second call finds the folder, opens nothing new
    assert run(env, "weekly", ) in (0, 1)
    assert len(list((env.work / "artifacts" / "benchmark").glob("*-week-20261012"))) == 1


def test_row3_missing_prints_the_rows_the_folder_lacks(env):
    folder = wc.open_week_folder(env.work, MONDAY, env.old)
    cfg = json.loads((folder / "args.json").read_text())
    stems = [f"{slug}-s{sd}" for sd in range(4, 7) for slug in cfg["slugs"]]
    for stem in stems[:21]:
        (folder / "rows" / f"{stem}.json").write_text(json.dumps({"slug": stem, "ok": False}))
    ns = argparse.Namespace(slugs=cfg["slugs"], seeds=3, seed=4, no_variants=True, construction_only=False, missing=True, row=None)
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert benchmark._single_rows(ns, folder) == 0
    assert buf.getvalue().split() == stems[21:] and len(stems[21:]) == 21


def test_row5_recut_cancels_fillers_drops_folder_opens_new(env, monkeypatch, capsys):
    switch(monkeypatch, True)
    calls = []
    monkeypatch.setattr(runs, "_run_commit", lambda argv: calls.append(argv) or 0)
    folder = wc.open_week_folder(env.work, MONDAY, env.old)
    for i in range(20):
        (folder / "rows" / f"b{i}.json").write_text("{}")
    store = Store(env.store)
    fillers = []
    for n in range(2):
        job = store.submit(host="pc", priority="P2", tag=f"filler-{n}", cmd="echo", job_class="filler")
        store.start(job.id)
        fillers.append(job.id)
    capsys.readouterr()
    assert run(env, "recut") == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1 and env.old[:7] in out[0] and env.new[:7] in out[0] and out[0].endswith("20")
    for jid in fillers:
        assert Store(env.store).get(jid).state == "stopped"
    base = env.work / "artifacts" / "benchmark"
    dropped = base / f"{folder.name}-dropped-{env.old[:7]}"
    assert len(list((dropped / "rows").glob("*.json"))) == 20
    new = wc.find_week_folder(env.work, MONDAY)
    assert new is not None and new != dropped and not list((new / "rows").glob("*.json"))
    assert json.loads((new / "args.json").read_text())["commit"] == env.new
    assert json.loads((env.work / "config" / "weekly_cut.json").read_text()) == {"20261012": env.new}
    assert len(calls) == 1
    argv = calls[0]
    assert argv[1:4] == ["-m", "tools.agentops", "commit"] and "--detach" in argv and argv[-1] == "config/weekly_cut.json"
    assert env.old[:7] in argv[4 + 1]


def test_recut_resubmits_the_monday_line_only_when_it_ran(env, monkeypatch):
    switch(monkeypatch, True)
    monkeypatch.setattr(runs, "_run_commit", lambda argv: 0)
    assert run(env, "weekly") == 0
    first = Store(env.store).jobs()[0]
    Store(env.store).start(first.id)
    assert run(env, "recut") == 0
    jobs = Store(env.store).jobs()
    assert jobs[0].state == "stopped" and len(jobs) == 2
    assert jobs[1].pin == env.new and jobs[1].state == "queued"


def test_row6_second_checkout_reads_the_same_cut(env, monkeypatch):
    switch(monkeypatch, False)
    monkeypatch.setattr(runs, "_run_commit", lambda argv: 0)
    assert run(env, "recut") == 0
    # the commit/push runner is stubbed: do by hand what it does, into the temp origin
    sh(env.work, "reset", "-q", "--hard", "origin/main")
    sh(env.work, "add", "config/weekly_cut.json")
    sh(env.work, "commit", "-q", "-m", "override")
    sh(env.work, "push", "-q", "origin", "main")
    other = env.tmp / "other"
    subprocess.run(["git", "clone", "-q", str(env.origin), str(other)], check=True)
    assert wc.cut_for_week(other, MONDAY) == env.new
    assert wc.cut_for_week(env.work, MONDAY) == env.new


def test_cmd_daemon_passes_the_checkout_as_cut_repo(env, monkeypatch):
    from junkroan.runs import daemon as daemon_mod
    seen = []

    class Stub:
        def __init__(self, store, host=None, **kwargs):
            seen.append(kwargs)

        def budget(self):
            class B:
                total = 0
                period = "x"
                def limit_for(self, role): return 0
                def window(self): return ""
            return B()

        def run(self, **kw):
            return 0

    monkeypatch.setenv("JUNKROAN_DAEMON_STATUS_DIR", str(env.tmp / "status"))
    monkeypatch.setattr(daemon_mod, "Daemon", Stub)
    run(env, "daemon", "--host", "pc", "--ticks", "0")
    assert len(seen) == 1 and seen[0]["cut_repo"] == env.work


@pytest.mark.parametrize("filler_switch", [False, True])
def test_928_weekly_again_runs_an_identical_tree_as_a_second_sample(env, monkeypatch, capsys, filler_switch):
    switch(monkeypatch, filler_switch)
    if not filler_switch:
        monkeypatch.setenv("JUNKROAN_HOST", "laptop")  # #1165: the no-folder line is host laptop; run as the laptop so the submit is local
    assert run(env, "weekly") == 0
    first = Store(env.store).jobs()[0]
    Store(env.store).start(first.id)
    if not filler_switch:  # a job without a pin never matches find_identical (dedupe.py:66): stand in for a started one
        monkeypatch.setattr(runs, "find_identical", lambda jobs, **kw: next(iter(jobs), None))
    capsys.readouterr()
    assert run(env, "weekly") == 1
    err = capsys.readouterr().err
    assert "identical to" in err and "`runs.py weekly --again`" in err
    assert len(Store(env.store).jobs()) == 1
    assert run(env, "weekly", "--again") == 0
    assert len(Store(env.store).jobs()) == 2


def test_928_submit_keeps_its_own_hint(env, monkeypatch, capsys):
    argv = ["--host", "pc", "--priority", "P2", "--no-issue", "--", *runs.WEEKLY_CORE_LINE]
    assert run(env, "submit", *argv) == 0
    capsys.readouterr()
    monkeypatch.setattr(runs, "find_identical", lambda jobs, **kw: next(iter(jobs), None))  # no pin on a queued job
    assert run(env, "submit", *argv) == 1
    err = capsys.readouterr().err
    assert "pass --again to run it anyway" in err and "weekly" not in err.split("pass")[-1]
