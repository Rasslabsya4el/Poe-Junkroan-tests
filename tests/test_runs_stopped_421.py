"""#421: a stopped job is stored `stopped`; its issue gets the hand-back comment but not `ready-for-agent`."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402

from test_runs_daemon import FakeGh, FakeLauncher, make_daemon  # noqa: E402


@pytest.fixture(autouse=True)
def _fakes(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: True)   # the pid is gone
    monkeypatch.setattr(runs_hosts, "apply_mode", lambda h, m, **kw: {"priority": "x", "transport": "local"})
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")


def _running_job(tmp_path):
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="st", cmd="echo st", issue=21)
    daemon.tick()
    assert store.get(job.id).state == "running"
    return daemon, store, launcher, gh, job


@pytest.mark.parametrize("how", ["stop", "mode_off"])
def test_stopped_job_is_stopped_with_comment_and_no_label(tmp_path, capsys, how) -> None:
    daemon, store, launcher, gh, job = _running_job(tmp_path)
    path = str(tmp_path / "jobs.jsonl")
    argv = ["stop", job.id, "--who", "t"] if how == "stop" else ["mode", "pc", "off", "--who", "t"]
    assert runs.main(["--store", path, *argv]) == 0
    assert f"{job.id} -> stopped (stopped by t)" in capsys.readouterr().out
    launcher.finish(launcher.started[0]["pid"], 1)
    daemon.tick()
    daemon.tick()
    got = store.get(job.id)
    assert got.state == "stopped" and got.reason == "stopped by t"
    assert an.detect_job_failed(got) is None
    assert len(gh.comments) == 1
    assert "was stopped" in str(gh.comments[0]) and "needs a requeue" in str(gh.comments[0])
    assert gh.labels == [] and not daemon._label_retry
    runs.main(["--store", path, "status"])
    out = capsys.readouterr().out
    assert "stopped" in out and "failed" not in out


def test_job_failing_on_its_own_is_failed_with_comment_and_label(tmp_path) -> None:
    daemon, store, launcher, gh, job = _running_job(tmp_path)
    launcher.finish(launcher.started[0]["pid"], 1)
    daemon.tick()
    assert store.get(job.id).state == "failed"
    assert len(gh.comments) == 1
    assert gh.labels == [(21, "ready-for-agent")]
