"""Has a benchmark tag already finished a run? (#365: a finished tag was started again for 24 h.)

`scripts/benchmark.py` writes `artifacts/benchmark/<YYYYMMDD-HHMM>[-<tag>][-no-<ablate>]/`. It writes
`results.json` and `report.md` after EVERY completed build (`persist_completed_row`), so neither file
alone marks the end; but until the last build the report starts with `partial: N of M builds`, and the
last write drops that line. A folder is finished when `results.json` exists and `report.md`, if it
exists, does not start with `partial:`.
"""

from __future__ import annotations

import re
from pathlib import Path

_STAMP = re.compile(r"^\d{8}-\d{4}-(?P<rest>.+)$")


def _is_finished(folder: Path) -> bool:
    if not (folder / "results.json").is_file():
        return False
    report = folder / "report.md"
    if report.is_file():
        try:
            with report.open(encoding="utf-8", errors="replace") as fh:
                return not fh.readline().startswith("partial:")
        except OSError:
            return False
    return True


def finished_run_dir(tag: str, root: Path) -> Path | None:
    """The newest finished results folder of ``tag`` under ``<root>/artifacts/benchmark/``, or None."""

    base = Path(root) / "artifacts" / "benchmark"
    if not tag or not base.is_dir():
        return None
    hits = []
    for folder in base.iterdir():
        m = _STAMP.match(folder.name)
        if not m or not folder.is_dir():
            continue
        rest = m.group("rest")
        if rest == tag or rest.startswith(tag + "-no-") or rest.startswith(tag + "-ablate"):
            if _is_finished(folder):
                hits.append(folder)
    return max(hits, key=lambda p: p.name) if hits else None
