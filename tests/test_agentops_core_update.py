"""tools/agentops/core_update.py (issue #153): `core status` / `core update`, run in a target.
No network: the home's GitHub read is stubbed by a fixture (a fake ``gh`` runner over canned
commits/files/manifests); every target is a git repo under ``tmp_path``."""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from tools.agentops import core_update
from tools.agentops.dispatch import apply_auto_core_update
from tools.agentops.leak_starter import PATTERNS_ENTRY  # #93: the starter the update writes when the target has none
from tests.test_agentops_core_update_881 import FakeHome

# -- #354 U2: the permission guard's registration and deny lines (moved from test_agentops_port) --

GUARD_DENY = [
    "mcp__ccd_session_mgmt__set_session_permission_mode", "Bash(git push --force*)", "Bash(git push -f*)",
    "Bash(git clean*)", "Bash(git worktree remove*)", "Bash(gh repo delete*)", "Bash(gh issue delete*)",
    "Bash(gh auth token*)", "Bash(format *)", "Bash(diskpart*)", "Bash(shutdown*)", "Bash(bcdedit*)",
]
GUARD_MATCHER = "Bash|PowerShell|Edit|Write|MultiEdit"
GUARD_COMMAND = 'python "$CLAUDE_PROJECT_DIR/tools/hooks/permission_guard.py"'

HOME_REPO = "someone/home-repo"

C0 = "c0000000" * 5  # the target's starting core_version
C1 = "c1111111" * 5  # touches a.txt (in the manifest)
C2 = "c2222222" * 5  # touches readme.txt (not in the manifest)
C3 = "c3333333" * 5  # the home's head: touches the manifest itself and b.txt


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _fake_result(stdout="", returncode=0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _tree_json(files: dict[str, str]) -> str:
    """The home's ``git/trees/<sha>?recursive=1`` answer over ``files`` (path -> text): every file a blob with its
    real git blob sha (computed here, as git does), not truncated (#148), so the update reads the tree once and
    fetches only what it lacks."""
    def blob_sha(text: str) -> str:
        data = text.encode("utf-8")
        return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

    return json.dumps({"truncated": False, "tree": [
        {"path": path, "mode": "100644", "type": "blob", "sha": blob_sha(text)}
        for path, text in files.items()]})


def _home_gh_runner(*, home_head: str = C3, manifest_at_head: str = "a.txt\nb.txt\n",
                     a_txt: str = "A1\n", b_txt: str = "B\n", extra_files: dict[str, str] | None = None):
    """A fixture standing in for the home's GitHub repo at C0 -> C1 -> C2 -> C3, without network.
    ``extra_files`` adds more ``path: content`` pairs the home is asked for at ``home_head``
    (issue #224: a manifest entry that is also a ``TARGET_OWNED_ENTRIES`` path)."""

    history = FakeHome([{"sha": C0, "parents": [], "files": []},
                        {"sha": C1, "parents": [C0], "files": ["a.txt"]},
                        {"sha": C2, "parents": [C1], "files": ["readme.txt"]},
                        {"sha": C3, "parents": [C2], "files": ["tools/agentops/core_manifest.txt", "b.txt"]}],
                       [], C0)
    served = {"tools/agentops/core_manifest.txt": manifest_at_head, "a.txt": a_txt, "b.txt": b_txt,
              **(extra_files or {})}
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): home_head + "\n",
        ("issue", "list", "--repo", HOME_REPO, "--label", "core-issue", "--state", "all",
         "--limit", "500", "--json", "number,title,body,state"): "[]",
        ("api", f"repos/{HOME_REPO}/git/trees/{home_head}?recursive=1"): _tree_json(served),
    }
    for path, content in served.items():
        table[("api", f"repos/{HOME_REPO}/contents/{path}?ref={home_head}", "--jq", ".content")] = _b64(content)

    def runner(args):
        key = tuple(args)
        if len(args) > 1 and ("/compare/" in args[1] or args[1] == "graphql"):
            return history.runner(args)
        if key not in table:
            raise AssertionError(f"unexpected gh call: {args}")
        return _fake_result(stdout=table[key])

    return runner


def _init_target(tmp_path: Path, *, update_rule: str = "word", core_version: str = C0) -> Path:
    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").mkdir()
    (target / "config").mkdir()
    (target / "config" / "orchestration.json").write_text(json.dumps({
        "repo": "someone/target-repo",
        "brain_chat_title": "Brain",
        "context_line": 150000,
        "claude_projects_dir": "target-repo",
        "bridge_dir": str(target / "var" / "agentops"),
        "bridge_lock": "var/locks/bridge.lock",
        "local_modules": [],
        "home": HOME_REPO,
        "core_version": core_version,
        "update_rule": update_rule,
    }, indent=2), encoding="utf-8")

    tools_dir = target / "tools" / "agentops"
    tools_dir.mkdir(parents=True)
    (tools_dir / "core_manifest.txt").write_text("a.txt\nold.txt\n", encoding="utf-8")
    (target / "a.txt").write_text("A0\n", encoding="utf-8")
    (target / "old.txt").write_text("OLD\n", encoding="utf-8")

    # the target's own files, to prove requirement 4
    (target / "CLAUDE.md").write_text("# my repo\nown rule\n", encoding="utf-8")
    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text(json.dumps({"permissions": {}}), encoding="utf-8")
    (target / "docs" / "agents" / "local").mkdir(parents=True)
    (target / "docs" / "agents" / "local" / "orch.md").write_text("own local orch notes\n", encoding="utf-8")
    return target


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


OWN_FILES = ["CLAUDE.md", ".claude/settings.json", "docs/agents/local/orch.md"]


def _own_shas(target: Path) -> dict[str, str]:
    return {f: _sha256(target / f) for f in OWN_FILES}


# -- acceptance 1: `word` -------------------------------------------------------------------

def test_word_status_counts_changes_touching_the_manifest_and_leaves_files_untouched(tmp_path) -> None:
    target = _init_target(tmp_path)
    before = _sha256(target / "a.txt"), _sha256(target / "old.txt"), _sha256(target / "tools/agentops/core_manifest.txt")

    result = core_update.run_core_status(target, gh_runner=_home_gh_runner())

    assert result.changes == 2  # C1 and C3 touch the manifest; C2 does not
    after = _sha256(target / "a.txt"), _sha256(target / "old.txt"), _sha256(target / "tools/agentops/core_manifest.txt")
    assert before == after


def test_word_update_rewrites_only_the_differing_files_and_sets_core_version(tmp_path) -> None:
    target = _init_target(tmp_path)

    result = core_update.run_core_update(target, gh_runner=_home_gh_runner())

    assert set(result.changed) == {"a.txt", "b.txt", PATTERNS_ENTRY}
    assert (target / "a.txt").read_text(encoding="utf-8") == "A1\n"
    assert (target / "b.txt").read_text(encoding="utf-8") == "B\n"
    settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    assert settings["core_version"] == C3


def test_word_second_update_changes_zero_files(tmp_path) -> None:
    # the home's manifest lists itself (core_manifest.txt does): the first update rewrites the target's copy,
    # so the second one sees no dropped entry; without the self entry the target's manifest never moves
    manifest = "a.txt\nb.txt\ntools/agentops/core_manifest.txt\n"
    target = _init_target(tmp_path)
    core_update.run_core_update(target, gh_runner=_home_gh_runner(manifest_at_head=manifest))

    result = core_update.run_core_update(target, gh_runner=_home_gh_runner(manifest_at_head=manifest))

    assert result.changed == []
    assert result.removed == []


# -- issue #224: TARGET_OWNED_ENTRIES are never rewritten by `core update` --------------------

def test_core_update_never_touches_target_owned_entries_even_when_home_differs(tmp_path) -> None:
    from tools.agentops.port import TARGET_OWNED_ENTRIES

    target = _init_target(tmp_path)
    owned_entry = sorted(TARGET_OWNED_ENTRIES)[0]
    owned_path = target / owned_entry
    owned_path.parent.mkdir(parents=True, exist_ok=True)
    owned_path.write_text("the target's own answers\n", encoding="utf-8")
    (target / "tools" / "agentops" / "core_manifest.txt").write_text(
        f"a.txt\nold.txt\n{owned_entry}\n", encoding="utf-8"
    )
    before = owned_path.read_text(encoding="utf-8")

    runner = _home_gh_runner(
        manifest_at_head=f"a.txt\nb.txt\n{owned_entry}\n",
        extra_files={owned_entry: "home's different content\n"},
    )
    result = core_update.run_core_update(target, gh_runner=runner)

    assert owned_entry not in result.changed
    assert owned_path.read_text(encoding="utf-8") == before


# -- acceptance 2: `auto` --------------------------------------------------------------------

def test_auto_update_applied_before_first_tick_with_one_log_line(tmp_path) -> None:
    target = _init_target(tmp_path, update_rule="auto")
    events_file = target / "artifacts" / "runs" / "events.jsonl"

    apply_auto_core_update(root=target, settings=json.loads(
        (target / "config" / "orchestration.json").read_text(encoding="utf-8")
    ), gh_runner=_home_gh_runner())

    assert (target / "a.txt").read_text(encoding="utf-8") == "A1\n"
    assert (target / "b.txt").read_text(encoding="utf-8") == "B\n"
    assert not (target / "old.txt").exists()
    lines = events_file.read_text(encoding="utf-8").splitlines()
    core_update_lines = [json.loads(l) for l in lines if json.loads(l).get("kind") == "core_update_auto"]
    assert len(core_update_lines) == 1


# -- acceptance 3: `home` --------------------------------------------------------------------

def test_home_rule_changes_nothing_and_exits_zero(tmp_path) -> None:
    target = _init_target(tmp_path, update_rule="home")
    before = _own_shas(target)

    status = core_update.run_core_status(target)
    update = core_update.run_core_update(target)

    assert status.changes == 0
    assert update.changed == []
    assert update.removed == []
    assert _own_shas(target) == before


# -- acceptance 4: the target's own files are safe --------------------------------------------

def test_own_files_are_byte_identical_except_core_version(tmp_path) -> None:
    target = _init_target(tmp_path)
    before = _own_shas(target)
    before_settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))

    core_update.run_core_update(target, gh_runner=_home_gh_runner())

    assert _own_shas(target) == before
    after_settings = json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))
    changed_keys = {k for k in after_settings if after_settings.get(k) != before_settings.get(k)}
    assert changed_keys == {"core_version", "core_version_before"}


# -- acceptance 5: the manifest moves ----------------------------------------------------------

def test_manifest_move_removes_one_and_adds_one(tmp_path) -> None:
    target = _init_target(tmp_path)

    result = core_update.run_core_update(target, gh_runner=_home_gh_runner())

    assert result.removed == ["old.txt"]
    assert not (target / "old.txt").exists()
    assert "b.txt" in result.changed  # newly added by the manifest move


# -- acceptance 6: a live ORCH ------------------------------------------------------------------

def test_live_orch_refuses_the_update_and_changes_nothing(tmp_path) -> None:
    target = _init_target(tmp_path)
    (target / "artifacts" / "runs").mkdir(parents=True)
    (target / "artifacts" / "runs" / "orch_session.json").write_text(
        json.dumps({"session": "abc123"}), encoding="utf-8"
    )
    before = _sha256(target / "a.txt")

    with pytest.raises(core_update.CoreUpdateError):
        core_update.run_core_update(target, gh_runner=_home_gh_runner())

    assert _sha256(target / "a.txt") == before
    assert not (target / "b.txt").exists()


def test_is_orch_live_reads_the_dispatchers_own_state_file(tmp_path) -> None:
    target = _init_target(tmp_path)
    assert core_update.is_orch_live(target) is False

    (target / "artifacts" / "runs").mkdir(parents=True)
    (target / "artifacts" / "runs" / "orch_session.json").write_text(
        json.dumps({"session": "abc123"}), encoding="utf-8"
    )
    assert core_update.is_orch_live(target) is True

    (target / "artifacts" / "runs" / "orch_session.json").write_text(
        json.dumps({"session": None}), encoding="utf-8"
    )
    assert core_update.is_orch_live(target) is False


# -- issue #228: a hook's file travels through the manifest, but a target's own
# `.claude/settings.json` never gets it registered ------------------------------------------------

HOOKS_ENTRY = "config/core_templates/settings.hooks.json"
H1 = "h1111111" * 5  # the home's head after the new hook was added

OLD_HOOKS_TEMPLATE = json.dumps({
    "enabledPlugins": {"mattpocock-skills@mattpocock": True},
    "hooks": {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "python \"$CLAUDE_PROJECT_DIR/tools/hooks/brain_reset_nudge.py\""}]}
        ],
    },
}, indent=2) + "\n"

NEW_HOOKS_TEMPLATE = json.dumps({
    "enabledPlugins": {"mattpocock-skills@mattpocock": True},
    "hooks": {
        "PermissionRequest": [
            {"hooks": [{"type": "command",
                        "command": "python \"$CLAUDE_PROJECT_DIR/tools/hooks/refuse_permission_prompt.py\"",
                        "timeout": 20}]}
        ],
        "UserPromptSubmit": [
            {"hooks": [{"type": "command",
                        "command": "python \"$CLAUDE_PROJECT_DIR/tools/hooks/brain_reset_nudge.py\""}]}
        ],
    },
}, indent=2) + "\n"


def _hooks_home_gh_runner():
    """The home at H1: one commit touching `a.txt` and the hooks template (one hook more than
    the target's own, already-ported copy)."""

    history = FakeHome([{"sha": C0, "parents": [], "files": []},
                        {"sha": H1, "parents": [C0], "files": ["a.txt", HOOKS_ENTRY]}], [], C0)
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): H1 + "\n",
        ("api", f"repos/{HOME_REPO}/git/trees/{H1}?recursive=1"): _tree_json({
            "a.txt": "A1\n", "tools/agentops/core_manifest.txt": f"a.txt\n{HOOKS_ENTRY}\n", HOOKS_ENTRY: NEW_HOOKS_TEMPLATE}),
        ("api", f"repos/{HOME_REPO}/contents/tools/agentops/core_manifest.txt?ref={H1}", "--jq", ".content"):
            _b64(f"a.txt\n{HOOKS_ENTRY}\n"),
        ("api", f"repos/{HOME_REPO}/contents/a.txt?ref={H1}", "--jq", ".content"): _b64("A1\n"),
        ("api", f"repos/{HOME_REPO}/contents/{HOOKS_ENTRY}?ref={H1}", "--jq", ".content"):
            _b64(NEW_HOOKS_TEMPLATE),
        ("issue", "list", "--repo", HOME_REPO, "--label", "core-issue", "--state", "all",
         "--limit", "500", "--json", "number,title,body,state"): "[]",
    }

    def runner(args):
        key = tuple(args)
        if len(args) > 1 and ("/compare/" in args[1] or args[1] == "graphql"):
            return history.runner(args)
        if key not in table:
            raise AssertionError(f"unexpected gh call: {args}")
        return _fake_result(stdout=table[key])

    return runner


def _init_hooks_target(tmp_path: Path) -> Path:
    """A target already ported with the *older* template: the hook file on disk names one hook
    (`UserPromptSubmit`) and `.claude/settings.json` already registers exactly that one, plus the
    target's own permissions and a second, unrelated plugin entry (proof of acceptance 2)."""

    target = tmp_path / "target"
    target.mkdir()
    (target / ".git").mkdir()
    (target / "config" / "core_templates").mkdir(parents=True)
    (target / "config" / "orchestration.json").write_text(json.dumps({
        "repo": "someone/target-repo",
        "brain_chat_title": "Brain",
        "context_line": 150000,
        "claude_projects_dir": "target-repo",
        "bridge_dir": str(target / "var" / "agentops"),
        "bridge_lock": "var/locks/bridge.lock",
        "local_modules": [],
        "home": HOME_REPO,
        "core_version": C0,
        "update_rule": "word",
    }, indent=2), encoding="utf-8")

    tools_dir = target / "tools" / "agentops"
    tools_dir.mkdir(parents=True)
    (tools_dir / "core_manifest.txt").write_text(f"a.txt\n{HOOKS_ENTRY}\n", encoding="utf-8")
    (target / "a.txt").write_text("A0\n", encoding="utf-8")
    (target / "config" / "core_templates" / "settings.hooks.json").write_text(
        OLD_HOOKS_TEMPLATE, encoding="utf-8"
    )

    (target / ".claude").mkdir()
    (target / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(ls:*)"]},
        "enabledPlugins": {
            "mattpocock-skills@mattpocock": True,
            "someone-else@some-marketplace": True,
        },
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command",
                            "command": "python \"$CLAUDE_PROJECT_DIR/tools/hooks/brain_reset_nudge.py\""}]}
            ],
        },
    }, indent=2), encoding="utf-8")
    return target


def test_core_update_registers_the_missing_hook_n_of_n(tmp_path) -> None:
    """Acceptance 1 + 3: after `core update` brings the newer template, all of the template's
    hooks are registered, and the report line names the count."""

    target = _init_hooks_target(tmp_path)

    result = core_update.run_core_update(target, gh_runner=_hooks_home_gh_runner())

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["PermissionRequest"]
    assert settings["hooks"]["UserPromptSubmit"]
    assert result.hooks_registered == result.hooks_total == 2
    assert "2/2 hook(s) registered" in result.message


def test_core_update_leaves_the_targets_own_settings_alone_twice_in_a_row(tmp_path) -> None:
    """Acceptance 2: the target's own permissions and second plugin entry are untouched, and a
    second `core update` in a row neither loses nor doubles anything."""

    target = _init_hooks_target(tmp_path)

    core_update.run_core_update(target, gh_runner=_hooks_home_gh_runner())
    result2 = core_update.run_core_update(target, gh_runner=_hooks_home_gh_runner())

    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]
    assert settings["enabledPlugins"]["someone-else@some-marketplace"] is True
    assert len(settings["hooks"]["PermissionRequest"]) == 1
    assert len(settings["hooks"]["UserPromptSubmit"]) == 1
    assert result2.hooks_registered == result2.hooks_total == 2


def test_core_status_counts_a_missing_registration_as_a_change_waiting(tmp_path) -> None:
    """Acceptance 4: `core_version` already matches the home's head (no file content differs), but
    `.claude/settings.json` never registered the hook that arrived with it -- still a change
    waiting."""

    target = _init_hooks_target(tmp_path)
    # simulate an update that copied the newer template file but (pre-fix) never merged it in:
    target_settings = target / "config" / "orchestration.json"
    data = json.loads(target_settings.read_text(encoding="utf-8"))
    data["core_version"] = H1
    target_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")
    (target / "config" / "core_templates" / "settings.hooks.json").write_text(
        NEW_HOOKS_TEMPLATE, encoding="utf-8"
    )

    result = core_update.run_core_status(target, gh_runner=_hooks_home_gh_runner())

    assert result.changes == 1


def test_is_orch_live_true_while_every_live_session_is_finishing(tmp_path) -> None:
    """#191: two live sessions, both finishing -- the top-level `session` mirrors none of them
    (`null`), but `sessions` is non-empty, so `is_orch_live` must still be True (#153 acceptance 6:
    `core update` refuses while ANY ORCH is live, finishing ones included)."""

    target = _init_target(tmp_path)
    (target / "artifacts" / "runs").mkdir(parents=True)
    (target / "artifacts" / "runs" / "orch_session.json").write_text(
        json.dumps({
            "session": None,
            "sessions": [
                {"session": "s1", "held": [1], "finishing": True},
                {"session": "s2", "held": [2, 3], "finishing": True},
            ],
        }), encoding="utf-8"
    )

    assert core_update.is_orch_live(target) is True

    (target / "artifacts" / "runs" / "orch_session.json").write_text(
        json.dumps({"session": None, "sessions": []}), encoding="utf-8"
    )
    assert core_update.is_orch_live(target) is False


# -- #312: the deny of clear_session travels through core update / core status ---------------

DENY_RULE = "mcp__ccd_session_mgmt__clear_session"


def _deny_template_gh_runner():
    template = json.loads(NEW_HOOKS_TEMPLATE)
    template["permissions"] = {"deny": [DENY_RULE]}
    text = json.dumps(template, indent=2) + "\n"
    base = _hooks_home_gh_runner()

    def runner(args):
        if tuple(args) == ("api", f"repos/{HOME_REPO}/contents/{HOOKS_ENTRY}?ref={H1}", "--jq", ".content"):
            return _fake_result(stdout=_b64(text))
        return base(args)

    return runner


def test_312_core_update_appends_the_deny_and_a_second_run_writes_nothing(tmp_path) -> None:
    target = _init_hooks_target(tmp_path)
    path = target / ".claude" / "settings.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["permissions"] = {"allow": ["A1", "A2"], "deny": ["D1", "D2"]}
    data["model"] = "x"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    core_update.run_core_update(target, gh_runner=_deny_template_gh_runner())
    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"]["deny"] == ["D1", "D2", DENY_RULE]
    assert settings["permissions"]["allow"] == ["A1", "A2"]
    assert settings["model"] == "x"

    before = path.read_bytes()
    core_update.run_core_update(target, gh_runner=_deny_template_gh_runner())
    assert path.read_bytes() == before


def test_312_core_status_names_the_missing_deny_as_a_change(tmp_path) -> None:
    target = _init_hooks_target(tmp_path)
    cfg = target / "config" / "orchestration.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["core_version"] = H1
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    template = json.loads(NEW_HOOKS_TEMPLATE)
    template["permissions"] = {"deny": [DENY_RULE]}
    (target / HOOKS_ENTRY).write_text(json.dumps(template), encoding="utf-8")
    settings_path = target / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["hooks"]["PermissionRequest"] = template["hooks"]["PermissionRequest"]
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    result = core_update.run_core_status(target, gh_runner=_hooks_home_gh_runner())

    assert result.changes == 1
    lines = [ln for ln in result.message.splitlines() if "lacks permissions.deny" in ln]
    assert lines == [f".claude/settings.json lacks permissions.deny: {DENY_RULE} (core update adds it)"]


# -- #313: `core status` exits 1 while any change waits, 0 when none ----------------------------

_orig_status = core_update.run_core_status


def test_313_status_exit_code_is_1_while_a_change_waits_and_0_after_update(tmp_path, monkeypatch, capsys) -> None:
    from types import SimpleNamespace

    target = _init_target(tmp_path)
    monkeypatch.setattr(core_update, "ROOT", target)
    runner = _home_gh_runner()
    monkeypatch.setattr(core_update, "run_core_status",
                        lambda root, gh_runner=None: _orig_status(root, gh_runner=runner))

    assert core_update.run_status_command(SimpleNamespace()) == 1
    assert "2 core change(s) waiting" in capsys.readouterr().out

    core_update.run_core_update(target, gh_runner=runner)
    assert core_update.run_status_command(SimpleNamespace()) == 0
    assert "0 core change(s) waiting" in capsys.readouterr().out


# -- #354 U2: the permission guard's registration and deny lines travel through core update ------

def test_354_core_update_registers_the_guard_hook_and_all_twelve_deny_lines(tmp_path) -> None:
    real = (Path(__file__).resolve().parents[1] / HOOKS_ENTRY).read_text(encoding="utf-8")
    base = _hooks_home_gh_runner()

    def runner(args):
        if tuple(args) == ("api", f"repos/{HOME_REPO}/contents/{HOOKS_ENTRY}?ref={H1}", "--jq", ".content"):
            return _fake_result(stdout=_b64(real))
        return base(args)

    target = _init_hooks_target(tmp_path)
    core_update.run_core_update(target, gh_runner=runner)
    settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
    guards = [e for e in settings["hooks"]["PreToolUse"]
              if e.get("matcher") == GUARD_MATCHER and e["hooks"][0]["command"] == GUARD_COMMAND]
    assert len(guards) == 1
    assert all(rule in settings["permissions"]["deny"] for rule in GUARD_DENY)
