"""The manifest ships the monitor's tests and every file they import."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "agentops" / "core_manifest.txt"
MOD = "mods/pob-slots"
# hooks/draw.ts is a copy of mods/shared/draw.ts made by `mods test` (sync_shared); hooks/addon.tsx and
# hooks/project.ts are the project's own files, written from the port stubs (tools/agentops/port.py).
GENERATED = {f"{MOD}/hooks/draw": f"{MOD}/../shared/draw.ts"}
PROJECT_OWN = {f"{MOD}/hooks/addon", f"{MOD}/hooks/project"}
IMPORT = re.compile(r"""from\s+['"](\.[^'"]*)['"]""")


def _manifest() -> set[str]:
    return {ln.strip() for ln in MANIFEST.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")}


def _resolve(src: str, spec: str) -> str | None:
    base = (Path(src).parent / spec).as_posix()
    parts: list[str] = []
    for seg in base.split("/"):
        if seg == "..":
            parts.pop()
        elif seg != ".":
            parts.append(seg)
    key = "/".join(parts)
    if key in PROJECT_OWN:
        return None
    if key in GENERATED:
        return "mods/shared/draw.ts"
    for ext in ("", ".ts", ".tsx", ".d.ts", "/index.d.ts", "/index.ts"):
        if (ROOT / (key + ext)).is_file():
            return key + ext
    raise AssertionError(f"{src}: import {spec} resolves to nothing")


def _closure(roots: set[str]) -> set[str]:
    seen, todo = set(), sorted(roots)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        if f.endswith((".ts", ".tsx")) and not f.endswith(".d.ts"):
            for spec in IMPORT.findall((ROOT / f).read_text(encoding="utf-8")):
                r = _resolve(f, spec)
                if r:
                    todo.append(r)
    return seen


def _shipped_tests() -> set[str]:
    return {m for m in _manifest() if m.startswith(f"{MOD}/test/")}


def test_pob_slots_tests_are_shipped():
    assert any(".test." in Path(m).name for m in _shipped_tests())


def test_every_import_of_a_shipped_test_is_shipped():
    assert not (_closure(_shipped_tests()) - _manifest())


def test_every_manifest_path_exists():
    assert not [p for p in _manifest() if not (ROOT / p).is_file()]


@pytest.mark.skipif(not (shutil.which("claude") or os.environ.get("CLAUDE_CODE_EXECPATH")),
                    reason="the claude CLI is not found")
def test_shipped_tests_pass_in_a_scratch_target(tmp_path, monkeypatch):
    from scripts import mods_ship_set

    scratch = mods_ship_set.scratch_target(tmp_path, ROOT, _shipped_tests())
    out = mods_ship_set.mods_test(scratch, tmp_path / "installed", ROOT)
    m = re.search(r"plugin test: (\d+) pass, (\d+) fail, exit (-?\d+)", out)
    assert m, out
    assert int(m.group(1)) > 0 and int(m.group(2)) == 0 and m.group(3) == "0", out
