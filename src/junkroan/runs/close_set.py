"""Issue #958 unit 4: which programs close at the end of "sleep" (a pure rule and a psutil reader).

``close_set`` decides from a snapshot alone; it kills nothing and reads no file. A process is KEPT when
any rule holds, else CLOSED:

1. its session id is not the console session's;
2. its owner is not the logged-on user (an owner that could not be read is kept too);
3. its executable lies under ``%SystemRoot%`` (an executable that could not be read is kept too);
4. it is the runs daemon, ``sshd`` or a descendant of either, or the calling process or one of its parents;
5. it owns a listening TCP port, or its name is in the ``keep`` list.

``read_snapshot`` returns ``None`` on any read failure, so the caller never acts on a partial snapshot.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from junkroan.runs.load_groups import _session_of

_NO_SESSION = -1  # a session id that could not be read: never the console session, so rule 1 keeps it
_NO_CONSOLE_SESSION = 0xFFFFFFFF  # WTSGetActiveConsoleSessionId: no console session attached


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    name: str
    exe: str  # full path, may be ""
    session: int
    owner: str  # account name, "DOMAIN\\user" or "user"
    ports: tuple[int, ...] = ()  # listening TCP ports the process owns


def _account(owner: str) -> str:
    return owner.rsplit("\\", 1)[-1].strip().lower()


def _norm_path(path: str) -> str:
    return path.replace("/", "\\").rstrip("\\").lower()


def _name(name: str) -> str:
    low = name.strip().lower()
    return low[:-4] if low.endswith(".exe") else low


def _lineage(proc: Proc, by_pid: dict[int, Proc]) -> set[int]:
    """The pid of ``proc`` and of its parents as far as the snapshot names them (cycle-safe)."""

    out = {proc.pid}
    ppid = proc.ppid
    while ppid not in out:
        out.add(ppid)
        parent = by_pid.get(ppid)
        if parent is None:
            break
        ppid = parent.ppid
    return out


def _under(path: str, root: str) -> bool:
    return bool(root) and (path == root or path.startswith(root + "\\"))


def close_set(
    processes: Sequence[Proc],
    *,
    console_session: int,
    user: str,
    system_root: str,
    protected_pids: Collection[int],
    keep: Collection[str],
    self_pid: int,
) -> tuple[list[Proc], list[tuple[Proc, str]]]:
    """Split ``processes`` into (closed, kept_with_rule), both in input order."""

    by_pid: dict[int, Proc] = {}
    for proc in processes:
        by_pid.setdefault(proc.pid, proc)
    protected = set(protected_pids)
    keep_names = {_name(k) for k in keep}
    user_account = _account(user)
    root = _norm_path(system_root)
    if self_pid in by_pid:
        self_tree = _lineage(by_pid[self_pid], by_pid)
    else:
        self_tree = {self_pid}

    closed: list[Proc] = []
    kept: list[tuple[Proc, str]] = []
    for proc in processes:
        reason = _keep_reason(proc, by_pid, self_tree, console_session, user_account, root, protected, keep_names)
        if reason is None:
            closed.append(proc)
        else:
            kept.append((proc, reason))
    return closed, kept


def _keep_reason(
    proc: Proc,
    by_pid: dict[int, Proc],
    self_tree: set[int],
    console_session: int,
    user_account: str,
    root: str,
    protected: set[int],
    keep_names: set[str],
) -> str | None:
    if proc.pid in self_tree:
        return "rule 4: the daemon itself"
    if proc.session != console_session:
        return "rule 1: not the console session"
    owner = _account(proc.owner)
    if not owner:
        return "rule 2: owner is not the user (owner not read)"
    if owner != user_account:
        return "rule 2: owner is not the user"
    exe = _norm_path(proc.exe)
    if not exe:
        return "rule 3: under %SystemRoot% (exe not read)"
    if _under(exe, root):
        return "rule 3: under %SystemRoot%"
    if _lineage(proc, by_pid) & protected:
        return "rule 4: the runs daemon / sshd or a descendant"
    if proc.ports:
        return "rule 5: listens on a port"
    if _name(proc.name) in keep_names:
        return "rule 5: in the keep list"
    return None


def read_snapshot() -> list[Proc] | None:
    """Every process with its owner, path, session and listening TCP ports; ``None`` on any read failure."""

    try:
        import psutil

        ports: dict[int, list[int]] = {}
        for conn in psutil.net_connections(kind="tcp"):
            if conn.status == psutil.CONN_LISTEN and conn.pid is not None and conn.laddr:
                ports.setdefault(int(conn.pid), []).append(int(conn.laddr.port))
        out: list[Proc] = []
        for handle in psutil.process_iter(["pid", "ppid", "name", "exe", "username"]):
            info = handle.info
            pid = int(info["pid"])
            session = _session_of(pid)
            out.append(
                Proc(
                    pid=pid,
                    ppid=int(info["ppid"] or 0),
                    name=info["name"] or "",
                    exe=info["exe"] or "",
                    session=_NO_SESSION if session is None else int(session),
                    owner=info["username"] or "",
                    ports=tuple(dict.fromkeys(ports.get(pid, ()))),
                )
            )
        return out
    except Exception:
        return None


def console_session_id() -> int | None:
    """The interactive console's session id (Win32 ``WTSGetActiveConsoleSessionId``), ``None`` elsewhere."""

    if sys.platform != "win32":
        return None
    try:
        import ctypes

        sid = int(ctypes.windll.kernel32.WTSGetActiveConsoleSessionId())
    except Exception:
        return None
    return None if sid == _NO_CONSOLE_SESSION else sid


def protected_pids(procs: Iterable[Proc], daemon_pid: int | None = None) -> set[int]:
    """The pids of every ``sshd`` process plus the runs daemon's pid (read by the caller, see ``daemon_pid``)."""

    out = {proc.pid for proc in procs if _name(proc.name) == "sshd"}
    if daemon_pid is not None:
        out.add(int(daemon_pid))
    return out


def plan_close(
    host: str,
    keep: Iterable[str] = (),
    *,
    reader=None,
    console=None,
    user: str | None = None,
    system_root: str | None = None,
    daemon: int | None = None,
    self_pid: int | None = None,
) -> tuple[list[Proc], list[tuple[Proc, str]]] | None:
    """The close set of this machine now: ``(closed, kept_with_rule)``, or ``None`` when the snapshot or the
    console session cannot be read (the caller then closes nothing). Every argument is a seam for tests; the
    defaults read the real machine (``read_snapshot``, the console session, the logged-on user, ``%SystemRoot%``,
    the daemon's status file and this process). A seam left ``None`` is resolved at call time."""

    import getpass
    import os

    procs = (reader or read_snapshot)()
    if procs is None:
        return None
    console_session = (console or console_session_id)()
    if console_session is None:
        return None
    root = system_root if system_root is not None else os.environ.get("SystemRoot", "")
    if not root:
        return None  # without %SystemRoot% rule 3 would keep nothing of Windows' own
    me = self_pid if self_pid is not None else os.getpid()
    status_pid = daemon if daemon is not None else daemon_pid(host)
    protected = protected_pids(procs, status_pid)
    protected.add(me)
    return close_set(
        procs,
        console_session=console_session,
        user=user if user is not None else getpass.getuser(),
        system_root=root,
        protected_pids=protected,
        keep=list(keep),
        self_pid=me,
    )


def daemon_pid(host: str) -> int | None:
    """The ``pid`` key of ``artifacts/runs/daemon-<host>.json`` (the daemon's status file), ``None`` if unreadable."""

    from junkroan.runs import hosts as runs_hosts

    try:
        data = json.loads(Path(runs_hosts.daemon_status_path(host)).read_text(encoding="utf-8"))
        return int(data["pid"])
    except Exception:
        return None
