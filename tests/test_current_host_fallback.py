"""current_host(): JUNKROAN_HOST wins; else the checkout root matching a host's daemon_repo_path."""

import json

from junkroan.pob import slot_budget


def _cfg(tmp_path, monkeypatch, daemon):
    path = tmp_path / "hosts.json"
    path.write_text(json.dumps({
        "pc": {"ssh": None, "repo_path": "C:\nowhere"},
        "laptop": {"ssh": "laptop", "daemon_repo_path": str(daemon)},
    }), encoding="utf-8")
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(path))


def test_matching_daemon_path_names_host(tmp_path, monkeypatch):
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    root = tmp_path / "Daemon"
    root.mkdir()
    _cfg(tmp_path, monkeypatch, str(root).upper())
    assert slot_budget.current_host(root=root) == "laptop"


def test_other_path_is_pc(tmp_path, monkeypatch):
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    _cfg(tmp_path, monkeypatch, tmp_path / "daemon")
    assert slot_budget.current_host(root=tmp_path / "elsewhere") == "pc"


def test_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("JUNKROAN_HOST", "Laptop")
    _cfg(tmp_path, monkeypatch, tmp_path / "daemon")
    assert slot_budget.current_host(root=tmp_path / "elsewhere") == "laptop"


def test_missing_config_is_pc(tmp_path, monkeypatch):
    monkeypatch.delenv("JUNKROAN_HOST", raising=False)
    monkeypatch.setenv("JUNKROAN_HOSTS_CONFIG", str(tmp_path / "absent.json"))
    assert slot_budget.current_host(root=tmp_path) == "pc"
