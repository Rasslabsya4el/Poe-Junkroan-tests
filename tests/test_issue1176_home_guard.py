"""#1176 unit f: every test runs under a tmp home; the owner's real ~/.claude is never written.

The guard is the autouse fixture `_home_is_tmp_per_test` in tests/conftest.py: HOME and USERPROFILE point at a
per-test folder (a sibling of tmp_path, so a test that lists its tmp_path sees only its own files), AGENTOPS_MODS_DIR
sits in it, and the import-time home constants are moved there.

`REAL_SETTINGS` is captured at collection time, before any test has redirected the home, so it is the owner's
real settings file. Test (c) only reads it (os.stat), never writes it.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from conftest import _redirect_home
from tools.agentops import mods

REAL_HOME = Path.home()  # collection time, before any test redirects the home
REAL_SETTINGS = REAL_HOME / ".claude" / "settings.json"

SRC = {
    ".claude-plugin/plugin.json": b'{\n  "name": "pob-slots",\n  "version": "0.3.0"\n}\n',
    "hooks/project.ts": b"export const MOD_DIR = 'x';\n",
    "addon/addon.py": b"print('addon')\n",
}


def _test_home() -> Path:
    """The home the guard gave this test (HOME; USERPROFILE names the same folder), never the owner's."""
    home = Path(os.environ["HOME"])
    assert home != REAL_HOME and not home.is_relative_to(REAL_HOME / ".claude")
    return home


def _stamp(path: Path):
    """(size, mtime_ns) of a file, read-only; None when it is missing."""
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return st.st_size, st.st_mtime_ns


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


def test_path_home_is_the_guards_home(tmp_path):
    assert Path.home() == _test_home()
    assert Path(os.environ["USERPROFILE"]) == _test_home()
    assert _test_home().is_relative_to(tmp_path.parent) and not _test_home().is_relative_to(tmp_path)


def test_user_settings_and_plugin_cache_defaults_are_inside_tmp_home(tmp_path):
    from tools.agentops import port

    # mods.default_settings_path under pytest (core 293e7d8e, #94): a throwaway settings file in the system temp folder,
    # never the owner's file (the guard's home is not where it sits; the throwaway is the core's own default)
    throwaway = mods.default_settings_path()
    assert throwaway != REAL_SETTINGS and throwaway.is_relative_to(Path(tempfile.gettempdir()))
    assert port.DEFAULT_USER_SETTINGS_PATH.is_relative_to(_test_home())
    assert port.PLUGIN_CACHE_ROOT.is_relative_to(_test_home())


@pytest.mark.skipif(not REAL_SETTINGS.is_file(), reason="no real ~/.claude/settings.json on this runner (#1207)")
def test_mod_install_writes_only_under_the_tmp_home(tmp_path, monkeypatch):
    # the same entry tests/test_issue885_plugin_id.py calls: mods.run_install(name), no settings_path given
    repo = tmp_path / "repo"
    for rel, data in SRC.items():
        p = repo / "mods" / "pob-slots" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    (repo / "config").mkdir(parents=True)
    (repo / "config" / "orchestration.json").write_text(
        json.dumps({"monitor": {"source": "pob-slots"}}), encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "import")
    monkeypatch.setenv("AGENTOPS_MODS_REPO", str(repo))

    settings = Path.home() / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"env": {}}\n', encoding="utf-8")
    # the settings file the install edits is the one AGENTOPS_SETTINGS_PATH names (mods.default_settings_path, core
    # 293e7d8e): the test's own file under its home, so the edit is checked where it lands
    monkeypatch.setenv("AGENTOPS_SETTINGS_PATH", str(settings))

    # the owner's real file must exist for this check to mean anything: a missing file is a failure, not None == None
    real_before = _stamp(REAL_SETTINGS)
    assert real_before is not None, f"the owner's real settings file {REAL_SETTINGS} is absent: nothing to stat"
    assert mods.run_install("pob-slots") == 0
    assert _stamp(REAL_SETTINGS) == real_before

    install = mods.install_root() / mods.install_name("pob-slots")
    assert install.is_dir() and install.is_relative_to(_test_home())
    value = json.loads(settings.read_text(encoding="utf-8"))["env"]["CLAUDE_CODE_PLUGIN_DIRS"]
    assert str(install) in value


def _paths_under_real_home(fn, tmp_path):
    """The Path defaults of `fn` (positional and keyword) that point under the owner's real home, outside the
    guard's basetemp (pytest's basetemp is itself under the real home, and each test's home is a sibling folder
    under it, so basetemp is excluded by name)."""
    values = [*(fn.__defaults__ or ()), *(fn.__kwdefaults__ or {}).values()]
    return [v for v in values if isinstance(v, Path) and v.is_relative_to(REAL_HOME)
            and not v.is_relative_to(tmp_path.parent)]


def test_d_resolve_plugin_without_a_cache_argument_reads_under_tmp(tmp_path):
    from tools.agentops import port

    settings = tmp_path / "settings-copy.json"  # a copy of the settings path, never the owner's file
    settings.write_text(json.dumps({"enabledPlugins": {f"{port.PLUGIN_ID}@mattpocock": True}}), encoding="utf-8")
    with pytest.raises(port.PortError) as err:
        port.resolve_plugin(settings)
    assert str(REAL_HOME / ".claude" / "plugins") not in str(err.value)
    assert str(tmp_path) in str(err.value)


def test_e_mods_commands_dir_resolves_under_tmp(tmp_path):
    from tools.agentops import install_folder

    # the function that builds the default (mods.run_install reads the same `~/.claude/commands` when none is given)
    assert install_folder.commands_dir().is_relative_to(_test_home())
    assert install_folder.install_root().is_relative_to(_test_home())


def test_f_port_entry_points_hold_no_default_under_the_real_home(tmp_path):
    from tools.agentops import port

    for fn in (port.run_port, port.run_dry_run, port.resolve_plugin, port.check_machine_ready):
        assert _paths_under_real_home(fn, tmp_path) == [], fn.__name__


def test_g_home_constants_of_monitor_are_under_tmp(tmp_path):
    from tools.agentops import monitor

    assert monitor.DEFAULT_PROJECTS_DIR.is_relative_to(_test_home())


def test_h_each_redirect_gives_its_own_home_and_the_test_home_comes_back(tmp_path_factory):
    """Two redirects in one test (two monkeypatch contexts), the same walk the guard runs per test. Self-contained:
    no other test has to run first. Each redirect sees its own home, and the test's own home is restored after both,
    so nothing leaks from one test to the next."""
    from tools.agentops import port

    base = tmp_path_factory.getbasetemp()
    own = port.DEFAULT_USER_SETTINGS_PATH
    assert own.is_relative_to(_test_home())
    seen = []
    for name in ("first", "second"):
        home = tmp_path_factory.mktemp(name) / "home"
        home.mkdir()
        with pytest.MonkeyPatch.context() as mp:
            _redirect_home(mp, home, base)
            seen.append(port.DEFAULT_USER_SETTINGS_PATH)
            assert port.DEFAULT_USER_SETTINGS_PATH.is_relative_to(home)
    assert seen[0] != seen[1]
    assert port.DEFAULT_USER_SETTINGS_PATH == own


def test_i_git_commit_has_an_identity_under_the_guard(tmp_path):
    # no `-c user.name`: the identity must come from the guard's own gitconfig, not from the owner's ~/.gitconfig
    repo = tmp_path / "fresh"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
    done = subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-m", "x"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_j_git_init_default_branch_is_main_under_the_guard(tmp_path):
    # the guard's gitconfig carries the owner's `[init] defaultBranch = main` (GIT_CONFIG_GLOBAL drops the owner's own)
    repo = tmp_path / "branchy"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(repo), "symbolic-ref", "--short", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert head == "main"


def test_k_the_bypass_disclaimer_is_accepted_in_the_test_home():
    """`guard install` prints an extra line while `~/.claude.json` lacks the accepted flag; the guard's home has it."""
    from tools.agentops import guard

    assert guard.default_claude_json() == _test_home() / ".claude.json"
    assert guard.disclaimer_accepted(guard.default_claude_json())


def test_l_one_original_path_object_is_moved_to_one_object_in_every_module():
    """A name copied from another module (`monitor_agents.DEFAULT_PROJECTS_DIR is monitor.DEFAULT_PROJECTS_DIR`)
    stays the same object after the redirect, not one new Path per module."""
    from tools.agentops import monitor, monitor_agents

    assert monitor.DEFAULT_PROJECTS_DIR is monitor_agents.DEFAULT_PROJECTS_DIR
