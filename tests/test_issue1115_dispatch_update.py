"""#1115 unit 1: a dispatcher whose `update_rule` is `auto` takes the home's core change before every
ORCH start, not only at its first tick. The home is a fixture (`_home_gh_runner`), the target a
folder under tmp_path; the fake `claude.exe` records when each start happens."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.test_agentops_core_update import C0, C3, _home_gh_runner, _init_target
from tests.test_agentops_dispatch import FakeClaude, FakeClock, FakeGh, _dispatcher, _issue
from tools.agentops import core_update
from tools.agentops.dispatch import apply_auto_core_update


def _settings(target: Path) -> dict:
    return json.loads((target / "config" / "orchestration.json").read_text(encoding="utf-8"))


def _set_core_version(target: Path, version: str) -> None:
    path = target / "config" / "orchestration.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["core_version"] = version
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class RecordingClaude(FakeClaude):
    """A fake `claude.exe` whose `start` records the target's core_version at the moment of spawn."""

    def __init__(self, target: Path, order: list) -> None:
        super().__init__(cwd=target)
        self.target = target
        self.order = order

    def start(self, offered, parked_by=None):
        self.order.append(("spawn", _settings(self.target)["core_version"]))
        return super().start(offered, parked_by)


def _auto_update(target: Path, runner, order: list):
    def update():
        order.append(("update",))
        return apply_auto_core_update(root=target, settings=_settings(target), gh_runner=runner)
    return update


def test_a_two_orch_starts_in_one_process_each_take_the_update_first(tmp_path: Path) -> None:
    target = _init_target(tmp_path, update_rule="auto")
    order: list = []
    runner = _home_gh_runner(home_head=C3)
    claude = RecordingClaude(target, order)
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.core_update = _auto_update(target, runner, order)

    d.tick()
    assert len(claude.started) == 1

    # the first ORCH ends; the target is behind the home again; a new ready issue appears
    claude._sessions.clear()
    _set_core_version(target, C0)
    gh._candidates = [_issue(2)]
    for _ in range(3):  # the ended session is cleared on a later tick; the start follows it
        d.tick()
        if len(claude.started) == 2:
            break

    assert len(claude.started) == 2
    assert order == [("update",), ("spawn", C3), ("update",), ("spawn", C3)]


def test_b_a_refusal_for_a_live_orch_is_one_log_line_and_the_start_goes_on(tmp_path: Path, capsys) -> None:
    target = _init_target(tmp_path, update_rule="auto")
    state = target / core_update.ORCH_STATE_ENTRY
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"sessions": [{"session": "still-live"}]}), encoding="utf-8")
    order: list = []
    claude = RecordingClaude(target, order)
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.core_update = _auto_update(target, _home_gh_runner(home_head=C3), order)

    d.tick()

    assert len(claude.started) == 1  # the start went on
    assert _settings(target)["core_version"] == C0  # the refused update changed nothing
    out = capsys.readouterr().out
    assert out.count("core update (auto) refused") == 1


def test_c_word_rule_never_calls_the_update(tmp_path: Path, monkeypatch) -> None:
    target = _init_target(tmp_path, update_rule="word")
    calls: list = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(message="should not run")

    monkeypatch.setattr(core_update, "run_core_update", fake_run)
    claude = RecordingClaude(target, [])
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.core_update = lambda: apply_auto_core_update(root=target, settings=_settings(target),
                                                   gh_runner=_home_gh_runner(home_head=C3))

    d.tick()

    assert len(claude.started) == 1
    assert calls == []
