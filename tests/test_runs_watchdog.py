"""#353 unit 2: the runs daemon watchdog, all with fakes (nothing real is started)."""

import json

import pytest
from datetime import datetime, timezone

from junkroan.runs import watchdog

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def _status(tmp_path, *, pid=77, last_tick="2026-09-30T11:59:55+00:00"):
    p = tmp_path / "daemon-pc.json"
    p.write_text(json.dumps({"pid": pid, "last_tick": last_tick, "tick_seconds": 10}))
    return p


def _run(host, path, alive, monkeypatch, launch, kill=None):
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    lines = []
    rc = watchdog.ensure(host, status_path=path, pid_alive=alive, launch=launch, err_path=path.parent / "daemon.err",
                         now=lambda: NOW, out=lines.append, kill=kill or (lambda p: pytest.fail("kill")))
    return rc, lines


def test_no_status_launches_once(tmp_path, monkeypatch):
    calls = []

    def launch(cmd, work):
        calls.append((cmd, work))
        return 4242

    rc, lines = _run("pc", tmp_path / "missing.json", lambda p: True, monkeypatch, launch)
    assert rc == 0 and lines == ["takeover: no status file", "pid 4242"]
    assert len(calls) == 1
    assert "daemon --host pc" in calls[0][0] and calls[0][1] == watchdog.ROOT


def test_dead_pid_and_stale_tick_launch(tmp_path, monkeypatch):
    calls = []

    def launch(cmd, work):
        calls.append(cmd)
        return 1

    _run("pc", _status(tmp_path), lambda p: False, monkeypatch, launch)
    killed = []
    _run("pc", _status(tmp_path, last_tick="2026-09-30T10:00:00+00:00"), lambda p: True, monkeypatch, launch,
         kill=killed.append)
    assert len(calls) == 2 and killed == [77]


def test_live_daemon_not_launched(tmp_path, monkeypatch):
    def launch(cmd, work):
        raise AssertionError("must not launch")

    rc, lines = _run("pc", _status(tmp_path), lambda p: True, monkeypatch, launch)
    assert rc == 0 and lines == ["alive pid 77"]


def test_launch_failure(tmp_path, monkeypatch, capsys):
    def launch(cmd, work):
        raise OSError("boom")

    rc, lines = _run("pc", tmp_path / "x.json", lambda p: False, monkeypatch, launch)
    err = capsys.readouterr().err.strip().splitlines()
    assert rc == 1 and lines[1:] == ["error: " + err[0]] and len(err) == 1 and "boom" in err[0]  # #521: the log keeps the error too


def test_other_host_refused(tmp_path, monkeypatch):
    def launch(cmd, work):
        raise AssertionError("must not launch")

    rc, lines = _run("laptop", tmp_path / "x.json", lambda p: False, monkeypatch, launch)
    assert rc == 2 and len(lines) == 1


def test_laptop_daemon_starts_with_remote_handback():
    # The laptop has no gh (#118): its daemon must store hand-backs, not post them.
    assert "--handback remote" in watchdog.daemon_command_line("laptop", python="py")
    assert "--handback" not in watchdog.daemon_command_line("pc", python="py")


def test_exe_path_with_a_space_is_quoted():
    # #73: the laptop's python is `C:\Program Files\Python312\python.exe`; unquoted, `cmd /c` ran `C:\Program`
    line = watchdog.daemon_command_line("laptop", python=r"C:\Program Files\Python312\python.exe")
    assert line.startswith(r'"C:\Program Files\Python312\python.exe" scripts\runs.py daemon --host laptop')
    assert watchdog.daemon_command_line("pc", python=r"C:\py\junkroan.exe").startswith(r"C:\py\junkroan.exe scripts")


def test_runs_daemon_ensure_calls_the_watchdog(monkeypatch):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import runs

    seen = []
    monkeypatch.setattr(watchdog, "main", lambda argv: seen.append(argv) or 0)
    assert runs.cmd_daemon(None, ["--ensure", "--host", "pc"]) == 0
    assert seen == [["--host", "pc"]]


def _stale_run(tmp_path, monkeypatch, last_tick, *, path=None):
    killed, launched = [], []
    rc, lines = _run("pc", path or _status(tmp_path, last_tick=last_tick), lambda p: True, monkeypatch,
                     lambda c, w: launched.append(c) or 9, kill=killed.append)
    return rc, lines, killed, launched


def test_tick_2_min_old_is_alive_nothing_killed(tmp_path, monkeypatch):
    rc, lines, killed, launched = _stale_run(tmp_path, monkeypatch, "2026-09-30T11:58:00+00:00")
    assert (killed, launched, lines) == ([], [], ["alive pid 77"])


def test_tick_3_min_old_kills_and_launches_with_one_line(tmp_path, monkeypatch):
    rc, lines, killed, launched = _stale_run(tmp_path, monkeypatch, "2026-09-30T11:57:00+00:00")
    assert killed == [77] and len(launched) == 1
    assert len(lines) == 3 and lines[2] == "pid 9"
    assert lines[0] == "takeover: daemon pid 77 tick age 180 s > stale 180 s"
    assert "2026-09-30T11:57:00+00:00" in lines[1] and "3 min" in lines[1]


def test_no_json_kills_nothing_but_launches(tmp_path, monkeypatch):
    rc, lines, killed, launched = _stale_run(tmp_path, monkeypatch, None, path=tmp_path / "none.json")
    assert killed == [] and len(launched) == 1


def test_dead_pid_with_stale_tick_kills_nothing(tmp_path, monkeypatch):
    killed = []
    rc, lines = _run("pc", _status(tmp_path, last_tick="2026-09-30T10:00:00+00:00"), lambda p: False, monkeypatch,
                     lambda c, w: 1, kill=killed.append)
    assert killed == []
    assert lines[0] == "takeover: daemon pid 77 dead"
    assert (tmp_path / "daemon.err").read_text().rstrip().endswith("watchdog: takeover: daemon pid 77 dead")


def test_no_status_file_writes_its_takeover_line(tmp_path, monkeypatch):
    rc, lines = _run("pc", tmp_path / "none.json", lambda p: True, monkeypatch, lambda c, w: 5)
    assert lines == ["takeover: no status file", "pid 5"]
    assert "watchdog: takeover: no status file" in (tmp_path / "daemon.err").read_text()


def test_last_tick_without_offset_is_aged_as_utc(tmp_path, monkeypatch):
    # daemon.py:239-240 reads an offset-less last_tick as UTC; 3 min old is stale, never a negative age
    rc, lines, killed, launched = _stale_run(tmp_path, monkeypatch, "2026-09-30T11:57:00")
    assert killed == [77]


def test_takeover_kills_only_the_daemon_and_its_job_is_adopted(tmp_path, monkeypatch):
    """#647 row 1: a real daemon process with a sleeping child; the real pid-only kill leaves the child
    alive and the next daemon's recover() adopts it instead of ending it as failed."""

    import subprocess
    import sys
    import time
    from pathlib import Path

    from junkroan.runs import daemon as daemon_mod
    from junkroan.runs.store import Store
    from tests.test_runs_daemon import FakeLauncher, make_daemon

    code = ("import subprocess,sys,time;"
            "c=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)']);"
            "print(c.pid,flush=True);time.sleep(120)")
    daemon_proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    child_pid = None
    backend = daemon_mod.QueueBackend()
    try:
        child_pid = int(daemon_proc.stdout.readline())
        status = _status(tmp_path, pid=daemon_proc.pid, last_tick="2026-09-30T11:50:00+00:00")
        monkeypatch.setenv("JUNKROAN_HOST", "pc")
        lines, launched = [], []
        rc = watchdog.ensure("pc", status_path=status, launch=lambda c, w: launched.append(c) or 9,
                             now=lambda: NOW, out=lines.append, err_path=tmp_path / "daemon.err")
        assert rc == 0 and len(launched) == 1
        daemon_proc.wait(timeout=20)
        deadline = time.time() + 20
        while backend.pid_alive(daemon_proc.pid) and time.time() < deadline:
            time.sleep(0.2)
        assert not backend.pid_alive(daemon_proc.pid)
        assert backend.pid_alive(child_pid)
        want = "takeover: daemon pid %d tick age 600 s > stale 180 s" % daemon_proc.pid
        assert lines[0] == want
        assert want in (tmp_path / "daemon.err").read_text()

        class RealAlive(FakeLauncher):
            def alive(self, pid):
                return backend.pid_alive(pid)

        messages = []
        daemon, store, _ = make_daemon(tmp_path, launcher=RealAlive())
        daemon.log = messages.append
        job = store.submit(host="pc", priority="P1", tag="kid", cmd="sleep", issue=48)
        store.start(job.id, out=str(tmp_path / "runs" / "kid.out"), pid=child_pid)
        assert daemon.recover() == []
        assert any("adopted running job" in m for m in messages)
        assert not any("ending it as failed" in m for m in messages)
    finally:
        for pid in (child_pid, daemon_proc.pid):
            if pid:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)
        daemon_proc.stdout.close()
