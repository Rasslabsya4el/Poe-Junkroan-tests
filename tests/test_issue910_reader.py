"""#910: the PC daemon's remote reader opens the job log where the host's daemon WRITES it.

The laptop daemon runs from a linked git worktree (`...-daemon`), so `store.DEFAULT_LOG` lies under the MAIN
checkout; the reader used to open `<daemon_repo_path>\\artifacts\\runs\\jobs.jsonl`, found nothing, read an
empty list and never handed a failed job back. No ssh and no PoB: the transport is a fake that runs the
script's paths against a local temp tree.
"""

from __future__ import annotations

import base64
import gzip
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import pytest  # noqa: E402

from junkroan.runs import remote_store  # noqa: E402
from test_runs_daemon import FakeGh, make_daemon  # noqa: E402


class _Result:
    returncode = 0
    stderr = ""

    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _gz64(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode("ascii")


def _fake_ssh(script: str) -> str:
    """What the remote powershell would print: reads the `$x = '<path>'` files from the local tree."""

    paths = dict(re.findall(r"\$(p|j|s|b) = '([^']*)'", script))

    def blob(key: str, missing: str) -> str:
        path = Path(paths[key])
        return _gz64(path.read_bytes()) if path.is_file() else missing

    if remote_store._SNAPSHOT_SPLIT in script:
        sep = f"\n{remote_store._SNAPSHOT_SPLIT}\n"
        return sep.join([blob("j", remote_store._MISSING_MARK), blob("s", ""), blob("b", "")])
    return blob("p", remote_store._MISSING_MARK)


def _transport(host_cfg, script, *, timeout):
    return _Result(_fake_ssh(script))


def _host(tmp_path: Path, rows: list[dict] | None, *, configured: bool = True) -> dict:
    """A laptop whose daemon checkout is a git worktree of `main` and whose log lies under `main`."""

    main = tmp_path / "main"
    daemon = tmp_path / "main-daemon"
    (main / ".git" / "worktrees" / "main-daemon").mkdir(parents=True)
    daemon.mkdir()
    (daemon / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'main-daemon'}\n", encoding="utf-8")
    runs = main / "artifacts" / "runs"
    runs.mkdir(parents=True)
    if rows is not None:
        (runs / "jobs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    cfg = {"ssh": "laptop", "repo_path": str(main), "daemon_repo_path": str(daemon)}
    if configured:
        cfg["jobs_log_path"] = str(runs / "jobs.jsonl")
    return cfg


def _submit(job: str, issue: int, ts: str) -> dict:
    return {"ts": ts, "job": job, "op": "submit", "host": "laptop", "priority": "P1", "issue": issue,
            "submitter": "", "tag": "t-" + job, "pin": "59923532", "cmd": "echo hi", "resumable": False,
            "workers": 1, "after": []}


def _failed_rows(ts: datetime) -> list[dict]:
    stamp = lambda d: (ts + timedelta(seconds=d)).isoformat()  # noqa: E731
    return [
        _submit("j-1", 910, stamp(0)),
        {"ts": stamp(1), "job": "j-1", "op": "start", "workers": 1, "pid": 1},
        {"ts": stamp(5), "job": "j-1", "op": "end", "rc": None, "reason": "pin 59923532 is not on this host"},
        {"ts": stamp(6), "job": "j-1", "op": "handback", "body": "<!-- runs-daemon -->\nfailed: pin not on this host\n"},
    ]


def test_a_reader_returns_the_rows_of_a_worktree_daemons_main_root_log(tmp_path: Path) -> None:
    t0 = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    cfg = _host(tmp_path, _failed_rows(t0))
    jobs = remote_store.read_remote_jobs(cfg, transport=_transport)
    assert [j.id for j in jobs] == ["j-1"] and jobs[0].state == "failed"
    snap = remote_store.read_remote_snapshot(cfg, host="laptop", transport=_transport)
    assert [j.id for j in snap.jobs] == ["j-1"]


def test_b_failed_rc_null_job_gets_one_comment_and_one_label_within_five_minutes(tmp_path: Path, monkeypatch) -> None:
    t0 = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    cfg = _host(tmp_path, _failed_rows(t0))
    monkeypatch.setattr(remote_store, "default_remote_transport", _transport)
    clock = {"t": t0.timestamp() + 6}
    commented_at: list[float] = []

    class Gh(FakeGh):
        def comment(self, issue, body):
            commented_at.append(clock["t"])
            return super().comment(issue, body)

        def issue_open(self, issue):
            return True

    gh = Gh()
    daemon, _, _ = make_daemon(tmp_path, gh=gh, host="pc", hosts_config={"laptop": cfg},
                               remote_pass_seconds=0.0, remote_mark_posted=lambda *a: True)
    daemon.clock = lambda: clock["t"]
    clock["t"] += 90      # the first pass after the end row
    assert daemon.remote_handback_pass() == ["j-1"]
    assert len(gh.comments) == 1 and gh.comments[0][0] == 910
    assert gh.labels == [(910, daemon.label)]
    assert commented_at[0] - (t0.timestamp() + 5) <= 300


def test_c_missing_log_is_one_logged_line_naming_the_path_not_silence(tmp_path: Path, monkeypatch) -> None:
    cfg = _host(tmp_path, None)
    with pytest.raises(remote_store.RemoteJobsLogMissing) as err:
        remote_store.read_remote_jobs(cfg, transport=_transport)
    assert cfg["jobs_log_path"] in str(err.value)

    monkeypatch.setattr(remote_store, "default_remote_transport", _transport)
    lines: list[str] = []
    daemon, _, _ = make_daemon(tmp_path, host="pc", hosts_config={"laptop": cfg}, remote_pass_seconds=0.0)
    daemon.log = lines.append
    assert daemon.remote_handback_pass() == []
    missing = [m for m in lines if "job log is missing" in m]
    assert len(missing) == 1 and cfg["jobs_log_path"] in missing[0]


def test_an_existing_empty_log_is_still_no_jobs(tmp_path: Path) -> None:
    cfg = _host(tmp_path, [])
    assert remote_store.read_remote_jobs(cfg, transport=_transport) == []
    assert remote_store.read_remote_snapshot(cfg, host="laptop", transport=_transport).jobs == []


def test_laptop_entry_of_hosts_json_names_the_main_root_log() -> None:
    cfg = json.loads((ROOT / "config" / "hosts.json").read_text(encoding="utf-8"))["laptop"]
    assert cfg["jobs_log_path"] == "C:\\Coding\\poe-junkroan-v2\\artifacts\\runs\\jobs.jsonl"
    assert remote_store.remote_jobs_log_path({"daemon_repo_path": "D:\\d"}) == "D:\\d\\artifacts\\runs\\jobs.jsonl"
