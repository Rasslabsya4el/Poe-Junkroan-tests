"""#642 unit 3: a laptop result that lacked artifacts/ (or only skipped) is requeued ONCE on the PC; a skip is no pass.
No PoB, no ssh."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from test_runs_daemon import FakeGh, FakeLauncher, FakeRemoteHost, make_daemon  # noqa: E402

from junkroan.runs import anomalies as anomalies_mod  # noqa: E402

GATE_PATH = r"artifacts\benchmark\20261005-1220-gate-20261005\smite-s4.pob.txt"
FNF = ("Traceback (most recent call last):\n  File \"x.py\", line 3, in <module>\n"
       f"FileNotFoundError: [Errno 2] No such file or directory: 'C:\\\\snap\\\\{GATE_PATH.replace(chr(92), chr(92) * 2)}'")
SKIPPED = "s\n1 skipped in 0.42s"
MIXED = ".sss\n3 passed, 1 skipped in 1.10s"


def rig(tmp_path, **kw):
    gh = FakeGh()
    remote = FakeRemoteHost(tmp_path, "laptop")
    daemon, store, _ = make_daemon(
        tmp_path, gh=gh, host="pc", hosts_config={"laptop": {"ssh": "laptop"}},
        remote_store_reader=lambda cfg: remote.read(cfg),
        remote_mark_posted=remote.mark_posted, remote_pass_seconds=0.0, **kw)
    return daemon, store, remote, gh


def laptop_result(remote, *, rc, tail, cmd="python scripts/probe_issue632_rage.py", verdict=None, **kw):
    job = remote.store.submit(host="laptop", priority="P2", tag="probe", cmd=cmd, issue=632, workers=2, **kw)
    remote.store.start(job.id)
    remote.store.end(job.id, rc=rc)
    body = (f"<!-- runs-daemon -->\nRun `probe` finished on host `laptop`: {verdict or f'rc {rc} (failed)'}.\n\n"
            f"- job: `{job.id}` (P2, 2 worker(s))\n- command: `{cmd}`\n\n```\n{tail}\n```\n")
    remote.store.record_handback(job.id, body)
    return job


def test_row2_missing_artifact_requeues_once_on_pc(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    job = laptop_result(remote, rc=1, tail=FNF, rc_is_reading=False)
    daemon.remote_handback_pass()
    daemon.remote_handback_pass()
    pc_jobs = store.jobs()
    assert len(pc_jobs) == 1
    new = pc_jobs[0]
    assert (new.host, new.cmd, new.issue, new.priority, new.requeued_from) == ("pc", job.cmd, 632, "P2", job.id)
    assert new.host_fixed and new.state == "queued"
    assert len(gh.comments) == 1
    assert f"requeued on pc as {new.id}: the laptop lacks {GATE_PATH}" in gh.comments[0][1]
    assert gh.labels == []                                  # the requeued job is live: no label yet


def test_once_survives_a_failed_mark_and_a_failed_comment(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    gh.fail_comments = 1
    laptop_result(remote, rc=1, tail=FNF)
    daemon.remote_handback_pass()           # comment fails after the submit
    daemon.remote_handback_pass()
    assert len(store.jobs()) == 1
    assert len(gh.comments) == 1 and "requeued on pc as" in gh.comments[0][1]


def test_requeued_job_failing_again_is_an_ordinary_failure(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    laptop_result(remote, rc=1, tail=FNF)
    daemon.remote_handback_pass()
    new = store.jobs()[0]
    # the second failure: a job with the marker, failing the same way, on any host
    marked = remote.store.submit(host="laptop", priority="P2", tag="probe2", cmd="python y.py", issue=632,
                                 requeued_from=new.id)
    remote.store.start(marked.id)
    remote.store.end(marked.id, rc=1)
    remote.store.record_handback(marked.id, f"<!-- runs-daemon -->\nfailed\n- job: `{marked.id}`\n```\n{FNF}\n```\n")
    before = len(store.jobs())
    daemon.remote_handback_pass()
    assert len(store.jobs()) == before          # the marked job is never requeued
    assert not any(j.requeued_from == marked.id for j in store.jobs())
    assert "requeued on pc" not in gh.comments[-1][1]


def test_a_pc_job_is_never_requeued(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    pc = Path(tmp_path)
    job = store.submit(host="pc", priority="P2", tag="p", cmd="python x.py", issue=632)
    store.start(job.id)
    store.end(job.id, rc=1)
    assert daemon._requeue_on_pc(store.get(job.id), f"- job: `{job.id}`\n{FNF}\n") .count("requeued") == 0
    assert len(store.jobs()) == 1 and pc.exists()


def test_row3_skipped_pytest_on_laptop_is_labelled_and_requeued(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    cmd = "python -m pytest tests/test_issue632_rage_candidate.py -m pob"
    laptop_result(remote, rc=0, tail=SKIPPED, cmd=cmd, verdict="rc 0 (skipped: no reading)", rc_is_reading=True)
    daemon.remote_handback_pass()
    daemon.remote_handback_pass()
    assert len(store.jobs()) == 1 and store.jobs()[0].rc_is_reading and store.jobs()[0].host == "pc"
    assert "rc 0 (skipped: no reading)" in gh.comments[0][1]
    assert f"requeued on pc as {store.jobs()[0].id}" in gh.comments[0][1]


def test_row3_comment_body_never_reads_a_skip_as_a_pass(tmp_path):
    launcher, gh = FakeLauncher(), FakeGh()
    daemon, store, _ = make_daemon(tmp_path, launcher=launcher, gh=gh)
    cmd = "python -m pytest tests/test_issue632_rage_candidate.py -m pob"
    out = tmp_path / "skipped.out"
    out.write_text(SKIPPED + "\n", encoding="utf-8")
    job = store.submit(host="pc", priority="P1", tag="s", cmd=cmd, issue=632)
    store.start(job.id, out=str(out))
    store.end(job.id, rc=0, out=str(out))
    assert "rc 0 (skipped: no reading)" in daemon.comment_body(store.get(job.id))
    assert "rc 0 (done)" not in daemon.comment_body(store.get(job.id))
    out.write_text(MIXED + "\n", encoding="utf-8")
    assert "rc 0 (done)" in daemon.comment_body(store.get(job.id))
    assert store.jobs()[0].id == job.id and len(store.jobs()) == 1      # a PC skip is not requeued here


def test_laptop_missing_artifact_raises_no_job_failed_anomaly_but_a_second_failure_does(tmp_path):
    out = tmp_path / "x.out"
    out.write_text(FNF + "\n", encoding="utf-8")
    remote = FakeRemoteHost(tmp_path, "laptop")
    job = remote.store.submit(host="laptop", priority="P2", tag="p", cmd="python x.py", issue=632)
    remote.store.start(job.id, out=str(out))
    ended = remote.store.end(job.id, rc=1, out=str(out))
    assert anomalies_mod.detect_job_failed(ended) is None
    marked = remote.store.submit(host="laptop", priority="P2", tag="q", cmd="python x.py", issue=632,
                                 requeued_from=job.id)
    remote.store.start(marked.id, out=str(out))
    ended2 = remote.store.end(marked.id, rc=1, out=str(out))
    assert anomalies_mod.detect_job_failed(ended2) is not None


# #642 unit 6c (rule 3, row 8): a laptop replay_bench that found no --builds files is requeued once on the PC.
NO_FILES_PATH = "artifacts/benchmark/20261013-0101-P2-core-3/ignite_penance_brand-s5.pob.txt"
NO_FILES = ("usage: replay_bench.py [-h] --builds BUILDS\n"
            f"replay_bench.py: error: --builds matched no files: {NO_FILES_PATH}")
NO_FILES_CMD = f"python scripts/replay_bench.py --builds {NO_FILES_PATH}"


def test_row8_matched_no_files_requeues_once_on_pc(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    job = laptop_result(remote, rc=2, tail=NO_FILES, cmd=NO_FILES_CMD, rc_is_reading=False)
    daemon.remote_handback_pass()
    daemon.remote_handback_pass()
    pc_jobs = store.jobs()
    assert len(pc_jobs) == 1
    new = pc_jobs[0]
    assert (new.host, new.cmd, new.issue, new.priority, new.requeued_from) == ("pc", job.cmd, 632, "P2", job.id)
    assert new.host_fixed and new.state == "queued"
    assert len(gh.comments) == 1
    assert f"requeued on pc as {new.id}: the laptop lacks {NO_FILES_PATH}" in gh.comments[0][1]


def test_row8_requeued_matched_no_files_failing_again_is_an_ordinary_failure(tmp_path):
    daemon, store, remote, gh = rig(tmp_path)
    laptop_result(remote, rc=2, tail=NO_FILES, cmd=NO_FILES_CMD, rc_is_reading=False)
    daemon.remote_handback_pass()
    new = store.jobs()[0]
    marked = remote.store.submit(host="laptop", priority="P2", tag="probe2", cmd=NO_FILES_CMD, issue=632,
                                 requeued_from=new.id)
    remote.store.start(marked.id)
    remote.store.end(marked.id, rc=2)
    remote.store.record_handback(marked.id, f"<!-- runs-daemon -->\nfailed\n- job: `{marked.id}`\n```\n{NO_FILES}\n```\n")
    before = len(store.jobs())
    daemon.remote_handback_pass()
    assert len(store.jobs()) == before          # the marked job is never requeued again
    assert not any(j.requeued_from == marked.id for j in store.jobs())
    assert "requeued on pc" not in gh.comments[-1][1]


def test_missing_artifact_reads_the_matched_no_files_line():
    from junkroan.runs import handback_gate as gate
    assert gate.missing_artifact(NO_FILES.splitlines()) == NO_FILES_PATH
    win = "replay_bench.py: error: --builds matched no files: artifacts\\benchmark\\x\\y.pob.txt"
    assert gate.missing_artifact([win]) == "artifacts\\benchmark\\x\\y.pob.txt"
    assert gate.missing_artifact(["replay_bench.py: error: --builds matched no files: C:\\elsewhere\\y"]) is None


def test_laptop_matched_no_files_raises_no_job_failed_anomaly(tmp_path):
    out = tmp_path / "nofiles.out"
    out.write_text(NO_FILES + "\n", encoding="utf-8")
    remote = FakeRemoteHost(tmp_path, "laptop")
    job = remote.store.submit(host="laptop", priority="P2", tag="p", cmd=NO_FILES_CMD, issue=632)
    remote.store.start(job.id, out=str(out))
    ended = remote.store.end(job.id, rc=2, out=str(out))
    assert anomalies_mod.detect_job_failed(ended) is None
