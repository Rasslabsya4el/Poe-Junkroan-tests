"""#468: `runs.py submit` refuses a job identical to one queued, running or done."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402
import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

BASE = ["python", "scripts/benchmark.py", "--seeds", "1"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    trees = {"pinA": "tree1", "pinB": "tree1", "pinC": "tree2"}
    monkeypatch.setattr(runs, "_src_tree_hash", lambda pin: trees.get(pin))
    monkeypatch.setattr(runs, "finished_run_dir", lambda tag, root: None)
    path = tmp_path / "jobs.jsonl"

    def submit(tag, cmd, pin="pinA", extra=()):
        return runs.main(["--store", str(path), "submit", "--host", "pc", "--priority", "P1",
                          *([] if ("--issue" in extra or "--no-issue" in extra) else ["--issue", "1"]), "--pin", pin, *extra, "--", *cmd])
    return Store(path), submit


def test_same_tree_same_command_modulo_workers_refused(env, capsys):
    store, submit = env
    assert submit("a", [*BASE, "--workers", "3", "--tag", "x"]) == 0
    first = capsys.readouterr().out.strip()
    assert submit("b", [*BASE, "--workers=5", "--tag=y"], pin="pinB") == 1
    err = capsys.readouterr().err
    assert first in err and "(queued)" in err and "tree1" in err
    assert len(store.jobs()) == 1


def test_different_command_accepted(env):
    store, submit = env
    assert submit("a", BASE) == 0
    assert submit("b", [*BASE, "--loop-seconds", "5400"]) == 0
    assert len(store.jobs()) == 2


def test_different_tree_accepted(env):
    store, submit = env
    assert submit("a", BASE) == 0
    assert submit("b", BASE, pin="pinC") == 0


def test_again_overrides(env):
    store, submit = env
    assert submit("a", BASE) == 0
    assert submit("b", BASE, extra=["--again"]) == 0


@pytest.mark.parametrize("end", ["cancel", "fail"])
def test_ended_not_ok_job_does_not_block(env, end):
    store, submit = env
    assert submit("a", BASE) == 0
    job = store.jobs()[0]
    if end == "cancel":
        store.cancel(job.id)
    else:
        store.start(job.id)
        store.end(job.id, rc=1)
    assert store.get(job.id).state in ("cancelled", "failed")
    assert submit("b", BASE) == 0


def test_done_job_blocks(env, capsys):
    store, submit = env
    assert submit("a", BASE) == 0
    job = store.jobs()[0]
    store.start(job.id)
    store.end(job.id, rc=0)
    assert submit("b", BASE) == 1
    assert "(done)" in capsys.readouterr().err


# -- #468 row 2: a refused submit's issue gets the hand-back too ------------------------------------

def _tests_dir():
    sys.path.insert(0, str(ROOT / "tests"))


def test_refused_submit_records_its_issue_and_reload_keeps_it(env, capsys):
    store, submit = env
    assert submit("a", BASE, extra=["--issue", "446"]) == 0
    first = capsys.readouterr().out.strip()
    assert submit("b", BASE, extra=["--issue", "447"]) == 1
    assert "#447 recorded on it, its hand-back goes there too" in capsys.readouterr().err
    assert submit("c", BASE, extra=["--issue", "447"]) == 1       # again: deduplicated
    capsys.readouterr()
    assert Store(store.path).get(first).extra_issues == (447,)


def test_refused_submit_without_issue_or_with_same_issue_records_nothing(env, capsys):
    store, submit = env
    assert submit("a", BASE, extra=["--issue", "446"]) == 0
    first = capsys.readouterr().out.strip()
    n_lines = len(store.path.read_text(encoding="utf-8").splitlines())
    assert submit("c", BASE, extra=["--issue", "446"]) == 1
    assert "recorded" not in capsys.readouterr().err
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == n_lines
    assert Store(store.path).get(first).extra_issues == ()
    # a ticketless run is only the core run (#578): the same core command again records nothing
    core = ["python", "scripts/benchmark.py", "--set", "core14"]
    assert submit("d", core, extra=["--no-issue"]) == 0
    capsys.readouterr()
    n_lines = len(store.path.read_text(encoding="utf-8").splitlines())
    assert submit("e", core, extra=["--no-issue"]) == 1
    assert "recorded" not in capsys.readouterr().err
    assert len(store.path.read_text(encoding="utf-8").splitlines()) == n_lines


def test_hand_back_goes_to_every_recorded_issue(tmp_path):
    _tests_dir()
    from test_runs_daemon import FakeGh, FakeLauncher, make_daemon
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=446)
    store.add_issue(job.id, 447)
    store.add_issue(job.id, 447)
    store.add_issue(job.id, 446)
    daemon.tick()
    launcher.finish(store.get(job.id).pid, 0)
    daemon.tick()
    assert sorted(i for i, _ in gh.comments) == [446, 447]
    assert sorted(gh.labels) == [(446, "ready-for-agent"), (447, "ready-for-agent")]
    daemon.tick()
    assert len(gh.comments) == 2                                  # never twice
    done = Store(store.path).get(job.id)
    assert done.posted and done.posted_extra == (447,) and not done.handback_pending


def test_a_failed_extra_post_retries_without_duplicating_the_first(tmp_path):
    _tests_dir()
    from test_runs_daemon import FakeGh, FakeLauncher, make_daemon
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=446)
    store.add_issue(job.id, 447)
    daemon.tick()
    real = gh.comment
    gh.comment = lambda issue, body: False if issue == 447 else real(issue, body)
    launcher.finish(store.get(job.id).pid, 0)
    daemon.tick()
    assert [i for i, _ in gh.comments] == [446]
    gh.comment = real
    daemon.retry_handbacks()
    assert sorted(i for i, _ in gh.comments) == [446, 447]
