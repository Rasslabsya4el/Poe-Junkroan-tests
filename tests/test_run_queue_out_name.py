"""Unique .out stems for queue lines without a PoB runtime (2026-09-22 22:23)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import run_queue  # noqa: E402

NOW = datetime(2026, 9, 23, 22, 23)


def test_tagged_command_uses_tag(tmp_path):
    name = run_queue.out_name('python scripts/benchmark.py --tag smoke', NOW, tmp_path)
    assert name == "20260923-2223-smoke"


def test_untagged_command_uses_script_stem(tmp_path):
    name = run_queue.out_name("python scripts/compare_runs.py a b", NOW, tmp_path)
    assert name == "20260923-2223-compare_runs"


def test_second_identical_call_gets_suffix(tmp_path):
    first = run_queue.out_name("python scripts/compare_runs.py a b", NOW, tmp_path)
    (tmp_path / f"{first}.out").write_text("", encoding="utf-8")
    second = run_queue.out_name("python scripts/compare_runs.py a b", NOW, tmp_path)
    assert second == "20260923-2223-compare_runs-2"


def test_command_without_scripts_path_falls_back_to_run(tmp_path):
    name = run_queue.out_name("python -c pass", NOW, tmp_path)
    assert name == "20260923-2223-run"