"""scripts/runs.py stop / mode H off / cancel-on-running (issue #353). Fakes only, no real process."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


def _running(store: Store, tag: str, pid, host: str = "pc"):
    job = store.submit(host=host, priority="P1", tag=tag, cmd="echo hi")
    store.start(job.id, pid=pid)
    return job


def _fake_killer(monkeypatch) -> list[int]:
    killed: list[int] = []
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: killed.append(pid) or True)
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    return killed


def test_stop_kills_tree_and_ends(tmp_path, monkeypatch, capsys) -> None:
    killed = _fake_killer(monkeypatch)
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    job = _running(store, "a", "4242")  # pid may come back as a string
    rc = runs.main(["--store", str(path), "stop", job.id, "--who", "tester"])
    assert rc == 0
    assert killed == [4242]
    got = Store(path).get(job.id)
    assert got.state == "stopped" and got.rc is None and got.reason == "stopped by tester"


def test_stop_refuses_not_running_and_remote(tmp_path, monkeypatch, capsys) -> None:
    killed = _fake_killer(monkeypatch)
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    queued = store.submit(host="pc", priority="P1", tag="q", cmd="echo hi")
    done = _running(store, "d", 1)
    store.end(done.id, rc=0)
    remote = _running(store, "r", 9, host="laptop")
    assert runs.main(["--store", str(path), "stop", queued.id]) == 1
    assert runs.main(["--store", str(path), "stop", done.id]) == 1
    assert runs.main(["--store", str(path), "stop", remote.id]) == 2
    assert "laptop" in capsys.readouterr().err
    assert killed == []


def test_mode_off_stops_every_running_job_of_local_host(tmp_path, monkeypatch, capsys) -> None:
    killed = _fake_killer(monkeypatch)
    monkeypatch.setattr(runs_hosts, "apply_mode", lambda h, m, **kw: {"priority": "x", "transport": "local"})
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(tmp_path / "modes.json"))  # record_mode must not touch the real one
    path = tmp_path / "jobs.jsonl"
    store = Store(path)
    a, b = _running(store, "a", 11), _running(store, "b", 12)
    other = _running(store, "c", 13, host="laptop")
    assert runs.main(["--store", str(path), "mode", "pc", "off"]) == 0
    assert sorted(killed) == [11, 12]
    fresh = Store(path)
    for j in (a, b):
        assert fresh.get(j.id).reason.startswith("stopped by ")
    assert fresh.get(other.id).state == "running"
    # remote host (#73): the stop goes over ssh (faked), nothing is stopped here
    scripts: list[str] = []

    class _Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: scripts.append(script) or _Done())
    assert runs.main(["--store", str(path), "mode", "laptop", "off"]) == 0
    assert len(scripts) == 1
    assert sorted(killed) == [11, 12] and Store(path).get(other.id).state == "running"


def test_cancel_running_points_at_stop(tmp_path, capsys) -> None:
    path = tmp_path / "jobs.jsonl"
    job = _running(Store(path), "a", 5)
    assert runs.main(["--store", str(path), "cancel", job.id]) == 1
    assert f"cancel: job {job.id} is running; use 'runs.py stop {job.id}' to kill its tree and end it" in capsys.readouterr().err


def _laptop_setup(tmp_path, monkeypatch):
    killed = _fake_killer(monkeypatch)
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    modes = tmp_path / "modes.json"
    monkeypatch.setenv("JUNKROAN_MODES_FILE", str(modes))
    calls: list = []

    def fake_apply(h, m, **kw):
        calls.append((h, m))
        return {"priority": "x", "transport": "local"}

    monkeypatch.setattr(runs_hosts, "apply_mode", fake_apply)
    path = tmp_path / "jobs.jsonl"
    job = _running(Store(path), "a", 21, host="laptop")
    return killed, modes, calls, path, job


def test_mode_off_local_stops_that_host_without_junkroan_host(tmp_path, monkeypatch, capsys) -> None:
    killed, _modes, _calls, path, job = _laptop_setup(tmp_path, monkeypatch)
    assert runs.main(["--store", str(path), "mode", "laptop", "off", "--local", "--who", "pg"]) == 0
    assert killed == [21]
    assert f"{job.id} -> stopped (stopped by pg)" in capsys.readouterr().out
    assert Store(path).get(job.id).state == "stopped"


def test_mode_off_without_local_stops_over_ssh_not_here(tmp_path, monkeypatch) -> None:
    killed, modes, calls, path, job = _laptop_setup(tmp_path, monkeypatch)
    scripts: list[str] = []

    class _Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(runs_hosts, "run_on_host", lambda cfg, script: scripts.append(script) or _Done())
    assert runs.main(["--store", str(path), "mode", "laptop", "off"]) == 0
    assert len(scripts) == 1 and calls == [] and killed == []
    assert Store(path).get(job.id).state == "running"
