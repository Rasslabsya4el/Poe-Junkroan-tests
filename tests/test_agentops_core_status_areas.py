"""#321 unit 2: `core status` prints one extra last line while the target's `areas` setting is
empty or missing, and none once it holds an area. Same stubbed home as the closed-issue tests."""

from __future__ import annotations

import json
from types import SimpleNamespace

from tests.test_agentops_core_status_closed import (
    ISSUE_LIST_KEY,
    HOME_REPO,
    B,
    _init_target,
    _issues_payload,
    _make_runner,
)
from tools.agentops import core_update

_orig_status = core_update.run_core_status

NO_AREAS = ("no areas set in config/orchestration.json: the brain proposes them in this chat "
            "(python -m tools.agentops areas propose)")


def _runner():
    table = {
        ("api", f"repos/{HOME_REPO}/commits/main", "--jq", ".sha"): B + "\n",
        ISSUE_LIST_KEY: _issues_payload([]),
    }
    return _make_runner(table, [])


def _set_areas(target, areas) -> None:
    path = target / "config" / "orchestration.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if areas is None:
        data.pop("areas", None)
    else:
        data["areas"] = areas
    path.write_text(json.dumps(data), encoding="utf-8")


def _lines(target) -> list[str]:
    return core_update.run_core_status(target, gh_runner=_runner()).message.splitlines()


def test_no_areas_line_only_while_areas_empty(tmp_path, monkeypatch, capsys) -> None:
    target = _init_target(tmp_path, core_version=B)
    monkeypatch.setattr(core_update, "ROOT", target)

    _set_areas(target, ["area:a"])
    with_areas = _lines(target)
    assert NO_AREAS not in with_areas

    for empty in ([], None):
        _set_areas(target, empty)
        assert _lines(target) == with_areas + [NO_AREAS]

    # exit code unchanged, the line is printed
    monkeypatch.setattr(core_update, "run_core_status",
                        lambda root, gh_runner=None: _orig_status(root, gh_runner=_runner()))
    assert core_update.run_status_command(SimpleNamespace()) == 0
    assert capsys.readouterr().out.splitlines()[-1] == NO_AREAS
    _set_areas(target, ["area:a"])
    assert core_update.run_status_command(SimpleNamespace()) == 0
    assert NO_AREAS not in capsys.readouterr().out
