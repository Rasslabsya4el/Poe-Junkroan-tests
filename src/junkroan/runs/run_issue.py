"""Pure builders for the run issue a finished whole-set benchmark job gets (issue #164, unit 1).

No gh calls and no daemon state: the daemon passes in `Job` records and run folders.
`scripts/` is not an importable package, so `compare_runs` is loaded by file path.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from junkroan.report_format import human_duration
from junkroan.runs.store import Job, main_root

ROOT = Path(__file__).resolve().parents[3]
#: Where finished run folders live on in the main checkout once their snapshot is cleaned up.
BENCHMARK_DIR = main_root(ROOT) / "artifacts" / "benchmark"
_SET_RE = re.compile(r"--set(?:=|\s+)(\S+)")
_GEAR_RE = re.compile(r"--gear(?:=|\s+)(\S+)")
_compare_module: Any = None


def _compare_runs() -> Any:
    global _compare_module
    if _compare_module is None:
        path = ROOT / "scripts" / "compare_runs.py"
        spec = importlib.util.spec_from_file_location("compare_runs", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _compare_module = module
    return _compare_module


def is_whole_set_job(job: Job) -> str | None:
    """The `--set` name of a benchmark job that ended rc 0, else None."""

    if job.rc != 0 or "scripts/benchmark.py" not in job.cmd.replace("\\", "/"):
        return None
    m = _SET_RE.search(job.cmd)
    return m.group(1) if m else None


def gear_of(job: Job) -> str | None:
    m = _GEAR_RE.search(job.cmd)
    return m.group(1) if m else None


def _end(job: Job) -> datetime | None:
    return datetime.fromisoformat(job.end_ts) if job.end_ts else None


def pick_control(job: Job, jobs: list[Job]) -> Job | None:
    """Newest earlier whole-set job with the same set and gear that has a run folder."""

    name, gear, mine = is_whole_set_job(job), gear_of(job), _end(job)
    if name is None or mine is None:
        return None
    best: tuple[datetime, Job] | None = None
    for other in jobs:
        end = _end(other)
        if other.id == job.id or end is None or end >= mine or not other.run_dir:
            continue
        if is_whole_set_job(other) != name or gear_of(other) != gear:
            continue
        if best is None or end > best[0]:
            best = (end, other)
    return best[1] if best else None


def resolve_run_dir(run_dir: str | Path | None, benchmark_dir: Path | None = None) -> str | None:
    """The run folder if it exists, else the same-named folder under `artifacts/benchmark`, else None."""

    if not run_dir:
        return None
    if Path(str(run_dir)).is_dir():
        return str(run_dir)
    kept = (benchmark_dir if benchmark_dir is not None else BENCHMARK_DIR) / PureWindowsPath(str(run_dir)).name
    return str(kept) if kept.is_dir() else None


def issue_text(job: Job, jobs: list[Job], benchmark_dir: Path | None = None) -> tuple[str, str]:
    """Title and body of the job's Run issue; its folder and its control's go through `resolve_run_dir`."""

    run_dir = resolve_run_dir(job.run_dir, benchmark_dir) or job.run_dir
    control = pick_control(job, jobs)
    control_dir = (resolve_run_dir(control.run_dir, benchmark_dir) or control.run_dir) if control else None
    return run_title(job, run_dir), run_body(job, run_dir, control_dir)


def run_title(job: Job, run_dir: str | Path) -> str:
    """At most 80 characters (the ticket shape): a long run folder name is cut, `#` never appears."""

    tail = f" ({is_whole_set_job(job)}, {job.host})"
    name = Path(str(run_dir)).name.replace("#", "")
    return f"Run {name[:max(0, 80 - 4 - len(tail))].rstrip('-_ ')}{tail}"[:80]


def _local(ts: str | None) -> str:
    return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M") if ts else "-"


def _duration(job: Job) -> str:
    if not job.start_ts or not job.end_ts:
        return "-"
    return human_duration((datetime.fromisoformat(job.end_ts) - datetime.fromisoformat(job.start_ts)).total_seconds())


def _fmt(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def _compare(control: Path, run: Path) -> tuple[str, str]:
    """The comparison text and verdict; a comparison that times out (#998) gives no text, as a failing script does."""

    try:
        res = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "compare_runs.py"), str(control), str(run), "--min-delta", "-5"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "", "error (timed out)"
    verdict = {0: "PASS", 1: "FAIL", 2: "incomplete"}.get(res.returncode, f"error (rc {res.returncode})")
    return res.stdout.strip() or res.stderr.strip(), verdict


def run_body(job: Job, run_dir: str | Path, control_run_dir: str | Path | None = None) -> str:
    cr = _compare_runs()
    run = Path(str(run_dir))
    summary = cr.summarize(cr._rows(run))
    name, gear = is_whole_set_job(job), gear_of(job)
    lines = [
        f"- job: `{job.id}`",
        f"- tag: `{job.tag}`",
        f"- host: {job.host}",
        f"- pin: {job.pin or '-'}",
        f"- cmd: `{job.cmd}`",
        f"- started: {_local(job.start_ts)}, ended: {_local(job.end_ts)}, duration: {_duration(job)}",
        f"- run folder: `{run_dir}` (`artifacts/benchmark/{run.name}`)",
        "",
        "| reference | seeds | median % of the author | spread | audit errors | failed |",
        "|---|---|---|---|---|---|",
    ]
    for slug, s in summary.items():
        lines.append(f"| {slug} | {s['seeds']} | {_fmt(s['median'])} | {_fmt(s['spread'])} | {s['audit_errors']} | {s['failed']} |")
    at_or_above = sum(1 for s in summary.values() if s["median"] is not None and s["median"] >= 100.0)
    errors = sum(s["audit_errors"] for s in summary.values())
    lines += ["", f"{at_or_above} of {len(summary)} references at or above the author", f"audit errors in total: {errors}", ""]
    verdict = None
    if control_run_dir is None:
        lines.append(f"no earlier run of {name} {gear}")
    else:
        table, verdict = _compare(Path(str(control_run_dir)), run)
        lines += [f"Compare with `{control_run_dir}`: **{verdict}**", "", "```", table, "```"]
    lines += ["", "Reviewed = the brain closes this issue with its verdict; every fix ticket is a sub-issue of it."]
    human = _human_block(job, name, len(summary), at_or_above, errors, verdict)
    return human + "\n## For the agent\n" + "\n".join(lines)


def _human_block(job: Job, name: str | None, refs: int, at_or_above: int, errors: int, verdict: str | None) -> str:
    """The plain summary for the owner (the ticket shape): no file path, no line reference."""

    compare = f"compared with the earlier run of the same set: {verdict}" if verdict else "no earlier run of the same set to compare with"
    return "\n".join([
        "## For the human",
        f"- **What:** a benchmark run of the {name} set on {job.host} ended ok in {_duration(job)}.",
        "- **Why:** the run queue's own report of a finished whole-set run.",
        "- **Plan:** the reader reviews the result and closes the issue with a verdict; a defect found becomes a sub-issue.",
        f"- **Result:** {at_or_above} of {refs} references at or above the author, {errors} audit errors in total, {compare}.",
        "- **Undo:** two-way door (nothing to undo: a report); touches nobody.",
        "",
    ])
