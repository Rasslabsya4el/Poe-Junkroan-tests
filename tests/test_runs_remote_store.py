"""`src/junkroan/runs/remote_store.py` (#81): reading another host's job store over SSH, cached.

No real SSH: `read_remote_jobs` takes an injected `transport`; `LaptopJobsCache` takes an injected
`reader` and an injected `executor` (a synchronous one here, `lambda fn: fn()`, so the background
refresh is deterministic in a test). A fake clock drives the TTL so no test sleeps.
"""

from __future__ import annotations

import base64
import json

import pytest

from junkroan.runs import remote_store
from junkroan.runs import ssh_transport
from junkroan.runs.store import Job


HOST_CFG = {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2"}


def _jobs_jsonl(*records: dict) -> str:
    return "\n".join(json.dumps(r) for r in records) + "\n"


def _submit_line(job_id: str, host: str, tag: str, issue: int) -> dict:
    return {
        "ts": "2026-09-26T10:00:00.000000+00:00", "job": job_id, "op": "submit",
        "host": host, "priority": "P1", "issue": issue, "submitter": "", "tag": tag,
        "pin": None, "cmd": "echo hi", "resumable": False, "workers": 1, "after": [],
    }



def _gz64(text: str) -> str:
    import gzip
    return base64.b64encode(gzip.compress(text.encode("utf-8"))).decode("ascii")

class _FakeResult:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ------------------------------------------------------------------------- read_remote_jobs ------

def test_read_remote_jobs_decodes_and_folds_the_remote_log():
    raw = _jobs_jsonl(_submit_line("j-1", "laptop", "laptop-job", 81))
    encoded = _gz64(raw)

    def transport(host_cfg, script, *, timeout):
        assert host_cfg is HOST_CFG
        assert timeout == remote_store.DEFAULT_TIMEOUT_SECONDS
        return _FakeResult(0, stdout=encoded)

    jobs = remote_store.read_remote_jobs(HOST_CFG, transport=transport)
    assert len(jobs) == 1
    assert isinstance(jobs[0], Job)
    assert jobs[0].tag == "laptop-job"
    assert jobs[0].host == "laptop"
    assert jobs[0].issue == 81


def test_read_remote_jobs_empty_file_is_no_jobs_not_an_error():
    jobs = remote_store.read_remote_jobs(HOST_CFG, transport=lambda cfg, script, *, timeout: _FakeResult(0, stdout=""))
    assert jobs == []


def test_910_absent_file_is_an_error_naming_the_path_not_no_jobs():
    """#910: the script prints the missing mark for an absent log; that is never "no jobs"."""
    with pytest.raises(remote_store.RemoteJobsLogMissing, match="poe-junkroan-v2.artifacts.runs.jobs.jsonl"):
        remote_store.read_remote_jobs(
            HOST_CFG, transport=lambda cfg, script, *, timeout: _FakeResult(0, stdout=remote_store._MISSING_MARK))


def test_read_remote_jobs_nonzero_exit_raises_unreachable():
    def transport(cfg, script, *, timeout):
        return _FakeResult(1, stderr="ssh: connect to host laptop port 22: Connection refused")

    with pytest.raises(remote_store.RemoteStoreUnreachable):
        remote_store.read_remote_jobs(HOST_CFG, transport=transport)


def test_read_remote_jobs_transport_exception_raises_unreachable():
    def transport(cfg, script, *, timeout):
        raise TimeoutError("ssh timed out")

    with pytest.raises(remote_store.RemoteStoreUnreachable):
        remote_store.read_remote_jobs(HOST_CFG, transport=transport)


def test_read_remote_jobs_uses_daemon_repo_path_when_set():
    """#120: the laptop's own runs daemon runs from a separate checkout (`daemon_repo_path`), not
    `config/hosts.json`'s plain `repo_path` -- the jobs read must land in that SAME store."""

    host_cfg = {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2",
                "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}
    captured: dict = {}

    def transport(cfg, script, *, timeout):
        captured["script"] = script
        return _FakeResult(0, stdout="")

    remote_store.read_remote_jobs(host_cfg, transport=transport)
    assert "poe-junkroan-v2-daemon" in captured["script"]
    assert "poe-junkroan-v2\\artifacts" not in captured["script"]


# --------------------------------------------------------------------------- read_remote_snapshot ---

def test_read_remote_snapshot_decodes_jobs_and_daemon_status_from_one_reply():
    jobs_raw = _jobs_jsonl(_submit_line("j-1", "laptop", "laptop-job", 81))
    status = {"host": "laptop", "pid": 222, "started": "2026-09-27T00:00:00+00:00",
              "last_tick": "2026-09-27T00:00:10+00:00", "tick_seconds": 10.0,
              "running": [], "queued": 0}
    stdout = (
        _gz64(jobs_raw) + "\n"
        + remote_store._SNAPSHOT_SPLIT + "\n"
        + _gz64(json.dumps(status))
    )
    calls = []

    def transport(host_cfg, script, *, timeout):
        calls.append(script)
        return _FakeResult(0, stdout=stdout)

    snapshot = remote_store.read_remote_snapshot(HOST_CFG, host="laptop", transport=transport)
    assert len(calls) == 1  # exactly one ssh round trip for both halves
    assert len(snapshot.jobs) == 1
    assert snapshot.jobs[0].tag == "laptop-job"
    assert snapshot.daemon_status == status


def test_read_remote_snapshot_missing_status_half_is_none_not_an_error():
    jobs_raw = _jobs_jsonl(_submit_line("j-1", "laptop", "laptop-job", 81))
    stdout = _gz64(jobs_raw) + "\n" + remote_store._SNAPSHOT_SPLIT + "\n"

    snapshot = remote_store.read_remote_snapshot(
        HOST_CFG, host="laptop", transport=lambda cfg, script, *, timeout: _FakeResult(0, stdout=stdout),
    )
    assert len(snapshot.jobs) == 1
    assert snapshot.daemon_status is None


def test_read_remote_snapshot_uses_daemon_repo_path_when_set():
    host_cfg = {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2",
                "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}
    captured: dict = {}

    def transport(cfg, script, *, timeout):
        captured["script"] = script
        return _FakeResult(0, stdout="\n" + remote_store._SNAPSHOT_SPLIT + "\n")

    remote_store.read_remote_snapshot(host_cfg, host="laptop", transport=transport)
    assert "poe-junkroan-v2-daemon" in captured["script"]
    assert "poe-junkroan-v2\\artifacts" not in captured["script"]


def _b64(text: str) -> str:
    return _gz64(text)


def _snapshot_reply(*halves: str) -> str:
    return ("\n" + remote_store._SNAPSHOT_SPLIT + "\n").join(halves)


def test_471_three_part_reply_carries_the_budget_and_two_part_reply_has_none():
    jobs_raw = _b64(_jobs_jsonl(_submit_line("j-1", "laptop", "laptop-job", 81)))
    budget = {"day": {"hours": [0, 24], "total": 2}, "strict_reserve": False}

    def read(stdout):
        return remote_store.read_remote_snapshot(
            HOST_CFG, host="laptop", transport=lambda cfg, script, *, timeout: _FakeResult(0, stdout=stdout))

    three = read(_snapshot_reply(jobs_raw, "", _b64(json.dumps(budget))))
    assert three.budget == budget and len(three.jobs) == 1
    two = read(_snapshot_reply(jobs_raw, ""))
    assert two.budget is None and len(two.jobs) == 1
    garbage = read(_snapshot_reply(jobs_raw, "", _b64("not json {")))
    assert garbage.budget is None and len(garbage.jobs) == 1


def test_471_script_names_the_daemon_jobs_file_and_the_plain_repo_budget_file():
    host_cfg = {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2",
                "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}
    captured: dict = {}

    def transport(cfg, script, *, timeout):
        captured["script"] = script
        return _FakeResult(0, stdout="")

    remote_store.read_remote_snapshot(host_cfg, host="laptop", transport=transport)
    script = captured["script"]
    assert "C:\\Coding\\poe-junkroan-v2-daemon\\artifacts\\runs\\jobs.jsonl" in script
    assert "C:\\Coding\\poe-junkroan-v2\\var\\machine_budget.json" in script


def test_read_remote_snapshot_nonzero_exit_raises_unreachable():
    def transport(cfg, script, *, timeout):
        return _FakeResult(1, stderr="ssh: connect to host laptop port 22: Connection refused")

    with pytest.raises(remote_store.RemoteStoreUnreachable):
        remote_store.read_remote_snapshot(HOST_CFG, transport=transport)


def test_laptop_jobs_cache_carries_daemon_status_from_a_remote_snapshot_reader():
    status = {"host": "laptop", "pid": 222, "last_tick": "2026-09-27T00:00:10+00:00"}
    job = Job(id="j-1", host="laptop", priority="P1", issue=81, submitter="", tag="t", pin=None,
              cmd="echo hi", resumable=False, state="queued", submit_ts="ts")

    def reader():
        return remote_store.RemoteSnapshot(jobs=[job], daemon_status=status)

    cache = remote_store.LaptopJobsCache(reader, ttl=60.0, clock=lambda: 0.0, executor=_sync)
    cache.read()
    reading = cache.read()
    assert reading.jobs == [job]
    assert reading.daemon_status == status


def test_laptop_jobs_cache_reader_returning_a_bare_list_leaves_daemon_status_none():
    job = Job(id="j-1", host="laptop", priority="P1", issue=81, submitter="", tag="t", pin=None,
              cmd="echo hi", resumable=False, state="queued", submit_ts="ts")
    cache = remote_store.LaptopJobsCache(lambda: [job], ttl=60.0, clock=lambda: 0.0, executor=_sync)
    cache.read()
    reading = cache.read()
    assert reading.jobs == [job]
    assert reading.daemon_status is None


# --------------------------------------------------------------------------- the argv / encoding ---

def test_build_ssh_argv_encoded_command_decodes_back_to_the_script():
    """#81 follow-up: a real read failed because `-Command "$p = '...'"` let a shell along the way
    eat `$p`. `-EncodedCommand` (base64 of UTF-16LE) survives every shell untouched. #87: this argv
    now comes from the one shared helper (`ssh_transport.build_ssh_argv`), also used by
    `hosts.run_on_host`."""

    script = "$p = 'C:\\Coding\\poe-junkroan-v2\\artifacts\\runs\\jobs.jsonl'; 'hi $p'"
    argv = ssh_transport.build_ssh_argv(HOST_CFG, script)
    assert argv[:2] == ["ssh", "laptop"]
    assert argv[2:6] == ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    decoded = base64.b64decode(argv[6]).decode("utf-16-le")
    assert decoded == script


# --------------------------------------------------------------------------- LaptopJobsCache ------

def _sync(fn):
    fn()


def test_cache_first_read_is_pending_not_no_jobs_not_unreachable():
    """Before the very first background refresh finishes, `read()` never blocks and never claims
    "no jobs" or "unreachable": it reports `pending=True` (#81 follow-up)."""

    def reader():
        return [Job(id="j-1", host="laptop", priority="P1", issue=81, submitter="", tag="t",
                    pin=None, cmd="echo hi", resumable=False, state="queued", submit_ts="ts")]

    cache = remote_store.LaptopJobsCache(reader, ttl=60.0, clock=lambda: 0.0, executor=_sync)
    first = cache.read()  # triggers the (synchronous, in this test) background refresh
    assert first.pending is True
    assert first.ok is False
    assert first.jobs == []

    second = cache.read()  # the refresh already completed by the time this test's executor returns
    assert second.ok is True
    assert second.pending is False
    assert len(second.jobs) == 1


def test_cache_serves_a_fresh_reading_with_no_further_reader_calls():
    calls = []

    def reader():
        calls.append(1)
        return [Job(id="j-1", host="laptop", priority="P1", issue=81, submitter="", tag="t",
                    pin=None, cmd="echo hi", resumable=False, state="queued", submit_ts="ts")]

    clock = {"t": 0.0}
    cache = remote_store.LaptopJobsCache(reader, ttl=60.0, clock=lambda: clock["t"], executor=_sync)

    cache.read()  # pending -> triggers the refresh
    first = cache.read()  # the refresh already completed
    assert first.ok is True and first.stale is False
    assert len(first.jobs) == 1

    clock["t"] = 30.0  # inside the 60 s TTL: no second reader call
    second = cache.read()
    assert second.ok is True
    assert len(calls) == 1
    assert second.age_seconds == pytest.approx(30.0)


def test_cache_refreshes_once_stale():
    calls = []

    def reader():
        calls.append(1)
        return [Job(id=f"j-{len(calls)}", host="laptop", priority="P1", issue=81, submitter="",
                    tag="t", pin=None, cmd="echo hi", resumable=False, state="queued", submit_ts="ts")]

    clock = {"t": 0.0}
    cache = remote_store.LaptopJobsCache(reader, ttl=10.0, clock=lambda: clock["t"], executor=_sync)
    cache.read()
    cache.read()
    clock["t"] = 11.0  # past the TTL
    cache.read()  # triggers the second refresh
    reading = cache.read()
    assert len(calls) == 2
    assert reading.ok is True and reading.stale is False


def test_cache_unreachable_with_no_prior_reading_reports_ok_false_and_no_jobs():
    def reader():
        raise remote_store.RemoteStoreUnreachable("ssh: Connection refused")

    cache = remote_store.LaptopJobsCache(reader, ttl=60.0, clock=lambda: 0.0, executor=_sync)
    cache.read()  # pending -> triggers the (failing) refresh
    reading = cache.read()
    assert reading.ok is False
    assert reading.stale is False
    assert reading.pending is False
    assert reading.jobs == []
    assert reading.age_seconds is None
    assert "Connection refused" in reading.error


def test_cache_unreachable_after_a_good_reading_serves_the_stale_one_with_its_age():
    state = {"fail": False}
    job = Job(id="j-1", host="laptop", priority="P1", issue=81, submitter="", tag="t", pin=None,
              cmd="echo hi", resumable=False, state="queued", submit_ts="ts")

    def reader():
        if state["fail"]:
            raise remote_store.RemoteStoreUnreachable("laptop unreachable")
        return [job]

    clock = {"t": 0.0}
    cache = remote_store.LaptopJobsCache(reader, ttl=10.0, clock=lambda: clock["t"], executor=_sync)
    cache.read()
    good = cache.read()
    assert good.ok is True

    state["fail"] = True
    clock["t"] = 25.0  # past the TTL: a refresh is attempted (and fails) on this call
    cache.read()
    reading = cache.read()
    assert reading.ok is False
    assert reading.stale is True
    assert reading.jobs == [job]  # never silently "no jobs": the last good reading, marked stale
    assert reading.age_seconds == pytest.approx(25.0)
    assert "unreachable" in reading.error


def test_cache_does_not_start_a_second_refresh_before_the_ttl_elapses_again():
    """A host that stays unreachable is retried at most once per `ttl`, not on every `read()`."""

    calls = []

    def reader():
        calls.append(1)
        raise remote_store.RemoteStoreUnreachable("laptop unreachable")

    clock = {"t": 0.0}
    cache = remote_store.LaptopJobsCache(reader, ttl=10.0, clock=lambda: clock["t"], executor=_sync)
    cache.read()
    assert len(calls) == 1
    cache.read()
    cache.read()
    assert len(calls) == 1  # still within the ttl since the last attempt: no retry yet
    clock["t"] = 11.0
    cache.read()
    assert len(calls) == 2


# ------------------------------------------------------------------------------- gzip (#509) ------

def test_509_decode_helper_round_trips_gzip_base64_of_120kb_jsonl():
    raw = _jobs_jsonl(*[_submit_line(f"j-{i}", "laptop", f"tag-{i}", i) for i in range(600)])
    assert len(raw) > 100_000
    encoded = _gz64(raw)
    assert len(encoded) < len(raw) // 3
    assert remote_store.decode_remote_blob(encoded).decode("utf-8") == raw


def test_509_every_reader_script_gzips_each_file():
    snap = remote_store._remote_snapshot_script("C:\r", "laptop")
    assert snap.count("G $") == 2 and snap.count("TrimJobs $") == 1  # status, budget via G; jobs via TrimJobs (#509 unit 3)
    for script in (snap, remote_store._remote_jobs_script("C:\r")):
        assert "IO.Compression.GZipStream" in script
        assert "ToBase64String($m.ToArray())" in script
    captured = {}
    remote_store.read_remote_anomalies(
        HOST_CFG, transport=lambda cfg, script, *, timeout: captured.setdefault("s", script) and _FakeResult(0))
    assert "GZipStream" in captured["s"] and "G $p" in captured["s"]
