"""#685 unit 1: scripts/suite_on_host.py with a FAKE transport (never the live laptop, #457)."""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("suite_on_host", Path(__file__).resolve().parents[1] / "scripts" / "suite_on_host.py")
soh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(soh)

SHA = "a" * 40
CONFIG = {"laptop": {"ssh": "laptop", "repo_path": "C:\\Coding\\repo", "daemon_repo_path": "C:\\Coding\\repo-daemon"}}
RUN = ["run", "--host", "laptop", "--commit", "HEAD", "--workers", "2"]


def done(argv, rc=0, out="", err=""):
    return subprocess.CompletedProcess(argv, rc, out, err)


def decode(argv):
    return base64.b64decode(argv[-1]).decode("utf-16-le")


class Fake:
    """git / scp / ssh answered locally; ssh is told apart by the script it carries (start, poll, cleanup)."""

    def __init__(self, ssh=None, push_rc=0, scp_rc=0, out_text="== 12 passed, 3 skipped in 5.00s ==\n"):
        self.calls = []
        self.ssh = ssh                      # answer (or exception) of the START call
        self.push_rc = push_rc
        self.scp_rc = scp_rc
        self.out_text = out_text
        self.poll = [done([], 0, "SUITE_DONE=0 300\n")]

    def __call__(self, argv, timeout):
        self.calls.append((list(argv), timeout))
        if argv[0] == "git" and argv[1] == "rev-parse":
            return done(argv, 0, SHA + "\n")
        if argv[0] == "git" and argv[1] == "push":
            return done(argv, self.push_rc if not argv[-1].startswith(":") else 0, "", "boom")
        if argv[0] == "ssh":
            script = decode(argv)
            if "schtasks /Create" in script:
                if isinstance(self.ssh, BaseException):
                    raise self.ssh
                return self.ssh if self.ssh is not None else done(argv, 0, "SUITE_STARTED=1\n")
            if "SUITE_DONE" in script:
                return self.poll.pop(0) if len(self.poll) > 1 else self.poll[0]
            return done(argv, 0, "")        # cleanup
        if argv[0] == "scp":
            if self.scp_rc == 0:
                Path(argv[-1]).write_text(self.out_text, encoding="utf-8")
            return done(argv, self.scp_rc, "", "")
        raise AssertionError(argv)

    def pushes(self):
        return [c[0] for c in self.calls if c[0][:2] == ["git", "push"]]

    def scripts(self):
        return [decode(c[0]) for c in self.calls if c[0][0] == "ssh"]


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(soh, "POLL_EVERY_S", 0)
    f = Fake()
    monkeypatch.setattr(soh, "_run", f)
    monkeypatch.setattr(soh, "load_hosts_config", lambda: CONFIG)
    return f


def run(tmp_path, *extra):
    return soh.main(RUN + ["--out", str(tmp_path / "o.txt")] + list(extra))


def test_argv_push_and_ssh(fake, tmp_path, capsys):
    assert run(tmp_path, "--timeout-min", "10") == 0
    pushes = fake.pushes()
    assert pushes[0][3].startswith(SHA + ":refs/merge-suite/aaaaaaaa-")
    ssh = next(c for c in fake.calls if c[0][0] == "ssh")
    assert ssh[1] == soh.START_TIMEOUT_S
    assert "ServerAliveInterval=30" in ssh[0] and ssh[0][ssh[0].index("-NoProfile") - 1] == "powershell"
    assert ssh[0][ssh[0].index("-NoProfile") - 2] == "laptop"
    script = fake.scripts()[0]
    assert "-n 2" in script and "JUNKROAN_NO_POB" in script
    assert "C:\\Coding\\repo-suite" in script and "New-Item -ItemType Junction" in script
    assert "$daemon = 'C:\\Coding\\repo-daemon'" in script
    # the suite runs in the interactive session: one-shot task through run-hidden.vbs, as the user, limited
    assert "run-hidden.vbs" in script and "explorer" in script and "/RL LIMITED" in script and "/SC ONCE" in script
    assert 'basetemp="C:\\Coding\\repo-suite-tmp"' in script
    assert any(c[0][0] == "scp" for c in fake.calls)
    assert "schtasks /Delete" in fake.scripts()[-1]
    assert all(c[1] <= 180 for c in fake.calls if c[0][0] == "ssh")
    out = capsys.readouterr().out
    assert "12 passed, 3 skipped" in out and "5 min" in out


def test_ref_deleted_after_ssh_failure(fake, tmp_path, capsys):
    fake.ssh = done([], 255, "", "ssh: connect to host laptop: Connection timed out")
    assert run(tmp_path) == 75
    pushes = fake.pushes()
    assert len(pushes) == 2 and pushes[1][3].startswith(":refs/merge-suite/")
    assert pushes[1][3][1:] == pushes[0][3].split(":", 1)[1]
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "timeout" in lines[0]
    assert "schtasks /Delete" in fake.scripts()[-1]


def test_start_timeout_is_75_with_reason(fake, tmp_path, capsys):
    fake.ssh = subprocess.TimeoutExpired(["ssh"], 180)
    assert run(tmp_path) == 75
    assert len(fake.pushes()) == 2
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "timeout" in lines[0]


def test_push_failure_is_75_and_cleans(fake, tmp_path):
    fake.push_rc = 1
    assert run(tmp_path) == 75
    assert not any(c[0][0] == "ssh" for c in fake.calls)
    assert len(fake.pushes()) == 2


def test_suite_rc_passthrough_after_a_running_poll(fake, tmp_path, capsys):
    fake.poll = [done([], 0, "SUITE_TASK=Status: Running\n"), done([], 0, "SUITE_DONE=1 60\n")]
    fake.out_text = "1 failed, 9 passed in 2.0s\n"
    assert run(tmp_path) == 1
    assert "1 failed, 9 passed" in capsys.readouterr().out
    assert len(fake.pushes()) == 2


def test_no_interactive_session_is_75_with_reason(fake, tmp_path, capsys):
    fake.ssh = done([], 72, "SUITE_STEP_FAILED=no interactive session logged in\n")
    assert run(tmp_path) == 75
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "no interactive session" in lines[0]
    assert len(fake.pushes()) == 2
    assert "schtasks /Delete" in fake.scripts()[-1]


def test_poll_link_loss_ends_by_itself_and_cleans(fake, tmp_path, capsys):
    fake.poll = [done([], 255, "", "ssh: connect to host laptop: Connection timed out")]
    assert run(tmp_path) == 75
    polls = [c for c in fake.calls if c[0][0] == "ssh" and "SUITE_DONE" in decode(c[0])]
    assert len(polls) == soh.POLL_MISSES and all(c[1] <= 30 for c in polls)
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "polling the suite" in lines[0]
    assert len(fake.pushes()) == 2


def test_task_died_without_result_is_75(fake, tmp_path, capsys):
    fake.poll = [done([], 0, "SUITE_TASK=Status: Ready\n")]
    assert run(tmp_path) == 75
    assert "ended without a result file" in capsys.readouterr().out


def test_pytest_args_replace_the_suite(fake, tmp_path):
    assert run(tmp_path, "--pytest-args", "tests/test_a.py::t") == 0
    script = fake.scripts()[0]
    assert "python -m pytest tests/test_a.py::t -q" in script and "not slow" not in script


def test_readings_json(monkeypatch, capsys):
    calls = []
    answer = done([], 0, '{"logical_cores":8,"cpu_percent":12.5,"free_ram_gb":4.6}\n')
    monkeypatch.setattr(soh, "_run", lambda argv, timeout: (calls.append((argv, timeout)), answer)[1])
    monkeypatch.setattr(soh, "load_hosts_config", lambda: CONFIG)
    assert soh.main(["readings", "--host", "laptop"]) == 0
    assert json.loads(capsys.readouterr().out) == {"host": "laptop", "logical_cores": 8, "cpu_percent": 12.5, "free_ram_gb": 4.6}
    assert calls[0][1] <= 10


def test_readings_failure_is_75(monkeypatch, capsys):
    ans = done([], 255, "", "ssh: connect to host laptop: No route to host")
    monkeypatch.setattr(soh, "_run", lambda argv, timeout: ans)
    monkeypatch.setattr(soh, "load_hosts_config", lambda: CONFIG)
    assert soh.main(["readings", "--host", "laptop"]) == 75
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 1 and "no route" in lines[0]


def test_readings_garbage_is_75(monkeypatch):
    monkeypatch.setattr(soh, "_run", lambda argv, timeout: done([], 0, "not json"))
    monkeypatch.setattr(soh, "load_hosts_config", lambda: CONFIG)
    assert soh.main(["readings", "--host", "laptop"]) == 75
