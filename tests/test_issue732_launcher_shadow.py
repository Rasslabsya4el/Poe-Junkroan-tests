"""Issue #732: `scripts/junkroan.py` must not hide the `junkroan` package when `scripts/` is ahead of `src/`.

Runs in subprocesses (outside pytest, so the #94 pin in conftest cannot mask the defect), each bounded.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SRC = ROOT / "src"


def _run(code: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(ROOT),
        env={**__import__("os").environ, "PYTHONPATH": str(SCRIPTS)},
    )


def test_import_junkroan_resolves_to_src_package():
    r = _run("import junkroan; print(junkroan.__file__)")
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == SRC / "junkroan" / "__init__.py"


@pytest.mark.parametrize("stmt", ["from junkroan.cli import main", "import junkroan.runs.store"])
def test_submodule_imports_with_scripts_first(stmt):
    r = _run(stmt)
    assert r.returncode == 0, r.stderr


def test_spawn_child_imports_store_with_scripts_ahead_of_src(tmp_path):
    prog = tmp_path / "spawn_probe.py"
    prog.write_text(
        "import sys, multiprocessing as mp\n"
        f"sys.path[:0] = [{str(SCRIPTS)!r}]\n"
        f"sys.path[:] = [p for p in sys.path if p != {str(SRC)!r}] + [{str(SRC)!r}]\n"
        "def _target():\n"
        "    import junkroan.runs.store\n"
        "if __name__ == '__main__':\n"
        "    ctx = mp.get_context('spawn')\n"
        "    p = ctx.Process(target=_target)\n"
        "    p.start(); p.join(30)\n"
        "    if p.is_alive():\n"
        "        p.kill(); sys.exit(99)\n"
        "    sys.exit(p.exitcode)\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(prog)], capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        env={k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"},
    )
    assert r.returncode == 0, r.stderr
