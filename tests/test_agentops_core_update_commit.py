"""Issue #284: a core update (either rule) ends with one commit of exactly the paths it wrote,
pushed under the merge lock; a dirty own path the update would write, or a refused push, changes
nothing and raises `CoreUpdateError`. Real git repos under `tmp_path` (a bare remote + a clone),
no network: the home's GitHub read is stubbed the same way `test_agentops_core_update.py` does."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import stood_clock
from tests.home_tree_fake import tree_reply  # #148: the home's tree read (`git/trees/<sha>?recursive=1`)
from tools.agentops import core_update
from tools.agentops.dispatch import apply_auto_core_update
from tools.agentops.leak_starter import PATTERNS_ENTRY  # #93: the starter the update's steps write when the target has none

HOME_REPO = "someone/home-repo"
GIT_TIMEOUT = 30  # seconds; every git call in this file is bounded
SETUP_GIT_TIMEOUT = 60  # seconds; the setup's git calls (`_run`) under the full run's load (#1025: a 30 s budget was spent on `git commit -m initial`)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _fake_result(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _stub_gh_runner(*, head: str, manifest_text: str, files: dict[str, str]):
    """Only the calls `run_core_update` itself makes: the home's head sha, the manifest at that
    head, and each manifest entry's content at that head -- `run_core_update` never calls
    `commits_between`/`commit_files` (that is `run_core_status`'s own job)."""

    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): head + "\n",
        ("api", f"repos/{HOME_REPO}/contents/tools/agentops/core_manifest.txt?ref={head}", "--jq", ".content"):
            _b64(manifest_text),
    }
    for path, content in files.items():
        table[("api", f"repos/{HOME_REPO}/contents/{path}?ref={head}", "--jq", ".content")] = _b64(content)
    # #148: the home's whole tree at head, in one call (`core_update.tree`): the blobs the contents calls above serve
    blobs = {"tools/agentops/core_manifest.txt": manifest_text.encode("utf-8"),
             **{path: content.encode("utf-8") for path, content in files.items()}}
    table[("api", f"repos/{HOME_REPO}/git/trees/{head}?recursive=1")] = tree_reply(blobs).stdout

    def runner(args):
        key = tuple(args)
        if key not in table:
            raise AssertionError(f"unexpected gh call: {args}")
        return _fake_result(stdout=table[key])

    return runner


# -- git plumbing used only by this test file --------------------------------------------------

def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Setup-only git calls (the fixture and the second clones): the longer budget."""
    result = stood_clock.run(args, cwd=str(cwd) if cwd else None,
                             encoding="utf-8", errors="replace", timeout=SETUP_GIT_TIMEOUT)
    assert result.returncode == 0, f"{args} failed: {result.stderr}"
    return result


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return stood_clock.run(["git", *args], cwd=str(cwd),
                           encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)


def _porcelain(cwd: Path) -> list[str]:
    # the core's run log writes `artifacts/` in the target (untracked here, ignored in a real one): filtered out
    return [line for line in _git(cwd, "status", "--porcelain").stdout.splitlines() if line[3:] != "artifacts/"]


def _head(cwd: Path) -> str:
    return _git(cwd, "rev-parse", "HEAD").stdout.strip()


def _remote_head(bare: Path, branch: str = "main") -> str:
    return _git(bare, "rev-parse", branch).stdout.strip()


def _commit_files(cwd: Path, sha: str = "HEAD") -> set[str]:
    out = _git(cwd, "show", "--name-only", "--pretty=format:", sha).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _commit_count(cwd: Path) -> int:
    return int(_git(cwd, "rev-list", "--count", "HEAD").stdout.strip())


def _init_git_target(tmp_path: Path, *, update_rule: str = "word", core_version: str = "A" * 40,
                      name: str = "target") -> tuple[Path, Path]:
    """A bare remote plus one clone, with an initial commit holding the target's settings, its
    manifest and `a.txt` -- the one manifest entry the fake home updates in these tests."""

    bare = tmp_path / f"{name}-bare.git"
    _run(["git", "init", "--bare", "-b", "main", str(bare)])

    target = tmp_path / name
    _run(["git", "clone", str(bare), str(target)])
    _run(["git", "-C", str(target), "config", "user.email", "test@example.com"])
    _run(["git", "-C", str(target), "config", "user.name", "Test"])

    (target / "config").mkdir()
    (target / "config" / "orchestration.json").write_text(json.dumps({
        "repo": "someone/target-repo",
        "brain_chat_title": "Brain",
        "context_line": 150000,
        "claude_projects_dir": "target-repo",
        "bridge_dir": "var/agentops",
        "bridge_lock": "var/locks/bridge.lock",
        "local_modules": [],
        "home": HOME_REPO,
        "core_version": core_version,
        "update_rule": update_rule,
    }, indent=2) + "\n", encoding="utf-8")

    (target / "tools" / "agentops").mkdir(parents=True)
    (target / "tools" / "agentops" / "core_manifest.txt").write_text("a.txt\n", encoding="utf-8")
    (target / "a.txt").write_text("A0\n", encoding="utf-8")

    _run(["git", "add", "."], cwd=target)
    _run(["git", "commit", "-m", "initial"], cwd=target)
    _run(["git", "push", "origin", "main"], cwd=target)
    return target, bare


HEAD_B = "b" * 40


def _run_update(rule: str, target: Path, gh_runner):
    """The two rules the brief asks row 5 to cover, both landing on `run_core_update` under the
    hood: `word` (called directly, as `run_update_command` would) and `auto` (through the
    dispatcher's own `apply_auto_core_update`)."""

    if rule == "word":
        return core_update.run_core_update(target, gh_runner=gh_runner)
    assert rule == "auto"
    settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    apply_auto_core_update(root=target, settings=settings, gh_runner=gh_runner)
    return None


@pytest.mark.parametrize("rule", ["word", "auto"])
def test_row1_update_commits_and_pushes_exactly_the_written_paths(tmp_path, rule) -> None:
    target, bare = _init_git_target(tmp_path, update_rule=rule)
    count_before = _commit_count(target)

    gh_runner = _stub_gh_runner(head=HEAD_B, manifest_text="a.txt\n", files={"a.txt": "A1\n"})
    _run_update(rule, target, gh_runner)

    assert _commit_count(target) == count_before + 1
    written_paths = {"a.txt", "config/orchestration.json", PATTERNS_ENTRY}
    assert _commit_files(target) == written_paths
    # `auto` also appends to `artifacts/runs/events.jsonl` (the dispatcher's own log line for this
    # run, `apply_auto_core_update`) -- untracked, outside the manifest, not part of this update
    porcelain = [line for line in _porcelain(target) if "artifacts/" not in line]
    assert porcelain == []
    assert _remote_head(bare) == _head(target)
    settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert settings["core_version"] == HEAD_B


@pytest.mark.parametrize("rule", ["word", "auto"])
def test_row2_the_targets_own_dirty_paths_are_untouched(tmp_path, rule) -> None:
    target, bare = _init_git_target(tmp_path, update_rule=rule)

    # two tracked files, modified but not committed
    (target / "a_own_tracked.txt").write_text("own tracked v0\n", encoding="utf-8")
    (target / "b_own_tracked.txt").write_text("own tracked v0\n", encoding="utf-8")
    _run(["git", "add", "a_own_tracked.txt", "b_own_tracked.txt"], cwd=target)
    _run(["git", "commit", "-m", "own tracked files"], cwd=target)
    _run(["git", "push", "origin", "main"], cwd=target)

    (target / "a_own_tracked.txt").write_text("own tracked v1 (dirty)\n", encoding="utf-8")
    (target / "b_own_tracked.txt").write_text("own tracked v1 (dirty)\n", encoding="utf-8")
    (target / "c_own_untracked.txt").write_text("own untracked (new)\n", encoding="utf-8")

    own_paths = {"a_own_tracked.txt", "b_own_tracked.txt", "c_own_untracked.txt"}
    before_lines = {line for line in _porcelain(target) if any(p in line for p in own_paths)}
    assert len(before_lines) == 3

    gh_runner = _stub_gh_runner(head=HEAD_B, manifest_text="a.txt\n", files={"a.txt": "A1\n"})
    _run_update(rule, target, gh_runner)

    after_lines = {line for line in _porcelain(target) if any(p in line for p in own_paths)}
    assert after_lines == before_lines
    assert own_paths.isdisjoint(_commit_files(target))


@pytest.mark.parametrize("rule", ["word", "auto"])
def test_row3_a_dirty_path_the_update_writes_refuses_and_writes_nothing(tmp_path, rule, capsys) -> None:
    target, bare = _init_git_target(tmp_path, update_rule=rule)
    dirty_content = "A0 (locally dirty)\n"
    (target / "a.txt").write_text(dirty_content, encoding="utf-8")
    head_before = _head(target)

    gh_runner = _stub_gh_runner(head=HEAD_B, manifest_text="a.txt\n", files={"a.txt": "A1\n"})

    if rule == "word":
        with pytest.raises(core_update.CoreUpdateError, match="a.txt"):
            core_update.run_core_update(target, gh_runner=gh_runner)
    else:
        settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
        apply_auto_core_update(root=target, settings=settings, gh_runner=gh_runner)
        printed = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(printed) == 1
        assert "a.txt" in printed[0]
        assert "refused" in printed[0]

    assert (target / "a.txt").read_text(encoding="utf-8") == dirty_content
    settings_after = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert settings_after["core_version"] == "A" * 40
    assert _head(target) == head_before


def test_row4_a_refused_push_is_undone_in_full_no_forced_push(tmp_path) -> None:
    target, bare = _init_git_target(tmp_path, update_rule="word")
    head_before = _head(target)
    a_txt_before = (target / "a.txt").read_bytes()
    manifest_before = (target / "tools" / "agentops" / "core_manifest.txt").read_bytes()
    settings_before = (target / "config" / "orchestration.json").read_bytes()

    # a second clone pushes first, moving the bare remote's main out from under `target`
    other = tmp_path / "other-clone"
    _run(["git", "clone", str(bare), str(other)])
    _run(["git", "-C", str(other), "config", "user.email", "other@example.com"])
    _run(["git", "-C", str(other), "config", "user.name", "Other"])
    (other / "unrelated.txt").write_text("someone else's commit\n", encoding="utf-8")
    _run(["git", "add", "unrelated.txt"], cwd=other)
    _run(["git", "commit", "-m", "unrelated, pushed first"], cwd=other)
    _run(["git", "push", "origin", "main"], cwd=other)
    moved_remote_head = _remote_head(bare)
    assert moved_remote_head != head_before

    gh_runner = _stub_gh_runner(head=HEAD_B, manifest_text="a.txt\n", files={"a.txt": "A1\n"})
    with pytest.raises(core_update.CoreUpdateError, match="push refused"):
        core_update.run_core_update(target, gh_runner=gh_runner)

    assert _head(target) == head_before
    assert (target / "a.txt").read_bytes() == a_txt_before
    assert (target / "tools" / "agentops" / "core_manifest.txt").read_bytes() == manifest_before
    assert (target / "config" / "orchestration.json").read_bytes() == settings_before
    settings_after = json.loads(settings_before.decode("utf-8"))
    assert settings_after["core_version"] == "A" * 40
    # no forced push: the remote still holds the other clone's commit, not overwritten
    assert _remote_head(bare) == moved_remote_head


def test_an_own_staged_path_is_not_swept_into_the_updates_commit(tmp_path) -> None:
    """The coordinator's fix 1: `git commit -m ...` alone commits the whole index, so an own path
    the target had already staged (its own `git add`, unrelated to the update) would land in the
    update's commit too. `_commit_and_push` must commit only its own paths (`--only`)."""

    target, bare = _init_git_target(tmp_path, update_rule="word")
    (target / "own_staged.txt").write_text("the owner's own staged work\n", encoding="utf-8")
    _run(["git", "add", "own_staged.txt"], cwd=target)
    staged_before = _git(target, "diff", "--cached", "--name-only").stdout.splitlines()
    assert staged_before == ["own_staged.txt"]

    gh_runner = _stub_gh_runner(head=HEAD_B, manifest_text="a.txt\n", files={"a.txt": "A1\n"})
    core_update.run_core_update(target, gh_runner=gh_runner)

    assert "own_staged.txt" not in _commit_files(target)
    staged_after = _git(target, "diff", "--cached", "--name-only").stdout.splitlines()
    assert staged_after == staged_before


def test_row4_undo_removes_a_new_path_and_restores_a_modified_one(tmp_path) -> None:
    """The coordinator's fix 2: after `git reset --soft HEAD~1`, a path the update itself created
    is not in `HEAD` any more, so a single `git restore --source=HEAD` over every written path
    fails outright. New paths must be unstaged and deleted; only pre-existing paths are restored
    from `HEAD`."""

    target, bare = _init_git_target(tmp_path, update_rule="word")
    head_before = _head(target)
    a_txt_before = (target / "a.txt").read_bytes()
    porcelain_before = _porcelain(target)

    other = tmp_path / "other-clone-2"
    _run(["git", "clone", str(bare), str(other)])
    _run(["git", "-C", str(other), "config", "user.email", "other@example.com"])
    _run(["git", "-C", str(other), "config", "user.name", "Other"])
    (other / "unrelated.txt").write_text("someone else's commit\n", encoding="utf-8")
    _run(["git", "add", "unrelated.txt"], cwd=other)
    _run(["git", "commit", "-m", "unrelated, pushed first"], cwd=other)
    _run(["git", "push", "origin", "main"], cwd=other)
    moved_remote_head = _remote_head(bare)
    assert moved_remote_head != head_before

    # the update both modifies `a.txt` and adds a brand new manifest entry, `new_file.txt`
    gh_runner = _stub_gh_runner(
        head=HEAD_B, manifest_text="a.txt\nnew_file.txt\n",
        files={"a.txt": "A1\n", "new_file.txt": "brand new\n"},
    )
    with pytest.raises(core_update.CoreUpdateError, match="push refused"):
        core_update.run_core_update(target, gh_runner=gh_runner)

    assert not (target / "new_file.txt").exists()
    assert (target / "a.txt").read_bytes() == a_txt_before
    assert _head(target) == head_before
    assert _porcelain(target) == porcelain_before
    settings_after = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert settings_after["core_version"] == "A" * 40
    assert _remote_head(bare) == moved_remote_head


# -- #316: one `core update` runs the post-copy steps of the UPDATED code, in the one commit ---

TEMPLATE_ENTRY = "config/core_templates/settings.hooks.json"
DENY_RULE = "mcp__ccd_session_mgmt__clear_session"


def _template_text() -> str:
    return json.dumps({
        "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python x.py"}]}]},
        "permissions": {"deny": [DENY_RULE]},
    }, indent=2) + "\n"


def _status_gh_runner(head: str, manifest_text: str, files: dict[str, str]):
    base = _stub_gh_runner(head=head, manifest_text=manifest_text, files=files)

    def runner(args):
        if tuple(args[:2]) == ("issue", "list"):
            return _fake_result(stdout="[]")
        if len(args) > 1 and "/compare/" in args[1]:
            return _fake_result(stdout="")  # the taken range holds no commit here
        return base(args)

    return runner


def test_316_one_update_brings_and_runs_the_deny_step_in_one_commit(tmp_path, monkeypatch) -> None:
    target, bare = _init_git_target(tmp_path)
    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text(json.dumps({"model": "x"}, indent=2) + "\n",
                                                       encoding="utf-8")
    manifest = f"a.txt\n{TEMPLATE_ENTRY}\n"
    (target / "tools" / "agentops" / "core_manifest.txt").write_text(manifest, encoding="utf-8")
    _run(["git", "add", "."], cwd=target)
    _run(["git", "commit", "-m", "settings"], cwd=target)
    count_before = _commit_count(target)

    # the running process holds the OLD code: no deny step
    real_merge = core_update._merge_permissions_deny
    monkeypatch.setattr(core_update, "_merge_permissions_deny", lambda settings, template: False)

    def updated_code_steps(root: Path) -> list[str]:
        monkeypatch.setattr(core_update, "_merge_permissions_deny", real_merge)
        return core_update.run_update_steps(root)

    files = {"a.txt": "A1\n", TEMPLATE_ENTRY: _template_text()}
    core_update.run_core_update(target, gh_runner=_stub_gh_runner(head=HEAD_B, manifest_text=manifest, files=files),
                                step_runner=updated_code_steps)

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["deny"] == [DENY_RULE]
    assert settings["model"] == "x"
    assert _commit_count(target) == count_before + 1
    assert ".claude/settings.json" in _commit_files(target)
    assert _porcelain(target) == []
    assert _remote_head(bare) == _head(target)

    status_runner = _status_gh_runner(HEAD_B, manifest, files)
    assert core_update.run_core_status(target, gh_runner=status_runner).changes == 0


def test_316_real_subprocess_runs_update_steps_in_the_target(tmp_path) -> None:
    repo = Path(core_update.__file__).resolve().parents[2]
    target = tmp_path / "t"
    (target / "config" / "core_templates").mkdir(parents=True)
    (target / ".claude").mkdir()
    shutil.copytree(repo / "tools", target / "tools", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(repo / "scripts", target / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    (target / "config" / "orchestration.json").write_text(json.dumps({
        "repo": "someone/target-repo", "brain_chat_title": "Brain", "context_line": 150000,
        "claude_projects_dir": "target-repo", "bridge_dir": "var/agentops",
        "bridge_lock": "var/locks/bridge.lock", "local_modules": [], "home": HOME_REPO}), encoding="utf-8")
    (target / TEMPLATE_ENTRY).write_text(_template_text(), encoding="utf-8")
    (target / ".claude" / "settings.json").write_text("{}\n", encoding="utf-8")

    paths = core_update._subprocess_step_runner(target)

    assert paths == [PATTERNS_ENTRY, ".claude/settings.json"]
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["deny"] == [DENY_RULE]
    assert core_update._subprocess_step_runner(target) == []
