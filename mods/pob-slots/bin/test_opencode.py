"""#678: opencode sessions become subagent rows of the Claude session that launched them.

    python -m pytest -q bin/test_opencode.py   (from the repo root, like the other bin tests)

The reading is a real one (fixtures/opencode_reading.json: the merge-pipeline research run of
09.10 19:5x, one root session and its 4 @general sub-sessions), served by a fake client.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import collect  # noqa: E402

READING = json.loads((HERE / "fixtures" / "opencode_reading.json").read_text(encoding="utf-8"))
ROOT = next(s["id"] for s in READING["sessions"] if not s.get("parentID"))
ORCH = "42be26c2-0000-0000-0000-000000000000"


class FakeClient:
    def __init__(self, status: dict):
        self.status = status
        self.calls: list[tuple[str, str]] = []

    def call(self, method, path, directory=None, body=None, timeout=60):
        self.calls.append((method, path))
        assert method == "GET", "the monitor never creates, aborts or prompts a session"
        if path == "/session":
            return READING["sessions"]
        if path == "/session/status":
            return self.status
        sid = path.split("/")[2]
        return READING["messages"].get(sid, [])


def orch_row() -> dict:
    return {"sid": ORCH, "name": "orch Poe-Junkroan #621", "kind": "background", "busy": True, "issue": 621,
            "held": [], "model": "Sonnet 5.5", "ctx": 90_000, "age": "40 min", "last": "",
            "subagents": [{"name": "worker #621", "type": "worker", "issue": 621, "model": "Sonnet 5.5",
                           "ctx": 50_000, "age": "10 min", "busy": True}]}


def rows(status: dict, registry: dict, tmp_path: Path) -> list[dict]:
    client = FakeClient(status)
    out = collect.opencode(client, registry=registry, now_ms=READING["recorded_ms"],
                           launch_cache=tmp_path / "launch.json")
    assert all(m == "GET" for m, _ in client.calls)
    return out


def test_research_run_under_the_orch_that_launched_it(tmp_path):
    all_busy = {s["id"]: {"type": "busy"} for s in READING["sessions"]}
    reg = {ROOT: {"directory": READING["directory"], "model": "gpt-5.6-terra", "claude_session": ORCH}}
    agents = [orch_row(), {**orch_row(), "sid": "brain", "name": "Brain: PoB", "subagents": []}]
    collect.attach_opencode(agents, rows(all_busy, reg, tmp_path))
    subs = agents[0]["subagents"]
    oc = [s for s in subs if s["type"] == "opencode"]
    assert [s["depth"] for s in oc] == [1, 2, 2, 2, 2]
    assert oc[0]["name"] == "research merge pipeline practices"
    assert {s["model"] for s in oc} == {"Terra 5.6"}
    assert all(s["busy"] for s in oc)
    assert subs[0]["type"] == "worker"  # the Claude subagent keeps its place on top
    assert agents[1]["subagents"] == []
    assert not any(a["name"] in ("Другое", "GPT") for a in agents)


def test_attribution_outlives_the_registry_entry(tmp_path):
    # The launcher unregisters the run when it ends; the collector remembered who launched it.
    reg = {ROOT: {"directory": READING["directory"], "claude_session": ORCH}}
    rows(READING["status"], reg, tmp_path)
    later = rows(READING["status"], {}, tmp_path)
    agents = [orch_row()]
    collect.attach_opencode(agents, later)
    assert len([s for s in agents[0]["subagents"] if s["type"] == "opencode"]) == 5


def test_no_launcher_record_is_not_drawn(tmp_path):
    # Owner 09.10 20:3x: "убери другое из В работе" -- a run with no launching session is not shown.
    agents = [orch_row()]
    collect.attach_opencode(agents, rows(READING["status"], {}, tmp_path))
    assert [a["name"] for a in agents] == ["orch Poe-Junkroan #621"]
    assert not any(s["type"] == "opencode" for s in agents[0]["subagents"])


def test_finished_long_ago_leaves_the_tile(tmp_path):
    client = FakeClient({})
    out = collect.opencode(client, registry={}, now_ms=READING["recorded_ms"] + 11 * 60 * 1000,
                           launch_cache=tmp_path / "launch.json")
    assert out == []


def test_model_names():
    assert collect.oc_model("gpt-5.6-terra") == "Terra 5.6"
    assert collect.oc_model("gpt-6-luna") == "Luna 6"
    assert collect.oc_model("deepseek-flash") == "DeepSeek"
