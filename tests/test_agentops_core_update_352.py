"""Issue #352: the preflight dirty check covers `.claude/settings.json` even when only the UPDATED
code's post-copy step would write it, and a failed step undoes the copy so a rerun is a full run.
Built the way #316's tests are: a real git target under `tmp_path`, the home's GitHub read stubbed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.agentops import core_update
from tests.test_agentops_core_update_commit import (
    DENY_RULE,
    HEAD_B,
    TEMPLATE_ENTRY,
    _commit_count,
    _commit_files,
    _git,
    _head,
    _init_git_target,
    _remote_head,
    _run,
    _status_gh_runner,
    _stub_gh_runner,
    _template_text,
)

HOOKS = {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python x.py"}]}]}
MANIFEST = f"a.txt\nnew.txt\n{TEMPLATE_ENTRY}\n"
FILES = {"a.txt": "A1\n", "new.txt": "N1\n", TEMPLATE_ENTRY: _template_text()}


def _status_short(target: Path) -> str:
    # the core's own run log writes `artifacts/` (untracked here, ignored in a real target): not a change of the update
    return "".join(f"{line}\n" for line in _git(target, "status", "--short").stdout.splitlines()
                   if line[3:] != "artifacts/")


def _target_with_hooks_registered(tmp_path: Path) -> tuple[Path, Path]:
    """The hook is already registered, so the OLD preview writes nothing into settings.json:
    only the deny step of the updated code does."""

    target, bare = _init_git_target(tmp_path)
    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text(json.dumps({"model": "x", "hooks": HOOKS}, indent=2) + "\n",
                                                       encoding="utf-8")
    (target / "tools" / "agentops" / "core_manifest.txt").write_text(MANIFEST, encoding="utf-8")
    _run(["git", "add", "."], cwd=target)
    _run(["git", "commit", "-m", "settings"], cwd=target)
    _run(["git", "push", "origin", "main"], cwd=target)
    return target, bare


def _old_code_without_deny(monkeypatch):
    """The running process holds the OLD code (no deny step); the step runner brings the new one."""

    real_merge = core_update._merge_permissions_deny
    monkeypatch.setattr(core_update, "_merge_permissions_deny", lambda settings, template: False)

    def updated_code_steps(root: Path) -> list[str]:
        monkeypatch.setattr(core_update, "_merge_permissions_deny", real_merge)
        return core_update.run_update_steps(root)

    return updated_code_steps


def _version(target: Path) -> str:
    return json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))["core_version"]


def test_352_a_own_settings_edit_is_refused_when_only_the_step_writes_it(tmp_path, monkeypatch) -> None:
    target, _ = _target_with_hooks_registered(tmp_path)
    settings_path = target / ".claude" / "settings.json"
    settings_path.write_text(json.dumps({"model": "own edit", "hooks": HOOKS}, indent=2) + "\n", encoding="utf-8")
    status_before = _status_short(target)
    head_before = _head(target)
    steps = _old_code_without_deny(monkeypatch)
    # the premise: the old preview does not see a settings.json change
    pending = {TEMPLATE_ENTRY: _template_text().encode("utf-8")}
    assert core_update._preview_hooks_template(target, pending)[2] is False

    with pytest.raises(core_update.CoreUpdateError) as err:
        core_update.run_core_update(target, gh_runner=_stub_gh_runner(head=HEAD_B, manifest_text=MANIFEST, files=FILES),
                                    step_runner=steps)

    assert str(err.value) == "core update refused: uncommitted change(s) at .claude/settings.json"
    assert _status_short(target) == status_before  # 0 files written
    assert (target / "a.txt").read_text(encoding="utf-8") == "A0\n"
    assert not (target / "new.txt").exists()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["model"] == "own edit"
    assert _version(target) == "A" * 40
    assert _head(target) == head_before


def test_352_b_a_failed_step_undoes_the_copy_and_the_rerun_is_one_full_commit(tmp_path, monkeypatch) -> None:
    target, bare = _target_with_hooks_registered(tmp_path)
    count_before = _commit_count(target)
    steps = _old_code_without_deny(monkeypatch)

    def failing_steps(root: Path) -> list[str]:
        # half-done work of the step before it fails: settings.json is touched too
        (root / ".claude" / "settings.json").write_text("{broken", encoding="utf-8")
        raise core_update.CoreUpdateError("core update: the post-copy steps failed (exit 1): boom")

    with pytest.raises(core_update.CoreUpdateError, match="boom"):
        core_update.run_core_update(target, gh_runner=_stub_gh_runner(head=HEAD_B, manifest_text=MANIFEST, files=FILES),
                                    step_runner=failing_steps)

    assert _status_short(target) == ""
    assert not (target / "new.txt").exists()
    assert _version(target) == "A" * 40
    assert _commit_count(target) == count_before

    core_update.run_core_update(target, gh_runner=_stub_gh_runner(head=HEAD_B, manifest_text=MANIFEST, files=FILES),
                                step_runner=steps)

    assert _commit_count(target) == count_before + 1
    committed = _commit_files(target)
    assert {"a.txt", "new.txt", TEMPLATE_ENTRY, ".claude/settings.json"} <= committed
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["deny"] == [DENY_RULE]
    assert _status_short(target) == ""
    assert _remote_head(bare) == _head(target)
    status = core_update.run_core_status(target, gh_runner=_status_gh_runner(HEAD_B, MANIFEST, FILES))
    assert status.changes == 0
    assert status.message.startswith("0 core change(s) waiting")
