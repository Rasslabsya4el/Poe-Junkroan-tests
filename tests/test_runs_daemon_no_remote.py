"""#457: a runs `Daemon` built in a test reads no remote host (conftest `no_remote_read_from_test_daemon`)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import remote_store  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

_REAL_READER = remote_store.read_remote_snapshot


class _Null:
    def __getattr__(self, name):
        return lambda *a, **k: None


class _NullQueue(_Null):
    def __init__(self, path) -> None:
        self.path = path


def test_test_daemon_with_live_hosts_config_reads_no_remote_host(tmp_path, monkeypatch, ssh_guard) -> None:
    from junkroan.pob import slot_budget
    from junkroan.runs import daemon as daemon_mod
    from junkroan.runs import hosts as runs_hosts

    calls: list = []

    def counting_reader(*a, **k):
        calls.append((a, k))
        return _REAL_READER(*a, **k)

    monkeypatch.setattr(remote_store, "read_remote_snapshot", counting_reader)

    live = runs_hosts.load_hosts_config()
    assert any(h != "pc" and cfg.get("ssh") for h, cfg in live.items()), "live hosts.json has no ssh host"

    d = daemon_mod.Daemon(
        Store(tmp_path / "jobs.jsonl"), host="pc",
        launcher=_Null(), gh=_Null(), queue=_NullQueue(tmp_path),
        budget_loader=lambda: slot_budget.Budget(period="day", hours=(0, 24), total=1, others=0,
                                                 min_free_ram_gb=0.0, strict_reserve=False),
        slot_lister=lambda: [],
        events_file=tmp_path / "events.jsonl", runs_dir=tmp_path / "runs", archive=False,
        log=lambda message: None,
    )
    d.remote_handback_pass()
    d.tick()

    assert calls == []
    assert not any(isinstance(a, (list, tuple)) and a and "ssh" in str(a[0]).lower() for a in ssh_guard.passed)
