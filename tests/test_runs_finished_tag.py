"""#365: `runs.py submit` refuses a tag whose results folder holds a finished run, unless --again."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402
import runs  # noqa: E402
from junkroan.runs.finished_tag import finished_run_dir  # noqa: E402
from junkroan.runs.store import Store  # noqa: E402

TAG = "P1-#1"  # the derived name (#578, #593)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(runs, "ROOT", tmp_path)
    monkeypatch.setattr(runs, "_today", lambda: __import__("datetime").date(2026, 10, 6))
    monkeypatch.setenv("JUNKROAN_HOST", "pc")
    return tmp_path


def _folder(root: Path, name: str, files=("results.json",), report: str | None = None) -> Path:
    d = root / "artifacts" / "benchmark" / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("[]", encoding="utf-8")
    if report is not None:
        (d / "report.md").write_text(report, encoding="utf-8")
    return d


def _submit(root: Path, *extra: str) -> int:
    return runs.main(["--store", str(root / "jobs.jsonl"), "submit", "--issue", "1", "--host", "pc", "--priority", "P1",
                      *extra, "--", "python", "x.py"])


def test_finished_tag_refused_naming_folder(root, capsys):
    d = _folder(root, f"20260927-0510-{TAG}")
    assert _submit(root) == 2
    assert str(d) in capsys.readouterr().err
    assert Store(root / "jobs.jsonl").jobs() == []


def test_again_queues(root, capsys):
    _folder(root, f"20260927-0510-{TAG}")
    assert _submit(root, "--again") == 0
    assert len(Store(root / "jobs.jsonl").jobs()) == 1


def test_folder_without_summary_is_not_finished(root):
    _folder(root, f"20260927-0510-{TAG}", files=("args.json",))
    assert _submit(root) == 0
    assert len(Store(root / "jobs.jsonl").jobs()) == 1


def test_partial_report_is_not_finished(root):
    _folder(root, f"20260927-0510-{TAG}", report="partial: 3 of 54 builds\n\n# Benchmark")
    assert finished_run_dir(TAG, root) is None
    _folder(root, f"20260928-0510-{TAG}", report="# Benchmark")
    assert finished_run_dir(TAG, root).name == f"20260928-0510-{TAG}"


def test_prefix_sharing_tag_not_matched(root):
    _folder(root, "20260927-0510-new18-tpl-main3-s4")
    assert finished_run_dir(TAG, root) is None
    assert finished_run_dir("new18-tpl-main3-s4", root) is not None


def test_ablate_folder_matches_and_newest_wins(root):
    _folder(root, f"20260926-0510-{TAG}")
    _folder(root, f"20260927-0510-{TAG}-no-gear")
    assert finished_run_dir(TAG, root).name == f"20260927-0510-{TAG}-no-gear"
