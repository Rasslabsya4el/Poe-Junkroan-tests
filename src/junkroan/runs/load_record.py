"""Load samples file: append, trim to 14 days, and the one hand-back line (#760). Pure, no subprocess."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Mapping

from junkroan.runs import load_groups

_TS_RE = re.compile(r'"ts":\s*"([^"]+)"')
_NO_SAMPLE = "Load at its end: no load sample"


def append_sample(path: Path | str, snap: Mapping[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(load_groups.public(snap)) + "\n")


def _line_ts(line: str) -> datetime | None:
    m = _TS_RE.search(line[:80])
    if not m:
        return None
    try:
        return datetime.fromisoformat(m.group(1))
    except ValueError:
        return None


def trim(path: Path | str, now: datetime, keep_days: int = 14) -> int:
    """Drop lines older than keep_days; unparseable lines are dropped too (no ts, no use).
    Rewrites through a temp file + os.replace. Returns the number of lines dropped."""
    p = Path(path)
    if not p.exists():
        return 0
    cutoff = now - timedelta(days=keep_days)
    kept: list[str] = []
    dropped = 0
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            ts = _line_ts(line)
            if ts is None or ts < cutoff:
                dropped += 1
            else:
                kept.append(line if line.endswith("\n") else line + "\n")
    if dropped == 0:
        return 0
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.writelines(kept)
    os.replace(tmp, p)
    return dropped


def _lines_from_end(path: Path, block: int = 65536) -> Iterator[str]:
    """Yield text lines newest first, reading backwards in blocks."""
    with path.open("rb") as f:
        pos = f.seek(0, os.SEEK_END)
        tail = b""
        while pos > 0:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            parts = (f.read(step) + tail).split(b"\n")
            tail = parts[0]
            for raw in reversed(parts[1:]):
                if raw.strip():
                    yield raw.decode("utf-8", errors="replace")
        if tail.strip():
            yield tail.decode("utf-8", errors="replace")


def _pytest_count(rec: Mapping[str, Any]) -> int:
    # whole_suite_pytest and merge_suite_pytest are counts; a merge-suite pytest that also runs the
    # whole suite is in both, and whole_suite_list marks it, so it is counted once.
    whole = int(rec.get("whole_suite_pytest") or 0)
    merge = int(rec.get("merge_suite_pytest") or 0)
    both = sum(1 for r in rec.get("whole_suite_list") or [] if r.get("merge_suite"))
    return whole + max(merge - both, 0)


def load_line(path: Path | str, end_ts: datetime, max_age_s: int = 60) -> str:
    p = Path(path)
    if not p.exists():
        return _NO_SAMPLE
    best: tuple[float, str] | None = None
    try:
        for line in _lines_from_end(p):
            ts = _line_ts(line)
            if ts is None:
                continue
            delta = (ts - end_ts).total_seconds()
            if delta < -max_age_s:
                break  # file is chronological: everything further back is older still
            if abs(delta) <= max_age_s and (best is None or abs(delta) < best[0]):
                best = (abs(delta), line)
    except OSError:
        return _NO_SAMPLE
    if best is None:
        return _NO_SAMPLE
    try:
        rec = json.loads(best[1])
        g = rec["groups"]
        pob = g["pob_counted"]["count"] + g["pob_filler"]["count"]
        return (f"Load at its end ({rec['ts']}): CPU {rec['cpu_pct']:g}%, "
                f"free RAM {rec['free_ram_mb'] / 1024:.1f} GB, PoB {pob}, "
                f"pytest {_pytest_count(rec)}, claude {g['claude']['count']}")
    except (ValueError, KeyError, TypeError):
        return _NO_SAMPLE
