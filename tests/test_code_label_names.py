"""#319 row 2: every label name the code gives to `gh label create` is one of the allowed 20.

Static (ast) collector over tools/, scripts/, src/. A name it cannot resolve to a string literal or
a module-level constant is a failure too, so a new dynamic name cannot slip past."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("tools", "scripts", "src")
EXTRA_ALLOWED = {"pob-free", "in-cloud", "autopilot", "autopilot-stuck", "provisional",
                 "cloud-lane", "core-issue", "core-epic"}
TEXT_RE = re.compile(r"gh label create\s+[\"']?([A-Za-z0-9][\w:\-]*)")


def _core_labels(root: Path) -> list[str]:
    return list(json.loads((root / "config" / "core_labels.json").read_text(encoding="utf-8")))


def _files(root: Path, suffixes: tuple[str, ...]):
    for d in SCAN_DIRS:
        base = root / d
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.suffix in suffixes and "__pycache__" not in p.parts:
                    yield p


def _is_label_create(node: ast.AST) -> ast.AST | None:
    """The name argument of a list literal [..., "label", "create", NAME, ...], else None."""
    if isinstance(node, ast.List):
        for i in range(len(node.elts) - 2):
            a, b = node.elts[i], node.elts[i + 1]
            if (isinstance(a, ast.Constant) and a.value == "label"
                    and isinstance(b, ast.Constant) and b.value == "create"):
                return node.elts[i + 2]
    return None


def _module_consts(tree: ast.Module) -> dict[str, str]:
    out = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = n.value.value
    return out


def _funcs(tree: ast.Module):
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _params(fn) -> list[str]:
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    return names[1:] if names and names[0] in ("self", "cls") else names


def _resolve(expr, fn, consts) -> list[str] | None:
    """Strings the expression can hold, or None when it is not statically known."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if not isinstance(expr, ast.Name):
        return None
    if expr.id in consts:
        return [consts[expr.id]]
    for loop in (n for n in ast.walk(fn) if isinstance(n, ast.For)):
        it = loop.iter
        if not isinstance(it, (ast.Tuple, ast.List)):
            continue
        tgt = loop.target
        if isinstance(tgt, ast.Name) and tgt.id == expr.id:
            elts = list(it.elts)
        elif isinstance(tgt, ast.Tuple):
            idx = [i for i, t in enumerate(tgt.elts) if isinstance(t, ast.Name) and t.id == expr.id]
            if not idx:
                continue
            elts = []
            for row in it.elts:
                if not isinstance(row, (ast.Tuple, ast.List)) or idx[0] >= len(row.elts):
                    return None
                elts.append(row.elts[idx[0]])
        else:
            continue
        out: list[str] = []
        for e in elts:
            r = _resolve(e, fn, consts)
            if r is None:
                return None
            out += r
        return out
    return None


def collect(root: Path) -> tuple[list[tuple[str, str, int]], list[tuple[str, int, str]]]:
    """(found, unresolved): found = (name, relative file, line); unresolved = (file, line, why)."""
    found: list[tuple[str, str, int]] = []
    unresolved: list[tuple[str, int, str]] = []
    creators: dict[str, tuple[int, str]] = {}  # function name -> (param index, param name)
    parsed = []
    for p in _files(root, (".py",)):
        tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"), filename=str(p))
        parsed.append((p.relative_to(root).as_posix(), tree, _module_consts(tree)))

    for rel, tree, consts in parsed:
        for fn in _funcs(tree):
            for node in ast.walk(fn):
                name_expr = _is_label_create(node)
                if name_expr is None:
                    continue
                if fn.name == "sync_labels":
                    for n in _core_labels(root):
                        found.append((n, rel, node.lineno))
                    continue
                if isinstance(name_expr, ast.Name) and name_expr.id in _params(fn):
                    creators[fn.name] = (_params(fn).index(name_expr.id), name_expr.id)
                    continue
                r = _resolve(name_expr, fn, consts)
                if r is None:
                    unresolved.append((rel, node.lineno, f"name {ast.unparse(name_expr)!r} of `label create`"))
                else:
                    found += [(n, rel, node.lineno) for n in r]

    for rel, tree, consts in parsed:
        for fn in _funcs(tree):
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                cname = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if cname not in creators or cname == fn.name:
                    continue
                idx, pname = creators[cname]
                arg = node.args[idx] if idx < len(node.args) else next(
                    (k.value for k in node.keywords if k.arg == pname), None)
                r = None if arg is None else _resolve(arg, fn, consts)
                if r is None:
                    why = "missing" if arg is None else ast.unparse(arg)
                    unresolved.append((rel, node.lineno, f"name argument {why!r} of {cname}()"))
                else:
                    found += [(n, rel, node.lineno) for n in r]

    for p in _files(root, (".py", ".ps1", ".sh")):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in TEXT_RE.finditer(line):
                found.append((m.group(1), p.relative_to(root).as_posix(), i))
    return found, unresolved


def violations(root: Path) -> list[str]:
    allowed = set(_core_labels(root)) | EXTRA_ALLOWED
    found, unresolved = collect(root)
    out = [f"{f}:{ln}: label {n!r} is not allowed" for n, f, ln in found if n not in allowed]
    out += [f"{f}:{ln}: cannot resolve statically: {why}" for f, ln, why in unresolved]
    return out


def test_code_creates_only_allowed_labels():
    found, _ = collect(ROOT)
    # the two autopilot labels are allowed but no code creates them today
    known = EXTRA_ALLOWED - {"autopilot", "autopilot-stuck"}
    assert {n for n, _, _ in found} >= known, "collector lost a known label"
    assert violations(ROOT) == []


def test_collector_reports_planted_names(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "core_labels.json").write_text('{"bug": {}}', encoding="utf-8")
    d = tmp_path / "tools"
    d.mkdir()
    (d / "planted.py").write_text(
        "def _ensure_label(runner, name):\n"
        "    runner(['label', 'create', name])\n"
        "def a(runner):\n"
        "    _ensure_label(runner, 'vetoed')\n"
        "def b(runner, dyn):\n"
        "    _ensure_label(runner, dyn)\n"
        "def c(runner):\n"
        "    _ensure_label(runner, 'bug')\n", encoding="utf-8")
    got = violations(tmp_path)
    assert any("planted.py:4" in v and "'vetoed'" in v for v in got), got
    assert any("planted.py:6" in v and "cannot resolve" in v for v in got), got
    assert len(got) == 2, got
