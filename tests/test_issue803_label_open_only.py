"""#803: the run queue labels only an open issue; every label add writes one log line. No PoB, no gh, no ssh."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_daemon import FakeGh, FakeLauncher, FakeRemoteHost, make_daemon  # noqa: E402


class OpenGh(FakeGh):
    def __init__(self, open_: bool | None) -> None:
        super().__init__()
        self.open_ = open_

    def issue_open(self, issue: int) -> bool | None:
        return self.open_


def _daemon_with_log(tmp_path, gh, **kw):
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh, **kw)
    lines: list[str] = []
    daemon.log = lines.append
    return daemon, store, launcher, lines


def _end_one(daemon, store, launcher, issue=500):
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=issue)
    daemon.tick()
    launcher.finish(store.get(job.id).pid, 0)
    daemon.tick()
    return job


def _issue_lines(lines, needle="ready-for-agent"):
    return [ln for ln in lines if needle in ln and "#500" in ln]


def test_handback_on_a_closed_issue_adds_no_label_and_logs_once(tmp_path: Path) -> None:
    gh = OpenGh(False)
    daemon, store, launcher, lines = _daemon_with_log(tmp_path, gh)
    _end_one(daemon, store, launcher)
    assert len(gh.comments) == 1
    assert gh.labels == []
    assert len(_issue_lines(lines)) == 1 and "closed" in _issue_lines(lines)[0]


def test_label_retry_on_a_closed_issue_adds_no_label(tmp_path: Path) -> None:
    gh = OpenGh(False)
    daemon, store, launcher, lines = _daemon_with_log(tmp_path, gh)
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=500)
    daemon._label_retry.add((job.id, 500))
    assert daemon.retry_handbacks() == [job.id]
    assert len(_issue_lines(lines)) == 1
    assert gh.labels == []


def test_remote_handback_on_a_closed_issue_adds_no_label_and_logs_once(tmp_path: Path) -> None:
    gh = OpenGh(False)
    remote = FakeRemoteHost(tmp_path, "laptop")
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: remote.read(cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=0.0,
    )
    lines: list[str] = []
    daemon.log = lines.append
    a = remote.store.submit(host="laptop", priority="P1", tag="a", cmd="echo", issue=500)
    remote.store.start(a.id)
    remote.store.end(a.id, rc=0)
    remote.store.record_handback(a.id, f"<!-- x -->\njob `{a.id}`\n")
    daemon.remote_handback_pass()
    assert len(gh.comments) == 1
    assert gh.labels == []
    assert len(_issue_lines(lines)) == 1


def test_handback_on_an_open_issue_labels_once_and_logs_once(tmp_path: Path) -> None:
    gh = OpenGh(True)
    daemon, store, launcher, lines = _daemon_with_log(tmp_path, gh)
    _end_one(daemon, store, launcher)
    assert gh.labels == [(500, "ready-for-agent")]
    assert len(_issue_lines(lines)) == 1 and "added" in _issue_lines(lines)[0]


def test_relabel_on_a_closed_issue_exits_nonzero_and_adds_nothing(tmp_path: Path, capsys) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), OpenGh(False)
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, hosts_config={}) != 0
    assert gh.labels == []
    assert "closed" in capsys.readouterr().err


def test_relabel_on_an_open_issue_still_labels(tmp_path: Path) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), OpenGh(True)
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, hosts_config={}) == 0
    assert gh.labels == [(500, "ready-for-agent")]
