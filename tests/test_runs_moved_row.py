"""A row the rebalancer moved (#655): shown as moved; cancel/stop go on to the target host. Fakes only."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

OLD = "j-20261009-1315-6217"
NEW = "j-20261009-1348-2c48"


def _store(tmp_path: Path) -> Path:
    path = tmp_path / "jobs.jsonl"
    recs = [
        {"ts": "2026-10-09T13:15:00+00:00", "job": OLD, "op": "submit", "host": "pc", "priority": "P1",
         "tag": "P1-#1", "cmd": "python -c pass"},
        {"ts": "2026-10-09T13:48:00+00:00", "job": OLD, "op": "moved", "to": f"laptop:{NEW}",
         "reason": f"moved to laptop:{NEW}"},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return path


def _fake(monkeypatch, rc=0, out="ok", err="", boom=None):
    calls: list[str] = []

    def run(cfg, script):
        calls.append(script)
        if boom:
            raise boom
        return subprocess.CompletedProcess(args=["ssh"], returncode=rc, stdout=out, stderr=err)

    monkeypatch.setattr(runs_hosts, "run_on_host", run)
    killed: list[int] = []
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: killed.append(pid) or True)
    return calls, killed


def test_a_status_row_says_moved(tmp_path, capsys):
    assert runs.main(["--store", str(_store(tmp_path)), "status", "--all", "--host", "pc"]) == 0
    row = next(l for l in capsys.readouterr().out.splitlines() if l.startswith(OLD))
    assert "moved" in row and f"laptop:{NEW}" in row and "cancelled" not in row


def test_b_cancel_goes_to_the_laptop(tmp_path, monkeypatch, capsys):
    path = _store(tmp_path)
    calls, killed = _fake(monkeypatch)
    assert runs.main(["--store", str(path), "cancel", OLD]) == 0
    assert len(calls) == 1
    assert f"cancel {NEW}" in calls[0] and "$env:JUNKROAN_HOST = 'laptop'" in calls[0]
    assert r"C:\Coding\poe-junkroan-v2-daemon" in calls[0]
    assert Store(path).get(OLD).reason.endswith(f"cancelled on laptop as {NEW}")
    assert OLD in capsys.readouterr().out and not killed


def test_b_stop_goes_to_the_laptop(tmp_path, monkeypatch):
    path = _store(tmp_path)
    calls, killed = _fake(monkeypatch, out=f"{NEW} -> stopped")
    assert runs.main(["--store", str(path), "stop", OLD]) == 0
    assert len(calls) == 1 and f"stop {NEW}" in calls[0] and "$env:JUNKROAN_HOST = 'laptop'" in calls[0]
    assert Store(path).get(OLD).reason.endswith(f"stopped on laptop as {NEW}")
    assert killed == []


def test_c_remote_error_exit_2_row_unchanged(tmp_path, monkeypatch, capsys):
    path = _store(tmp_path)
    before = path.read_text(encoding="utf-8")
    for verb in ("cancel", "stop"):
        _fake(monkeypatch, rc=1, err="job is done")
        assert runs.main(["--store", str(path), verb, OLD]) == 2
        err = capsys.readouterr().err.strip().splitlines()
        assert len(err) == 1 and "laptop" in err[0] and "job is done" in err[0]
        _fake(monkeypatch, boom=TimeoutError("ssh timed out"))
        assert runs.main(["--store", str(path), verb, OLD]) == 2
        assert "ssh timed out" in capsys.readouterr().err
    assert path.read_text(encoding="utf-8") == before
