"""#1165: the weekly core run's no-folder line is submitted to the laptop (host fixed), not the PC.

`runs.py weekly` builds its line in `cmd_weekly` -> `_submit_weekly`, which hands the line to `cmd_submit`.
The test replaces `cmd_submit` with a recorder, so no store, no git and no PoB run. The no-folder line (no
filler switch on) must name `--host laptop` and a note without "PC only"; the folder line (a filler switch on)
stays on the PC, the folder lives there.
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


@pytest.fixture
def submitted(monkeypatch):
    """Records the argv of every `cmd_submit` call the weekly command makes."""
    calls: list[list[str]] = []

    def fake_submit(store, argv, *, again_hint="--again"):
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(runs, "cmd_submit", fake_submit)
    monkeypatch.setattr(runs, "_now", lambda: datetime(2026, 10, 17, 12, 0))  # Saturday -> week of 12.10
    return calls


def _value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_weekly_no_filler_switch_submits_to_laptop(submitted, monkeypatch):
    monkeypatch.setattr(runs, "_any_filler_switch", lambda: False)
    assert runs.cmd_weekly(None, []) == 0
    (argv,) = submitted
    assert _value(argv, "--host") == "laptop"
    assert "PC only" not in _value(argv, "--note")


def test_weekly_filler_switch_on_folder_line_stays_on_pc(submitted, monkeypatch, tmp_path):
    folder = tmp_path / "20261012-1200-week-20261012"
    folder.mkdir()
    (folder / "args.json").write_text(json.dumps({"commit": "a" * 40}), encoding="utf-8")
    monkeypatch.setattr(runs, "_any_filler_switch", lambda: True)
    monkeypatch.setattr(runs.weekly_cut, "find_week_folder", lambda root, monday: folder)
    assert runs.cmd_weekly(None, []) == 0
    (argv,) = submitted
    assert _value(argv, "--host") == "pc"
    assert "--resume" in argv[argv.index("--") + 1:]
    assert "PC only" in _value(argv, "--note")  # the folder line is untouched (#1165 rule 3)
