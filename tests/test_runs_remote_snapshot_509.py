"""#509 unit 3: the snapshot's jobs half leaves out hand-back / Run-issue bodies nobody can use any more.

The trimming runs in PowerShell on the laptop; here the REAL script is run through the local
powershell.exe on a temp jobs file (no ssh), and the daemon's hand-back pass is run on the folded
result and on the full file: same calls.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from test_runs_daemon import FakeGh, FakeRemoteHost, make_daemon  # noqa: E402
from junkroan.runs import daemon as daemon_mod  # noqa: E402
from junkroan.runs import remote_store  # noqa: E402
from junkroan.runs.store import Store, fold  # noqa: E402

POWERSHELL = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
pytestmark = pytest.mark.skipif(not POWERSHELL.is_file(), reason="needs Windows PowerShell 5.1")

CREATE_NO_WINDOW = 0x08000000


def _body(job_id: str) -> str:
    return f"{daemon_mod.RUNS_DAEMON_MARKER}\nrun for job `{job_id}` " + "x" * 400 + "\n"


def _ended(store: Store, tag: str, issue: int) -> str:
    job = store.submit(host="laptop", priority="P1", tag=tag, cmd="echo x", issue=issue)
    store.start(job.id)
    store.end(job.id, rc=0)
    store.record_handback(job.id, _body(job.id))
    return job.id


def _build_store(tmp: Path) -> tuple[Store, dict[str, str]]:
    store = Store(tmp / "jobs.jsonl")
    ids: dict[str, str] = {}
    ids["pending"] = _ended(store, "pending", 11)               # not posted: body must travel
    ids["posted"] = _ended(store, "posted", 12)
    store.mark_posted(ids["posted"])                             # posted: body may go
    ids["extra"] = _ended(store, "extra", 13)
    store.add_issue(ids["extra"], 14)
    store.mark_posted(ids["extra"])                              # issue 14 still waits: body must travel
    job = store.submit(host="laptop", priority="P1", tag="rerun", cmd="echo x", issue=15)
    ids["rerun"] = job.id
    store.start(job.id)
    store.end(job.id, rc=1)
    store.record_handback(job.id, _body(job.id))
    store.mark_posted(ids["rerun"])
    store.requeue(ids["rerun"])
    store.start(ids["rerun"])
    store.end(ids["rerun"], rc=0)
    store.record_handback(ids["rerun"], _body(ids["rerun"]))     # second body, unposted: must travel
    ids["runissue_done"] = _ended(store, "ri-done", 16)
    store.mark_posted(ids["runissue_done"])
    store.record_run_issue_body(ids["runissue_done"], "title", "R" * 500)
    store.record_run_issue(ids["runissue_done"], 900)            # Run issue made: body may go
    ids["runissue_open"] = _ended(store, "ri-open", 17)
    store.mark_posted(ids["runissue_open"])
    store.record_run_issue_body(ids["runissue_open"], "title", "R" * 500)   # not made: body must travel
    live = store.submit(host="laptop", priority="P1", tag="live", cmd="echo x", issue=18)
    store.start(live.id)
    ids["running"] = live.id
    return store, ids


def _trimmed_jobs(tmp: Path):
    """Run the real snapshot script on ``tmp`` as a fake repo; return (jobs, snapshot_script_stdout)."""

    runs_dir = tmp / "repo" / "artifacts" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "jobs.jsonl").write_bytes((tmp / "jobs.jsonl").read_bytes())
    script = remote_store._remote_snapshot_script(str(tmp / "repo"), "laptop")
    import base64
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    out = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True, text=True, timeout=60, creationflags=CREATE_NO_WINDOW)
    assert out.returncode == 0, out.stderr
    class Transport:
        returncode, stdout, stderr = 0, out.stdout, ""
    snapshot = remote_store.read_remote_snapshot(
        {"ssh": "x", "repo_path": str(tmp / "repo")}, host="laptop", transport=lambda cfg, s, *, timeout: Transport())
    return snapshot.jobs, len(out.stdout)


def test_509_trim_drops_only_bodies_that_are_no_longer_needed(tmp_path: Path) -> None:
    store, ids = _build_store(tmp_path)
    full = store.jobs()
    trimmed, _ = _trimmed_jobs(tmp_path)
    by_full = {j.id: j for j in full}
    by_trim = {j.id: j for j in trimmed}
    assert set(by_full) == set(by_trim)
    for key in ("pending", "extra", "rerun", "running"):
        assert by_trim[ids[key]] == by_full[ids[key]], key
    assert by_full[ids["posted"]].handback_body and by_trim[ids["posted"]].handback_body is None
    assert by_trim[ids["runissue_open"]].run_issue_body == by_full[ids["runissue_open"]].run_issue_body
    assert by_trim[ids["runissue_done"]].run_issue_body is None
    assert by_full[ids["runissue_done"]].run_issue_body
    # everything but the two body fields is identical for every job
    for jid, job in by_full.items():
        t = by_trim[jid]
        assert {**job.as_dict(), "handback_body": None, "run_issue_body": None, "run_issue_title": None} == \
               {**t.as_dict(), "handback_body": None, "run_issue_body": None, "run_issue_title": None}


def _handback_calls(tmp: Path, jobs_list) -> tuple[list, list, list]:
    gh = FakeGh()
    remote = FakeRemoteHost(tmp, "laptop")
    marked: list[str] = []
    daemon, _, _ = make_daemon(
        tmp, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: list(jobs_list),
        remote_mark_posted=lambda cfg, host, job_id: marked.append(job_id) is None,
        remote_mark_run_issue=lambda cfg, host, job_id, number: True,
    )
    daemon._make_run_issue = lambda title, body: 901
    daemon._attach_run_issue = lambda number: None
    done = daemon.remote_handback_pass()
    return done, gh.comments + gh.labels, marked


def test_509_hand_back_pass_makes_the_same_calls_on_trimmed_and_full_jobs(tmp_path: Path) -> None:
    store, ids = _build_store(tmp_path)
    full = store.jobs()
    trimmed, _ = _trimmed_jobs(tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = _handback_calls(tmp_path / "a", full)
    b = _handback_calls(tmp_path / "b", trimmed)
    assert a == b
    done, calls, marked = a
    assert set(done) == {ids["pending"], ids["extra"], ids["rerun"]}   # the work is real, not vacuous
    assert len(calls) >= 3


def test_509_trimmed_snapshot_is_much_smaller_than_the_untrimmed_one(tmp_path: Path) -> None:
    store, _ = _build_store(tmp_path)
    _, size = _trimmed_jobs(tmp_path)
    import base64, gzip
    full_size = len(base64.b64encode(gzip.compress((tmp_path / "jobs.jsonl").read_bytes())))
    assert size < full_size
