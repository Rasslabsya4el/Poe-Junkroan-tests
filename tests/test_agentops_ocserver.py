"""Tests for tools/agentops/ocserver.py against a fake HTTP server standing in for `opencode
serve` (issue #46): no real network call, no real opencode. Covers session create, prompt,
steer, abort, usage read, and the deny-list."""

from __future__ import annotations

import json
import os
import posixpath
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import pytest

from tools.agentops import ocserver


class FakeOpencodeHandler(BaseHTTPRequestHandler):
    """A minimal stand-in for opencode serve's session API."""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # keep pytest output quiet
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        store = self.server.store
        if path == "/session/status":
            self._send_json(store["statuses"])
            return
        if path.startswith("/session/") and path.endswith("/message"):
            session_id = path.split("/")[2]
            self._send_json(store["messages"].get(session_id, []))
            return
        if path == "/question":
            self._send_json(store["questions"])
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        store = self.server.store
        body = self._read_body()
        if path == "/session":
            session_id = f"sess{len(store['sessions']) + 1}"
            store["sessions"][session_id] = body
            store["calls"].append(("create_session", body))
            self._send_json({"id": session_id, "title": body.get("title")})
            return
        if path.endswith("/prompt_async"):
            session_id = path.split("/")[2]
            store["prompts"].setdefault(session_id, []).append(body)
            store["calls"].append(("prompt_async", session_id, body))
            store["statuses"][session_id] = {"type": "busy"}
            self._send_json({})
            return
        if path.endswith("/abort"):
            session_id = path.split("/")[2]
            store["calls"].append(("abort", session_id))
            store["statuses"].pop(session_id, None)
            self._send_json({})
            return
        if path.startswith("/question/") and path.endswith("/reply"):
            store["calls"].append(("answer", body))
            self._send_json({})
            return
        self._send_json({"error": "not found"}, status=404)


@pytest.fixture
def fake_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpencodeHandler)
    server.store = {
        "sessions": {}, "prompts": {}, "statuses": {}, "questions": [], "messages": {}, "calls": [],
    }
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=5)


def make_client(fake_server) -> ocserver.Client:
    port = fake_server.server_address[1]
    return ocserver.Client({"port": port, "password": "test"}, base_url=f"http://127.0.0.1:{port}")


def test_create_session_and_prompt_async(fake_server):
    client = make_client(fake_server)
    session = client.create_session("C:/copy", title="task-1")
    assert session["id"] == "sess1"
    client.prompt_async("C:/copy", session["id"], agent="agentops", provider_id="codex-sale-oai",
                        model="gpt-5.6-terra", system="sys", text="hello")
    calls = fake_server.store["calls"]
    assert calls[0][0] == "create_session"
    assert calls[1] == ("prompt_async", "sess1", {
        "agent": "agentops",
        "model": {"providerID": "codex-sale-oai", "modelID": "gpt-5.6-terra"},
        "system": "sys",
        "parts": [{"type": "text", "text": "hello"}],
    })


def test_steer_sends_another_prompt(fake_server):
    client = make_client(fake_server)
    session = client.create_session("C:/copy", title="task-1")
    client.prompt_async("C:/copy", session["id"], agent="agentops", provider_id="p", model="m",
                        system="s", text="first")
    client.steer("C:/copy", session["id"], agent="agentops", provider_id="p", model="m", system="s",
                text="steered")
    prompts = fake_server.store["prompts"][session["id"]]
    assert [p["parts"][0]["text"] for p in prompts] == ["first", "steered"]


def test_abort(fake_server, tmp_path):
    directory = str(tmp_path)
    client = make_client(fake_server)
    session = client.create_session(directory, title="t")
    client.prompt_async(directory, session["id"], agent="agentops", provider_id="p", model="m",
                        system="s", text="go")
    assert session["id"] in client.statuses([directory])
    client.abort(directory, session["id"])
    assert session["id"] not in client.statuses([directory])


def test_answer_question(fake_server):
    client = make_client(fake_server)
    fake_server.store["questions"] = [{"id": "q1", "sessionID": "sess1",
                                      "questions": [{"question": "which base?"}]}]
    pending = client.open_questions("C:/copy", "sess1")
    assert len(pending) == 1
    client.answer_question("C:/copy", "q1", ["a rare wand"])
    assert fake_server.store["calls"][-1] == ("answer", {"answers": [["a rare wand"]]})


def test_usage_totals_assistant_messages(fake_server):
    client = make_client(fake_server)
    fake_server.store["messages"]["sess1"] = [
        {"info": {"role": "user"}, "parts": []},
        {"info": {"role": "assistant", "tokens": {"input": 100, "output": 40, "reasoning": 5,
                                                   "cache": {"read": 10, "write": 2}}}, "parts": []},
        {"info": {"role": "assistant", "tokens": {"input": 50, "output": 20}}, "parts": []},
    ]
    usage = client.usage("C:/copy", "sess1")
    assert usage == {"input": 150, "output": 60, "reasoning": 5, "cache_read": 10, "cache_write": 2, "messages": 2}


def test_usage_none_without_assistant_messages(fake_server):
    client = make_client(fake_server)
    fake_server.store["messages"]["sess1"] = [{"info": {"role": "user"}, "parts": []}]
    assert client.usage("C:/copy", "sess1") is None


# -- the deny-list (requirement 3) -----------------------------------------------------------

@pytest.mark.parametrize("command", [
    "git worktree remove --force foo",
    "taskkill /PID 1 /T /F",
    "git push origin main",
    "git reset --hard HEAD~1",
    "git stash pop",
    "git clean -fdx",
    "rm -rf artifacts",
    "Remove-Item -Recurse -Force var",
    "git branch -D main",
])
def test_deny_list_blocks_dangerous_commands(command):
    assert ocserver.is_denied(command)


@pytest.mark.parametrize("command", [
    "python -m pytest -q",
    "git status",
    "git log --oneline -5",
    "git worktree add -b foo .claude/worktrees/foo HEAD",
])
def test_deny_list_allows_ordinary_commands(command):
    assert not ocserver.is_denied(command)


@pytest.mark.parametrize("command,expected", [
    ("git worktree remove --force foo", True),
    ("taskkill /PID 1 /T /F", True),
    ("git push origin main", True),
    ("git reset --hard HEAD~1", True),
    ("git stash pop", True),
    ("git clean -fdx", True),
    ("rm -rf artifacts", True),
    ("Remove-Item -Recurse -Force var", True),
    ("git branch -D main", True),
    ("python -m pytest -q", False),
    ("git status", False),
    ("git log --oneline -5", False),
    ("git worktree add -b foo .claude/worktrees/foo HEAD", False),
])
def test_deny_list_matches_case_insensitively_on_posix(monkeypatch, command, expected):
    """Requirement 3: prove the Linux/macOS behaviour on this (Windows) PC by making
    `os.path.normcase` behave like it does on POSIX (a no-op), since `fnmatch.fnmatch`
    (the old implementation) relies on `os.path.normcase` to lower-case on Windows only.
    `is_denied` must not depend on that OS-specific lowering: it lowers both sides itself
    and matches with `fnmatchcase`."""
    monkeypatch.setattr(os.path, "normcase", posixpath.normcase)
    assert ocserver.is_denied(command) is expected


def test_build_config_applies_deny_list_and_keeps_provider_table():
    base = {"$schema": "https://opencode.ai/config.json",
           "provider": {"codex-sale-oai": {"models": {"gpt-5.6-terra": {}}}},
           "permission": {"*": "allow"}}
    config = ocserver.build_config(base=base)
    assert config["provider"] == base["provider"]  # requirement 1: provider/models untouched
    assert config["permission"]["bash"]["*"] == "allow"
    assert config["permission"]["bash"]["git push*"] == "deny"
    assert config["share"] == "disabled"


def test_build_config_reads_this_repos_opencode_json():
    config = ocserver.build_config()
    models = config["provider"]["codex-sale-oai"]["models"]
    assert set(models) == {"gpt-5.6-terra", "deepseek-flash", "gpt-6-luna"}
    assert "openai" not in config["provider"]  # never the built-in openai/* models (requirement 1)


# -- 2026-09-26 follow-up: the real smoke run came back in 2.9 s with 0 tokens ----------------
# ("no reddit.com URL" instead of an explicit call failure). Two causes, two fixes below.

def test_signature_differs_with_enable_exa():
    """`config_hash` alone does not change with `enable_exa` (it is an env var, not part of
    OPENCODE_CONFIG_CONTENT) -- `ensure` must compare something that does, or a server started
    once without web search gets silently reused for a `research` call that needs it."""
    cfg = {"provider": {}, "permission": {}}
    assert ocserver._signature(cfg, False) != ocserver._signature(cfg, True)


def test_ensure_restarts_the_server_when_enable_exa_changes(monkeypatch):
    base = {"provider": {"p": {}}, "permission": {}}
    monkeypatch.setattr(ocserver, "read_opencode_config", lambda path=None: base)
    monkeypatch.setattr(ocserver, "registry", lambda: {})
    monkeypatch.setattr(ocserver.Client, "statuses", lambda self, dirs: {})  # nothing busy: safe to restart

    stale_signature = ocserver._signature(ocserver.build_config(base=base), False)  # started without exa
    monkeypatch.setattr(ocserver, "load_state", lambda base_url=None: {
        "pid": 1, "port": 1, "password": "x", "config": stale_signature,
    })

    calls = []
    monkeypatch.setattr(ocserver, "stop", lambda: calls.append("stop"))

    def fake_start(*, config_path=None, enable_exa=False):
        calls.append(("start", enable_exa))
        return {"pid": 2, "port": 2, "password": "y",
               "config": ocserver._signature(ocserver.build_config(base=base), enable_exa)}

    monkeypatch.setattr(ocserver, "start", fake_start)

    ocserver.ensure(enable_exa=True)  # requirement 2, `research`: needs web search on

    assert calls == ["stop", ("start", True)]  # the mismatched server was stopped and restarted WITH exa


def test_ensure_reuses_the_server_when_enable_exa_is_unchanged(monkeypatch):
    base = {"provider": {"p": {}}, "permission": {}}
    monkeypatch.setattr(ocserver, "read_opencode_config", lambda path=None: base)
    matching_signature = ocserver._signature(ocserver.build_config(base=base), True)
    monkeypatch.setattr(ocserver, "load_state", lambda base_url=None: {
        "pid": 1, "port": 1, "password": "x", "config": matching_signature,
    })
    calls = []
    monkeypatch.setattr(ocserver, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(ocserver, "start", lambda **kw: calls.append("start"))

    ocserver.ensure(enable_exa=True)

    assert calls == []  # already running with the settings we want: no restart


def test_wait_for_idle_waits_out_the_grace_window_before_accepting_idle(fake_server, tmp_path):
    """The race: `prompt_async` returns before opencode's own async job shows up as busy, so the
    FIRST status check can still read idle even though nothing has run yet. `wait_for_idle` must
    not treat that as "finished" until the grace window has passed."""
    directory = str(tmp_path)
    client = make_client(fake_server)
    session = client.create_session(directory, title="t")
    # No prompt_async: the session is never busy, simulating the race window.
    clock = {"t": 0.0}
    sleeps: list[float] = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    outcome = ocserver.wait_for_idle(client, directory, session["id"], minutes=1.0, min_grace_seconds=5.0,
                                     poll_seconds=1.0, sleep=fake_sleep, clock=lambda: clock["t"])

    assert outcome == "finished"
    assert clock["t"] >= 5.0  # waited out the grace window instead of returning after 0 s
    assert sum(sleeps) >= 5.0


def test_wait_for_idle_returns_as_soon_as_a_seen_busy_session_goes_idle(fake_server, tmp_path):
    directory = str(tmp_path)
    client = make_client(fake_server)
    session = client.create_session(directory, title="t")
    fake_server.store["statuses"][session["id"]] = {"type": "busy"}
    clock = {"t": 0.0}

    def fake_sleep(seconds):
        clock["t"] += seconds
        fake_server.store["statuses"].pop(session["id"], None)  # goes idle after the first poll

    outcome = ocserver.wait_for_idle(client, directory, session["id"], minutes=1.0, min_grace_seconds=5.0,
                                     poll_seconds=1.0, sleep=fake_sleep, clock=lambda: clock["t"])

    assert outcome == "finished"
    assert clock["t"] < 5.0  # returned as soon as the SEEN-busy session went idle, not held for the grace window


def test_last_error_reads_the_last_message_error(fake_server, tmp_path):
    directory = str(tmp_path)
    client = make_client(fake_server)
    session = client.create_session(directory, title="t")
    fake_server.store["messages"][session["id"]] = [
        {"info": {"role": "assistant", "error": {"name": "ProviderModelNotFoundError", "message": "bad model id"}},
         "parts": []},
    ]
    assert "bad model id" in client.last_error(directory, session["id"])


# -- both callers of `pid_alive` read an exited process (handle still held) as gone (#195) -----

def test_load_state_reads_an_exited_server_with_held_handle_as_gone(monkeypatch, tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    assert dead.wait(timeout=10) == 0
    # `dead` (and its handle) is kept alive/held here on purpose.
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"pid": dead.pid, "port": 1, "password": "x"}), encoding="utf-8")
    monkeypatch.setattr(ocserver, "STATE_FILE", state_file)
    try:
        assert ocserver.load_state() is None
    finally:
        dead.wait(timeout=10)


def test_stop_reads_an_exited_server_with_held_handle_as_gone(monkeypatch, tmp_path):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    assert dead.wait(timeout=10) == 0
    # `dead` (and its handle) is kept alive/held here on purpose.
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"pid": dead.pid, "port": 1, "password": "x"}), encoding="utf-8")
    monkeypatch.setattr(ocserver, "STATE_FILE", state_file)
    try:
        assert ocserver.stop() == "server not running"
    finally:
        dead.wait(timeout=10)


def test_last_error_is_none_without_an_error(fake_server, tmp_path):
    directory = str(tmp_path)
    client = make_client(fake_server)
    session = client.create_session(directory, title="t")
    fake_server.store["messages"][session["id"]] = [{"info": {"role": "assistant"}, "parts": []}]
    assert client.last_error(directory, session["id"]) is None


def test_register_records_the_launching_claude_session(monkeypatch, tmp_path):
    # #679: the monitor draws an opencode run under the Claude session that launched it.
    monkeypatch.setattr(ocserver, "SESSIONS_FILE", tmp_path / "sessions.json")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "abc")
    ocserver.register("s1", model="m")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    ocserver.register("s2", model="m")
    data = ocserver.registry()
    assert data["s1"]["model"] == "m" and data["s1"]["claude_session"] == "abc" and data["s1"]["started"]
    assert data["s2"]["claude_session"] is None
