"""#1183 unit 4: the PC takes back a dead laptop's queued jobs (fake run_on_host, fake snapshot, no PoB).

The laptop's store is a real `Store`; the fake `run_on_host` runs the real `Store.cancel` there, the way
`scripts/runs.py cancel --local` does on the laptop (see tests/test_runs_remote_cancel_1183.py).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from junkroan.runs import hosts as runs_hosts
from junkroan.runs import rebalance
from junkroan.runs.remote_store import RemoteSnapshot
from junkroan.runs.store import Store
from tests.test_runs_daemon import BUDGET_NIGHT_10, FakeGh, FakeLauncher, make_daemon

CONFIG = {
    "pc": {"ssh": None, "modes": {"normal": {"day": {"hours": [0, 24], "total": 10}}}},
    "laptop": {"ssh": "laptop", "modes": {"normal": {"day": {"hours": [0, 24], "total": 3}}}},
}
CMD = "python scripts/benchmark.py --workers 1"


def rig(tmp_path: Path, monkeypatch, *, cancel_ok: bool = True):
    """A PC daemon whose laptop is a real Store; returns (daemon, pc_store, laptop_store, events, gh, launcher, ssh_scripts)."""

    laptop = Store(tmp_path / "laptop.jsonl")
    ssh_scripts: list[str] = []

    def fake_run_on_host(host_cfg, powershell_script):
        ssh_scripts.append(powershell_script)
        if not cancel_ok:  # the laptop refuses (its copy is no longer queued there): exit 1, nothing cancelled
            return subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr="cancel: refused on the laptop")
        job_id = re.search(r"'cancel' '([^']+)'", powershell_script).group(1)
        job = laptop.cancel(job_id, reason=None)
        return subprocess.CompletedProcess(["ssh"], 0, stdout=f"{job.id} -> {job.state}\n", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    gh = FakeGh()
    launcher = FakeLauncher()
    daemon, store, _ = make_daemon(tmp_path, budget=BUDGET_NIGHT_10, hosts_config=CONFIG, gh=gh, launcher=launcher)
    daemon._read_remote_snapshot = lambda cfg, host: RemoteSnapshot(
        jobs=laptop.jobs(), daemon_status=None, budget=None)
    events: list[dict] = []
    daemon._append_event = events.append
    daemon.log = lambda line: None
    return daemon, store, laptop, events, gh, launcher, ssh_scripts


def test_1183_movable_queued_laptop_job_moves_to_pc(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch)
    job = laptop.submit(host="laptop", priority="P2", tag="waiter", cmd=CMD, issue=77, workers=1, submitter="t")

    result = rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert result.moved == [job.id]
    assert result.stayed_fixed == [] and result.failed == []
    assert [j for j in laptop.jobs(state="queued") if not j.host_fixed] == []
    pc_queued = store.jobs(state="queued")
    assert len(pc_queued) == 1
    copy = pc_queued[0]
    assert (copy.host, copy.tag, copy.issue, copy.priority, copy.cmd, copy.host_fixed) == \
        ("pc", "waiter", 77, "P2", CMD, False)
    assert copy.moved_from == "laptop"
    assert laptop.get(job.id).state == "cancelled"
    assert len(events) == 1
    event = events[0]
    assert (event["kind"], event["reason"], event["job"], event["new_job"], event["from"], event["to"]) == \
        ("moved", "daemon_dead", job.id, copy.id, "laptop", "pc")


def test_1183_fixed_laptop_job_stays_and_is_named(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch)
    fixed = laptop.submit(host="laptop", priority="P2", tag="fixed", cmd=CMD, workers=1,
                          host_fixed=True, host_reason="host flag")

    result = rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert result.stayed_fixed == [fixed.id]
    assert result.moved == [] and result.failed == []
    assert laptop.get(fixed.id).state == "queued"
    assert store.jobs(state="queued") == []
    assert ssh == [] and events == []


def test_1183_remote_cancel_false_cancels_local_copy_and_fails(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch, cancel_ok=False)
    job = laptop.submit(host="laptop", priority="P2", tag="refused", cmd=CMD, workers=1)

    result = rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert result.moved == []
    assert [jid for jid, _reason in result.failed] == [job.id]
    assert store.jobs(state="queued") == []  # the PC copy was cancelled again: no live copy on the PC
    assert [j for j in store.jobs() if j.tag == "refused"][0].state == "cancelled"
    assert events == []


def test_1183_running_laptop_job_is_untouched(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch)
    running = laptop.submit(host="laptop", priority="P2", tag="runs", cmd=CMD, workers=1)
    laptop.start(running.id, out="out.txt", run_dir="run", pid=4242, workers=1)

    result = rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert result.moved == [] and result.stayed_fixed == [] and result.failed == []
    assert laptop.get(running.id).state == "running"
    assert store.jobs(state="queued") == []
    assert ssh == [] and events == []


def test_1183_no_issue_comment_and_no_keymaster_session(tmp_path: Path, monkeypatch) -> None:
    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch)
    laptop.submit(host="laptop", priority="P2", tag="waiter", cmd=CMD, issue=77, workers=1)
    laptop.submit(host="laptop", priority="P2", tag="fixed", cmd=CMD, workers=1, host_fixed=True, host_reason="host flag")

    rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert gh.comments == [] and gh.labels == []
    assert launcher.started == []


def test_1183_job_the_pc_moved_to_the_laptop_comes_back(tmp_path: Path, monkeypatch) -> None:
    """The incident itself: the rebalance sent a waiting job to the laptop (moved_from set), then the daemon died."""

    daemon, store, laptop, events, gh, launcher, ssh = rig(tmp_path, monkeypatch)
    stranded = laptop.submit(host="laptop", priority="P2", tag="stranded", cmd=CMD, issue=77, workers=1,
                             moved_from="pc")

    result = rebalance.reclaim_from_dead_host(daemon, "laptop")

    assert result.moved == [stranded.id] and result.failed == []
    assert [j.tag for j in store.jobs(state="queued")] == ["stranded"]
    assert laptop.get(stranded.id).state == "cancelled"
