"""`mods install` prints the two manual steps nobody else prints (#1043 acceptance 3).

The settings file and the commands folder are injected (temp paths); the user's home is redirected to tmp_path too,
so no test reads or writes the real ~/.claude.
"""

import json

import pytest

from tools.agentops import install_folder, mods

NAME = "x-src"
# the command file is written from the core stub with the mod's own COMMAND, TITLE and MOD_DIR (install_folder.command_step)
PROJECT_WITH_COMMAND = "export const COMMAND = 'x-cmd'\nexport const TITLE = 'X Mod'\nexport const MOD_DIR = 'C:/x/mod'\n"
TEMPLATE = b"---\ndescription: Open the pane\n---\nAnswered by the /pob command of its mod.\n"


@pytest.fixture
def mod(tmp_path, monkeypatch):
    repo, inst_root, home = tmp_path / "repo", tmp_path / "inst", tmp_path / "home"
    src = repo / "mods" / NAME
    (src / "hooks").mkdir(parents=True)
    (src / "hooks" / "register.tsx").write_bytes(b"export const a = 1\n")
    (src / "hooks" / "project.ts").write_text(PROJECT_WITH_COMMAND, encoding="utf-8")
    monkeypatch.setenv("AGENTOPS_MODS_REPO", str(repo))
    monkeypatch.setenv("AGENTOPS_MODS_DIR", str(inst_root))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return {"repo": repo, "inst": inst_root / NAME, "settings": tmp_path / "settings.json",
            "commands": tmp_path / "commands"}


def _settings(path, plugin_dirs=None):
    env = {} if plugin_dirs is None else {"CLAUDE_CODE_PLUGIN_DIRS": plugin_dirs}
    path.write_text(json.dumps({"env": env}), encoding="utf-8")


def test_folder_unlisted_is_added_to_the_plugin_dirs_line(mod, capsys):
    _settings(mod["settings"], plugin_dirs="C:/other/mods")
    mod["commands"].mkdir()
    assert mods.run_install(NAME, settings_path=mod["settings"], commands_dir=mod["commands"]) == 0
    out = capsys.readouterr().out
    folder = str(mod["inst"])
    # #46: install writes the one key; the line is `CLAUDE_CODE_PLUGIN_DIRS: <old> -> <new>`
    assert f"CLAUDE_CODE_PLUGIN_DIRS: C:/other/mods -> C:/other/mods;{folder}" in out
    assert "restart Claude Code once" in out
    assert "command file written" in out  # the command file step ran too
    assert json.loads(mod["settings"].read_text(encoding="utf-8")) == {"env": {"CLAUDE_CODE_PLUGIN_DIRS": f"C:/other/mods;{folder}"}}


def test_command_file_absent_is_written_from_the_core_stub(mod, capsys):
    _settings(mod["settings"], plugin_dirs=str(mod["inst"]))
    mod["commands"].mkdir()
    assert mods.run_install(NAME, settings_path=mod["settings"], commands_dir=mod["commands"]) == 0
    written = mod["commands"] / "x-cmd.md"
    assert written.is_file()
    text = written.read_bytes()
    stub = install_folder.COMMAND_STUB.read_bytes()
    assert text == stub.replace(b"{command}", b"x-cmd").replace(b"{title}", b"X Mod").replace(b"{mod_dir}", b"C:/x/mod")
    assert b"{" not in text
    out = capsys.readouterr().out
    assert f"command file written: {written}" in out
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in out


def test_both_present_prints_neither_line(mod, capsys):
    _settings(mod["settings"], plugin_dirs=str(mod["inst"]))
    mod["commands"].mkdir()
    (mod["commands"] / "x-cmd.md").write_bytes(b"already here\n")
    assert mods.run_install(NAME, settings_path=mod["settings"], commands_dir=mod["commands"]) == 0
    out = capsys.readouterr().out
    assert "manual settings step" not in out and "command file" not in out
    assert "CLAUDE_CODE_PLUGIN_DIRS" not in out
    assert (mod["commands"] / "x-cmd.md").read_bytes() == b"already here\n"


def test_mod_without_project_ts_prints_only_the_settings_line(mod, capsys):
    mod["settings"].write_text("{}", encoding="utf-8")
    mod["commands"].mkdir()
    (mod["commands"] / "pob.md").write_bytes(TEMPLATE)
    (mod["repo"] / "mods" / NAME / "hooks" / "project.ts").unlink()
    assert mods.run_install(NAME, settings_path=mod["settings"], commands_dir=mod["commands"]) == 0
    out = capsys.readouterr().out
    assert "restart Claude Code once" in out and "CLAUDE_CODE_PLUGIN_DIRS" in out
    assert "command file" not in out
    assert sorted(p.name for p in mod["commands"].iterdir()) == ["pob.md"]


def test_missing_stub_names_the_missing_command_file(mod, capsys, monkeypatch, tmp_path):
    _settings(mod["settings"], plugin_dirs=str(mod["inst"]))
    monkeypatch.setattr(install_folder, "COMMAND_STUB", tmp_path / "absent.stub")
    assert mods.run_install(NAME, settings_path=mod["settings"], commands_dir=mod["commands"]) == 0
    out = capsys.readouterr().out
    assert "no command file written" in out and "x-cmd.md" in out
    assert not (mod["commands"] / "x-cmd.md").exists()
