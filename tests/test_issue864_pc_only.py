"""#864 unit 2: one marker `pc_only` skips PC-only tests when JUNKROAN_HOST names another host; no PoB."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import not_on_pc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import suite_on_host  # noqa: E402


@pytest.mark.parametrize("host,skips", [("laptop", True), ("pc", False), (None, False), ("", False)])
def test_a_condition_function(host, skips, monkeypatch):
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    assert not_on_pc(host) is skips


def _run_child(tmp_path: Path, host: str | None) -> str:
    tmp_path.mkdir()
    (tmp_path / "test_child.py").write_text(
        "\n".join(["import sys", f"sys.path.insert(0, {str(ROOT / 'tests')!r})", "from conftest import pc_only", "",
                   "@pc_only", "def test_x():", "    assert True", ""]), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("JUNKROAN_HOST", "PYTEST_ADDOPTS")}  # the merge suite adds `-p tools.agentops.suite_plan_plugin`; the child sees only src/
    env["PYTHONPATH"] = str(ROOT / "src")
    if host is not None:
        env["JUNKROAN_HOST"] = host
    res = subprocess.run([sys.executable, "-m", "pytest", "test_child.py", "-q", "-p", "no:cacheprovider"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    return res.stdout + res.stderr


def test_b_child_is_skipped_on_laptop_and_passes_on_pc_or_unset(tmp_path):
    assert "1 skipped" in _run_child(tmp_path / "l", "laptop")
    assert "1 passed" in _run_child(tmp_path / "p", "pc")
    assert "1 passed" in _run_child(tmp_path / "u", None)


def test_c_remote_start_script_exports_the_host_name():
    cfg = {"name": "laptop", "ssh": "laptop", "repo_path": "C:\\r\\repo"}
    script = suite_on_host.remote_start_script(cfg, "refs/x", "a" * 40, "python -m pytest", {"A": "1"},
                                               "C:\\r\\out.txt", "task1")
    assert "$env:JUNKROAN_HOST = ''laptop''" in script  # the runner is quoted into a PowerShell string
    assert "$env:A = ''1''" in script
