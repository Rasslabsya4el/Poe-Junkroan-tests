"""#405: every finished job posts its comment; `ready-for-agent` only when the issue has no job left
queued, held or running (both hosts' stores). No PoB, no ssh."""

from __future__ import annotations
from conftest import pc_only

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from test_runs_daemon import FakeGh, FakeLauncher, FakeRemoteHost, make_daemon  # noqa: E402


def _finish(launcher: FakeLauncher, daemon, job_id: str, store) -> None:
    pid = store.get(job_id).pid
    launcher.finish(pid, 0)
    daemon.tick()


def test_after_chain_label_only_on_the_last_job(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    a = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=405)
    b = store.submit(host="pc", priority="P1", tag="b", cmd="python x.py", issue=405, after=[a.id])
    daemon.tick()
    _finish(launcher, daemon, a.id, store)
    assert len(gh.comments) == 1 and gh.labels == []
    daemon.tick()
    _finish(launcher, daemon, b.id, store)
    assert len(gh.comments) == 2 and gh.labels == [(405, "ready-for-agent")]


def test_independent_jobs_label_when_the_running_one_ends(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    a = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=405)
    b = store.submit(host="pc", priority="P1", tag="b", cmd="python x.py", issue=405)
    daemon.tick()
    assert store.get(b.id).state == "running"
    _finish(launcher, daemon, a.id, store)
    assert len(gh.comments) == 1 and gh.labels == []
    _finish(launcher, daemon, b.id, store)
    assert len(gh.comments) == 2 and gh.labels == [(405, "ready-for-agent")]


def test_a_live_job_on_the_other_host_holds_the_remote_label(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: remote.read(cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=0.0,
    )
    a = remote.store.submit(host="laptop", priority="P1", tag="a", cmd="echo", issue=405)
    b = remote.store.submit(host="laptop", priority="P1", tag="b", cmd="echo", issue=405)
    remote.store.start(a.id)
    remote.store.end(a.id, rc=0)
    remote.store.record_handback(a.id, f"<!-- x -->\njob `{a.id}`\n")
    daemon.remote_handback_pass()
    assert len(gh.comments) == 1 and gh.labels == []
    remote.store.start(b.id)
    remote.store.end(b.id, rc=0)
    remote.store.record_handback(b.id, f"<!-- x -->\njob `{b.id}`\n")
    daemon.remote_handback_pass()
    assert len(gh.comments) == 2 and gh.labels == [(405, "ready-for-agent")]


def test_one_issue_three_jobs_label_once_then_again_for_a_fourth(tmp_path: Path) -> None:
    """#500: ends of jobs 1 and 2 add no label, job 3 adds it once, a later 4th adds it again; another issue holds nothing."""
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    other = store.submit(host="pc", priority="P1", tag="o", cmd="python x.py", issue=777)
    jobs = [store.submit(host="pc", priority="P1", tag=f"j{i}", cmd="python x.py", issue=500) for i in range(3)]
    daemon.tick()
    _finish(launcher, daemon, jobs[0].id, store)
    daemon.tick()
    _finish(launcher, daemon, jobs[1].id, store)
    assert [lab for lab in gh.labels if lab[0] == 500] == []
    daemon.tick()
    _finish(launcher, daemon, jobs[2].id, store)
    assert [lab for lab in gh.labels if lab[0] == 500] == [(500, "ready-for-agent")]
    assert store.get(other.id).state in ("running", "queued")      # still live: it held nothing back
    fourth = store.submit(host="pc", priority="P1", tag="j3", cmd="python x.py", issue=500)
    daemon.tick()
    _finish(launcher, daemon, fourth.id, store)
    assert [lab for lab in gh.labels if lab[0] == 500] == [(500, "ready-for-agent")] * 2


# -- runs.py relabel (#500) ---------------------------------------------------------------------

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


def test_relabel_held_back_while_a_job_is_queued_then_added(tmp_path: Path, capsys) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), FakeGh()
    job = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=500)
    store.submit(host="pc", priority="P1", tag="o", cmd="python x.py", issue=777)
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, hosts_config={}) == 0
    assert gh.labels == [] and job.id in capsys.readouterr().out
    store.cancel(job.id)
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, hosts_config={}) == 0
    assert gh.labels == [(500, "ready-for-agent")]


@pc_only
def test_relabel_counts_the_other_hosts_store(tmp_path: Path, capsys) -> None:
    store, gh = Store(tmp_path / "jobs.jsonl"), FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    lap = remote.store.submit(host="laptop", priority="P1", tag="l", cmd="echo", issue=500)
    cfg = {"laptop": {"ssh": "laptop"}}
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, remote_reader=remote.read, hosts_config=cfg) == 0
    assert gh.labels == [] and lap.id in capsys.readouterr().out
    remote.store.start(lap.id)
    remote.store.end(lap.id, rc=0)
    assert runs.cmd_relabel(store, ["--issue", "500"], gh=gh, remote_reader=remote.read, hosts_config=cfg) == 0
    assert gh.labels == [(500, "ready-for-agent")]


def test_keymaster_md_names_the_relabel_command() -> None:
    text = (ROOT / "docs" / "agents" / "keymaster.md").read_text(encoding="utf-8")
    assert "runs.py relabel --issue" in text


# -- #515: a no_label job hands back its comment and never the label ---------------------------------

def test_no_label_local_handback_comments_without_the_label(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    a = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=4, no_label=True)
    daemon.tick()
    _finish(launcher, daemon, a.id, store)
    assert len(gh.comments) == 1 and gh.comments[0][0] == 4 and gh.labels == []


def test_no_label_remote_handback_comments_without_the_label(tmp_path: Path) -> None:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    daemon, _, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: remote.read(cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=0.0,
    )
    a = remote.store.submit(host="laptop", priority="P1", tag="a", cmd="echo", issue=4, no_label=True)
    remote.store.start(a.id)
    remote.store.end(a.id, rc=0)
    remote.store.record_handback(a.id, f"<!-- x -->\njob `{a.id}`\n")
    daemon.remote_handback_pass()
    assert len(gh.comments) == 1 and gh.comments[0][0] == 4 and gh.labels == []


def test_without_no_label_the_comment_and_the_label_as_before(tmp_path: Path) -> None:
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    a = store.submit(host="pc", priority="P1", tag="a", cmd="python x.py", issue=4)
    assert a.no_label is False
    daemon.tick()
    _finish(launcher, daemon, a.id, store)
    assert len(gh.comments) == 1 and gh.labels == [(4, "ready-for-agent")]


def test_a_store_row_without_no_label_loads_false(tmp_path: Path) -> None:
    _, store, _ = make_daemon(tmp_path)
    a = store.submit(host="pc", priority="P1", tag="old", cmd="x", issue=4)
    assert a.no_label is False
    b = store.submit(host="pc", priority="P1", tag="new", cmd="x", issue=4, no_label=True)
    assert store.get(b.id).no_label is True
