"""#861 rule 3: a pin-less job is not started on a host whose HEAD does not contain the commit it was submitted
at ("host behind main"). Real temp git repos, FakeLauncher; no PoB."""

from __future__ import annotations

import json
from pathlib import Path

from test_runs_daemon import FakeLauncher, make_daemon  # noqa: F401  (tests/ is on sys.path)
from test_runs_daemon import _isolated_daemon_status  # noqa: F401  (autouse fixture of that file)
from test_runs_daemon_follow_main import make_pair, sh

from junkroan.runs.store import Store


def build(tmp_path: Path, clone: Path):
    (tmp_path / "d").mkdir()
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path / "d", launcher=launcher)
    lines: list[str] = []
    daemon.log = lines.append
    daemon._host_checkout = clone
    return daemon, store, launcher, lines


def test_job_submitted_ahead_of_host_is_held_then_starts_after_catch_up(tmp_path: Path) -> None:
    _, clone, first, second = make_pair(tmp_path)  # clone HEAD = first; second is on origin only
    daemon, store, launcher, lines = build(tmp_path, clone)
    store.submit(host="pc", priority="P2", tag="a", cmd="echo a", submit_commit=second)

    report = daemon.tick()
    assert len(launcher.started) == 0
    assert report.started == []
    assert any("host behind main" in line and second[:12] in line for line in lines), lines
    assert store.jobs(state="queued")[0].tag == "a"

    sh(clone, "fetch", "-q", "origin")
    sh(clone, "checkout", "-q", "--detach", "origin/main")  # the host catches up
    daemon.tick()
    assert len(launcher.started) == 1


def test_pinned_job_and_job_without_commit_are_never_held(tmp_path: Path) -> None:
    _, clone, first, second = make_pair(tmp_path)
    daemon, store, launcher, lines = build(tmp_path, clone)
    store.submit(host="pc", priority="P2", tag="pinned", cmd="echo a", pin=second, submit_commit=second)
    store.submit(host="pc", priority="P2", tag="old", cmd="echo b")
    store.submit(host="pc", priority="P2", tag="same", cmd="echo c", submit_commit=first)  # host contains it

    daemon.tick()
    assert not any("host behind main" in line for line in lines), lines
    assert len(launcher.started) == 3


def test_unknown_commit_counts_as_behind(tmp_path: Path) -> None:
    _, clone, *_ = make_pair(tmp_path)
    daemon, store, launcher, lines = build(tmp_path, clone)
    store.submit(host="pc", priority="P2", tag="a", cmd="echo a", submit_commit="f" * 40)
    daemon.tick()
    assert len(launcher.started) == 0
    assert any("host behind main" in line for line in lines)


def test_status_loads_old_ledger_rows_without_the_field(tmp_path: Path, capsys) -> None:
    import runs  # scripts/ is on sys.path in test_runs_cli

    path = tmp_path / "jobs.jsonl"
    path.write_text(json.dumps({
        "ts": "2026-10-01T10:00:00", "job": "j1", "op": "submit", "host": "pc", "priority": "P2", "issue": None,
        "submitter": "", "tag": "old", "pin": None, "cmd": "echo", "resumable": False, "workers": 1,
        "after": [], "class": "run"}) + "\n", encoding="utf-8")
    job = Store(path).get("j1")
    assert job is not None and job.submit_commit is None
    assert runs.main(["--store", str(path), "status"]) == 0
    assert "old" in capsys.readouterr().out
