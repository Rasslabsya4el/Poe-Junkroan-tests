"""#686: a job whose ticket is closed is stopped / cancelled by the PC daemon; fakes only (no gh, no ssh)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import runs  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import ticket_closed  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402
from test_runs_daemon import FakeGh, make_daemon  # noqa: E402


class StateGh(FakeGh):
    def __init__(self, states, fail=False):
        super().__init__()
        self.states = states
        self.fail = fail
        self.calls: list[int] = []

    def issue_state(self, issue):
        self.calls.append(issue)
        return None if self.fail else self.states.get(issue, "OPEN")


def _build(tmp_path, gh, **kw):
    daemon, store, _ = make_daemon(tmp_path, gh=gh)
    logs: list[str] = []
    daemon.log = logs.append
    now = [1000.0]
    daemon.clock = lambda: now[0]
    killed: list[int] = []
    daemon._spike_killer = lambda pid: killed.append(pid) or True
    daemon._ticket_check_seconds = 300.0
    return daemon, store, logs, now, killed


def _running(store, tag, issue, pid, **kw):
    job = store.submit(host="pc", priority="P1", tag=tag, cmd="echo hi", issue=issue, **kw)
    store.start(job.id, pid=pid)
    return job


def test_row1_closed_running_stopped_queued_cancelled(tmp_path):
    gh = StateGh({621: "CLOSED"})
    daemon, store, logs, now, killed = _build(tmp_path, gh)
    run = _running(store, "a", 621, 4242)
    queued = store.submit(host="pc", priority="P1", tag="b", cmd="echo hi", issue=621)
    assert sorted(daemon.ticket_closed_pass()) == sorted([run.id, queued.id])
    assert store.get(run.id).state == "stopped" and store.get(run.id).reason == "ticket #621 closed"
    assert store.get(queued.id).state == "cancelled" and store.get(queued.id).reason == "ticket #621 closed"
    assert killed == [4242]
    assert gh.calls == [621]  # one gh call for the distinct issue


def test_row2_untouched(tmp_path):
    gh = StateGh({1: "OPEN", 2: "CLOSED"})
    daemon, store, logs, now, killed = _build(tmp_path, gh)
    open_job = _running(store, "a", 1, 11)
    outlives = _running(store, "b", 2, 12, outlives_ticket=True, note="reads the result later")
    noissue = store.submit(host="pc", priority="P1", tag="c", cmd="echo hi")
    core = store.submit(host="pc", priority="P1", tag="d", cmd="python scripts/benchmark.py --set core14 --seeds 3", issue=2)
    assert daemon.ticket_closed_pass() == []
    assert [store.get(j.id).state for j in (open_job, outlives, noissue, core)] == ["running", "running", "queued", "queued"]
    assert killed == []
    assert ticket_closed.watched(store.get(outlives.id)) is False and ticket_closed.watched(store.get(core.id)) is False


def test_row3_gh_failure_touches_nothing_one_log_line(tmp_path):
    gh = StateGh({}, fail=True)
    daemon, store, logs, now, killed = _build(tmp_path, gh)
    run = _running(store, "a", 621, 4242)
    store.submit(host="pc", priority="P1", tag="b", cmd="echo hi", issue=622)
    assert daemon.ticket_closed_pass() == []
    assert store.get(run.id).state == "running" and killed == []
    assert len(logs) == 1 and "gh could not read" in logs[0]


def test_runs_at_most_every_five_minutes(tmp_path):
    gh = StateGh({621: "OPEN"})
    daemon, store, logs, now, killed = _build(tmp_path, gh)
    _running(store, "a", 621, 4242)
    daemon.ticket_closed_pass()
    now[0] += 299
    daemon.ticket_closed_pass()
    assert gh.calls == [621]
    now[0] += 2
    daemon.ticket_closed_pass()
    assert gh.calls == [621, 621]


def test_laptop_job_goes_through_the_transport(tmp_path):
    gh = StateGh({7: "CLOSED"})
    daemon, store, logs, now, killed = _build(tmp_path, gh)
    sent = []
    daemon._remote_ticket_stop = lambda cfg, host, job_id, action, reason: sent.append((host, job_id, action, reason)) or True
    daemon._hosts_config = {"laptop": {"ssh": "laptop"}}
    lap = Store(tmp_path / "laptop.jsonl")
    run = lap.submit(host="laptop", priority="P1", tag="x", cmd="echo hi", issue=7)
    lap.start(run.id, pid=5)
    queued = lap.submit(host="laptop", priority="P1", tag="y", cmd="echo hi", issue=7)
    daemon._remote_jobs_seen["laptop"] = [lap.get(run.id), lap.get(queued.id)]
    done = daemon.ticket_closed_pass()
    assert sorted(done) == sorted([run.id, queued.id])
    assert sorted(sent) == sorted([("laptop", run.id, "stop", "ticket #7 closed"), ("laptop", queued.id, "cancel", "ticket #7 closed")])
    assert killed == []


def test_laptop_ssh_failure_skips_with_one_log_line(tmp_path):
    gh = StateGh({7: "CLOSED"})
    daemon, store, logs, now, killed = _build(tmp_path, gh)

    def boom(*a):
        raise OSError("ssh down")

    daemon._remote_ticket_stop = boom
    daemon._hosts_config = {"laptop": {"ssh": "laptop"}}
    lap = Store(tmp_path / "laptop.jsonl")
    run = lap.submit(host="laptop", priority="P1", tag="x", cmd="echo hi", issue=7)
    lap.start(run.id, pid=5)
    daemon._remote_jobs_seen["laptop"] = [lap.get(run.id)]
    assert daemon.ticket_closed_pass() == []
    assert len(logs) == 1 and "unreachable" in logs[0]


def test_ssh_transport_runs_local_stop(monkeypatch):
    seen = []
    monkeypatch.setattr(daemon_mod.runs_hosts, "run_on_host", lambda cfg, script: seen.append(script) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(daemon_mod.runs_hosts, "daemon_repo_path", lambda cfg: "C:/repo")
    assert daemon_mod._remote_ticket_stop_over_ssh({"ssh": "l"}, "laptop", "j-1", "stop", "ticket #7 closed")
    assert "'stop' 'j-1' '--local' '--reason' 'ticket #7 closed'" in seen[0]


def test_stop_cli_records_reason_and_status_shows_it(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runs, "TREE_KILLER", lambda pid: True)
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    store = Store(tmp_path / "jobs.jsonl")
    run = _running(store, "a", 621, 4242)
    queued = store.submit(host="pc", priority="P1", tag="b", cmd="echo hi", issue=621)
    assert runs.cmd_stop(store, [run.id, "--local", "--reason", "ticket #621 closed"]) == 0
    assert runs.cmd_cancel(store, [queued.id, "--local", "--reason", "ticket #621 closed"]) == 0
    capsys.readouterr()
    assert runs.cmd_status(store, []) == 0
    out = capsys.readouterr().out
    assert out.count("ticket #621 closed") == 2


def test_submit_flag_persisted(tmp_path):
    store = Store(tmp_path / "jobs.jsonl")
    job = store.submit(host="pc", priority="P1", tag="a", cmd="x", issue=1, outlives_ticket=True)
    assert store.get(job.id).outlives_ticket is True
    assert store.get(store.submit(host="pc", priority="P1", tag="b", cmd="x", issue=1).id).outlives_ticket is False
