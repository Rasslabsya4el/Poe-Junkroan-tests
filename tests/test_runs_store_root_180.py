"""Issue #180: the default store of a linked worktree is the main checkout's."""
from junkroan.runs.store import main_root


def test_worktree_resolves_to_main(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    assert main_root(wt) / "artifacts" / "runs" / "jobs.jsonl" == main / "artifacts" / "runs" / "jobs.jsonl"


def test_main_checkout_is_itself(tmp_path):
    (tmp_path / "main" / ".git").mkdir(parents=True)
    assert main_root(tmp_path / "main") == tmp_path / "main"
