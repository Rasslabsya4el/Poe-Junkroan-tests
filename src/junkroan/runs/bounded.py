"""``subprocess.run`` whose timeout really bounds the call (#521).

``subprocess.run(capture_output=True, timeout=t)`` kills only the direct child on TimeoutExpired;
on Windows, Git for Windows' cmd git.exe wrapper dies while its children ``git.exe`` + ``ssh.exe``
keep the inherited pipes, so the following ``communicate()`` waits for ever. ``run_bounded`` kills the
whole tree and drains the pipes with a deadline of its own.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Callable, Sequence

from junkroan.runs.stopper import taskkill_tree

#: #998 row 1: the kill path of a timed-out call waits at most KILL_SECONDS for taskkill, KILL_GONE_SECONDS
#: for the pid check after a nonzero taskkill exit, and DRAIN_SECONDS for the pipes: 9 s in all, so one call
#: takes at most its own timeout + 10 s. A process still alive after that is abandoned, never waited for.
KILL_SECONDS = 4.0
KILL_GONE_SECONDS = 2.0
DRAIN_SECONDS = 3.0


def _kill_tree_on_budget(pid: int) -> Any:
    """`taskkill_tree` with this module's kill budget (#998 row 1)."""

    return taskkill_tree(pid, timeout=KILL_SECONDS, gone_wait=KILL_GONE_SECONDS)


#: Kills a pid's whole tree; replaced by tests.
TREE_KILLER: Callable[[int], Any] = _kill_tree_on_budget


def run_bounded(argv: Sequence[str], *, timeout: float, **kwargs: Any) -> subprocess.CompletedProcess:
    """``subprocess.run(argv, timeout=timeout, **kwargs)`` with the whole process tree killed on timeout."""

    inp = kwargs.pop("input", None)
    capture = kwargs.pop("capture_output", False)
    check = kwargs.pop("check", False)
    if capture:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    if inp is not None:
        kwargs["stdin"] = subprocess.PIPE
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs.setdefault("start_new_session", True)
    proc = subprocess.Popen(list(argv), **kwargs)
    try:
        out, err = proc.communicate(inp, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            TREE_KILLER(proc.pid)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            out, err = proc.communicate(timeout=DRAIN_SECONDS)
        except Exception:
            out, err = exc.stdout, exc.stderr
            for pipe in (proc.stdout, proc.stderr, proc.stdin):
                try:
                    if pipe:
                        pipe.close()
                except Exception:
                    pass
        raise subprocess.TimeoutExpired(proc.args, timeout, output=out, stderr=err) from None
    except BaseException:
        try:
            TREE_KILLER(proc.pid)
        except Exception:
            pass
        raise
    rc = proc.returncode
    if check and rc:
        raise subprocess.CalledProcessError(rc, proc.args, output=out, stderr=err)
    return subprocess.CompletedProcess(proc.args, rc, out, err)
