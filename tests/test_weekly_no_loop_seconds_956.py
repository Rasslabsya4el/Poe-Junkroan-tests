"""#956 unit 4: the weekly core run's command line passes no `--loop-seconds` (PoB-free).

`runs.py weekly` builds its line in `cmd_weekly` -> `_submit_weekly`, which hands the line to `cmd_submit`.
The test replaces `cmd_submit` with a recorder, so no store, no git and no PoB run; it reads the argv the
weekly command would submit, in both branches (filler switch off: today's line; on: the week's `--resume` line).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import runs  # noqa: E402

FLAG = "--loop-seconds"


@pytest.fixture
def submitted(monkeypatch):
    """Records the argv of every `cmd_submit` call the weekly command makes."""
    calls: list[list[str]] = []

    def fake_submit(store, argv, *, again_hint="--again"):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(runs, "cmd_submit", fake_submit)
    monkeypatch.setattr(runs, "_now", lambda: datetime(2026, 10, 10, 12, 0))  # Saturday -> week of 12.10
    return calls


def _benchmark_part(argv: list[str]) -> list[str]:
    """The line after the `--` that separates submit's own flags from the run's command."""
    return argv[argv.index("--") + 1:]


def test_weekly_core_line_constant_has_no_loop_seconds():
    assert FLAG not in runs.WEEKLY_CORE_LINE
    assert runs.WEEKLY_CORE_LINE[:2] == ["python", "scripts/benchmark.py"]


def test_weekly_switch_off_submits_a_line_without_loop_seconds(submitted, monkeypatch):
    monkeypatch.setattr(runs, "_any_filler_switch", lambda: False)
    assert runs.cmd_weekly(None, []) == 0
    (argv,) = submitted
    assert FLAG not in argv
    cmd = _benchmark_part(argv)
    assert cmd[:2] == ["python", "scripts/benchmark.py"] and "--resume" not in cmd


def test_weekly_switch_on_resume_line_without_loop_seconds(submitted, monkeypatch, tmp_path):
    folder = tmp_path / "20261010-1200-week-20261012"
    folder.mkdir()
    (folder / "args.json").write_text(json.dumps({"commit": "a" * 40}), encoding="utf-8")
    monkeypatch.setattr(runs, "_any_filler_switch", lambda: True)
    monkeypatch.setattr(runs.weekly_cut, "find_week_folder", lambda root, monday: folder)
    assert runs.cmd_weekly(None, []) == 0
    (argv,) = submitted
    assert FLAG not in argv
    cmd = _benchmark_part(argv)
    assert "--resume" in cmd and FLAG not in cmd
