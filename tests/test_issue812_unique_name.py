"""#812: two ORCH sessions started with the same offer must not share a name, so the dispatcher's
messages by name (the #694 hand-off, the #137 wake) are never refused as ambiguous. The fake
`claude` refuses a duplicate name exactly as the SendMessage tool does. No PoB, no real claude/gh."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tools.agentops.dispatch as dp  # noqa: E402
from tools.agentops import monitor  # noqa: E402
from tools.agentops.dispatch import ClaudeCli, TickReport, build_command  # noqa: E402

from tests.test_agentops_dispatch import FakeGh, _dispatcher, _issue  # noqa: E402


class StrictClaude(ClaudeCli):
    """The real `ClaudeCli.start` (its subprocess call is stubbed); `wake` models SendMessage."""

    def __init__(self) -> None:
        super().__init__(exe="claude.exe")
        self.names: dict[str, str] = {}   # session id -> --name
        self.delivered: list[tuple[str, str]] = []  # (session id, message)
        self.refused: list[str] = []

    def run_stub(self, cmd, **kwargs):
        sid = f"sess{len(self.names) + 1}"
        self.names[sid] = cmd[cmd.index("--name") + 1]
        return subprocess.CompletedProcess(cmd, 0, stdout=f"backgrounded · {sid}\n", stderr="")

    def wake(self, chat: str, message: str):
        hits = [sid for sid, name in self.names.items() if name == chat]
        if len(hits) != 1:
            self.refused.append(chat)
            return False, f"{len(hits)} agents are named '{chat}'. Re-send with the ref of the one you mean"
        self.delivered.append((hits[0], message))
        return True, '{"success":true}'

    def list_sessions(self):
        return [{"id": sid, "name": n, "kind": "background", "state": "working", "status": "busy"}
                for sid, n in self.names.items()]


@pytest.fixture
def two_sessions(tmp_path, monkeypatch):
    claude = StrictClaude()
    monkeypatch.setattr(dp.subprocess, "run", claude.run_stub)
    gh = FakeGh(candidates=[_issue(1)])
    d = _dispatcher(tmp_path, claude=claude, gh=gh)
    d.tick()                          # session A offered #1
    d.sessions[0].finishing = True    # D110: a further session may start
    d._maybe_start(TickReport())      # session B, the same offer
    assert [c.session for c in d.sessions] == ["sess1", "sess2"]
    return claude, gh, d


def test_same_offer_gets_different_names(two_sessions) -> None:
    claude, _, d = two_sessions
    assert claude.names["sess1"] != claude.names["sess2"]
    assert d.sessions[0].name != d.sessions[1].name


def test_handoff_message_reaches_the_session_it_means(two_sessions) -> None:
    claude, _, d = two_sessions
    a, b = d.sessions
    a.held, b.held = {1}, set()
    d._hand_off_held(b, {1})   # B newly claims #1: A is told
    assert claude.refused == []
    assert [sid for sid, _ in claude.delivered] == ["sess1"]
    b.held, a.held = {1}, set()
    d._tell_session(b, "orch_handoff_told", "x", issue=9)
    assert claude.delivered[-1][0] == "sess2" and claude.refused == []


def test_wake_message_reaches_the_session_it_means(two_sessions) -> None:
    claude, gh, d = two_sessions
    gh._candidates = [_issue(1), _issue(2, 2)]
    for cur in d.sessions:
        cur.held = set()
        cur.started_at -= 10_000
    for cur, sid in zip(d.sessions, ("sess1", "sess2")):
        d._maybe_wake(cur, TickReport())
        assert claude.delivered[-1][0] == sid
    assert claude.refused == []


def test_name_still_parses_for_every_reader() -> None:
    name = build_command([5, 6], "claude.exe", tag="a3f9")[3]
    assert name == f"orch {dp.REPO_NAME} #5 #6 ~a3f9"
    assert dp._ORCH_NAME_RE.match(name)
    assert dp._ISSUE_RE.findall(name) == ["5", "6"]
    assert monitor._is_orch({"name": name}) and monitor._issue_from_name(build_command([5], 'claude.exe', tag='a3f9')[3]) == 5
