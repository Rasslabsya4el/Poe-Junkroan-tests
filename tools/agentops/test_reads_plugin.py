"""pytest plugin (``-p tools.agentops.test_reads_plugin``): which non-python files / directories each test
opened, via an audit hook (#681, moved here by #690). The dump goes to the directory named by the env var
``SELREPLAY_OUT``, one ``reads-<pid>.json`` per xdist worker; without the var the plugin does nothing."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from tools.agentops.test_select import COLLECT_KEY

_state = {"root": None, "cur": COLLECT_KEY, "files": {}, "dirs": {}}


def _norm(path) -> str | None:
    root = _state["root"]
    if root is None:
        return None
    try:
        p = os.fspath(path)
        if isinstance(p, bytes):
            return None
        ap = os.path.abspath(p)
        rel = os.path.relpath(ap, root).replace("\\", "/")
    except Exception:
        return None
    if rel.startswith("..") or rel.startswith(".git/") or "__pycache__" in rel:
        return None
    return rel


def _audit(event, args):
    if _state["root"] is None:
        return
    if event == "open":
        rel = _norm(args[0]) if args and isinstance(args[0], (str, os.PathLike)) else None
        if rel and not rel.endswith((".py", ".pyc", ".pyd")) and ".testmon" not in rel:
            _state["files"].setdefault(_state["cur"], set()).add(rel)
    elif event in ("os.listdir", "os.scandir", "glob.glob"):
        a = args[0] if args else None
        if isinstance(a, (str, os.PathLike)):
            rel = _norm(a)
            if rel is not None:
                _state["dirs"].setdefault(_state["cur"], set()).add(rel)


def pytest_configure(config):
    out = os.environ.get("SELREPLAY_OUT")
    if not out:
        return
    _state["root"] = os.path.abspath(str(config.rootpath))
    sys.addaudithook(_audit)


def pytest_runtest_logstart(nodeid, location):
    _state["cur"] = nodeid


def pytest_runtest_logfinish(nodeid, location):
    _state["cur"] = COLLECT_KEY


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("SELREPLAY_OUT")
    if not out or _state["root"] is None:
        return
    Path(out).mkdir(parents=True, exist_ok=True)
    data = {"files": {k: sorted(v) for k, v in _state["files"].items()},
            "dirs": {k: sorted(v) for k, v in _state["dirs"].items()}}
    Path(out, f"reads-{os.getpid()}.json").write_text(json.dumps(data), encoding="utf-8")
