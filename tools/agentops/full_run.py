"""`python -m tools.agentops full-run [--commit <sha>] [--detach]` (#690): the full suite on main, after a
merge ran only the tests its change can affect.

One full run under pytest-testmon plus the audit-hook plugin (``test_reads_plugin``) in its own worktree,
then the selection map (``var/agentops/test_map/``: ``testmondata``, ``reads/``, ``meta.json``) is
replaced. Green: ``last_green_commit`` moves to the commit. Red (after the same one re-check of the failed
ids the merge does): the map is still replaced, ``last_green_commit`` stays, and ONE ``needs-triage``
issue names the failing ids and the branches landed since the last green commit. Nothing is reverted.

One run at a time (``var/agentops/full_run.lock``). A call during a run writes ``full_run.pending`` and
returns 0; the running run starts one more on the then-current ``origin/main`` when it ends. The run never
waits for the merge line: the merge suite goes first by priority (``run_suite_by_merge_state``) and by its
worker formula, which takes this run's CPU out of the busy share. Its pytest tree runs at Normal and
drops to BELOW_NORMAL only while a merge suite runs (#775: at BELOW_NORMAL beside a full machine it stood
at 0 tests for minutes); ``TreePriorityWatcher`` re-sets the tree when that state changes.
"""

from __future__ import annotations

import contextlib
import json
import re
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

from . import merge as _merge
from .suite_worktree import FULL_WORKTREE, ensure_suite_worktree
from .suite_host import parse_skipped
from .test_select import load_testmon, map_dir, read_meta, write_meta
from .gh_call import run_gh
from .util import human_duration, no_window_flags, pid_alive

ROOT = _merge.ROOT
PLUGIN = "tools.agentops.test_reads_plugin"
PLAN_PLUGIN = "tools.agentops.suite_plan_plugin"
TESTMON_FLAGS = f"--testmon --testmon-forceselect -p {PLUGIN} -p {PLAN_PLUGIN} --durations=25"
MAX_IDS_IN_ISSUE = 40
MAX_BRANCHES_IN_ISSUE = 60


def _agentops(root: Path) -> Path:
    return root / "var" / "agentops"


def lock_path(root: Path) -> Path:
    return _agentops(root) / "full_run.lock"


def pending_path(root: Path) -> Path:
    return _agentops(root) / "full_run.pending"


def hold_path(root: Path) -> Path:
    return _agentops(root) / "full_run_hold.json"


def _read_hold_since(root: Path) -> float | None:
    try:
        since = json.loads(hold_path(root).read_text(encoding="utf-8")).get("since")
        return float(since) if since is not None else None
    except Exception:
        return None


def _write_hold_since(root: Path, since: float | None) -> None:
    """#907: the first-wait clock of the one-shot full run; only ever rewritten (`null` on a go), never removed."""
    path = hold_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"since": since}), encoding="utf-8")


def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


# -- the lock and the pending flag -----------------------------------------------------------------

def try_lock(root: Path) -> bool:
    """Take ``full_run.lock`` (pid + start); a lock whose pid is dead is taken over."""
    path = lock_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder = json.loads(path.read_text(encoding="utf-8"))
                pid = holder.get("pid")
            except (OSError, ValueError, AttributeError):
                pid = None
            if pid is not None and pid != os.getpid() and pid_alive(pid):
                return False
            try:
                path.unlink()
            except OSError:
                return False
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "started": _iso()}, fh)
        return True
    return False


def restart_lock(root: Path) -> None:
    """Rewrite the held lock's `started` to now (a later run of the same row)."""
    try:
        lock_path(root).write_text(json.dumps({"pid": os.getpid(), "started": _iso()}), encoding="utf-8")
    except OSError:
        pass


def unlock(root: Path) -> None:
    try:
        lock_path(root).unlink()
    except OSError:
        pass


def write_pending(root: Path, commit: str) -> None:
    pending_path(root).parent.mkdir(parents=True, exist_ok=True)
    pending_path(root).write_text(commit, encoding="utf-8")


def take_pending(root: Path) -> str | None:
    """The commit the pending file asks for (None when there is no file); the file is deleted."""
    p = pending_path(root)
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        p.unlink()
    except OSError:
        pass
    return text or "origin/main"


# -- git -------------------------------------------------------------------------

def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", creationflags=no_window_flags())


def current_main(root: Path = ROOT) -> str:
    """``origin/main`` after a fetch."""
    _git(root, "fetch", "origin", "main")
    res = _git(root, "rev-parse", "origin/main")
    if res.returncode != 0:
        raise RuntimeError(f"git rev-parse origin/main failed: {res.stderr.strip()}")
    return res.stdout.strip()


def landed_since(root: Path, last_green: str | None, commit: str) -> list[str]:
    """First-parent merge subjects in ``last_green..commit`` (git is exact)."""
    if not last_green:
        return []
    res = _git(root, "log", "--first-parent", "--merges", "--format=%s", f"{last_green}..{commit}")
    if res.returncode != 0:
        return [f"(git log {last_green[:8]}..{commit[:8]} failed: {res.stderr.strip()[:120]})"]
    return [l for l in res.stdout.splitlines() if l.strip()]


# -- the issue --------------------------------------------------------------------------------------

def issue_title(ids: list[str]) -> str:
    first = ids[0] if ids else "the suite failed"
    return f"Full suite on main is red: {first}" + (f" (+{len(ids) - 1} more)" if len(ids) > 1 else "")


def issue_body(commit: str, ids: list[str], branches: list[str], last_green: str | None, out_path: Path) -> str:
    n = len(ids)
    shown = ids[:MAX_IDS_IN_ISSUE]
    lines = [
        "## For the human",
        f"- **What:** the full test suite run on main after a landing is red: {n} failing test{'s' if n != 1 else ''}.",
        "- **Why:** a merge runs only the tests its change can affect, so a breakage outside that reach shows only here.",
        "- **Plan:** find the landing that broke it from the list below and fix or revert it; nothing was reverted automatically.",
        f"- **Result:** the full run on the same commit is green; shown by the next full run on main (now {n} failing).",
        "- **Undo:** two-way door (one revert); touches the merge line's reading of the test map.",
        "",
        "## For the agent",
        f"Commit under test: `{commit}`. Suite output: `{out_path}`.",
        "",
        f"Failing after one re-check ({n}):",
        *[f"- `{i}`" for i in shown],
    ]
    if n > len(shown):
        lines.append(f"- ... and {n - len(shown)} more (see the output file)")
    lines.append("")
    if last_green:
        lines.append(f"Landed since the last green full run (`{last_green}`), newest first ({len(branches)}):")
        lines += [f"- {b}" for b in branches[:MAX_BRANCHES_IN_ISSUE]] or ["- none (nothing landed in that range)"]
        if len(branches) > MAX_BRANCHES_IN_ISSUE:
            lines.append(f"- ... and {len(branches) - MAX_BRANCHES_IN_ISSUE} more")
    else:
        lines.append("No previous green run: there is no last green commit to list landings from.")
    lines += ["", "Not in this ticket: reverting a landing; the weekly benchmark."]
    return "\n".join(lines)


def open_issue(gh: Callable[[list[str]], subprocess.CompletedProcess], title: str, body: str) -> bool:
    res = gh(["issue", "create", "--title", title, "--body", body,
              "--label", "needs-triage", "--label", "area:orchestration"])
    return res.returncode == 0


def open_red_tickets(gh: Callable[[list[str]], subprocess.CompletedProcess]) -> list[dict] | None:
    """Open "Full suite on main is red" issues ({number, title, body}); None when the listing fails (#849)."""
    try:
        res = gh(["issue", "list", "--state", "open", "--search", "Full suite on main is red in:title",
                  "--json", "number,title,body", "--limit", "100"])
        if res.returncode != 0:
            return None
        rows = json.loads(res.stdout)
        return [r for r in rows if str(r.get("title", "")).startswith("Full suite on main is red")]
    except Exception:
        return None


_ID_CHARS = re.compile(r"[A-Za-z0-9_\[\]\-.:/]")


def names_id(text: str, test_id: str) -> bool:
    """#851: ``text`` holds ``test_id`` as a whole test id (no id character right before or after it)."""
    start = text.find(test_id)
    while start != -1:
        end = start + len(test_id)
        if (start == 0 or not _ID_CHARS.match(text[start - 1])) and (end == len(text) or not _ID_CHARS.match(text[end])):
            return True
        start = text.find(test_id, start + 1)
    return False


def report_red(gh: Callable[[list[str]], subprocess.CompletedProcess], commit: str, ids: list[str],
               branches: list[str], last_green: str | None, out_path: Path) -> None:
    """#849: one open ticket per failing test. Ids an open ticket names get a comment there, the rest one new ticket."""
    tickets = open_red_tickets(gh) or []
    named: dict[int, list[str]] = {}
    fresh: list[str] = []
    for i in ids:
        hit = next((t for t in tickets if names_id(str(t.get("title", "")) + chr(10) + str(t.get("body") or ""), i)), None)
        if hit is None:
            fresh.append(i)
        else:
            named.setdefault(hit["number"], []).append(i)
    for number, nids in named.items():
        body = issue_body(commit, nids, branches, last_green, out_path)
        body = body.split("## For the agent" + chr(10), 1)[-1]
        gh(["issue", "comment", str(number), "--body",
            "Another red full run names this ticket's failing test." + chr(10) * 2 + body])
    if fresh or not named:
        open_issue(gh, issue_title(fresh), issue_body(commit, fresh, branches, last_green, out_path))


def _real_gh(root: Path) -> Callable[[list[str]], subprocess.CompletedProcess]:
    def run(args: list[str]) -> subprocess.CompletedProcess:
        return run_gh(args, cwd=root)
    return run


# -- the map ----------------------------------------------------------------------------------------

def swap_map(root: Path, new_dir: Path) -> None:
    """``new_dir`` becomes ``var/agentops/test_map/``: a reader sees the old map or the new one, never half
    of either (the old directory is renamed away, then the new one renamed in)."""
    target = map_dir(root)
    old = target.with_name(f"{target.name}.old-{os.getpid()}")
    if target.exists():
        os.replace(target, old)
    os.replace(new_dir, target)
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)  # a plain directory of our own files, no junctions


# -- priority by day (#839) -------------------------------------------------------------------------

def is_day_now() -> bool:
    """True in the budget's "day" period (mode normal 08:00-01:00; play is always day). The env var
    ``JUNKROAN_FORCE_PERIOD=day|night`` overrides it (tests, never the real clock). Never raises: a budget
    that cannot be read answers False (no priority change)."""
    forced = os.environ.get("JUNKROAN_FORCE_PERIOD", "").strip().lower()
    if forced in ("day", "night"):
        return forced == "day"
    try:
        from junkroan.pob import slot_budget
        return slot_budget.load_budget().period == "day"
    except Exception:
        return False


def suite_priority_flags() -> int:
    """``creationflags`` for a pytest tree the system starts: BELOW_NORMAL by day, nothing by night."""
    return getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0) if is_day_now() else 0


# -- priority (#735) --------------------------------------------------------------------------------

@contextlib.contextmanager
def below_normal_priority():
    """The full run's own process runs below normal while the suite is going: a child inherits the
    class at spawn (Windows) or the niceness (POSIX), so pytest and every xdist worker give way to a
    merge suite. The previous priority comes back on exit. merge.py's spawn is not touched."""
    try:
        import psutil
        me = psutil.Process()
        old = me.nice()
        me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            me.nice(old)
        except Exception:
            pass


def run_suite_below_normal(*args, **kwargs):
    """``merge._run_suite`` with the children started below normal priority (#735's primitive; since
    #775 the full run itself goes through ``run_suite_by_merge_state``)."""
    with below_normal_priority():
        return _merge._run_suite(*args, **kwargs)


# -- priority by merge-suite state (#775) -----------------------------------------------------------

WATCH_POLL_S = 5.0


def _classes() -> tuple[int, int]:
    import psutil
    if os.name == "nt":
        return psutil.NORMAL_PRIORITY_CLASS, psutil.BELOW_NORMAL_PRIORITY_CLASS
    return 0, 10


def merge_suite_running() -> bool:
    """The daemon's own signal (#715, ``daemon.py`` ``_suite_seen``): the snapshot's ``merge_suite_pytest``
    of ``load_groups``, read from one live process table; True when at least one top-level pytest runs
    under a merge-suite directory."""
    from junkroan.runs import load_groups
    snap = load_groups.snapshot(load_groups.read_proc_table(), {}, wall=0.0, ncpu=1)
    return int(snap.get("merge_suite_pytest") or 0) >= 1


def own_tree() -> list:
    """Every descendant of this process (the shell wrapper, pytest, xdist workers, their children)."""
    import psutil
    try:
        return psutil.Process().children(recursive=True)
    except Exception:
        return []


class TreePriorityWatcher:
    """Sets the full run's pytest tree to Normal while no merge suite runs and to BELOW_NORMAL while one
    does (#775: at BELOW_NORMAL beside a loaded machine the tree stood at 0 tests for minutes, at Normal it
    moved in every reading). A child inherits its class at spawn, so every poll re-sets the whole tree,
    including processes started since the last poll. A process already below BELOW_NORMAL (Idle: the
    owner's play mode, the daemon's keeper) is left alone. Nothing is restored on exit: the tree ends
    with the suite. When the signal cannot be read the last target stays."""

    def __init__(self, poll_s: float | None = None, *, signal=None, tree=None, day=None) -> None:
        import threading
        self.poll_s = WATCH_POLL_S if poll_s is None else poll_s  # read at call time, so a test can set it
        self.signal = signal or merge_suite_running
        self.tree = tree or own_tree
        self.day = day or is_day_now  # #839: by day the tree is BELOW_NORMAL always
        self.target = None
        self._stop = threading.Event()
        self._thread: "threading.Thread | None" = None
        self._threading = threading

    def step(self) -> None:
        normal, below = _classes()
        try:
            self.target = below if (self.day() or self.signal()) else normal
        except Exception:
            if self.target is None:
                self.target = normal
        for proc in self.tree():
            try:
                current = proc.nice()
                if current in (normal, below) and current != self.target:
                    proc.nice(self.target)
            except Exception:
                pass  # vanished or denied: the next poll reads the tree again

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:
                pass
            self._stop.wait(self.poll_s)

    def start(self) -> None:
        self._thread = self._threading.Thread(target=self._loop, name="full-run-priority", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(self.poll_s + 10)


@contextlib.contextmanager
def tree_priority_watch(**kwargs):
    w = TreePriorityWatcher(**kwargs)
    w.start()
    try:
        yield w
    finally:
        w.stop()


def run_suite_by_merge_state(*args, **kwargs):
    """``merge._run_suite`` with the pytest tree at Normal, and BELOW_NORMAL only while a merge suite runs."""
    with tree_priority_watch():
        return _merge._run_suite(*args, **kwargs)


# -- one run ----------------------------------------------------------------------------------------

def _one_run(commit: str, root: Path, suite_cmd: str, suite_env: dict[str, str], gh, shared) -> int:
    """0 green, 1 red. Raises on setup errors."""
    wt = ensure_suite_worktree(root, commit, shared, lock=None, name=FULL_WORKTREE)
    target = map_dir(root)
    new_dir = target.with_name(f"{target.name}.new-{os.getpid()}")
    if new_dir.exists():
        shutil.rmtree(new_dir, ignore_errors=True)
    (new_dir / "reads").mkdir(parents=True)
    out_path = _agentops(root) / "full_run" / f"{commit[:8]}.out"
    env = {**suite_env, "TESTMON_DATAFILE": str(new_dir / "testmondata"),
           "SELREPLAY_OUT": str(new_dir / "reads"),
           "SUITE_PLAN_FILE": str(out_path) + ".plan.json"}

    if (target / "testmondata").exists():  # the last run's stored durations (the new datafile starts empty)
        env["SUITE_DURATIONS_FILE"] = str(target / "testmondata")

    is_pytest = _merge._is_pytest_command(suite_cmd)
    cmd = f"{suite_cmd} {TESTMON_FLAGS}" if is_pytest else suite_cmd
    cmd = _merge._augmented_suite_cmd(cmd)
    cmd, workers, head = _merge._with_workers(cmd, is_pytest, wt)
    started = time.time()
    stall = _merge.StallWatch(out_path)
    ok, output = run_suite_by_merge_state(cmd, wt, env, out_path, head, stall=stall)
    if stall.reason:  # no test finished for longer than the bound: not a test failure, no map swap, no issue;
        # the run ends here, so the caller frees the lock and starts the pending commit's run as after any run
        shutil.rmtree(new_dir, ignore_errors=True)  # a plain directory of this run's own files
        print(f"full run {commit[:8]}: {stall.reason}")
        return 1
    ids: list[str] = []
    if not ok:
        _count, ids = _merge._parse_pytest_failures(output)
        ids = list(dict.fromkeys(ids))
        if ids:
            with tree_priority_watch():
                ids, _ = _merge._recheck_failed(cmd, ids, wt, env, out_path)
        else:
            ids = [f"(the suite exited non-zero and named no failed test; see {out_path})"]
    green = not ids
    print(f"full run {commit[:8]}: {'green' if green else f'red ({len(ids)} failing)'}, "
          f"suite {human_duration(time.time() - started)}" + (f", {workers} workers" if workers > 1 else ""))

    prev = read_meta(target) or {}
    last_green = commit if green else prev.get("last_green_commit")
    try:
        total = len(load_testmon(str(new_dir / "testmondata"))[1])
    except Exception:
        total = 0
    write_meta(new_dir, {"map_commit": commit, "total": total, "built_at": _iso(),
                         "last_green_commit": last_green,
                         "skipped": parse_skipped(output) if parse_skipped(output) is not None else prev.get("skipped")})
    swap_map(root, new_dir)
    if not green:
        branches = landed_since(root, prev.get("last_green_commit"), commit)
        report_red(gh, commit, ids, branches, prev.get("last_green_commit"), out_path)
    return 0 if green else 1


def run_full(commit: str | None = None, *, root: Path = ROOT, suite_cmd: str | None = None,
             suite_env: dict[str, str] | None = None, gh=None, resolve_head=None, admission=None,
             clock: Callable[[], float] = time.time) -> int:
    """0 = green (or queued behind a running run, or held back by a busy PC: #898), 1 = red.

    ``admission``: a callable returning a ``slot_budget.Admission`` (default ``slot_budget.admission_now``); the
    check runs before the lock, only here (the merge's own suite run never goes through it); an error means go."""
    try:
        if admission is None:
            from junkroan.pob.slot_budget import admission_now as admission
        import inspect
        from .core_settings import load as _load_settings

        now = clock()
        since = _read_hold_since(root)
        cap = _load_settings().get("full_run_admission_hold_cap_s")
        cap = float(cap) if cap is not None else None
        if "waited_s" in inspect.signature(admission).parameters:
            verdict = admission(waited_s=0.0 if since is None else max(0.0, now - since), hold_cap_s=cap)
        else:
            verdict = admission()
        if not verdict.go:
            if since is None:
                _write_hold_since(root, now)
            print(f"full run not started: {verdict.line()}")
            return 0
        _write_hold_since(root, None)
        if getattr(verdict, "reason", None) == "hold cap":
            print(f"full run started by hold cap: {verdict.line()}")
    except Exception:
        pass
    resolve_head = resolve_head or (lambda: current_main(root))
    gh = gh or _real_gh(root)
    commit = commit or resolve_head()
    _merge.wait_while_held()  # #779: in play no full run starts; the request waits for normal
    if not try_lock(root):
        write_pending(root, commit)
        print(f"a full run is already going; {commit[:8]} is pending")
        return 0
    os.environ["JUNKROAN_POB_NOT_STEPPED_DOWN"] = "1"  # #775: its worker-count probes do not count PoB's cores as free
    try:
        rc = 0
        while True:
            restart_lock(root)  # #745: `started` is this run's, not the first of the row
            cmd = suite_cmd or _merge.resolve_suite_cmd(None)
            env = suite_env if suite_env is not None else _merge.resolve_suite_env()
            rc = _one_run(commit, root, cmd, env, gh, _merge.resolve_suite_shared())
            if take_pending(root) is None:
                return rc
            nxt = resolve_head()
            if nxt == commit:
                return rc
            commit = nxt
    finally:
        os.environ.pop("JUNKROAN_POB_NOT_STEPPED_DOWN", None)
        unlock(root)


# -- CLI --------------------------------------------------------------------------------------------

def add_subparser(sub) -> None:
    p = sub.add_parser("full-run", help="the full suite on main under testmon; rebuilds the test map (#690)")
    p.add_argument("--commit", help="the commit to run (default: origin/main after a fetch)")
    p.add_argument("--detach", action="store_true",
                   help="run as a process no session's shell holds (windowless); result file as for merge --detach")


def run_full_run_command(args) -> int:
    if getattr(args, "detach", False):
        from .detach import run_detach_command
        return run_detach_command(args, list(sys.argv[1:]))
    return run_full(args.commit)


def register(core) -> None:
    """A local module of this repo (``local_modules`` of the settings file), not part of the core."""
    core.command("full-run", add_subparser, run_full_run_command, after="merge-status")
