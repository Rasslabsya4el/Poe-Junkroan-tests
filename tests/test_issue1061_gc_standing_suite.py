"""#1061: `python -m tools.agentops worktree gc` (first pass and `--dirty`) keeps the two standing suite folders,
merge-suite (`suite_worktree.SUITE_NAME`) and full-run (`full_run.FULL_WORKTREE`), whatever their state:
decision `kept: standing suite folder`, 0 removals with `--apply`. A throwaway repo in a temp dir, both folders
dirty (a tracked edit and an untracked file), plus one clean folder under a made-up name for the control."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.agentops import worktree as wtmod  # noqa: E402
from tools.agentops.cli import main as cli_main  # noqa: E402
from tools.agentops.full_run import FULL_WORKTREE  # noqa: E402
from tools.agentops.suite_worktree import SUITE_NAME  # noqa: E402

STANDING = "kept: standing suite folder"


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def gc_repo(tmp_path, monkeypatch):
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "t")
    # the machine's gitconfig may set core.autocrlf=true: the throwaway repo keeps bytes as written
    _git(main, "config", "core.autocrlf", "false")
    (main / "f.txt").write_bytes(b"base line\n")
    _git(main, "add", "f.txt")
    _git(main, "commit", "-q", "-m", "init")
    monkeypatch.chdir(main)
    monkeypatch.setattr(wtmod, "gh_issue_state", lambda number, _main: "")
    return main


def _dirty(path: Path) -> None:
    """A tracked edit and an untracked file: the state the first pass calls `kept: dirty`."""
    (path / "f.txt").write_bytes(b"edited line\n")
    (path / "new.txt").write_bytes(b"untracked\n")


def _build(main: Path) -> tuple[Path, Path, Path]:
    wts = main / ".claude" / "worktrees"
    suite, full, clean = wts / SUITE_NAME, wts / FULL_WORKTREE, wts / "wt-clean-control"
    for wt in (suite, full, clean):
        _git(main, "worktree", "add", "-q", "--detach", str(wt), "main")
    _dirty(suite)
    _dirty(full)
    return suite, full, clean


def _rows(out: str, names: tuple[str, ...]) -> dict[str, str]:
    """{worktree folder name: the reason or decision column} from the table of either pass."""
    lines = out.splitlines()
    header = next(line for line in lines if line.startswith("worktree") and ("reason" in line or "decision" in line))
    column = 2
    found = {}
    for line in lines[lines.index(header) + 2:]:
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) > column and cells[0] in names:
            found[cells[0]] = cells[column]
    return found


def _listed(main: Path) -> set[str]:
    return {Path(line[len("worktree "):]).name for line in _git(main, "worktree", "list", "--porcelain").splitlines()
            if line.startswith("worktree ")}


def test_first_pass_keeps_both_dirty_standing_folders(gc_repo, capsys):
    main = gc_repo
    _build(main)
    assert cli_main(["worktree", "gc"]) == 0
    out = capsys.readouterr().out
    assert _rows(out, (SUITE_NAME, FULL_WORKTREE)) == {SUITE_NAME: STANDING, FULL_WORKTREE: STANDING}, out
    assert "dry run" in out


def test_first_pass_apply_removes_nothing_of_the_standing_folders(gc_repo, capsys):
    main = gc_repo
    suite, full, _clean = _build(main)
    assert cli_main(["worktree", "gc", "--apply"]) == 0
    out = capsys.readouterr().out
    assert _rows(out, (SUITE_NAME, FULL_WORKTREE)) == {SUITE_NAME: STANDING, FULL_WORKTREE: STANDING}, out
    assert "removed merge-suite" not in out and "removed full-run" not in out, out
    assert suite.is_dir() and full.is_dir()
    assert {SUITE_NAME, FULL_WORKTREE} <= _listed(main)


def test_dirty_pass_dry_run_shows_both_standing_folders_as_kept(gc_repo, capsys):
    main = gc_repo
    _build(main)
    assert cli_main(["worktree", "gc", "--dirty"]) == 0
    out = capsys.readouterr().out
    assert _rows(out, (SUITE_NAME, FULL_WORKTREE)) == {SUITE_NAME: STANDING, FULL_WORKTREE: STANDING}, out
    assert "dry run" in out


def test_dirty_pass_apply_removes_and_saves_nothing_of_the_standing_folders(gc_repo, capsys):
    main = gc_repo
    suite, full, _clean = _build(main)
    assert cli_main(["worktree", "gc", "--dirty", "--apply"]) == 0
    out = capsys.readouterr().out
    assert _rows(out, (SUITE_NAME, FULL_WORKTREE)) == {SUITE_NAME: STANDING, FULL_WORKTREE: STANDING}, out
    assert "removed merge-suite" not in out and "removed full-run" not in out, out
    assert suite.is_dir() and full.is_dir()
    assert {SUITE_NAME, FULL_WORKTREE} <= _listed(main)
    save_root = main / "var" / "agentops" / "worktree-save"
    assert not (save_root / SUITE_NAME).exists() and not (save_root / FULL_WORKTREE).exists()


def test_clean_standing_folder_is_kept_too(gc_repo, capsys):
    """Whatever its state: a clean, merged standing folder is kept as well, not `merged` and removed."""
    main = gc_repo
    wts = main / ".claude" / "worktrees"
    suite = wts / SUITE_NAME
    _git(main, "worktree", "add", "-q", "--detach", str(suite), "main")
    assert cli_main(["worktree", "gc", "--apply"]) == 0
    out = capsys.readouterr().out
    assert _rows(out, (SUITE_NAME,)) == {SUITE_NAME: STANDING}, out
    assert suite.is_dir()
