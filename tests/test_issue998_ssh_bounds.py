"""#998: a host that did not answer in this pass is not asked again in the same pass.

A fake runner that always times out stands in for a dead link; no real ssh, no sleeping.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from junkroan.runs import hosts, remote_store, row_sync
from junkroan.runs.pass_guard import GUARD

HOST = {"name": "laptop", "ssh": "laptop", "repo_path": "C:/x"}
KEY = "ssh:laptop"
SKIPPED = "skipped: ssh down this pass"


@pytest.fixture(autouse=True)
def fresh_pass():
    GUARD.begin()
    yield
    GUARD.begin()


class HungRunner:
    """Every call times out like a dead link; counts the calls and the timeouts they were given."""

    def __init__(self) -> None:
        self.calls = 0
        self.timeouts: list = []

    def __call__(self, args, *a, **kw):
        self.calls += 1
        self.timeouts.append(kw.get("timeout"))
        raise subprocess.TimeoutExpired(args, kw.get("timeout"))


@pytest.fixture
def hung(monkeypatch):
    runner = HungRunner()
    monkeypatch.setattr(hosts, "run_bounded", runner)           # hosts imports run_bounded at load time
    monkeypatch.setattr("junkroan.runs.bounded.run_bounded", runner)  # row_sync and remote_store import it inside calls
    return runner


def _folder_with_cut(tmp_path):
    folder = tmp_path / "week"
    folder.mkdir()
    (folder / "args.json").write_text(json.dumps({"commit": "c" * 40}), encoding="utf-8")
    return folder


def test_run_on_host_is_bounded_at_45_seconds(hung):
    with pytest.raises(subprocess.TimeoutExpired):
        hosts.run_on_host(HOST, "Write-Output 1")
    assert hung.timeouts == [45]


def test_second_run_on_host_in_the_same_pass_makes_no_call(hung):
    with pytest.raises(subprocess.TimeoutExpired):
        hosts.run_on_host(HOST, "first")
    assert GUARD.down(KEY)
    skipped = hosts.run_on_host(HOST, "second")
    assert skipped.returncode == 255
    assert skipped.stdout == ""
    assert skipped.stderr == SKIPPED
    assert hung.calls == 1


def test_after_begin_the_host_is_tried_again(hung):
    with pytest.raises(subprocess.TimeoutExpired):
        hosts.run_on_host(HOST, "first")
    GUARD.begin()
    with pytest.raises(subprocess.TimeoutExpired):
        hosts.run_on_host(HOST, "second")
    assert hung.calls == 2


def test_one_timeout_logs_one_line(hung, capsys):
    with pytest.raises(subprocess.TimeoutExpired):
        hosts.run_on_host(HOST, "s")
    for _ in range(2):
        assert hosts.run_on_host(HOST, "s").returncode == 255
    err = capsys.readouterr().err
    assert err.count("runs-daemon: ssh laptop did not answer") == 1
    assert hung.calls == 1


def test_row_sync_pass_with_five_rows_makes_one_ssh_call(hung, tmp_path):
    # The five finished rows sit on the laptop; the first call that would list them hangs.
    folder = _folder_with_cut(tmp_path)
    transport = row_sync.SshTransport(HOST)
    sync = row_sync.RowSync(transport, log=lambda message: None, seconds=0.0)
    assert sync.run(folder, now=0.0) == 0
    assert hung.calls == 1
    assert hung.timeouts == [45]


def test_row_sync_timeout_also_skips_the_other_ssh_calls_of_the_pass(hung, tmp_path):
    folder = _folder_with_cut(tmp_path)
    sync = row_sync.RowSync(row_sync.SshTransport(HOST), log=lambda message: None, seconds=0.0)
    sync.run(folder, now=0.0)
    skipped = hosts.run_on_host(HOST, "after the row sync")
    assert skipped.returncode == 255
    assert hung.calls == 1


def test_remote_store_read_after_mark_down_is_unreadable_without_a_call():
    GUARD.mark_down(KEY, "TimeoutExpired")
    calls: list = []

    def transport(cfg, script, *, timeout):
        calls.append(script)
        raise AssertionError("a skipped read must not call the transport")

    with pytest.raises(remote_store.RemoteStoreUnreachable, match=SKIPPED):
        remote_store.read_remote_snapshot(HOST, transport=transport)
    with pytest.raises(remote_store.RemoteStoreUnreachable, match=SKIPPED):
        remote_store.read_remote_jobs(HOST, transport=transport)
    with pytest.raises(remote_store.RemoteStoreUnreachable, match=SKIPPED):
        remote_store.read_remote_anomalies(HOST, transport=transport)
    assert calls == []


def test_remote_store_default_transport_timeout_marks_the_host_down(hung):
    with pytest.raises(remote_store.RemoteStoreUnreachable):
        remote_store.read_remote_snapshot(HOST)
    assert GUARD.down(KEY)
    with pytest.raises(remote_store.RemoteStoreUnreachable, match=SKIPPED):
        remote_store.read_remote_jobs(HOST)
    assert hung.calls == 1
    assert hung.timeouts == [remote_store.DEFAULT_TIMEOUT_SECONDS]


def test_default_transport_never_waits_longer_than_45_seconds(hung):
    with pytest.raises(subprocess.TimeoutExpired):
        remote_store.default_remote_transport(HOST, "s", timeout=120)
    assert hung.timeouts == [45]


def test_an_os_error_marks_the_host_down(monkeypatch):
    def cannot_start(*a, **k):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(hosts, "run_bounded", cannot_start)
    with pytest.raises(FileNotFoundError):
        hosts.run_on_host(HOST, "s")
    assert GUARD.down(KEY)


def test_a_programming_error_does_not_mark_the_host_down(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("real host call from a test")

    monkeypatch.setattr(hosts, "run_bounded", boom)
    with pytest.raises(RuntimeError):
        hosts.run_on_host(HOST, "s")
    assert not GUARD.down(KEY)


def test_a_nonzero_return_code_does_not_mark_the_host_down(monkeypatch):
    # #998 (ssh fail down): rc 255 is ssh's own "could not reach the host" and DOES mark; any other code is the remote's.
    monkeypatch.setattr(hosts, "run_bounded",
                        lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "Connection refused"))
    assert hosts.run_on_host(HOST, "s").returncode == 1
    assert not GUARD.down(KEY)
