"""#412: `stop` / `mode off` judge the kill by the pid, not by taskkill's exit code. Fakes only."""

from __future__ import annotations

import subprocess as sp
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import anomalies as an  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

from test_runs_daemon import FakeGh, FakeLauncher, make_daemon  # noqa: E402

win_only = pytest.mark.skipif(sys.platform != "win32", reason="taskkill")


def _running(store: Store, tag: str, pid):
    job = store.submit(host="pc", priority="P1", tag=tag, cmd="echo hi")
    store.start(job.id, pid=pid)
    return job


@win_only
def test_taskkill_nonzero_exit_but_pid_gone_counts_as_killed(monkeypatch) -> None:
    monkeypatch.setattr(sp, "run", lambda *a, **k: sp.CompletedProcess(a, 1, "", "ERROR: half-gone"))
    monkeypatch.setattr(runs, "_pid_gone", lambda pid, **k: True)
    assert runs.taskkill_tree(4242) is True
    monkeypatch.setattr(runs, "_pid_gone", lambda pid, **k: False)
    assert runs.taskkill_tree(4242) is False


@win_only
def test_mode_off_nonzero_taskkill_dead_pid_stops_one_and_raises_no_anomaly(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(sp, "run", lambda *a, **k: sp.CompletedProcess(a, 1, "", "ERROR: x"))
    monkeypatch.setattr(runs, "_pid_gone", lambda pid, **k: True)
    monkeypatch.setattr(runs, "TREE_KILLER", runs.taskkill_tree)
    monkeypatch.setattr(runs_hosts, "apply_mode", lambda h, m, **kw: {"priority": "x", "transport": "local"})
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    path = tmp_path / "jobs.jsonl"
    job = _running(Store(path), "a", 77)
    assert runs.main(["--store", str(path), "mode", "pc", "off", "--who", "t"]) == 0
    assert "pc: stopped 1 running job(s)" in capsys.readouterr().out
    got = Store(path).get(job.id)
    assert got.reason == "stopped by t"
    assert an.detect_job_failed(got) is None


def test_daemon_tick_keeps_stopped_by_and_hand_back_says_stopped(tmp_path: Path) -> None:
    launcher = FakeLauncher()
    gh = FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    job = store.submit(host="pc", priority="P1", tag="st", cmd="echo st", issue=12)
    daemon.tick()
    pid = launcher.started[0]["pid"]
    store.stop(job.id, reason="stopped by hand")
    launcher.finish(pid, 1)
    daemon.tick()
    got = store.get(job.id)
    assert got.rc is None and got.reason == "stopped by hand"
    assert len(gh.comments) == 1
    body = str(gh.comments[0])
    assert "was stopped" in body and "needs a requeue" in body and "finished on host" not in body
