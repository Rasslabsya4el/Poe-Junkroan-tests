"""#1183 unit 2: the PC cancels a queued job in the laptop's own store over ssh (fake run_on_host, no PoB).

The fake runs the real `Store.cancel` on a temp store, so a running job is refused by the store itself,
the way `scripts/runs.py cancel --local` refuses it on the laptop (exit 1, "is running" on stderr).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from junkroan.runs import hosts as runs_hosts
from junkroan.runs import rebalance
from junkroan.runs.store import Store

HOST_CFG = {"ssh": "laptop"}


def _remote_store(tmp_path: Path, monkeypatch, *, fail: str | None = None):
    """Install a fake run_on_host that cancels in `laptop`'s store; returns (store, scripts)."""

    store = Store(tmp_path / "laptop.jsonl")
    scripts: list[str] = []

    def fake_run_on_host(host_cfg, powershell_script):
        scripts.append(powershell_script)
        if fail == "raise":
            raise OSError("ssh: connect to host laptop port 22: Connection timed out")
        if fail == "rc255":
            return subprocess.CompletedProcess(["ssh"], 255, stdout="", stderr="ssh: Could not resolve hostname laptop")
        job_id = re.search(r"'cancel' '([^']+)'", powershell_script).group(1)
        try:
            job = store.cancel(job_id, reason=None)
        except Exception as exc:  # the real store's refusal: a running job is not queued
            state = store.get(job_id).state
            msg = (f"cancel: job {job_id} is running; use 'runs.py stop {job_id}' to kill its tree and end it"
                   if state == "running" else f"cancel: {exc} (only a queued job can be cancelled)")
            return subprocess.CompletedProcess(["ssh"], 1, stdout="", stderr=msg)
        return subprocess.CompletedProcess(["ssh"], 0, stdout=f"{job.id} -> {job.state}\n", stderr="")

    monkeypatch.setattr(runs_hosts, "run_on_host", fake_run_on_host)
    return store, scripts


def test_1183_queued_job_cancelled_on_laptop_returns_true(tmp_path: Path, monkeypatch) -> None:
    store, scripts = _remote_store(tmp_path, monkeypatch)
    job = store.submit(host="laptop", priority="P2", tag="waiter", cmd="python scripts/benchmark.py", workers=1)

    assert rebalance.remote_cancel_queued(HOST_CFG, job.id) is True

    assert len(scripts) == 1
    assert job.id in scripts[0] and "cancel" in scripts[0] and "--local" in scripts[0]
    assert store.get(job.id).state == "cancelled"


def test_1183_ssh_failure_returns_false_and_never_raises(tmp_path: Path, monkeypatch) -> None:
    store, scripts = _remote_store(tmp_path, monkeypatch, fail="raise")
    job = store.submit(host="laptop", priority="P2", tag="waiter", cmd="python scripts/benchmark.py", workers=1)

    assert rebalance.remote_cancel_queued(HOST_CFG, job.id) is False
    assert store.get(job.id).state == "queued"


def test_1183_ssh_rc255_returns_false_and_never_raises(tmp_path: Path, monkeypatch, capsys) -> None:
    store, scripts = _remote_store(tmp_path, monkeypatch, fail="rc255")
    job = store.submit(host="laptop", priority="P2", tag="waiter", cmd="python scripts/benchmark.py", workers=1)

    assert rebalance.remote_cancel_queued(HOST_CFG, job.id) is False
    assert store.get(job.id).state == "queued"
    assert "Could not resolve hostname laptop" in capsys.readouterr().err


def test_1183_running_job_is_not_cancelled_and_says_why(tmp_path: Path, monkeypatch, capsys) -> None:
    store, scripts = _remote_store(tmp_path, monkeypatch)
    job = store.submit(host="laptop", priority="P2", tag="running", cmd="python scripts/benchmark.py", workers=1)
    store.start(job.id, out="out.txt", run_dir="run", pid=4242, workers=1)

    assert rebalance.remote_cancel_queued(HOST_CFG, job.id) is False

    assert store.get(job.id).state == "running"
    assert "running" in capsys.readouterr().err
