"""Weekly gate bookkeeping (#642): which gate dir is newest, which gates a host holds, which commands read a gate. Pure: no PoB, no ssh."""

from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path

from junkroan.runs.run_name import _line

from junkroan.runs.store import MAIN_ROOT

#: The main checkout whatever checkout this runs from (worktree, daemon checkout, snapshot): one bookkeeping
#: file and one artifacts root for every reader (#642), the convention of `store.MAIN_ROOT`.
ROOT = MAIN_ROOT
DEFAULT_PATH = ROOT / "var" / "runs" / "gates_present.json"

# A gate dir: the old `<date>-<time>-gate-<date>` form, or a weekly core run dir `<date>-<time>-P<prio>-core[-<n>]`
# (`benchmark.py` stamps `<date>-<time>` + `-<tag>`, the tag being the name `run_name.derive_name` gives: #578).
GATE_DIR_RE = re.compile(r"^\d{8}-\d{4}-(?:gate-.*|P\d+-core(?:-\d+)?)$")

_ARTIFACT = re.compile(r"artifacts[\\/]+benchmark[\\/]")
_PROBE = re.compile(r"scripts[\\/]probe_")
_POB_TEST = re.compile(r"tests[\\/][^\s\"']*pob[^\s\"'\\/]*$")
_MARKER_POB = re.compile(r"(?<![\w-])pob(?![\w-])")


def newest_gate(artifacts_dir: Path) -> str | None:
    bench = Path(artifacts_dir) / "benchmark"
    if not bench.is_dir():
        return None
    names = [p.name for p in bench.iterdir() if p.is_dir() and GATE_DIR_RE.match(p.name)]
    return max(names) if names else None


def dir_key(rel: str) -> str:
    """The ``gates_present`` entry of ``artifacts/<rel>``: a benchmark dir by its bare name (like a gate), any other as ``rel`` (#701)."""

    return rel[len("benchmark/"):] if rel.startswith("benchmark/") else rel


def _load(path: Path) -> dict[str, list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    if not text.strip():
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def gates_present(host: str, path: Path | None = None) -> set[str]:
    return set(_load(Path(path) if path else DEFAULT_PATH).get(host, []))


def record_gate(host: str, name: str, path: Path | None = None) -> None:
    p = Path(path) if path else DEFAULT_PATH
    data = _load(p)
    names = list(data.get(host, []))
    if name in names:
        return
    names.append(name)
    data[host] = sorted(names)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, posix=False)
    except ValueError:
        return line.split()


def _pytest_selects_pob(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        expr = None
        if tok == "-m" and i + 1 < len(tokens):
            expr = tokens[i + 1]
        elif tok.startswith("-m") and len(tok) > 2 and not tok.startswith("--"):
            expr = tok[2:].lstrip("=")
        elif tok.startswith("--markers="):
            continue
        if expr is None:
            continue
        expr = expr.strip("\"'")
        if re.search(r"(?<![\w-])not\s+pob(?![\w-])", expr):
            continue
        if _MARKER_POB.search(expr):
            return True
    return False


def needs_gate(cmd: str | list[str] | tuple[str, ...]) -> bool:
    line = _line(cmd)
    if _ARTIFACT.search(line) or _PROBE.search(line):
        return True
    toks = _tokens(line)
    if any(_POB_TEST.search(t.strip("\"'")) for t in toks):
        return True
    return "pytest" in line and _pytest_selects_pob(toks)
