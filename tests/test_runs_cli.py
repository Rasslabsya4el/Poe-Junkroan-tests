"""scripts/runs.py: submit, status, cancel, import-queue (issue #40, no PoB)."""

from __future__ import annotations
from conftest import pc_only

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402


@pc_only
def test_submit_prints_job_id(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--host", "pc", "--priority", "P1",
                     "--issue", "12", "--", "python", "scripts/benchmark.py", "--seeds", "1"])
    assert rc == 0
    job_id = capsys.readouterr().out.strip()
    assert job_id.startswith("j-")

    store = Store(store_path)
    job = store.get(job_id)
    assert job.host == "pc" and job.priority == "P1" and job.issue == 12 and job.tag == "P1-#12"
    assert job.cmd == "python scripts/benchmark.py --seeds 1 --workers auto --tag P1-#12"  # #700: no --workers on the line -> auto
    assert job.state == "queued"


@pc_only
def test_submit_rc_is_reading_flag_is_stored(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    base = ["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1"]
    assert runs.main([*base, "--rc-is-reading", "--", "python", "-c", "pass"]) == 0
    marked = capsys.readouterr().out.strip()
    assert runs.main([*base, "--", "python", "-c", "pass"]) == 0
    plain = capsys.readouterr().out.strip()
    store = Store(store_path)
    assert store.get(marked).rc_is_reading is True
    assert store.get(plain).rc_is_reading is False


def test_old_submit_row_without_rc_is_reading_loads_false() -> None:
    from junkroan.runs.store import fold
    row = {"ts": "2026-10-01T00:00:00+00:00", "job": "j-old", "op": "submit", "host": "pc",
           "priority": "P1", "tag": "old", "cmd": "echo"}
    assert fold([row])["j-old"].rc_is_reading is False


# -- issue #118: `mark-posted` (another host's daemon calls this over ssh) -----------------------

def test_mark_posted_cli_marks_the_job_in_this_store(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)
    job = store.submit(host="laptop", priority="P1", tag="lap", cmd="echo hi", issue=118)
    store.start(job.id)
    store.end(job.id, rc=0)
    store.record_handback(job.id, "the body")

    rc = runs.main(["--store", str(store_path), "mark-posted", job.id])
    assert rc == 0
    assert f"{job.id} -> posted" in capsys.readouterr().out
    assert Store(store_path).get(job.id).posted is True


def test_mark_posted_cli_unknown_job_fails(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "mark-posted", "j-does-not-exist"])
    assert rc == 1
    assert "no such job" in capsys.readouterr().err


def test_submit_with_pin_and_resumable(tmp_path: Path, capsys, monkeypatch) -> None:
    # #120: `--host laptop` from the PC now goes over ssh to the laptop's own store; this test is
    # about `--pin`/`--resumable`, not that path, so it runs as if it were submitted ON the laptop
    # (`JUNKROAN_HOST`, the same "which host am I" `slot_budget.current_host()` already reads).
    monkeypatch.setenv("JUNKROAN_HOST", "laptop")
    store_path = tmp_path / "jobs.jsonl"
    runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "laptop", "--priority", "P0",
               "--pin", "abc123", "--resumable", "--", "echo", "hi"])
    job_id = capsys.readouterr().out.strip()
    job = Store(store_path).get(job_id)
    assert job.pin == "abc123" and job.resumable is True and job.host == "laptop"


# -- #120: `submit --host <other>` goes to that host's own store over ssh --------------------

def test_submit_own_host_stays_local(tmp_path: Path, capsys, monkeypatch) -> None:
    """`--host <this host>` behaves exactly as before: written straight to the local store, no ssh."""

    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    calls: list = []
    monkeypatch.setattr(runs.runs_hosts, "run_on_host", lambda *a, **k: calls.append((a, k)))
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                     "--", "echo", "hi"])
    assert rc == 0
    assert calls == [], "no ssh call for this host's own submit"
    job_id = capsys.readouterr().out.strip()
    job = Store(store_path).get(job_id)
    assert job.host == "pc" and job.tag == "P1-#1"


def test_submit_other_host_makes_exactly_one_remote_call_and_writes_nothing_locally(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")  # this process is the PC; --host laptop is "other"
    calls: list[tuple[dict, str]] = []

    def fake_run_on_host(host_cfg: dict, script: str):
        calls.append((host_cfg, script))
        return SimpleResult(0, "j-20260927-1200-abcd\n", "")

    monkeypatch.setattr(runs.runs_hosts, "run_on_host", fake_run_on_host)
    monkeypatch.setattr(
        runs.runs_hosts, "load_hosts_config",
        lambda: {"laptop": {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2"}},
    )
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "laptop", "--priority", "P1",
                     "--", "python", "scripts/benchmark.py", "--seeds", "1"])
    assert rc == 0
    assert len(calls) == 1, "exactly one remote call"
    host_cfg, script = calls[0]
    assert host_cfg["ssh"] == "laptop"
    assert "$env:JUNKROAN_HOST = 'laptop';" in script, (
        "without this the remote side's own current_host() defaults to 'pc' and the forwarded "
        "submit would go remote again, ssh-ing from the laptop to itself"
    )
    assert "cd 'C:\\Coding\\poe-junkroan-v2'" in script  # no daemon_repo_path here: falls back
    assert "runs.py' 'submit' '--issue' '1' '--host' 'laptop'" in script
    # #203: the command crosses PowerShell as one base64 token, not as loose arguments
    token = script.split("'--argv-b64' '")[1].split("'")[0]
    assert runs.decode_argv(token) == ["python", "scripts/benchmark.py", "--seeds", "1", "--workers", "auto"]  # #700
    assert capsys.readouterr().out.strip() == "j-20260927-1200-abcd"
    assert Store(store_path).jobs() == [], "0 rows in the local store"


def test_submit_other_host_cds_into_daemon_repo_path_when_set(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    """#120 send-back: the laptop's own runs daemon runs from a separate checkout
    (`C:\\Coding\\poe-junkroan-v2-daemon`) -- the remote submit must land THERE, not in
    `config/hosts.json`'s plain `repo_path`."""

    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    calls: list[tuple[dict, str]] = []

    def fake_run_on_host(host_cfg: dict, script: str):
        calls.append((host_cfg, script))
        return SimpleResult(0, "j-20260927-1200-beef\n", "")

    monkeypatch.setattr(runs.runs_hosts, "run_on_host", fake_run_on_host)
    monkeypatch.setattr(
        runs.runs_hosts, "load_hosts_config",
        lambda: {"laptop": {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2",
                             "daemon_repo_path": "C:\\Coding\\poe-junkroan-v2-daemon"}},
    )
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "laptop", "--priority", "P1",
                     "--", "echo", "hi"])
    assert rc == 0
    script = calls[0][1]
    assert "cd 'C:\\Coding\\poe-junkroan-v2-daemon'" in script
    assert capsys.readouterr().out.strip() == "j-20260927-1200-beef"
    assert Store(store_path).jobs() == []


def test_submit_other_host_unreachable_writes_nothing_and_exits_nonzero(
    tmp_path: Path, capsys, monkeypatch,
) -> None:
    monkeypatch.setenv("JUNKROAN_HOST", "pc")

    def failing_run_on_host(host_cfg: dict, script: str):
        raise TimeoutError("ssh timed out")

    monkeypatch.setattr(runs.runs_hosts, "run_on_host", failing_run_on_host)
    monkeypatch.setattr(
        runs.runs_hosts, "load_hosts_config",
        lambda: {"laptop": {"ssh": "laptop", "repo_path": "C:\\Coding\\poe-junkroan-v2"}},
    )
    store_path = tmp_path / "jobs.jsonl"
    rc = runs.main(["--store", str(store_path), "submit", "--issue", "1", "--host", "laptop", "--priority", "P1",
                     "--", "echo", "hi"])
    assert rc != 0
    captured = capsys.readouterr()
    err_lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(err_lines) == 1
    assert "laptop" in err_lines[0] and "ssh timed out" in err_lines[0]
    assert Store(store_path).jobs() == [], "0 rows in the local store"


class SimpleResult:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_cancel_only_a_queued_job(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)
    job = store.submit(host="pc", priority="P1", tag="t", cmd="echo hi")

    rc = runs.main(["--store", str(store_path), "cancel", job.id])
    assert rc == 0
    assert "cancelled" in capsys.readouterr().out
    assert Store(store_path).get(job.id).state == "cancelled"

    running = store.submit(host="pc", priority="P1", tag="t2", cmd="echo hi")
    store.start(running.id)
    rc = runs.main(["--store", str(store_path), "cancel", running.id])
    assert rc != 0
    assert "use 'runs.py stop" in capsys.readouterr().err


def test_status_json_lists_jobs(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)
    store.submit(host="pc", priority="P1", tag="a", cmd="echo a")
    store.submit(host="pc", priority="P2", tag="b", cmd="echo b")

    rc = runs.main(["--store", str(store_path), "status", "--json"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["tag"] for r in rows} == {"a", "b"}


def test_status_table_renders_human_durations(tmp_path: Path, capsys) -> None:
    """The status table's duration column uses human_duration: seconds, minutes, hours (principle 7)."""

    store_path = tmp_path / "jobs.jsonl"
    store = Store(store_path)

    from datetime import datetime, timedelta, timezone
    from junkroan.runs import store as store_mod

    now = datetime.now(timezone.utc)
    short = store.submit(host="pc", priority="P1", tag="short", cmd="echo a")
    medium = store.submit(host="pc", priority="P1", tag="medium", cmd="echo b")
    long_ = store.submit(host="pc", priority="P1", tag="long", cmd="echo c")

    def finish(job, start_offset_seconds: float, run_seconds: float) -> None:
        start_ts = (now - timedelta(seconds=start_offset_seconds)).isoformat(timespec="seconds")
        end_ts = (now - timedelta(seconds=start_offset_seconds - run_seconds)).isoformat(timespec="seconds")
        store._write_line({"ts": start_ts, "job": job.id, "op": "start", "out": None, "run_dir": None})
        store._write_line({"ts": end_ts, "job": job.id, "op": "end", "rc": 0, "out": None, "run_dir": None})

    finish(short, 45, 45)        # 45 s run
    finish(medium, 47 * 60, 47 * 60)    # 47 min run
    finish(long_, 100 * 60, 100 * 60)   # 100 min = 1 h 40 min run (>= the 90 min hours threshold)

    rc = runs.main(["--store", str(store_path), "status"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "45 s" in out
    assert "47 min" in out
    assert "1 h 40 min" in out


def test_import_queue_imports_only_pending_and_dedupes(tmp_path: Path, capsys) -> None:
    queue = tmp_path / "queue.txt"
    queue.write_text(
        "# a comment\n"
        "\n"
        "done 20260101-1200 python scripts/old.py --seeds 1\n"
        "@abc1234 python scripts/benchmark.py --seeds 3\n"
        "python scripts/search.py Fireball\n",
        encoding="utf-8",
    )
    store_path = tmp_path / "jobs.jsonl"

    rc = runs.main(["--store", str(store_path), "import-queue", "--queue", str(queue)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "imported 2 of 2" in out

    store = Store(store_path)
    jobs = store.jobs()
    assert len(jobs) == 2
    cmds = {j.cmd for j in jobs}
    assert cmds == {"python scripts/benchmark.py --seeds 3", "python scripts/search.py Fireball"}
    pins = {j.pin for j in jobs}
    assert pins == {"abc1234", None}
    assert all(j.host == "pc" and j.priority == "P2" for j in jobs)

    # queue.txt itself is untouched
    assert "done 20260101-1200 python scripts/old.py --seeds 1" in queue.read_text(encoding="utf-8")
    assert "@abc1234 python scripts/benchmark.py --seeds 3" in queue.read_text(encoding="utf-8")

    rc = runs.main(["--store", str(store_path), "import-queue", "--queue", str(queue)])
    assert rc == 0
    out2 = capsys.readouterr().out
    assert "imported 0 of 2" in out2
    assert len(Store(store_path).jobs()) == 2  # no duplicates on a second run


def _bare(store_path: Path, *flags: str) -> int:
    return runs.main(["--store", str(store_path), "submit", "--host", "pc", "--priority", "P1",
                      *flags, "--", "python", "-c", "pass"])


def test_submit_without_issue_or_no_issue_is_refused(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _bare(store_path) == 2
    err = capsys.readouterr().err
    assert "--issue" in err and "--no-issue" in err
    assert Store(store_path).jobs() == []


@pc_only
def test_submit_no_issue_queues_with_issue_none(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert runs.main(["--store", str(store_path), "submit", "--host", "pc", "--priority", "P1", "--no-issue",
                      "--", "python", "scripts/benchmark.py", "--set", "core14"]) == 0
    job = Store(store_path).get(capsys.readouterr().out.strip())
    assert job.issue is None


def test_submit_issue_and_no_issue_together_is_refused(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _bare(store_path, "--issue", "4", "--no-issue") == 2
    assert Store(store_path).jobs() == []


@pc_only
def test_submit_no_label_flag(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _bare(store_path, "--issue", "4", "--no-label") == 0
    labelless = capsys.readouterr().out.strip()
    assert _bare(store_path.with_name("b.jsonl"), "--issue", "4") == 0
    plain = capsys.readouterr().out.strip()
    assert Store(store_path).get(labelless).no_label is True
    assert Store(store_path.with_name("b.jsonl")).get(plain).no_label is False


def test_submit_no_label_with_no_issue_is_refused(tmp_path: Path) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _bare(store_path, "--no-issue", "--no-label") == 2
    assert Store(store_path).jobs() == []


# -- issue #551: a shell-expanded --builds glob is refused at submit ------------------------------

def _submit_builds(store_path: Path, *builds_tokens: str) -> int:
    return runs.main(["--store", str(store_path), "submit", "--host", "pc", "--priority", "P1",
                      "--issue", "551", "--", "python", "scripts/replay_bench.py", *builds_tokens])


def test_expanded_builds_glob_is_refused(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    rc = _submit_builds(store_path, "--builds", "a.pob.txt", "b.pob.txt", "c.pob.txt", "--move", "flask")
    err = capsys.readouterr().err
    assert rc != 0
    assert "into 3 paths" in err and "quote it" in err
    assert Store(store_path).jobs() == []


@pc_only
def test_quoted_builds_glob_is_stored_verbatim(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _submit_builds(store_path, "--builds", "artifacts/x/*.pob.txt", "--move", "flask") == 0
    job = Store(store_path).get(capsys.readouterr().out.strip())
    assert "artifacts/x/*.pob.txt" in job.cmd


@pc_only
def test_single_builds_path_is_accepted(tmp_path: Path, capsys) -> None:
    store_path = tmp_path / "jobs.jsonl"
    assert _submit_builds(store_path, "--builds", "a.pob.txt", "--move", "flask") == 0
    assert len(Store(store_path).jobs()) == 1
