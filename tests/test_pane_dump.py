"""#843 unit 1: scripts/pane_dump.py dumps the drawn tree of a ref; plugin test run only (node, no PoB)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import pc_only

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pane_dump", ROOT / "scripts" / "pane_dump.py")
pane_dump = importlib.util.module_from_spec(spec)
sys.modules["pane_dump"] = pane_dump
spec.loader.exec_module(pane_dump)


needs_claude = pytest.mark.skipif(pane_dump.claude_exe() is None,
                                  reason="no claude.exe on this machine (CLAUDE_EXE, the app package, PATH)")


def walk(n):
    yield n
    for c in n.get("children") or []:
        if isinstance(c, dict):
            yield from walk(c)


def text_of(n) -> str:
    return "".join(c if isinstance(c, str) else text_of(c) for c in n.get("children") or [])


@needs_claude
@pc_only
def test_current_worktree_123_columns_has_three_cards_and_a_picture(tmp_path):
    out = tmp_path / "now.json"
    t0 = time.time()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "pane_dump.py"), "--ref", str(ROOT),
                        "--fixture", "live-fast", "--cols", "123", "--out", str(out)],
                       capture_output=True, text=True, timeout=900)
    wall = time.time() - t0
    print(f"dump wall time {wall:.1f} s")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "installs 0 clicks 0" in r.stdout
    d = json.loads(out.read_text(encoding="utf-8"))
    assert set(d) == {"ref", "fixture", "tab", "presses", "open_square", "cols", "tree"}
    nodes = list(walk(d["tree"]))
    words = " ".join(text_of(n) for n in nodes if n["type"] == "Text")
    allwords = words + " " + " ".join(str(n["props"].get("alt", "")) for n in nodes if n["type"] == "Svg")
    for card in ("Agents", "Merge", "PC"):
        assert card in allwords, card
    assert sum(1 for n in nodes if n["type"] == "Svg") >= 1


@needs_claude
@pc_only
def test_open_square_press_of_a_seed_cell_draws_the_build_block():
    """#948: the seed cell press (a Markdown link since #937) opens the square: the tree differs from the closed one.
    Red before the fix: the dump of --open-square stopped with 'no Button keyed cell-...' (SystemExit from dump)."""
    closed = pane_dump.dump(str(ROOT), "live-fast", cols=123, open_square=False)
    opened = pane_dump.dump(str(ROOT), "live-fast", cols=123, open_square=True)
    assert opened["open_square"] is True
    assert json.dumps(closed["tree"], sort_keys=True) != json.dumps(opened["tree"], sort_keys=True)


@needs_claude
@pc_only
def test_baseline_ref_dumps_a_nonempty_tree():
    d = pane_dump.dump("50ea5412", "live-fast", cols=123)
    assert len(list(walk(d["tree"]))) > 10
