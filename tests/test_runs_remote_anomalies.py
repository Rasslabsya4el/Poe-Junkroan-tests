"""#467: the laptop never starts a keymaster; the PC's daemon starts it for the laptop's queue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from junkroan.runs import anomalies as an
from junkroan.runs import daemon as daemon_mod
from junkroan.runs.store import Store

from tests.test_runs_anomalies import FakeKeymasterCli, make_guard, make_job
from tests.test_runs_daemon import make_daemon

ENTRY = {"kind": "job_failed", "key": "job_failed:abc", "job": "abc", "detail": "job abc failed (rc 1)"}


def test_a_guard_with_the_start_path_off_queues_and_starts_nothing(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1, issue=48)
    launcher = FakeKeymasterCli()
    guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=launcher, host="laptop",
                            start_keymasters=False, log=lambda message: None)

    assert guard.check(ended_jobs=[job]) == []
    assert launcher.started == []
    assert [a.key for a in an._read_state(tmp_path / "anomalies.json").queue] == [f"job_failed:{job.id}"]


def test_an_adopted_laptop_anomaly_starts_one_keymaster_naming_the_host_and_job(tmp_path: Path) -> None:
    guard, launcher = make_guard(tmp_path)
    taken: list[str] = []

    adopted = guard.adopt_remote("laptop", [ENTRY], lambda key: taken.append(key) or True)
    started = guard.check()

    assert [a.key for a in adopted] == ["laptop:job_failed:abc"] and taken == ["job_failed:abc"]
    assert len(started) == 1 and len(launcher.started) == 1
    _anomaly, cmd = launcher.started[0]
    assert "keymaster: job_failed laptop abc" in " ".join(cmd)
    assert "host: laptop" in cmd[-1] and "job: abc" in cmd[-1] and "ssh laptop" in cmd[-1]
    assert "poe-junkroan-v2-daemon" in cmd[-1]
    # offered again (the mark failed last time): marked again, never queued or started twice
    assert guard.adopt_remote("laptop", [ENTRY], lambda key: True) == []
    assert guard.check() == [] and len(launcher.started) == 1


def test_take_queued_drops_the_entry_but_keeps_it_handled(tmp_path: Path) -> None:
    store = Store(tmp_path / "jobs.jsonl")
    job = make_job(store, rc=1)
    path = tmp_path / "anomalies.json"
    guard = an.AnomalyGuard(path=path, launcher=FakeKeymasterCli(), start_keymasters=False,
                            log=lambda message: None)
    guard.check(ended_jobs=[job])

    assert an.take_queued(f"job_failed:{job.id}", path) is True
    assert an.take_queued(f"job_failed:{job.id}", path) is False
    state = an._read_state(path)
    assert state.queue == [] and state.handled == {f"job_failed:{job.id}"}


def test_the_pc_daemons_remote_pass_starts_one_keymaster_for_a_laptop_anomaly(tmp_path: Path) -> None:
    laptop_queue: list[dict[str, Any]] = [dict(ENTRY)]
    marked: list[str] = []

    def mark(host_cfg: Any, host: str, key: str) -> bool:
        marked.append(key)
        laptop_queue[:] = [e for e in laptop_queue if e["key"] != key]
        return True

    launcher = FakeKeymasterCli()
    daemon, _, _ = make_daemon(tmp_path, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
                               remote_pass_seconds=0.0)
    daemon.anomaly_guard = an.AnomalyGuard(path=tmp_path / "anomalies.json", launcher=launcher,
                                           host="pc", log=lambda message: None)
    daemon._remote_anomaly_reader = lambda host_cfg: list(laptop_queue)
    daemon._remote_mark_anomaly_taken = mark

    assert daemon.remote_anomaly_pass() == ["laptop:job_failed:abc"]
    daemon._check_anomalies(daemon_mod.TickReport())

    assert len(launcher.started) == 1 and marked == ["job_failed:abc"]
    prompt = an.build_prompt(launcher.started[0][0])
    assert "host: laptop" in prompt and "job: abc" in prompt
    # a second pass finds the laptop's queue empty: nothing more starts
    assert daemon.remote_anomaly_pass() == []
    daemon._check_anomalies(daemon_mod.TickReport())
    assert len(launcher.started) == 1


def _stuck(job: str) -> dict[str, Any]:
    return {"kind": "job_stuck", "key": f"job_stuck:{job}", "job": job, "detail": f"job {job} is stuck"}


def test_a_laptop_job_stuck_whose_job_already_ended_is_not_adopted(tmp_path: Path) -> None:
    guard, launcher = make_guard(tmp_path)
    taken: list[str] = []

    adopted = guard.adopt_remote("laptop", [_stuck("X")], lambda key: taken.append(key) or True,
                                 lambda job_id: "done")

    assert adopted == [] and taken == ["job_stuck:X"]      # dropped from the laptop's queue, never queued here
    assert guard.check() == [] and launcher.started == []


def test_an_adopted_laptop_job_stuck_is_dropped_when_its_job_ends_on_the_laptop(tmp_path: Path) -> None:
    clock = {"t": 1000.0}
    guard, launcher = make_guard(tmp_path, clock=lambda: clock["t"])
    launcher.set_row("working", "busy")                      # a keymaster is live: X waits in the queue
    states = {"X": "running"}

    guard.adopt_remote("laptop", [_stuck("X")], lambda key: True, lambda job_id: states[job_id])
    assert guard.check(origin_job_state=lambda host, job_id: states[job_id]) == []
    assert [a.key for a in an._read_state(tmp_path / "anomalies.json").queue] == ["laptop:job_stuck:X"]

    states["X"] = "done"
    launcher.finish_all()
    assert guard.check(origin_job_state=lambda host, job_id: states[job_id]) == []
    assert launcher.started == []
    assert an._read_state(tmp_path / "anomalies.json").queue == []


def test_an_adopted_laptop_job_failed_with_an_issue_reaches_the_keymaster_prompt(tmp_path: Path) -> None:
    guard, launcher = make_guard(tmp_path)
    guard.adopt_remote("laptop", [{**ENTRY, "issue": 467}], lambda key: True)
    guard.check()
    prompt = launcher.started[0][1][-1]
    assert "host: laptop" in prompt and "issue: #467" in prompt
