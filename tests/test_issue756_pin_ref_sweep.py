"""#756 rule 2: the PC daemon sweeps pin refs no job of any host holds (PoB-free)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import pin_ref  # noqa: E402
from test_issue756_pin_travels import g, pins_on_origin, world  # noqa: E402
from test_runs_daemon import FakeRemoteHost, make_daemon  # noqa: E402


def _setup(tmp_path: Path):
    origin, pc, _laptop, pin = world(tmp_path)
    assert pin_ref.push_pin(pc, pin)[0]
    remote = FakeRemoteHost(tmp_path, "laptop")
    (tmp_path / "d").mkdir()
    daemon, store, queue = make_daemon(
        tmp_path / "d", host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: remote.read(cfg))
    queue.sweep_pin_refs = lambda held, failed: pin_ref.sweep(pc, held, failed)
    return origin, pc, pin, remote, daemon, store


def _laptop_job(remote, pin: str, tag: str, *, end: bool):
    job = remote.store.submit(host="laptop", priority="P1", tag=tag, cmd="echo x", pin=pin[:7])
    if end:
        remote.store.start(job.id, out="o", pid=None)
        remote.store.end(job.id, rc=0)
    return job


def count(origin: Path) -> int:
    return len([x for x in pins_on_origin(origin).splitlines() if x])


def test_ended_laptop_job_ref_is_swept(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    _laptop_job(remote, pin, "a", end=True)
    assert count(origin) == 1
    daemon.remote_handback_pass()
    assert count(origin) == 0


def test_second_live_laptop_job_keeps_the_ref(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    _laptop_job(remote, pin, "a", end=True)
    _laptop_job(remote, pin, "b", end=False)       # queued, a 7-char pin against the 40-char ref
    daemon.remote_handback_pass()
    assert count(origin) == 1


def test_ref_held_by_no_job_is_dropped(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    assert count(origin) == 1
    daemon.remote_handback_pass()
    assert count(origin) == 0


def test_read_only_push_is_logged_once_and_does_not_raise(tmp_path):
    origin, pc, pin, remote, daemon, store = _setup(tmp_path)
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'The key you are authenticating with has been marked as read only.' >&2\nexit 1\n")
    hook.chmod(0o755)
    logs: list[str] = []
    daemon.log = logs.append
    daemon.remote_handback_pass()
    daemon._last_remote_pass = None
    daemon.remote_handback_pass()
    assert count(origin) == 1
    assert len([m for m in logs if "pin sweep" in m and "not deleted" in m]) == 1
