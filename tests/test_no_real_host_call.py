"""#451: under pytest no ssh process is ever spawned unless the test replaced the transport."""

from __future__ import annotations

import subprocess
import sys

import pytest

from junkroan.runs import hosts, remote_store

HOST_CFG = {"ssh": "laptop", "repo_path": "C:/x"}


@pytest.fixture
def no_spawn(ssh_guard):
    """Beneath the guard: a recorder that fails the test (and spawns nothing) on any ssh argv."""

    seen: list = []

    def recorder(args, *a, **kw):
        seen.append(args)
        assert args[0] not in ("ssh", "ssh.exe"), "guard let an ssh argv through"
        return subprocess.CompletedProcess(args, 0, "", "")

    ssh_guard.real_run = recorder
    return seen


def test_run_on_host_refuses_ssh(no_spawn):
    with pytest.raises(RuntimeError, match="real host call from a test"):
        hosts.run_on_host(HOST_CFG, "Write-Output 1")
    assert no_spawn == []


def test_apply_mode_laptop_off_refuses_ssh(no_spawn, tmp_path):
    config = hosts.load_hosts_config()
    with pytest.raises(RuntimeError, match="real host call from a test"):
        hosts.apply_mode("laptop", "off", config=config, events_file=tmp_path / "e.jsonl")
    assert no_spawn == []


def test_remote_store_transport_refuses_ssh(no_spawn):
    with pytest.raises(RuntimeError, match="real host call from a test"):
        remote_store.default_remote_transport(HOST_CFG, "Write-Output 1", timeout=5)
    assert no_spawn == []


def test_popen_and_shell_string_refused():
    with pytest.raises(RuntimeError, match="real host call from a test"):
        subprocess.Popen(["C:/Windows/System32/OpenSSH/ssh.exe", "laptop", "x"])
    with pytest.raises(RuntimeError, match="real host call from a test"):
        subprocess.run("ssh laptop echo 1", shell=True)


def test_non_ssh_runs(ssh_guard):
    out = subprocess.run([sys.executable, "-c", "print(1)"], capture_output=True, text=True)
    assert out.stdout.strip() == "1"
    assert ssh_guard.passed[-1][0] == sys.executable


def test_test_local_fake_wins(monkeypatch):
    calls = []

    def fake(cfg, script):
        calls.append(script)
        return subprocess.CompletedProcess([], 0, "ok", "")

    monkeypatch.setattr(hosts, "run_on_host", fake)
    assert hosts.run_on_host(HOST_CFG, "s").stdout == "ok"
    assert calls == ["s"]


def test_test_local_subprocess_run_patch_wins(monkeypatch):
    # #521: the transport runs through `run_bounded` (Popen + tree kill), so a test-local patch of that runner is the one that wins
    monkeypatch.setattr("junkroan.runs.bounded.run_bounded", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "fake", ""))
    assert remote_store.default_remote_transport(HOST_CFG, "s", timeout=1).stdout == "fake"


def test_bounded_runner_is_still_guarded():
    """#521: `run_bounded` starts its child through `subprocess.Popen`, which the conftest guard covers: an ssh argv raises before spawning."""

    import pytest as _pytest
    from junkroan.runs.bounded import run_bounded

    with _pytest.raises(RuntimeError, match="real host call from a test"):
        run_bounded(["ssh", "laptop", "echo"], capture_output=True, text=True, timeout=5)
