"""#509 unit 4: the daemon's background ssh reads wait 30 s, a foreground read a human waits on 10 s."""

from __future__ import annotations
from conftest import pc_only

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from test_runs_daemon import make_daemon  # noqa: E402
from junkroan.runs import remote_store  # noqa: E402

CFG = {"laptop": {"ssh": "laptop", "repo_path": "C:/x"}}


def _recording(monkeypatch) -> list[float]:
    seen: list[float] = []

    def transport(host_cfg, script, *, timeout):
        seen.append(timeout)
        raise OSError("fake: no link")

    monkeypatch.setattr(remote_store, "default_remote_transport", transport)
    return seen


def test_daemon_snapshot_read_waits_30(tmp_path, monkeypatch) -> None:
    seen = _recording(monkeypatch)
    daemon, _store, _queue = make_daemon(tmp_path, hosts_config=CFG)
    try:
        daemon._read_remote_snapshot(CFG["laptop"], "laptop")
    except remote_store.RemoteStoreUnreachable:
        pass
    assert seen == [30.0]


def test_daemon_anomalies_read_waits_30(tmp_path, monkeypatch) -> None:
    seen = _recording(monkeypatch)
    daemon, _store, _queue = make_daemon(tmp_path, hosts_config=CFG, remote_pass_seconds=0.0)
    daemon.anomaly_guard = SimpleNamespace(adopt_remote=lambda *a, **k: None, start_keymasters=True)
    daemon.remote_anomaly_pass()
    assert seen == [30.0]


@pc_only
def test_relabel_status_read_waits_10(tmp_path, monkeypatch) -> None:
    seen = _recording(monkeypatch)
    _d, store, _q = make_daemon(tmp_path)
    runs.cmd_relabel(store, ["--issue", "500"], gh=None, hosts_config=CFG)
    assert seen == [10.0]
