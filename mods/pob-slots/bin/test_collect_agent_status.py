"""#1005 U2: `collect.agents()` puts a `status` word on every agent row, every subagent row and every opencode
subagent row (the classifier is `tools/agentops/agent_status.py`, unit 1).

Stubbed: `claude agents` (`ma.live_sessions_raw`), `ma.panel_agents`, the price table, the orch state and the opencode
server (`collect.opencode`). The transcripts are copies of `tests/fixtures/agent_status/*.jsonl` in a temp folder that
`ma.DEFAULT_PROJECTS_DIR` points at. No `claude` process, no network.

    python -m pytest -q -s mods/pob-slots/bin/test_collect_agent_status.py
"""
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "agent_status"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import collect  # noqa: E402
from tools.agentops import agent_status as ags  # noqa: E402
from tools.agentops import monitor_agents as ma  # noqa: E402
import tools.agentops as agentops_pkg  # noqa: E402


def _copy(projects: Path, rel: str, fixture: str) -> None:
    path = projects / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / f"{fixture}.jsonl", path)


@pytest.fixture
def world(tmp_path, monkeypatch):
    projects = tmp_path / "projects"
    projects.mkdir()
    monkeypatch.setattr(ma, "DEFAULT_PROJECTS_DIR", projects)
    monkeypatch.setattr(ma, "_token_meter", lambda: SimpleNamespace(load_prices=lambda path: {}))
    monkeypatch.setattr(ma, "load_orch_state", lambda *a, **k: None)
    state = SimpleNamespace(rows=[], oc=[])
    monkeypatch.setattr(ma, "live_sessions_raw", lambda *a, **k: [])
    monkeypatch.setattr(ma, "panel_agents", lambda *a, **k: {"sessions": state.rows})
    monkeypatch.setattr(collect, "opencode", lambda *a, **k: state.oc)
    return SimpleNamespace(projects=projects, state=state, monkeypatch=monkeypatch)


def _scene(w) -> None:
    """A chat, an autopilot (busy, one running subagent with no transcript) and an ORCH with two subagents:
    one running (its transcript ends on a Read) in `subagents`, one not running in `held_issues`."""
    _copy(w.projects, "chat-1.jsonl", "chat_end_turn")
    _copy(w.projects, "auto-1.jsonl", "orch_test")
    _copy(w.projects, "orch-1.jsonl", "orch_end_turn")
    _copy(w.projects, "orch-1/subagents/agent-r1.jsonl", "orch_read")
    w.state.rows = [
        {"session_id": "chat-1", "name": "chat", "kind": "interactive", "status": "idle", "subagents": []},
        {"session_id": "auto-1", "name": "autopilot 1005", "kind": "background", "status": "busy",
         "subagents": [{"agent_id": "w0", "running": True, "task": "waiting"}]},
        {"session_id": "orch-1", "name": "orch dispatcher", "kind": "background", "status": "idle",
         "subagents": [{"agent_id": "r1", "running": True, "task": "reader"}],
         "held_issues": [{"number": 1, "subagents": [{"agent_id": "d1", "running": False, "task": "finished"}]}]},
    ]


def _all_rows(out: list[dict]) -> list[dict]:
    return out + [s for r in out for s in r.get("subagents") or []]


def _by_sid(out: list[dict]) -> dict:
    return {r["sid"]: r for r in out}


def test_status_words_of_rows_and_subagents(world):
    _scene(world)
    out = collect.agents()
    rows = _by_sid(out)
    assert rows["chat-1"]["status"] == "ждёт ответа"
    assert rows["auto-1"]["status"] == "гоняет тесты"
    subs = {s["id"]: s for s in rows["orch-1"]["subagents"]}
    assert subs["r1"]["status"] == "читает код"
    assert subs["d1"]["status"] == "завершён"


def test_opencode_status(world):
    _scene(world)
    world.state.oc = [
        {"id": "oc1", "title": "Research A", "parent": None, "claude": "chat-1", "busy": True, "model": "Terra 5.6",
         "ctx": 0, "age": "1 min", "last": "webfetch: x", "created": 1},
        {"id": "oc2", "title": "Research B", "parent": None, "claude": "chat-1", "busy": False, "model": "",
         "ctx": 0, "age": "", "last": "", "created": 2},
    ]
    subs = {s["name"]: s for s in _by_sid(collect.agents())["chat-1"]["subagents"]}
    assert subs["Research A"]["status"] == "ищет в интернете"
    assert subs["Research B"]["status"] == "завершён"


def test_missing_transcript_is_neutral(world):
    world.state.rows = [
        {"session_id": "gone-1", "name": "chat", "kind": "interactive", "status": "busy",
         "subagents": [{"agent_id": "x9", "running": True, "task": "lost"}]},
    ]
    row = _by_sid(collect.agents())["gone-1"]
    assert row["status"] == ags.NEUTRAL
    assert row["subagents"][0]["status"] == ags.NEUTRAL


def test_every_row_has_a_status_word(world, capsys):
    _scene(world)
    world.state.oc = [
        {"id": "oc1", "title": "Research A", "parent": None, "claude": "chat-1", "busy": True, "model": "",
         "ctx": 0, "age": "", "last": "webfetch: x", "created": 1},
    ]
    out = collect.agents()
    everything = _all_rows(out)
    missing = [r.get("name") for r in everything if r.get("status") not in ags.STATUS_WORDS]
    print(f"\nrows and subagents: {len(everything)}, without a status word: {len(missing)}")
    assert len(everything) >= 6
    assert missing == []


def test_without_the_classifier_rows_have_no_status(world, monkeypatch):
    _scene(world)
    world.state.oc = [
        {"id": "oc1", "title": "Research A", "parent": None, "claude": "chat-1", "busy": True, "model": "",
         "ctx": 0, "age": "", "last": "webfetch: x", "created": 1},
    ]
    monkeypatch.setitem(sys.modules, "tools.agentops.agent_status", None)
    monkeypatch.delattr(agentops_pkg, "agent_status")
    out = collect.agents()
    assert len(out) == 3
    assert "status" not in out[0]
    assert all("status" not in r for r in _all_rows(out))
