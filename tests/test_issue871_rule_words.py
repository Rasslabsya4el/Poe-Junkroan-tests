"""#871 / #876: the returned-worker rule is written in the core files, none of it in the local ORCH file."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_core_orch_names_the_worker_stop_and_the_no_wait_rule():
    text = _read("docs/agents/orch.md")
    assert "stop --worker-worktree <wt-name>" in text
    assert "start no wait on that worker's files" in text


def test_worker_files_say_a_worker_ends_its_own_waits():
    for name in ("worker", "worker-strong"):
        assert "end your own background shells, Monitor and waits" in _read(f".claude/agents/{name}.md")


def test_local_orch_file_holds_no_copy_of_the_rule():
    local = _read("docs/agents/local/orch.md")
    assert "stop --worker-worktree" not in local
    assert "(#871)" not in local
