"""#1096 unit 3a: collect.py reaches `tools.agentops.monitor_dashboard` (a module outside the core manifest) through the
settings key `monitor_dashboard`, resolved at call time. An absent key, an unreadable settings file or a missing module
gives None, and `slow()` keeps its fallback `{"at": ...}`. `_agent_status()` still returns `tools.agentops.agent_status`.

No PoB, no network: collect's settings reader is replaced, and `slow()`'s branch is exercised through its helper.

    python -m pytest -q tests/test_issue1096_collect_imports.py
"""
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "mods" / "pob-slots" / "bin"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BIN))

import collect  # noqa: E402
from tools.agentops import agent_status as ags  # noqa: E402
from tools.agentops import core_settings  # noqa: E402

KEY = "monitor_dashboard"
MODULE = "tools.agentops.monitor_dashboard"
AGENT_KEY = "agent_status"
# read before any patch: token_meter (imported by monitor_dashboard) reads claude_projects_dir from the same loader
REAL = core_settings.load()


def _settings(monkeypatch, data):
    monkeypatch.setattr(collect, "settings", lambda root=None: data)


def test_key_present_resolves_the_monitor_dashboard_module(monkeypatch):
    _settings(monkeypatch, {**REAL, KEY: MODULE})
    assert collect._settings_module(KEY) is importlib.import_module(MODULE)


def test_this_repo_settings_file_names_the_monitor_dashboard():
    assert core_settings.load().get(KEY) == MODULE


def test_absent_key_gives_none(monkeypatch):
    _settings(monkeypatch, {k: v for k, v in REAL.items() if k != KEY})
    assert collect._settings_module(KEY) is None


def test_missing_module_gives_none(monkeypatch):
    _settings(monkeypatch, {**REAL, KEY: "tools.agentops.no_such_module_1096"})
    assert collect._settings_module(KEY) is None


def test_unreadable_settings_give_none(monkeypatch):
    def broken(root=None):
        raise RuntimeError("unreadable settings file")

    monkeypatch.setattr(collect, "settings", broken)
    assert collect._settings_module(KEY) is None


def test_slow_keeps_its_fallback_when_the_helper_gives_none(monkeypatch):
    monkeypatch.setattr(collect, "_settings_module", lambda key: None)
    assert set(collect.slow()) == {"at"}


def test_slow_keeps_its_fallback_when_the_module_is_missing(monkeypatch):
    # None in sys.modules makes any import of the name raise ImportError: the module is "missing" here
    _settings(monkeypatch, {**REAL, KEY: MODULE})
    monkeypatch.setitem(sys.modules, MODULE, None)
    assert set(collect.slow()) == {"at"}


def test_agent_status_still_resolves_to_the_module():
    assert collect._agent_status() is ags


def test_agent_status_absent_key_gives_none(monkeypatch):
    _settings(monkeypatch, {k: v for k, v in REAL.items() if k != AGENT_KEY})
    assert collect._agent_status() is None
