"""A pinned job's commit travels through origin under a ref of its own (#756 rule 2).

``submit`` pushes the pin to ``refs/junkroan-pins/<full sha>`` when origin does not hold it; the host's
``make_snapshot`` fetches that ref when the pin does not resolve; the daemon deletes it from origin (and
the local copy) when the last job holding the pin has ended. Every git call is bounded (60 s).
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from junkroan.runs.bounded import run_bounded
from junkroan.runs.pass_guard import GUARD

PREFIX = "refs/junkroan-pins/"
TIMEOUT = 60.0
#: #998 row 3: the network git calls. One that hits its limit marks origin down for the rest of the pass.
NETWORK_SUBCOMMANDS = frozenset({"ls-remote", "fetch", "push"})
GIT_GUARD_KEY = "git:origin"


def _log(message: str) -> None:
    """One line on stderr in the daemon's style (`hosts._log`); never raises."""
    try:
        sys.stderr.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} runs-daemon: {message}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _git(repo: Path, *args: str, timeout: float | None = None) -> subprocess.CompletedProcess:
    if timeout is None:
        timeout = TIMEOUT      # read at call time, so a test on a busy PC can widen it (#844)
    network = bool(args) and args[0] in NETWORK_SUBCOMMANDS
    if network and GUARD.down(GIT_GUARD_KEY):  # #998: origin already did not answer in this pass
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr="skipped: origin did not answer this pass")
    try:
        return run_bounded(["git", *args], timeout=timeout, cwd=str(repo), capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:  # #998: a hit is one log line, the call counts as failed
        first = GUARD.mark_down(GIT_GUARD_KEY, repr(exc)) if network else True
        if first:
            _log(f"git {args[0] if args else ''} did not answer within {timeout:g} s; "
                 "the call counts as failed" + ("; origin is skipped for the rest of the pass" if network else ""))
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr=repr(exc))
    except Exception as exc:  # git missing: a failed call, never a raise
        return subprocess.CompletedProcess(["git", *args], 1, stdout="", stderr=repr(exc))


def _exists_at(repo: Path, ref: str, path: str) -> bool | None:
    """True/False: `git cat-file -e <ref>:<path>`; None when git could not answer (bad ref, git missing)."""
    res = _git(repo, "cat-file", "-e", f"{ref}:{path}")
    if res.returncode == 0:
        return True
    return False if "does not exist" in res.stderr or "exists on disk, but not in" in res.stderr else None


def script_candidates(argv: list[str]) -> tuple[list[str], str | None] | None:
    """The repo file a job command runs, or None when it cannot be told (no .py, shell form, `-c`).

    Forms: `python [opts] path/x.py ...` (python, python.exe, py, python3; a leading `set X=1 &&` or
    `cd d &&` chain is walked past) and `python -m pkg.mod` (candidates src/pkg/mod.py, pkg/mod.py and the
    `__main__.py` forms; third-party modules are told apart by their top package not being in the repo).
    Returns (paths of which one must exist, top-level dir that must exist for a `-m` to count as ours).
    """
    toks = [t.strip("\"'") for t in argv]
    for i, t in enumerate(toks):
        if t.replace("\\", "/").rsplit("/", 1)[-1].lower() not in ("python", "python.exe", "py", "python3", "python3.exe"):
            continue
        j = i + 1
        while j < len(toks):
            a = toks[j]
            if a == "-m" and j + 1 < len(toks):
                mod = toks[j + 1].split(".")
                rel = "/".join(mod)
                return ([f"src/{rel}.py", f"{rel}.py", f"src/{rel}/__main__.py", f"{rel}/__main__.py"], mod[0])
            if a == "-c":
                return None
            if a.startswith("-"):
                j += 1
                continue
            p = a.replace("\\", "/")
            if p.endswith(".py") and not p.startswith("/") and ":" not in p and ".." not in p.split("/"):
                return ([p[2:] if p.startswith("./") else p], None)
            return None
        return None
    return None


def missing_script(repo: Path, pin: str | None, argv: list[str]) -> tuple[str, str] | None:
    """(file, ref) when the job's script is certainly absent from the checkout at the pin (HEAD without one).

    Anything unreadable is a skip (None): a pin git cannot resolve, a git failure, a command without a .py.
    An unknown option of an existing script is not looked at.
    """
    found = script_candidates(argv)
    if found is None:
        return None
    paths, top = found
    ref = full_sha(repo, pin) if pin else full_sha(repo, "HEAD")
    if ref is None:
        return None
    if top is not None:
        tops = [_exists_at(repo, ref, d) for d in (f"src/{top}", top, f"src/{top}.py", f"{top}.py")]
        if True not in tops:
            return None  # not a module of this repo (pytest, pip): nothing to check
    results = [_exists_at(repo, ref, p) for p in paths]
    if any(r is not False for r in results):
        return None
    return paths[0], ref


def full_sha(repo: Path, pin: str) -> str | None:
    res = _git(repo, "rev-parse", "--verify", "--quiet", f"{pin}^{{commit}}")
    out = res.stdout.strip()
    return out if res.returncode == 0 and out else None


def origin_holds(repo: Path, sha: str) -> bool:
    res = _git(repo, "branch", "-r", "--contains", sha)
    return res.returncode == 0 and bool(res.stdout.strip())


def push_pin(repo: Path, pin: str) -> tuple[bool, str]:
    """Push ``pin`` to its own ref on origin unless origin holds it. (ok, message); never raises."""

    sha = full_sha(repo, pin)
    if sha is None:
        return False, f"pin {pin} is not a commit here; nothing pushed"
    if origin_holds(repo, sha):
        return True, f"pin {sha[:10]} is on origin; nothing pushed"
    res = _git(repo, "push", "origin", f"{sha}:{PREFIX}{sha}")
    if res.returncode != 0:
        return False, f"push of pin {sha[:10]} to origin failed: {res.stderr.strip()[:200]}"
    return True, f"pin {sha[:10]} pushed to origin as {PREFIX}{sha[:10]}"


def _remote_refs(repo: Path) -> list[tuple[str, str]]:
    res = _git(repo, "ls-remote", "origin", f"{PREFIX}*")
    if res.returncode != 0:
        return []
    out = []
    for line in res.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith(PREFIX):
            out.append((parts[1], parts[1][len(PREFIX):]))
    return out


def fetch_pin(repo: Path, pin: str) -> bool:
    """One bounded fetch of the pin's ref from origin (a short sha is matched by prefix). True when fetched."""

    for ref, sha in _remote_refs(repo):
        if sha.startswith(pin.lower()) or pin.lower().startswith(sha):
            res = _git(repo, "fetch", "origin", f"+{ref}:{ref}")
            return res.returncode == 0
    return False


def sweep(repo: Path, held_pins: list[str], failed: set[str]) -> list[str]:
    """Delete every ``refs/junkroan-pins/*`` on origin that no pin in ``held_pins`` names (#756 rule 2).

    A pin matches a ref by full sha (resolved here when it is a commit) or by prefix (a short pin of a
    host whose commit is not here). A ref whose delete failed once is in ``failed`` and is not tried again.
    Returns one log line per deleted or newly failed ref; never raises.
    """

    held = {p.lower() for p in held_pins if p}
    held |= {s for s in (full_sha(repo, p) for p in held_pins if p) if s}
    msgs: list[str] = []
    for ref, sha in _remote_refs(repo):
        if ref in failed or any(sha.startswith(p) or p.startswith(sha) for p in held):
            continue
        msg = drop_pin(repo, sha)
        if msg.startswith("pin ref") and "not deleted" in msg:
            failed.add(ref)
        if msg:
            msgs.append(msg)
    return msgs


def drop_pin(repo: Path, pin: str) -> str:
    """Delete the pin's ref from origin and the local copy, best effort. A message for the log."""

    sha = full_sha(repo, pin) or pin
    if not sha:
        return ""
    ref = f"{PREFIX}{sha}"
    res = _git(repo, "push", "origin", "--delete", ref)
    _git(repo, "update-ref", "-d", ref)
    if res.returncode == 0:
        return f"pin ref {ref} deleted from origin"
    err = res.stderr.strip()
    return "" if "does not exist" in err or "unable to delete" in err else f"pin ref {ref} not deleted: {err[:200]}"
