"""Building blocks for the runs daemon restarting itself at a job boundary (issue #340).

`RestartWatch` answers "did the checkout's HEAD move by a commit that touches the daemon's own code?";
`respawn` starts the daemon again with the same argv; `wait_for_predecessor` lets the new daemon wait until
the old one has exited.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from junkroan.runs.bounded import run_bounded

WATCHED_PATHS: tuple[str, ...] = (
    "src/junkroan/runs",
    "scripts/runs.py",
    "config/hosts.json",
    "scripts/run_queue.py",  # #920: loaded by path at runtime (daemon.run_queue), so a fix there never reached a running daemon
    "scripts/compare_runs.py",  # #920: loaded by path (run_issue._compare_runs)
    "scripts/benchmark.py",  # #920: imported through sys.path by weekly_cut / weekly_fillers
    "tools/agentops",  # #491: anomalies.py imports tools.agentops.dispatch.find_claude_exe, so a fix there must restart the daemon
)
REPLACES_ENV = "JUNKROAN_DAEMON_REPLACES"

GitRunner = Callable[[list[str]], str]

#: A network call of git cannot sit on a dead network for ever (#521); an already set value wins.
GIT_SSH_COMMAND = "ssh -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2"


def git_env() -> dict[str, str]:
    """The inherited environment plus ``GIT_SSH_COMMAND`` unless the environment already has one."""

    env = dict(os.environ)
    env.setdefault("GIT_SSH_COMMAND", GIT_SSH_COMMAND)
    return env


def git_runner(repo: Path, *, timeout: float = 30.0) -> GitRunner:
    """A runner of `git -C repo <args>` returning stdout; raises on failure."""

    def run(args: list[str]) -> str:
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        return run_bounded(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
            env=git_env(),
            **kwargs,
        ).stdout

    return run


class RestartWatch:
    def __init__(
        self,
        start: str,
        git: GitRunner,
        *,
        paths: Sequence[str] = WATCHED_PATHS,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.start = start
        self._git = git
        self._paths = tuple(paths)
        self._log = log
        self._clean_head: str | None = None

    @classmethod
    def from_repo(cls, repo: Path, *, log: Callable[[str], None] | None = None) -> "RestartWatch":
        git = git_runner(repo)
        return cls(git(["rev-parse", "HEAD"]).strip(), git, log=log)

    def due(self) -> tuple[str, str] | None:
        """(start, head) when HEAD moved by a commit touching a watched path, else None. Never raises."""
        try:
            head = self._git(["rev-parse", "HEAD"]).strip()
            if head == self.start or head == self._clean_head:
                return None
            out = self._git(["diff", "--name-only", f"{self.start}..{head}", "--", *self._paths])
            if any(line.strip() for line in out.splitlines()):
                return (self.start, head)
            self._clean_head = head
            return None
        except Exception as exc:
            if self._log is not None:
                self._log(f"restart watch: git failed ({exc!r})")
            return None


FOLLOW_MAIN_SECONDS = 300.0
#: Failed follow-main steps in a row (the checkout, not the fetch) before `follow_main_failed` is raised (#861).
FOLLOW_MAIN_FAIL_LIMIT = 3


def _git_error_line(exc: BaseException) -> str:
    """Git's own stderr of a failed call (its non-empty lines joined, at most 300 chars), else the exception text."""

    err = getattr(exc, "stderr", None)
    if isinstance(err, bytes):
        err = err.decode("utf-8", "replace")
    lines = [line.strip() for line in str(err or "").splitlines() if line.strip()]
    return " | ".join(lines)[:300] if lines else repr(exc)


class FollowMain:
    """Keeps a detached daemon checkout on `origin/main` (#444).

    Active only when this repo root IS the host's explicit `daemon_repo_path` and its HEAD is detached;
    the PC daemon (main checkout, a branch) is never moved. `step()` is for the job boundary: fetch (at most
    once per `every` seconds), then `checkout --detach origin/main` when it differs from HEAD. Never raises.
    """

    def __init__(
        self,
        repo: Path,
        daemon_repo_path: str | None,
        git: GitRunner,
        *,
        log: Callable[[str], None] | None = None,
        every: float = FOLLOW_MAIN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._git = git
        self._log = log
        self._every = every
        self._clock = clock
        self._last: float | None = None
        #: The current streak of failed steps: how many, the wall time of its first (its id), git's last error line.
        self.fail_count = 0
        self.streak_id: str | None = None
        self.last_error = ""
        self.is_daemon_checkout = bool(daemon_repo_path) and (
            os.path.normcase(os.path.realpath(str(repo))) == os.path.normcase(os.path.realpath(str(daemon_repo_path)))
        )

    def step(self) -> bool:
        """True when HEAD was moved to `origin/main`."""
        if not self.is_daemon_checkout:
            return False
        try:
            try:
                self._git(["symbolic-ref", "-q", "HEAD"])
                return False  # a branch is checked out
            except subprocess.CalledProcessError:
                pass  # detached
            now = self._clock()
            if self._last is not None and now - self._last < self._every:
                return False
            self._last = now
            try:
                self._git(["fetch", "origin"])
            except Exception as exc:
                if self._log is not None:
                    self._log(f"follow main: git fetch failed ({exc!r}); staying on the old HEAD")
                return False
            head = self._git(["rev-parse", "HEAD"]).strip()
            target = self._git(["rev-parse", "origin/main"]).strip()
            if head == target:
                self._reset_streak()
                return False
            self._git(["checkout", "--detach", "origin/main"])
            self._reset_streak()
            if self._log is not None:
                self._log(f"follow main: {head[:12]} -> {target[:12]}")
            return True
        except Exception as exc:
            self.fail_count += 1
            if self.streak_id is None:
                self.streak_id = str(int(time.time()))
            self.last_error = _git_error_line(exc)
            if self._log is not None:
                self._log(f"follow main: git failed ({exc!r})")
            return False

    def _reset_streak(self) -> None:
        self.fail_count = 0
        self.streak_id = None
        self.last_error = ""

    def streak(self) -> tuple[str, int, str] | None:
        """(streak id, failures so far, git's error line) once the streak reached the limit, else None."""

        if self.fail_count >= FOLLOW_MAIN_FAIL_LIMIT and self.streak_id is not None:
            return (self.streak_id, self.fail_count, self.last_error)
        return None


def _stream_or_devnull(stream: Any) -> Any:
    try:
        stream.fileno()
        return stream
    except Exception:
        return subprocess.DEVNULL


def respawn(
    argv: Sequence[str] | None = None,
    *,
    executable: str | None = None,
    popen: Callable[..., Any] = subprocess.Popen,
    pid: int | None = None,
) -> int:
    """Start a detached copy of this process; returns the child's pid."""
    cmd = [executable or sys.executable, *(argv if argv is not None else sys.argv)]
    env = dict(os.environ)
    env[REPLACES_ENV] = str(pid if pid is not None else os.getpid())
    kwargs: dict[str, Any] = {
        "cwd": os.getcwd(),
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": _stream_or_devnull(sys.stdout),
        "stderr": _stream_or_devnull(sys.stderr),
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return popen(cmd, **kwargs).pid


def wait_for_predecessor(
    env: Mapping[str, str],
    pid_alive: Callable[[int], bool],
    *,
    timeout: float = 60.0,
    poll: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int | None:
    """Wait until the pid named in env[REPLACES_ENV] is gone (or `timeout`); returns that pid, or None."""
    try:
        pid = int(env[REPLACES_ENV])
    except (KeyError, ValueError):
        return None
    deadline = clock() + timeout
    while pid_alive(pid) and clock() < deadline:
        sleep(poll)
    return pid
