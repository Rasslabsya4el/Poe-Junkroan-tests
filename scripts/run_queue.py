"""Run the benchmark / search commands queued in artifacts/runs/queue.txt one after another, so the
machine never idles between runs (ROADMAP Phase 7, autonomy protocol).

    python scripts/run_queue.py [--after-pid N [--adopt NAME]] [--queue artifacts/runs/queue.txt]

The queue file holds one command per line (`#` comments and blank lines ignored). The first
unconsumed line is taken, marked consumed in place (prefixed with `done <stamp> `), and run with
stdout+stderr into artifacts/runs/<stamp>-<tag>.out; then the file is read again, so lines appended
while a run goes are picked up. The runner exits when the queue is empty for 10 minutes. Launch it
detached (PowerShell Start-Process); `--after-pid` waits for another process (a running benchmark) to
end first, and `--adopt NAME` writes that run's end line for it (a runner replaced mid-run). The
runner's own log: artifacts/runs/queue.log.

Every long command runs from a snapshot of the code: a detached git worktree of HEAD under
snapshots/<name> at the repo root (new snapshots; older ones under artifacts/runs/snap/<name> are dropped
by their old path), with `var`, `artifacts` and `vendor` reached through directory
junctions to the live checkout, removed when the run ends. 2026-09-18, speed-both: a merge landed
on main seven minutes into the run; the benchmark's worker processes (old code, alive for hours)
re-read the merged `rails_default.json` at every next build, met a floor whose derived stat their
code could not produce, and optimized 13 of 18 builds against an infinite violation. Short scripts
(`compare_runs.py`, which may revert on main) run from the live checkout. A line that starts with
`@<commit> ` snapshots that commit instead of HEAD: a proof of one change runs on the same code as
its baseline plus that change, whatever landed on main since.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
RUNS = ROOT / "artifacts" / "runs"
SNAPSHOTS = ROOT / "snapshots"  # outside artifacts/: a junction to artifacts/ inside it would loop
SHARED_DIRS = ("var", "artifacts", "vendor")  # untracked, reached from the snapshot through junctions
LIVE_SCRIPTS = ("compare_runs.py",)  # act on the live checkout (git revert), never snapshotted


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with (RUNS / "queue.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


PID_TIMEOUT_S = 15   # #998: tasklist bounded, so one pass of the daemon never freezes on it
GIT_TIMEOUT_S = 30   # #998: every git / mklink call of a snapshot bounded


def pid_alive(pid: int) -> bool:
    """A timeout or an unreadable tasklist counts as ALIVE: no job is ended on a failed read (#998)."""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, timeout=PID_TIMEOUT_S).stdout  # bytes: the console code page is not UTF-8
    except Exception:
        return True
    return str(pid) in (out or b"").decode("ascii", "ignore")


def take_next(queue: Path) -> str | None:
    if not queue.is_file():
        return None
    lines = queue.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("done "):
            continue
        lines[i] = f"done {datetime.now():%Y%m%d-%H%M} {s}"
        queue.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return s
    return None


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT_S)


def split_pin(line: str) -> tuple[str, str]:
    """(commit, command) of a queue line: `@<commit> <command>` pins the snapshot, else HEAD."""

    m = re.match(r"@(\S+)\s+(.*)", line)
    return (m.group(1), m.group(2)) if m else ("HEAD", line)


def junction_target_refusal(link: Path, target: Path, worktree: Path) -> str:
    """Same check as tools/agentops/worktree.py check_junction_target (this script imports nothing from
    tools/): a message naming both paths when the target lies under the worktree or the link, or the
    link lies under its own target (a loop for every recursive walk), else ''."""

    def norm(p: Path) -> str:
        return os.path.normcase(os.path.realpath(p))

    t = norm(target)
    link_path = os.path.normcase(os.path.join(os.path.realpath(link.parent), link.name))  # not realpath(link): an existing junction would resolve into its target
    for outer in (norm(worktree), link_path):
        if t == outer or t.startswith(outer.rstrip("\\/") + os.sep):
            return f"junction {link} -> {target} refused: the target lies inside {outer}"
    if link_path.startswith(t.rstrip("\\/") + os.sep):
        return (f"junction {link} -> {target} refused: the link lies inside its own target {target} "
                f"(a loop for every recursive walk)")
    return ""


def _walk(root: Path):
    """Every entry path under `root`; a junction or symlink is yielded once and never descended."""

    stack = [root]
    while stack:
        with os.scandir(stack.pop()) as it:
            entries = list(it)
        for e in entries:
            p = Path(e.path)
            yield p
            if os.path.isjunction(p) or e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append(p)


LAST_SNAPSHOT_FAILURE: str | None = None   # why the last make_snapshot returned None (#756)


def make_snapshot(name: str, commit: str = "HEAD") -> tuple[Path, str] | None:
    """A detached worktree of `commit` (HEAD unless the queue line pins one) for one run, or None
    (the run then uses the live checkout). A git call that times out (#998) is a failed snapshot."""

    global LAST_SNAPSHOT_FAILURE
    LAST_SNAPSHOT_FAILURE = None
    try:
        return _make_snapshot(name, commit)
    except subprocess.TimeoutExpired:
        LAST_SNAPSHOT_FAILURE = f"pin {commit}: git timed out after {GIT_TIMEOUT_S} s"
        log(f"snapshot failed for {name}: {LAST_SNAPSHOT_FAILURE}; running from the live checkout")
        return None


def _make_snapshot(name: str, commit: str) -> tuple[Path, str] | None:
    global LAST_SNAPSHOT_FAILURE
    snap = SNAPSHOTS / name
    SNAPSHOTS.mkdir(parents=True, exist_ok=True)
    def present() -> bool:
        # #889: `rev-parse --short <full sha>` echoes an absent sha back; only --verify <c>^{commit} knows
        res = _git("rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}")
        return res.returncode == 0 and bool(res.stdout.strip())

    head = _git("rev-parse", "--short", commit).stdout.strip() if present() else ""
    if not head and commit != "HEAD":
        # #756 rule 2: the pin may travel through origin under a ref of its own; one bounded fetch
        from junkroan.runs import pin_ref
        try:
            pin_ref.fetch_pin(ROOT, commit)
        except Exception as exc:
            log(f"snapshot {name}: pin fetch failed ({exc!r})")
        head = _git("rev-parse", "--short", commit).stdout.strip() if present() else ""
    if not head:
        LAST_SNAPSHOT_FAILURE = f"pin {commit} is not on this host"
        log(f"snapshot failed for {name}: unknown commit {commit}; running from the live checkout")
        return None
    res = _git("worktree", "add", "--detach", "--quiet", str(snap), commit)
    if res.returncode != 0 or not snap.is_dir():
        LAST_SNAPSHOT_FAILURE = f"pin {commit}: git worktree add failed: {res.stderr.strip()[:200]}"
        log(f"snapshot failed for {name}: {res.stderr.strip()[:200]}; running from the live checkout")
        return None
    for d in SHARED_DIRS:
        if (ROOT / d).is_dir() and not (snap / d).exists():
            bad = junction_target_refusal(snap / d, ROOT / d, snap)
            if bad:
                LAST_SNAPSHOT_FAILURE = f"pin {commit}: junction {d} refused: {bad}"
                log(f"snapshot {name}: {bad}; dropped")
                drop_snapshot(snap)
                return None
            try:
                j = subprocess.run(["cmd", "/c", "mklink", "/J", str(snap / d), str(ROOT / d)], capture_output=True, timeout=GIT_TIMEOUT_S)
                failed, why = j.returncode != 0, (j.stderr or j.stdout or b"").decode("ascii", "ignore").strip()[:120]
            except subprocess.TimeoutExpired:
                failed, why = True, f"timed out after {GIT_TIMEOUT_S} s"
            if failed:
                LAST_SNAPSHOT_FAILURE = f"pin {commit}: mklink /J {d} failed"
                log(f"snapshot {name}: junction {d} failed ({why}); dropped")
                drop_snapshot(snap)
                return None
    return snap, head


SNAP_GIT_TIMEOUT_S = 60  # #998 row 3: one snapshot git call (status, add, diff) waits at most this long


def _snap_git(snap: Path, *args: str) -> subprocess.CompletedProcess:
    """One git call in a snapshot, bounded (#998). A hit is a failed call (rc 1, the stderr says why), so the
    caller reads it the way it reads any failed git call; one log line."""
    from junkroan.runs.bounded import run_bounded  # the tree-killing runner (#521), imported here like pin_ref

    argv = ["git", "-C", str(snap), *args]
    try:
        return run_bounded(argv, timeout=SNAP_GIT_TIMEOUT_S, capture_output=True)
    except subprocess.TimeoutExpired:
        log(f"snapshot {snap.name}: git {args[0] if args else ''} did not answer within {SNAP_GIT_TIMEOUT_S} s; "
            "the call counts as failed")
        return subprocess.CompletedProcess(argv, 1, stdout=b"", stderr=f"timed out after {SNAP_GIT_TIMEOUT_S} s".encode())


def save_snapshot_diff(snap: Path, job_id: str, pin: str = "HEAD") -> Path | None:
    """What a job changed in its snapshot, saved as `artifacts/runs/jobs/<job_id>/snapshot.diff` (a
    `git apply`-able binary diff against `pin`), or None when it changed nothing. The junctioned
    SHARED_DIRS are left out of the status, the staging and the diff. Raises when git fails, so the
    caller can keep the snapshot instead of dropping unsaved work."""

    spec = ["--", ".", *(f":(exclude){d}" for d in SHARED_DIRS)]
    st = _snap_git(snap, "status", "--porcelain", *spec)
    if st.returncode != 0:
        raise RuntimeError(f"git status failed: {st.stderr.decode('utf-8', 'replace').strip()[:200]}")
    changed = [ln[3:].strip() for ln in st.stdout.decode("utf-8", "replace").splitlines() if ln.strip()]
    if not changed:
        return None
    add = _snap_git(snap, "add", "-A", *spec)
    if add.returncode != 0:
        raise RuntimeError(f"git add failed: {add.stderr.decode('utf-8', 'replace').strip()[:200]}")
    diff = _snap_git(snap, "diff", "--binary", "--cached", pin, *spec)
    if diff.returncode != 0:
        raise RuntimeError(f"git diff failed: {diff.stderr.decode('utf-8', 'replace').strip()[:200]}")
    target = RUNS / "jobs" / job_id / "snapshot.diff"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(diff.stdout)
    shown = ", ".join(changed[:10]) + (f", +{len(changed) - 10} more" if len(changed) > 10 else "")
    log(f"job {job_id}: snapshot changed {len(changed)} path(s): {shown}; diff saved to {target}")
    return target


def drop_snapshot(snap: Path) -> None:
    """Junctions go first, as directory entries (the targets stay); the worktree is removed only when
    none is left, so a tree walk can never reach var/ or artifacts/ through one."""

    for d in SHARED_DIRS:
        link = snap / d
        if link.exists():
            try:
                os.rmdir(link)
            except OSError as exc:
                log(f"snapshot {snap.name}: junction {d} not removed ({exc}); worktree kept")
                return
    res = _git("worktree", "remove", "--force", str(snap))
    if res.returncode != 0:
        log(f"snapshot {snap.name}: worktree not removed: {res.stderr.strip()[:200]}")


def wants_snapshot(cmd: str) -> bool:
    return not any(s in cmd for s in LIVE_SCRIPTS)


def is_benchmark_command(cmd: str) -> bool:
    return "benchmark.py" in cmd


def benchmark_run_dir(cmd: str, output: Path, started_at: float) -> Path | None:
    """Find the output directory a benchmark command just wrote, including a failed partial run."""

    if output.is_file():
        for line in reversed(output.read_text(encoding="utf-8", errors="replace").splitlines()):
            if line.startswith("report: "):
                path = Path(line.removeprefix("report: ").strip()).parent
                if path.is_dir():
                    return path

    match = re.search(r"--tag(?:\s+|=)(?:\"([^\"]+)\"|'([^']+)'|(\S+))", cmd)
    tag = next((value for value in match.groups() if value) if match else (), None)
    benchmark_root = ROOT / "artifacts" / "benchmark"
    if not benchmark_root.is_dir():
        return None

    def updated_during_run(path: Path) -> bool:
        return any(
            artifact.is_file() and artifact.stat().st_mtime >= started_at - 2
            for artifact in (path / "results.json", path / "report.md")
        )

    candidates = [
        path for path in benchmark_root.iterdir()
        if path.is_dir() and updated_during_run(path)
        and (tag is None or path.name.endswith(f"-{tag}"))
    ]
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name)) if candidates else None


def archive_benchmark_run(run_dir: Path | None, output: Path) -> int:
    """Copy one completed benchmark's readable artifacts outside the worktree.

    Archival deliberately never raises: a failed backup must not prevent the queue from moving to
    its next run, and it never mutates the source run directory.
    """

    if run_dir is None or not run_dir.is_dir():
        log(f"archive benchmark: run directory missing ({run_dir})")
        return 0

    files = [path for path in (run_dir / "results.json", run_dir / "report.md") if path.is_file()]
    files.extend(sorted(path for path in run_dir.glob("*.pob.txt") if path.is_file()))
    for folder in ("rows", "logs"):
        source = run_dir / folder
        if source.is_dir():
            files.extend(sorted(path for path in _walk(source) if path.is_file()))
    if output.is_file():
        files.append(output)

    archive_root = Path(os.environ.get("JUNKROAN_ARCHIVE") or r"C:\Coding\poe-junkroan-archive")
    destination = archive_root / "benchmark" / run_dir.name
    copied = 0
    try:
        for source in files:
            target = destination / (source.name if source == output else source.relative_to(run_dir))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied += 1
    except OSError as exc:
        log(f"archive benchmark {run_dir.name}: failed after {copied} files: {exc}")
        return 0
    log(f"archive benchmark {run_dir.name}: {copied} files -> {destination}")
    return copied


def out_name(cmd: str, now: datetime, runs_dir: Path) -> str:
    """A unique stem for the run's .out file: `--tag` wins, else the command's own script name
    (compare_runs, gear_transplant, ...), and a `-2`, `-3`, ... suffix when that file already
    exists (two untagged queue lines starting in the same minute overwrote each other, 2026-09-22
    22:23)."""

    stamp = f"{now:%Y%m%d-%H%M}"
    tag = re.search(r"--tag\s+(\S+)", cmd)
    if tag:
        base = tag.group(1)
    else:
        script = re.search(r"scripts[\\/]([^\\/\s]+)\.py", cmd)
        base = script.group(1) if script else "run"
    name = f"{stamp}-{base}"
    if not (runs_dir / f"{name}.out").exists():
        return name
    i = 2
    while (runs_dir / f"{name}-{i}.out").exists():
        i += 1
    return f"{name}-{i}"


def main() -> int:
    # Ctrl+C immunity (2026-09-18): processes created through WMI share one console, and twice a
    # console Ctrl+C (22:27, 01:28: the second at the very second a Codex CLI run started in another
    # WMI-launched chain) killed the runner, the benchmark and its workers at once. The runner ignores
    # SIGINT and every run gets its own process group, so a console Ctrl+C reaches neither.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default=str(RUNS / "queue.txt"))
    ap.add_argument("--after-pid", type=int)
    ap.add_argument("--adopt", help="with --after-pid: the run name whose end line this runner writes when the pid ends")
    ap.add_argument("--idle-minutes", type=float, default=10.0)
    ap.add_argument("--no-snapshot", action="store_true", help="run every command from the live checkout")
    args = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    queue = Path(args.queue)
    if args.after_pid:
        log(f"waiting for pid {args.after_pid} to end")
        while pid_alive(args.after_pid):
            time.sleep(30)
        log(f"pid {args.after_pid} ended")
        if args.adopt:
            log(f"end {args.adopt}: rc adopted (its runner was replaced while it ran)")
    idle_since = time.time()
    while True:
        cmd = take_next(queue)
        if cmd is None:
            if time.time() - idle_since > args.idle_minutes * 60:
                log("queue empty, exiting")
                return 0
            time.sleep(30)
            continue
        idle_since = time.time()
        pin, cmd = split_pin(cmd)
        name = out_name(cmd, datetime.now(), RUNS)
        out = RUNS / f"{name}.out"
        snap = make_snapshot(name, pin) if wants_snapshot(cmd) and not args.no_snapshot else None
        cwd = snap[0] if snap else ROOT
        log(f"start {name}{f' @{snap[1]} (snapshot)' if snap else ''}: {cmd}")
        started_at = time.time()
        # Everything the queue starts (and everything those start in turn) is role "queue" for the
        # machine-wide PoB slot budget: it may take any slot, while agents / workers / pytest are
        # confined to the first `others` (src/junkroan/pob/slot_budget.py).
        env = {**os.environ, "JUNKROAN_POB_ROLE": "queue"}
        with out.open("w", encoding="utf-8") as f:
            rc = subprocess.run(cmd, shell=True, cwd=str(cwd), stdout=f, stderr=subprocess.STDOUT, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode
        log(f"end {name}: rc {rc} -> {out}")
        if is_benchmark_command(cmd):
            archive_benchmark_run(benchmark_run_dir(cmd, out, started_at), out)
        if snap:
            try:
                save_snapshot_diff(snap[0], name, snap[1])
            except Exception as exc:
                log(f"snapshot {name}: diff not saved ({exc}); worktree kept")
                continue
            drop_snapshot(snap[0])


if __name__ == "__main__":
    raise SystemExit(main())
