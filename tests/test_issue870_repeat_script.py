"""#870: the repeat script's own pytest temp root is usable on a fresh checkout (no `var/repeat_870` yet)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import repeat_under_load_870 as script  # noqa: E402


def test_the_temp_root_parent_exists_after_the_call_and_pytest_accepts_it(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "ROOT", tmp_path)
    base = script.temp_root(4242)
    assert base.parent.is_dir() and base == tmp_path / "var" / "repeat_870" / "4242"
    child = tmp_path / "test_child.py"
    child.write_text("def test_ok(tmp_path):\n    assert tmp_path.is_dir()\n", encoding="utf-8")
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:faulthandler", "-p", "no:cacheprovider",
                          "--basetemp", str(base), str(child)], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stdout + res.stderr
