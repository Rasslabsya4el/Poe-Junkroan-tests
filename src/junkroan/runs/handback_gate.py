"""#642 unit 3: two reads of a job's out text that change how its hand-back is worded and whether it is requeued.

* A job that died with ``FileNotFoundError`` on a path under ``artifacts/`` ran on a host that lacks the
  weekly build artifacts (artifacts are not in git): :func:`missing_artifact`.
* A pytest job whose summary has ``skipped`` and no ``passed`` read nothing, whatever its rc 0 looks like:
  :func:`skipped_without_reading`.

Pure functions of text; the daemon owns what is done with them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from junkroan.runs.rebalance import _runs_pytest
from junkroan.runs.store import Job

SKIPPED_VERDICT = "rc 0 (skipped: no reading)"
TAIL_LINES = 40

_ARTIFACT_RE = re.compile(r"""FileNotFoundError.*?(artifacts(?:\\{1,2}|/)[^'"\r\n]*)""")
_NO_FILES_RE = re.compile(r"""matched no files: (artifacts(?:\\{1,2}|/)[^'"\r\n]*)""")   # #642 unit 6c: replay_bench --builds
_SUMMARY_COUNT_RE = re.compile(r"\b\d+ (?:passed|skipped|failed|errors?|xfailed|xpassed|deselected|warnings?)\b")
_SKIPPED_RE = re.compile(r"\b\d+ skipped\b")
_PASSED_RE = re.compile(r"\b\d+ passed\b")
_SKIP_PATH_RE = re.compile(r"(artifacts[\\/][^\s'\"]+)")


def out_tail_lines(out: str | None, limit: int = TAIL_LINES) -> list[str]:
    """The last ``limit`` lines of a local out file; empty when it cannot be read."""

    if not out:
        return []
    try:
        path = Path(out)
        if not path.is_file():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except Exception:
        return []


def missing_artifact(lines: Iterable[str]) -> str | None:
    """The path from ``artifacts/`` on of the last ``FileNotFoundError`` (or ``matched no files:``) in ``lines``;
    None when none names one."""

    found = None
    for line in lines:
        match = _ARTIFACT_RE.search(line) or _NO_FILES_RE.search(line)
        if match:
            found = match.group(1).rstrip(".")
    if found is None:
        return None
    return re.sub(r"\\{2,}", r"\\", found)


def skipped_without_reading(cmd, rc, lines: Iterable[str]) -> bool:
    """A pytest command with rc 0 whose summary line has ``skipped`` and no ``passed``."""

    if rc != 0 or not _runs_pytest(cmd):
        return False
    for line in reversed(list(lines)):
        if _SUMMARY_COUNT_RE.search(line) and re.search(r"\bin \d", line):
            return bool(_SKIPPED_RE.search(line)) and not _PASSED_RE.search(line)
    return False


def skip_path(lines: Iterable[str]) -> str | None:
    """An ``artifacts/...`` path named by a skip reason in ``lines``, when there is one."""

    for line in lines:
        match = _SKIP_PATH_RE.search(line)
        if match and "skip" in line.lower():
            return match.group(1).replace("\\\\", "\\")
    return None


def laptop_lacks_artifact(job: Job) -> bool:
    """For the laptop daemon's own anomaly check: this failed job is the missing-artifacts case,
    which the PC requeues once instead of raising an anomaly."""

    if job.host == "pc" or job.requeued_from or job.rc in (None, 0):
        return False
    return missing_artifact(out_tail_lines(job.out)) is not None
