"""tools/hooks/autopilot_commit_guard.py (issue #142, the brain's decision on #142 comment
5855352848). No network, no live session: a real temp git repo, the hook run as a subprocess with a
JSON `PreToolUse` payload on stdin."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.timing_bound import bound

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PROJECT_ROOT / "tools" / "hooks" / "autopilot_commit_guard.py"
SETTINGS_PATH = PROJECT_ROOT / "tools" / "agentops" / "autopilot_settings.json"


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(["init"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    return repo


def _write(repo: Path, rel: str, content: str = "x") -> Path:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _run_hook(command: str, cwd: Path) -> subprocess.CompletedProcess:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)], input=json.dumps(payload),
        capture_output=True, text=True,
        # python start + up to 3 git calls (each up to GIT_TIMEOUT_SECONDS=5 in the hook, :83): a fixed 10 s
        # starved on a loaded PC (#844); the limit follows the machine
        timeout=bound(10.0, 60.0),
    )


def _deny_reason(result: subprocess.CompletedProcess) -> str | None:
    out = result.stdout.strip()
    if not out:
        return None
    obj = json.loads(out)
    return obj["hookSpecificOutput"]["permissionDecisionReason"]


# -- required case 1: all staged paths inside the list -> allowed, empty stdout -----------------

def test_all_staged_paths_inside_list_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "GLOSSARY.md")
    _write(repo, "docs/adr/0001-foo.md")
    _run_git(["add", "GLOSSARY.md", "docs/adr/0001-foo.md"], repo)

    result = _run_hook('git commit -m "docs"', repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- required case 2: 1 path outside -> refused, path named --------------------------------------

def test_one_path_outside_refused_and_named(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/foo.py")
    _run_git(["add", "src/foo.py"], repo)

    result = _run_hook('git commit -m "code"', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/foo.py" in reason
    assert "ready-for-agent" in reason


# -- required case 3: mixed, 1 inside and 1 outside -> refused -----------------------------------

def test_mixed_paths_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "GLOSSARY.md")
    _write(repo, "src/foo.py")
    _run_git(["add", "GLOSSARY.md", "src/foo.py"], repo)

    result = _run_hook('git commit -m "mixed"', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/foo.py" in reason
    assert "GLOSSARY.md" not in reason


# -- required case 4: no `git commit` -> does nothing ---------------------------------------------

def test_no_git_commit_does_nothing(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/foo.py")
    _run_git(["add", "src/foo.py"], repo)

    result = _run_hook("git status", repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- required case 5: `git commit -am msg` with a modified tracked file outside -> refused --------

def test_commit_am_with_modified_file_outside_list_refused(tmp_path):
    repo = _init_repo(tmp_path)
    src = _write(repo, "src/foo.py", "one")
    _run_git(["add", "src/foo.py"], repo)
    _run_git(["commit", "-m", "initial"], repo)
    src.write_text("two", encoding="utf-8")

    result = _run_hook('git commit -am "update"', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/foo.py" in reason


# -- explicit pathspecs after `--` also count -----------------------------------------------------

def test_explicit_pathspec_outside_list_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/foo.py", "one")
    _run_git(["add", "src/foo.py"], repo)
    _run_git(["commit", "-m", "initial"], repo)
    (repo / "src" / "foo.py").write_text("two", encoding="utf-8")

    result = _run_hook('git commit -m "update" -- src/foo.py', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/foo.py" in reason


# -- an internal error (not a repo) fails open -----------------------------------------------------

def test_not_a_repo_fails_open(tmp_path):
    not_a_repo = tmp_path / "not_a_repo"
    not_a_repo.mkdir()

    result = _run_hook('git commit -m "x"', not_a_repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- shell/PowerShell chaining after `git commit` must not be read as pathspecs ------------------

def test_chained_push_after_commit_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "GLOSSARY.md")
    _run_git(["add", "GLOSSARY.md"], repo)

    result = _run_hook('git commit -m "x" && git push origin main', repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_commit_dash_capital_f_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "docs/STATE.md")
    _run_git(["add", "docs/STATE.md"], repo)

    result = _run_hook("git commit -F msg.txt", repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_git_add_then_commit_separated_by_semicolon_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/a.py")
    _run_git(["add", "src/a.py"], repo)

    result = _run_hook('git add src/a.py; git commit -m "x"', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/a.py" in reason


def test_powershell_if_push_after_commit_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "GLOSSARY.md")
    _run_git(["add", "GLOSSARY.md"], repo)

    result = _run_hook('git commit -m "x"; if ($?) { git push origin main }', repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- git add <path> && git commit ...: PreToolUse runs before `add` stages anything (#142 follow-up,
# the live check that committed src/outside.py because `git diff --cached` was still empty) --------

def test_add_then_commit_untracked_outside_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/outside.py")

    result = _run_hook('git add src/outside.py && git commit -m x', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/outside.py" in reason


def test_add_dash_capital_a_then_commit_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/outside.py")

    result = _run_hook("git add -A && git commit -m x", repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/outside.py" in reason


def test_add_dot_then_commit_semicolon_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "src/outside.py")

    result = _run_hook('git add . ; git commit -m x', repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "src/outside.py" in reason


def test_add_then_commit_untracked_inside_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "GLOSSARY.md")

    result = _run_hook("git add GLOSSARY.md && git commit -m x", repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_add_then_commit_with_dash_c_pairs_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "docs/adr/0200-x.md")

    result = _run_hook('git add docs/adr/0200-x.md && git -c user.name=t commit -m x', repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


# -- #222: a commit is read only where the shell would run one, never inside a heredoc's body or a
# quoted argument to another command -------------------------------------------------------------

_HEREDOC_PRELUDE = (
    "cat > /tmp/body.txt <<'EOF'\n"
    'git commit -m "never git stash"\n'
    "echo hello\n"
    'grep -rn "foo" .\n'
    "EOF\n"
)


def test_heredoc_body_with_commit_words_no_real_commit_passed(tmp_path):
    repo = _init_repo(tmp_path)

    command = _HEREDOC_PRELUDE + "gh issue edit 215 --body-file /tmp/body.txt"
    result = _run_hook(command, repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_heredoc_prelude_then_real_commit_of_disallowed_path_refused(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "some/other/path.py")
    _run_git(["add", "some/other/path.py"], repo)

    command = (
        _HEREDOC_PRELUDE
        + "gh issue edit 215 --body-file /tmp/body.txt "
        + '&& git commit -m x some/other/path.py'
    )
    result = _run_hook(command, repo)

    reason = _deny_reason(result)
    assert reason is not None
    assert "some/other/path.py" in reason


def test_heredoc_prelude_then_real_commit_of_state_md_passed(tmp_path):
    repo = _init_repo(tmp_path)
    _write(repo, "docs/STATE.md")
    _run_git(["add", "docs/STATE.md"], repo)

    command = (
        _HEREDOC_PRELUDE
        + "gh issue edit 215 --body-file /tmp/body.txt "
        + '&& git commit -m x docs/STATE.md'
    )
    result = _run_hook(command, repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_commit_words_inside_quoted_gh_comment_body_passed(tmp_path):
    repo = _init_repo(tmp_path)

    double_quoted = _run_hook(
        'gh issue comment 1 --body "run git commit -m y foo.py"', repo,
    )
    single_quoted = _run_hook(
        "gh issue comment 1 --body 'run git commit -m y foo.py'", repo,
    )

    for result in (double_quoted, single_quoted):
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# -- autopilot_settings.json parses and holds the PreToolUse entry --------------------------------

def test_autopilot_settings_json_has_pre_tool_use_entry():
    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    pre_tool_use = settings["hooks"]["PreToolUse"]
    assert len(pre_tool_use) == 1
    entry = pre_tool_use[0]
    assert entry["matcher"] == "Bash|PowerShell"
    commands = [h["command"] for h in entry["hooks"]]
    assert any("autopilot_commit_guard.py" in c for c in commands)


# -- #545: agentops commit value flags and redirections are text, never paths ---------------------

_ENTRY_CMD = (
    'git status && python -m tools.agentops commit -m "State: x" --state-entry "tests/test_pending_facts.py '
    'and pending_facts.py:82 fixed" --state-as "autopilot #486" docs/STATE.md 2>&1'
)


def test_agentops_commit_state_entry_text_and_redirect_not_paths(tmp_path):
    repo = _init_repo(tmp_path)
    result = _run_hook(_ENTRY_CMD, repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_agentops_commit_forbidden_positional_still_refused(tmp_path):
    repo = _init_repo(tmp_path)
    cmd = _ENTRY_CMD.replace("docs/STATE.md", "src/foo.py")

    reason = _deny_reason(_run_hook(cmd, repo))

    assert reason is not None
    assert "src/foo.py" in reason
    assert "2>&1" not in reason
    assert "autopilot #486" not in reason
    assert "pending_facts" not in reason


def test_agentops_commit_without_git_token_forbidden_positional_refused(tmp_path):
    repo = _init_repo(tmp_path)

    reason = _deny_reason(_run_hook('python -m tools.agentops commit -m "x" src/foo.py', repo))

    assert reason is not None
    assert "src/foo.py" in reason


def test_agentops_commit_without_git_token_state_entry_text_allowed(tmp_path):
    repo = _init_repo(tmp_path)
    cmd = 'python -m tools.agentops commit -m "x" --state-entry "mentions src/foo.py" docs/STATE.md'

    result = _run_hook(cmd, repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_git_commit_message_mentions_path_but_forbidden_pathspec_refused(tmp_path):
    repo = _init_repo(tmp_path)

    reason = _deny_reason(_run_hook('git commit -m "mentions src/x.py" -- src/foo.py > out.txt 2>&1', repo))

    assert reason is not None
    assert "src/foo.py" in reason
    assert "src/x.py" not in reason
    assert "out.txt" not in reason
