"""`scripts/clean_runs_events.py` (issue #387): the one-time cleaner of the runs event feed.

Tmp files only; the real `artifacts/runs/events.jsonl` is never touched.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

from junkroan.runs import hosts as runs_hosts

_SPEC = importlib.util.spec_from_file_location(
    "clean_runs_events", Path(__file__).resolve().parents[1] / "scripts" / "clean_runs_events.py"
)
cleaner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cleaner)


def _line(event: dict) -> bytes:
    return (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")


def _keymaster(session: str, detail: str, job: str | None = None) -> dict:
    return {"kind": "keymaster_start", "session": session,
            "anomaly": {"detail": detail, "host": None, "job": job, "key": "k", "kind": "job_failed", "out": None}}


REAL = [
    {"ts": "2026-09-27T23:01:22+00:00", "kind": "issue_ready_seen", "issue": 236},
    _keymaster("b71f0128", "job j-20260927-0400-81f7 ended rc null", "j-20260927-0400-81f7"),
    {"issue": 35, "job": "j-20260927-0359-8b3e", "kind": "end", "rc": 0, "ts": "2026-09-27T05:38:09"},
]
TEST_LINES = {
    "echo-x": _keymaster("km-9", "job j-20260926-2022-d3eb ended rc 1 (failed); cmd `echo x`", "j-20260926-2022-d3eb"),
    "pytest-tmp": {"kind": "keymaster_start", "session": "ab12cd34",
                   "anomaly": {"job": "j-stuck", "out": "C:\\Users\\user\\AppData\\Local\\Temp\\pytest-of-user\\pytest-4301\\x.out"}},
    "wrong-host": {"kind": "keymaster_start", "session": "ab12cd34",
                   "anomaly": {"detail": "job j-1 (`wrong-host-daemon`) is queued for host 'laptop'", "job": "j-1"}},
    "fake-keymaster-session": _keymaster("km-1", "laptop unreachable for 3 probes in a row"),
    "lease-overrun-fixture": {"held_for": 605.77, "issue": 61, "kind": "lease_overrun", "pid": None},
}


def _write(path: Path, events: list[dict]) -> bytes:
    data = b"".join(_line(e) for e in events)
    path.write_bytes(data)
    return data


def _quiet(_msg: str) -> None:
    pass


def test_classifier_drops_each_named_pattern_and_keeps_real_lines() -> None:
    assert set(TEST_LINES) == set(cleaner.PATTERNS)
    for name, event in TEST_LINES.items():
        assert cleaner.classify(_line(event)) == name
    for event in REAL:
        assert cleaner.classify(_line(event)) is None
    assert cleaner.classify(b"not json at all\n") is None  # unparseable stays
    # a real overrun (far past the fixture's 10 minutes) stays
    assert cleaner.classify(_line({"held_for": 4000.0, "issue": 61, "kind": "lease_overrun", "pid": None})) is None


def test_dry_run_writes_nothing_and_counts(tmp_path: Path) -> None:
    feed = tmp_path / "events.jsonl"
    original = _write(feed, REAL + list(TEST_LINES.values()))
    out: list[str] = []
    assert cleaner.run(feed, tmp_path / "jobs.jsonl", apply=False, out=out.append) == 0
    assert feed.read_bytes() == original
    assert not (tmp_path / "events.jsonl.pre387").exists()
    text = "\n".join(out)
    assert "lines total: 8" in text and "dropped total: 5" in text and "kept: 3" in text
    assert "present in jobs.jsonl: 0" in text


def test_apply_refuses_when_a_dropped_line_names_a_known_job(tmp_path: Path) -> None:
    feed = tmp_path / "events.jsonl"
    original = _write(feed, REAL + [TEST_LINES["echo-x"]])
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_bytes(_line({"job": "j-20260926-2022-d3eb", "op": "submit"}))
    out: list[str] = []
    assert cleaner.run(feed, jobs, apply=True, out=out.append) == 3
    assert feed.read_bytes() == original
    assert "j-20260926-2022-d3eb" in "\n".join(out)
    # the same feed with an unrelated jobs store applies
    jobs.write_bytes(_line({"job": "j-other", "op": "submit"}))
    assert cleaner.run(feed, jobs, apply=True, out=_quiet) == 0
    assert feed.read_bytes() == b"".join(_line(e) for e in REAL)
    assert (tmp_path / "events.jsonl.pre387").read_bytes() == original


def test_concurrent_appender_loses_nothing_and_keeps_order(tmp_path: Path) -> None:
    feed = tmp_path / "events.jsonl"
    initial = [REAL[i % 3] for i in range(1500)]
    for i in range(1500):
        initial.insert(i * 2, TEST_LINES["fake-keymaster-session"])
    _write(feed, initial)
    total = 300
    started = threading.Event()
    errors: list[BaseException] = []

    def appender() -> None:
        try:
            for n in range(total):
                runs_hosts.append_event({"kind": "mode", "n": n}, path=feed)
                if n == 5:
                    started.set()
                time.sleep(0.001)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            started.set()

    thread = threading.Thread(target=appender)
    thread.start()
    assert started.wait(30)
    applies = 0
    deadline = time.monotonic() + 60
    while (thread.is_alive() or applies < 3) and time.monotonic() < deadline:
        assert cleaner.run(feed, tmp_path / "jobs.jsonl", apply=True, out=_quiet) == 0
        applies += 1
    thread.join(30)
    assert not thread.is_alive() and not errors
    lines = feed.read_bytes().splitlines()
    assert len(lines) == 1500 + total
    assert [json.loads(l) for l in lines[:1500]] == [REAL[i % 3] for i in range(1500)]
    assert [json.loads(l)["n"] for l in lines[1500:]] == list(range(total))


def test_reader_never_sees_a_partial_file_during_the_rewrite(tmp_path: Path) -> None:
    feed = tmp_path / "events.jsonl"
    events = []
    for i in range(3000):
        events.append(dict(REAL[1], n=i))
        events.append(TEST_LINES["fake-keymaster-session"])
    original = _write(feed, events)
    cleaned = b"".join(_line(dict(REAL[1], n=i)) for i in range(3000))
    seen: list[bytes] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                seen.append(feed.read_bytes())
            except OSError:  # Windows: the instant of the swap
                pass

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        time.sleep(0.05)
        assert cleaner.run(feed, tmp_path / "jobs.jsonl", apply=True, out=_quiet) == 0
        time.sleep(0.05)
    finally:
        stop.set()
        thread.join(30)
    assert seen and not thread.is_alive()
    assert {s for s in seen} <= {original, cleaned}  # only the whole old or the whole new file
    assert cleaned in seen
