"""One-time cleaner: drop test-written lines from the live runs event feed (issue #387).

    python scripts/clean_runs_events.py [--path events.jsonl] [--jobs jobs.jsonl]           # dry run
    python scripts/clean_runs_events.py [--path ...] [--jobs ...] --apply                   # rewrite

A line is dropped only when it matches a NAMED test-only pattern (``PATTERNS``); anything else, an
unparseable line included, is kept. Before ``--apply`` rewrites anything, every job id found in the
dropped lines is looked up in ``jobs.jsonl``: a dropped line that names a job the store knows is a
real event, so the script refuses.

Writer safety: live daemons append through ``junkroan.runs.hosts.append_event``, which takes the
sidecar lock ``<path>.lock`` around its write. The cleaner copies the file to ``<path>.pre387``,
writes the kept lines to a tmp file, then under that lock re-reads what was appended since (by byte
offset), filters it the same way, appends it, and ``os.replace``s the tmp over the feed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.runs import hosts as runs_hosts  # noqa: E402
from junkroan.runs.store import DEFAULT_LOG  # noqa: E402

LOCK_WAIT_SECONDS = 30.0
REPLACE_RETRY_SECONDS = 10.0
BACKUP_SUFFIX = ".pre387"

_JOB_ID = re.compile(r"\bj-[0-9A-Za-z][0-9A-Za-z_-]*")


def _fake_keymaster_session(event: dict | None, raw: str) -> bool:
    session = event.get("session") if event else None
    return isinstance(session, str) and re.fullmatch(r"km-\d+", session) is not None


def _lease_overrun_fixture(event: dict | None, raw: str) -> bool:
    if not event or event.get("kind") != "lease_overrun" or event.get("issue") != 61:
        return False
    held = event.get("held_for")
    return isinstance(held, (int, float)) and 600 <= held < 610


#: name -> (one-line reason, predicate(parsed event or None, raw line text)).
PATTERNS: dict[str, tuple[str, Callable[[dict | None, str], bool]]] = {
    "echo-x": (
        "the `echo x` command is the tests' stand-in job; no real submit runs it",
        lambda event, raw: "echo x" in raw,
    ),
    "pytest-tmp": (
        "a pytest tmp_path (`pytest-of-user`) in an out path: a test wrote the line",
        lambda event, raw: "pytest-of-user" in raw,
    ),
    "wrong-host": (
        "the `wrong-host-daemon` job of test_runs_anomalies",
        lambda event, raw: "wrong-host" in raw,
    ),
    "fake-keymaster-session": (
        "keymaster sessions are `km-1` / `km-2` in the tests; real ones are 8 hex digits",
        _fake_keymaster_session,
    ),
    "lease-overrun-fixture": (
        "lease_overrun for issue 61 with held_for 600-610 s: the test's fixed 10 min reservation, "
        "347 copies at 605-606 s, a real overrun would grow",
        _lease_overrun_fixture,
    ),
}


def split_complete(data: bytes) -> tuple[list[bytes], bytes]:
    """``(complete lines with their newline, trailing bytes without one)``."""

    lines = data.splitlines(keepends=True)
    tail = b""
    if lines and not lines[-1].endswith(b"\n"):
        tail = lines.pop()
    return lines, tail


def classify(line: bytes) -> str | None:
    """The name of the test-only pattern ``line`` matches, else ``None`` (keep)."""

    raw = line.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except ValueError:
        parsed = None
    event = parsed if isinstance(parsed, dict) else None
    for name, (_reason, predicate) in PATTERNS.items():
        if predicate(event, raw):
            return name
    return None


def job_ids_in(line: bytes) -> set[str]:
    raw = line.decode("utf-8", errors="replace")
    ids = set(_JOB_ID.findall(raw))
    try:
        event = json.loads(raw)
    except ValueError:
        return ids
    if isinstance(event, dict):
        for holder in (event, event.get("anomaly")):
            if isinstance(holder, dict) and isinstance(holder.get("job"), str):
                ids.add(holder["job"])
    return ids


def known_job_ids(jobs_path: Path) -> set[str]:
    known: set[str] = set()
    try:
        text = jobs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return known
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("job"), str):
            known.add(row["job"])
    return known


def filter_lines(lines: list[bytes]) -> tuple[list[bytes], Counter, set[str]]:
    kept: list[bytes] = []
    dropped: Counter = Counter()
    ids: set[str] = set()
    for line in lines:
        name = classify(line)
        if name is None:
            kept.append(line)
        else:
            dropped[name] += 1
            ids |= job_ids_in(line)
    return kept, dropped, ids


def _replace_with_retry(tmp: Path, target: Path) -> None:
    deadline = time.monotonic() + REPLACE_RETRY_SECONDS
    while True:
        try:
            os.replace(tmp, target)
            return
        except PermissionError:  # Windows: a reader or a writer still has the file open
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _report_dry(total: int, dropped: Counter, kept: int, ids: set[str], known: set[str]) -> list[str]:
    present = sorted(ids & known)
    out = [f"lines total: {total}"]
    for name, (reason, _p) in PATTERNS.items():
        out.append(f"  dropped {name}: {dropped.get(name, 0)}  ({reason})")
    out.append(f"dropped total: {sum(dropped.values())}")
    out.append(f"kept: {kept}")
    out.append(f"job ids in dropped lines: {len(ids)}; present in jobs.jsonl: {len(present)}")
    if present:
        out.append("  present: " + ", ".join(present))
    return out


def run(path: Path, jobs_path: Path, apply: bool, out: Callable[[str], None] = print) -> int:
    path = Path(path)
    if not path.exists():
        out(f"no such feed: {path}")
        return 2
    original = path.read_bytes()
    lines, tail = split_complete(original)
    offset = len(original) - len(tail)  # the partial tail (a writer mid-line) is left for the second read
    kept, dropped, ids = filter_lines(lines)
    known = known_job_ids(jobs_path)
    present = sorted(ids & known)
    for line in _report_dry(len(lines), dropped, len(kept), ids, known):
        out(line)
    if not apply:
        out("dry run: nothing written (pass --apply)")
        return 0
    if present:
        out(f"REFUSED: {len(present)} dropped line(s) name a job the store knows: {', '.join(present)}")
        return 3

    backup = path.with_name(path.name + BACKUP_SUFFIX)
    backup.write_bytes(original)
    tmp = path.with_name(path.name + ".tmp387")
    tmp.write_bytes(b"".join(kept))

    with runs_hosts.events_feed_lock(path, timeout=LOCK_WAIT_SECONDS) as lock:
        if not lock.locked:
            tmp.unlink(missing_ok=True)
            out("REFUSED: could not take the sidecar lock in time; nothing changed")
            return 4
        with path.open("rb") as handle:
            handle.seek(offset)
            added = handle.read()
        added_lines, added_tail = split_complete(added)
        added_kept, added_dropped, added_ids = filter_lines(added_lines)
        late_present = sorted(added_ids & known_job_ids(jobs_path))
        if late_present:
            tmp.unlink(missing_ok=True)
            out(f"REFUSED: lines appended meanwhile name known jobs: {', '.join(late_present)}")
            return 3
        with tmp.open("ab") as handle:
            handle.write(b"".join(added_kept) + added_tail)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_with_retry(tmp, path)

    final_kept = len(kept) + len(added_kept)
    appended_total = len(added_lines)
    out(
        f"applied: before {len(lines)}, dropped {sum(dropped.values()) + sum(added_dropped.values())}, "
        f"appended meanwhile {appended_total} (kept {len(added_kept)}), kept {final_kept}"
    )
    expected = len(lines) - sum(dropped.values()) + len(added_kept)
    if final_kept != expected:
        out(f"MISMATCH: kept {final_kept} != before - dropped + appended-kept = {expected}")
        return 5
    out(f"original saved as {backup}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", type=Path, default=None, help="events feed (default: the real one)")
    parser.add_argument("--jobs", type=Path, default=DEFAULT_LOG, help="jobs.jsonl (default: the real one)")
    parser.add_argument("--apply", action="store_true", help="rewrite the feed (default: dry run)")
    args = parser.parse_args(argv)
    return run(args.path or runs_hosts.events_path(), args.jobs, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
