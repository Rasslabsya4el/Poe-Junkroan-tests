"""#1109 unit 1: the brain notice goes to the brain chat of the issue's area (`brain_chats`), else to `brain_chat_title`.

Fakes only: no `claude`, no message. Row 5 drives the real `GhCli` through a counting runner (no `gh` process).
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from tools.agentops import core_settings
from tools.agentops.brain_notice import BrainNotifier, IssueRead, brain_target
from tools.agentops.dispatch import GhCli

ROOT = Path(__file__).resolve().parents[1]
P = "P"  # brain_chat_title
O = "O"  # the chat of area:orchestration (the test table's)
CLOSED_AT = "2026-10-15T09:00:00Z"


class Sender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def __call__(self, title: str, message: str) -> None:
        self.messages.append((title, message))


class Fakes:
    def __init__(self, chats) -> None:
        self.chats = chats
        self.infos: dict[int, IssueRead | None] = {}
        self.live: dict[str, bool] = {}  # chat title -> live; absent = live
        self.sender = Sender()
        self.logs: list[str] = []

    def live_for(self, target: str) -> bool:
        return self.live.get(target, True)

    def notifier(self, path: Path) -> BrainNotifier:
        return BrainNotifier(
            state_path=path, brain_title=P, brain_chats=self.chats,
            send=self.sender, issue_info=lambda n: self.infos.get(n),
            autopilot_live_for=lambda n: None, brain_live=lambda: self.live_for(P),
            brain_live_for=self.live_for, log=self.logs.append,
            now=lambda: datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc),
        )


def _orchestration(title: str = "Orchestration ticket") -> IssueRead:
    return IssueRead(title, "Closed by merge.", None, CLOSED_AT, ("area:orchestration", "bug"))


def _builds(title: str = "Builds ticket") -> IssueRead:
    return IssueRead(title, "Closed by merge.", None, CLOSED_AT, ("area:builds",))


def test_row1_one_tick_closing_two_areas_sends_one_message_to_each_chat(tmp_path):
    f = Fakes({"area:orchestration": O})
    f.infos = {1: _orchestration(), 2: _builds()}

    sent = f.notifier(tmp_path / "state.json").observe({1: "closed", 2: "closed"})

    assert len(f.sender.messages) == 2
    by_target = dict(f.sender.messages)
    assert set(by_target) == {O, P}
    assert by_target[O] == "#1 Orchestration ticket: closed: Closed by merge."
    assert by_target[P] == "#2 Builds ticket: closed: Closed by merge."
    assert sent == [by_target[O], by_target[P]]


def test_row1_a_chat_that_is_not_live_holds_only_its_own_issue_until_it_is_live(tmp_path):
    f = Fakes({"area:orchestration": O})
    f.infos = {1: _orchestration(), 2: _builds()}
    f.live[O] = False
    notifier = f.notifier(tmp_path / "state.json")

    notifier.observe({1: "closed", 2: "closed"})
    assert f.sender.messages == [(P, "#2 Builds ticket: closed: Closed by merge.")]

    f.live[O] = True
    notifier.observe({})
    assert f.sender.messages[1:] == [(O, "#1 Orchestration ticket: closed: Closed by merge.")]
    assert len(f.sender.messages) == 2


def test_row2_no_area_or_an_unmapped_area_goes_to_brain_chat_title(tmp_path):
    f = Fakes({"area:orchestration": O})
    f.infos = {1: IssueRead("No area", "Closed by merge.", None, CLOSED_AT, ("bug",)),
               2: IssueRead("Unmapped", "Closed by merge.", None, CLOSED_AT, ("area:crafting",))}

    f.notifier(tmp_path / "state.json").observe({1: "closed", 2: "closed"})

    assert f.sender.messages == [(P, "#1 No area: closed: Closed by merge.\n#2 Unmapped: closed: Closed by merge.")]


def test_row2_empty_or_missing_brain_chats_is_todays_single_message(tmp_path):
    for chats in ({}, None):
        f = Fakes(chats)
        f.infos = {1: _orchestration(), 2: _builds()}

        f.notifier(tmp_path / f"state-{id(chats)}.json").observe({1: "closed", 2: "closed"})

        assert f.sender.messages == [(P, "#1 Orchestration ticket: closed: Closed by merge.\n"
                                         "#2 Builds ticket: closed: Closed by merge.")]


def test_row2_brain_target_helper_maps_an_area_or_falls_back_to_the_title():
    settings = {"brain_chat_title": P, "brain_chats": {"area:orchestration": O}}

    assert brain_target(settings, ["bug", "area:orchestration"]) == O
    assert brain_target(settings, ["area:builds"]) == P
    assert brain_target(settings, []) == P
    assert brain_target({"brain_chat_title": P, "brain_chats": {}}, ["area:orchestration"]) == P
    assert brain_target({"brain_chat_title": P}, ["area:orchestration"]) == P


def test_row5_the_news_of_n_issues_costs_n_issue_view_calls_and_routes_by_their_labels(tmp_path):
    calls: list[list[str]] = []
    labels = {1: ["area:orchestration"], 2: ["area:builds"], 3: []}

    def runner(args, stdin=None):
        calls.append(list(args))
        number = int(args[2])
        payload = {"title": f"T{number}", "closedAt": CLOSED_AT,
                   "comments": [{"id": f"IC_{number}", "body": f"closed {number}"}],
                   "labels": [{"name": name} for name in labels[number]]}
        return subprocess.CompletedProcess(args, 0, json.dumps(payload), "")

    gh = GhCli(repo="o/r", runner=runner)
    sender = Sender()
    notifier = BrainNotifier(
        state_path=tmp_path / "state.json", brain_title=P, brain_chats={"area:orchestration": O},
        send=sender, issue_info=gh.issue_title_and_last_comment, autopilot_live_for=lambda n: None,
        brain_live=lambda: True, log=lambda text: None,
        now=lambda: datetime(2026, 10, 15, 9, 0, 0, tzinfo=timezone.utc),
    )

    notifier.observe({1: "closed", 2: "closed", 3: "closed"})

    assert len([c for c in calls if c[:2] == ["issue", "view"]]) == 3
    by_target = {target: message for target, message in sender.messages}
    assert len(sender.messages) == 2
    assert by_target[O] == "#1 T1: closed: closed 1"
    assert by_target[P] == "#2 T2: closed: closed 2\n#3 T3: closed: closed 3"


def test_row6_the_core_default_is_an_empty_table_and_a_file_without_the_key_reads_it_empty(tmp_path):
    assert core_settings.DEFAULTS["brain_chats"] == {}
    path = tmp_path / "orchestration.json"
    path.write_text(json.dumps({key: "x" for key in core_settings.REQUIRED_KEYS}), encoding="utf-8")
    assert core_settings.load(path)["brain_chats"] == {}


def test_row6_this_repos_settings_map_the_orchestration_area_to_its_chat():
    settings = core_settings.load(ROOT / "config" / "orchestration.json")
    # #1117 row 7: the orchestration area's news go to the brain chat at the home, whose title is "Brain: orch layer" (#24 of the home).
    assert settings["brain_chats"] == {"area:orchestration": "Brain: orch layer"}
