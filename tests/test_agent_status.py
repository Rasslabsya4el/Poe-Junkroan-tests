"""#1005 U1: `tools/agentops/agent_status.py` classifies a Claude Code session's tail into one Russian status.

Three kinds of check, all on the module's public functions:

1. Recorded fixtures `tests/fixtures/agent_status/<kind>_<state>.jsonl`: 6 real transcript lines each, ending on
   the record that makes the state (strings cut to 120 chars). Table-driven; every fixture file must have a row.
2. Bash / tool / ended / opencode / kind rows, and synthetic records for the states no real transcript of that kind
   holds (built in the test from the shape of real lines; see `SYNTHETIC`).
3. Every status any check returns is in STATUS_WORDS, has at most 3 words and a Cyrillic letter.

    python -m pytest -q tests/test_agent_status.py
    python -m pytest -q -s tests/test_agent_status.py   (prints the fixture pass count)
"""
import json
import re
from pathlib import Path

import pytest

from tools.agentops import agent_status as A

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "agent_status"
CYRILLIC = re.compile(r"[\u0400-\u04FF]")

# Every fixture file and the status its last record must give (kind = the part before the first "_").
EXPECTED = {
    "chat_test": "гоняет тесты",
    "chat_merge": "мерджит",
    "chat_write": "правит код",
    "chat_ticket_write": "пишет тикет",
    "chat_read": "читает код",
    "chat_after_result": "думает",
    "chat_end_turn": "ждёт ответа",
    "chat_agent_fg": "ждёт воркера",
    "chat_monitor": "ждёт события",
    "autopilot_ticket_write": "пишет тикет",
    "autopilot_merge": "мерджит",
    "autopilot_read": "читает код",
    "autopilot_write": "правит код",
    "autopilot_agent_fg": "ждёт воркера",
    "autopilot_after_result": "думает",
    "autopilot_td_pending": "ждёт воркеров",
    "autopilot_td_idle": "ждёт события",
    "autopilot_monitor": "ждёт события",
    "keymaster_ticket_write": "пишет тикет",
    "keymaster_read": "читает код",
    "keymaster_after_result": "думает",
    "keymaster_end_turn": "ждёт события",
    "keymaster_td_idle": "ждёт события",
    "orch_test": "гоняет тесты",
    "orch_ticket_write": "пишет тикет",
    "orch_agent_fg": "ждёт воркера",
    "orch_after_result": "думает",
    "orch_merge": "мерджит",
    "orch_end_turn": "ждёт события",
    "orch_td_idle": "ждёт события",
    "orch_td_pending": "ждёт воркеров",
    "orch_read": "читает код",
    "orch_write": "правит код",
    "orch_monitor": "ждёт события",
    "subagent_test": "гоняет тесты",
    "subagent_merge": "мерджит",
    "subagent_end_report": "сдаёт отчёт",
    "subagent_after_result": "думает",
    "subagent_write": "правит код",
    "subagent_ticket_write": "пишет тикет",
}


def assert_status(status: str) -> str:
    """Every status the module returns: in STATUS_WORDS, at most 3 words, a Cyrillic letter."""
    assert status in A.STATUS_WORDS, status
    assert len(status.split()) <= 3, status
    assert CYRILLIC.search(status), status
    return status


def load_fixture(name: str) -> list[dict]:
    lines = (FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def bash(command) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_t", "name": "Bash", "input": {"command": command}}],
        "stop_reason": "tool_use"}}


def tool(name: str, inp: dict) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": "toolu_t", "name": name, "input": inp}], "stop_reason": "tool_use"}}


def turn_duration(pending: int) -> dict:
    return {"type": "system", "subtype": "turn_duration", "durationMs": 1000,
            "pendingBackgroundAgentCount": pending}


NOISE = [{"type": "attachment", "attachment": {"type": "environment"}},
         {"type": "last-prompt", "lastPrompt": "x"},
         {"type": "custom-title", "customTitle": "x"}]


# ---------------------------------------------------------------- 1. recorded fixtures

def test_fixture_files_match_the_table():
    on_disk = {p.stem for p in FIXTURES.glob("*.jsonl")}
    assert on_disk == set(EXPECTED), (sorted(on_disk - set(EXPECTED)), sorted(set(EXPECTED) - on_disk))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_recorded_fixture_gives_its_status(name):
    records = load_fixture(name)
    assert 4 <= len(records) <= 12
    kind = name.split("_", 1)[0]
    assert assert_status(A.classify(records, kind=kind)) == EXPECTED[name]


def test_fixture_pass_count(capsys):
    passed = sum(A.classify(load_fixture(n), kind=n.split("_", 1)[0]) == s for n, s in EXPECTED.items())
    print(f"\nagent_status fixtures passed: {passed}/{len(EXPECTED)}")
    assert passed == len(EXPECTED)


# ---------------------------------------------------------------- 2. synthetic records (states no real line of that kind holds)

CHAT_END_TURN = load_fixture("chat_end_turn")

SYNTHETIC = [
    ("autopilot", [bash("python -m pytest -q tests/test_x.py")], "гоняет тесты"),
    ("keymaster", [bash("python -m pytest -q tests/test_x.py")], "гоняет тесты"),
    ("keymaster", [bash("python -m tools.agentops merge hover-972 --issue 983")], "мерджит"),
    ("keymaster", [tool("Edit", {"file_path": "C:/x/tools/agentops/y.py", "old_string": "a", "new_string": "b"})],
     "правит код"),
    ("keymaster", [tool("Agent", {"description": "x", "prompt": "y"})], "ждёт воркера"),
    ("chat", CHAT_END_TURN + [turn_duration(1)], "ждёт воркеров"),
    ("chat", CHAT_END_TURN + [turn_duration(0)], "ждёт ответа"),
]


@pytest.mark.parametrize("kind,records,expected", SYNTHETIC)
def test_synthetic_record_gives_its_status(kind, records, expected):
    assert assert_status(A.classify(records, kind=kind)) == expected


# ---------------------------------------------------------------- 3. Bash classification (no fixture)

BASH_ROWS = [
    # the 10 priority rows, one per row
    ("python -m tools.agentops merge hover-972 --issue 983", "мерджит"),
    ("python -m pytest -q tests/test_x.py", "гоняет тесты"),
    ("gh issue comment 5 --body hi", "пишет тикет"),
    ("gh issue list --label ready-for-agent", "читает тикет"),
    ("python -m tools.agentops worktree add x", "работает с git"),
    ("python scripts/benchmark.py --workers 2", "запускает PoB"),
    ("python scripts/runs.py reserve", "смотрит очередь runs"),
    ("cat var/job.out", "смотрит логи"),
    ("sleep 60", "ждёт процесс"),
    ("rg foo src", "читает код"),
    ("python -c 'print(1)'", "запускает команду"),
    # the rows the spec names in its own examples
    ("git -C x merge main", "мерджит"),
    ("npm run test", "гоняет тесты"),
    ("git -C x push origin HEAD", "работает с git"),
    ("git -C x commit -m \"run pytest here\"", "работает с git"),
    ("cat > body.md <<'EOF'\ngh issue create --title x\nEOF", "читает код"),
    ("python find_x.py", "запускает команду"),
]


@pytest.mark.parametrize("command,expected", BASH_ROWS)
def test_bash_command_rows(command, expected):
    assert assert_status(A.classify_bash(command)) == expected


def test_bash_non_string_command_is_plain_run():
    assert assert_status(A.classify([bash(5)], kind="chat")) == "запускает команду"


# ---------------------------------------------------------------- tool table

TOOL_ROWS = [
    ("Read", {"file_path": "C:/x/var/job.log"}, "смотрит логи"),
    ("Read", {"file_path": "C:/x/docs/STATE.md"}, "читает доки"),
    ("Read", {"file_path": "C:/x/tools/agentops/y.py"}, "читает код"),
    ("Edit", {"file_path": "C:/x/docs/a.md"}, "пишет доки"),
    ("Write", {"file_path": "C:/x/tests/t.py"}, "правит код"),
    ("Grep", {"pattern": "x"}, "ищет в коде"),
    ("Glob", {"pattern": "*.py"}, "ищет в коде"),
    ("WebSearch", {"query": "x"}, "ищет в интернете"),
    ("WebFetch", {"url": "https://x"}, "ищет в интернете"),
    ("mcp__Claude_Browser__navigate", {"url": "https://x"}, "работает в браузере"),
    ("mcp__unslop__progress", {"x": 1}, "работает"),
    ("Agent", {"run_in_background": True, "prompt": "p"}, "запускает воркера"),
    ("Agent", {"prompt": "p"}, "ждёт воркера"),
    ("SendMessage", {"to": "a"}, "пишет агенту"),
    ("ListAgents", {}, "смотрит агентов"),
    ("TaskStop", {"task_id": "a"}, "останавливает задачу"),
    ("ToolSearch", {"query": "x"}, "ищет инструмент"),
    ("Skill", {"skill": "x"}, "читает инструкцию"),
    ("Monitor", {"command": "x"}, "ждёт события"),
    ("ScheduleWakeup", {"delaySeconds": 60}, "ждёт события"),
    ("CronCreate", {"cron": "x"}, "ждёт события"),
    ("AskUserQuestion", {"questions": []}, "ждёт ответа"),
    ("TodoWrite", {"todos": []}, "ведёт план"),
    ("TaskCreate", {"subject": "x"}, "ведёт план"),
    ("TaskUpdate", {"taskId": "1"}, "ведёт план"),
]


@pytest.mark.parametrize("name,inp,expected", TOOL_ROWS)
def test_tool_table_rows(name, inp, expected):
    assert assert_status(A.classify([tool(name, inp)], kind="orch")) == expected


# ---------------------------------------------------------------- 4. records the rules do not know

def test_unknown_records_give_neutral():
    assert A.classify([], kind="chat") == A.NEUTRAL == "работает"
    assert A.classify(NOISE, kind="chat") == A.NEUTRAL
    assert A.classify([tool("SomethingNew", {})], kind="chat") == A.NEUTRAL
    assert A.classify([tool("mcp__other__thing", {})], kind="chat") == A.NEUTRAL
    unknown_block = {"type": "assistant", "message": {"role": "assistant",
                     "content": [{"type": "mystery", "x": 1}], "stop_reason": "tool_use"}}
    assert A.classify([unknown_block], kind="chat") == A.NEUTRAL
    unknown_end = {"type": "assistant", "message": {"role": "assistant",
                   "content": [{"type": "mystery", "x": 1}], "stop_reason": "end_turn"}}
    assert A.classify([unknown_end], kind="chat") == A.NEUTRAL
    for status in (A.NEUTRAL, A.classify([], kind="chat")):
        assert_status(status)


def test_noise_and_other_system_records_are_skipped():
    records = [bash("python -m pytest -q x"), {"type": "system", "subtype": "stop_hook_summary"}] + NOISE
    assert A.classify(records, kind="orch") == "гоняет тесты"


# ---------------------------------------------------------------- 5. kinds, ended, opencode, overrides

def test_session_kind_rows():
    assert A.session_kind("interactive", "Brain: PoB") == "chat"
    assert A.session_kind("background", "autopilot #982") == "autopilot"
    assert A.session_kind("background", "orch Poe-Junkroan #1005 ~ba4d") == "orch"
    assert A.session_kind("background", "keymaster: job_stuck x") == "keymaster"
    assert A.session_kind("background", "dispatch-test") == "agent"
    assert A.session_kind(None, None) == "agent"
    assert A.session_kind("background", None) == "agent"


def test_classify_ended_rows():
    assert A.classify_ended("done") == "завершён"
    assert A.classify_ended("stopped") == "остановлен"
    assert A.classify_ended("failed") == "упал"
    assert A.classify_ended("running") == A.NEUTRAL
    assert A.classify_ended(None) == A.NEUTRAL
    for state in ("done", "stopped", "failed", "x", None):
        assert_status(A.classify_ended(state))


OPENCODE_ROWS = [
    ("", False, "завершён"),
    ("read: x", False, "завершён"),
    ("webfetch: https://x", True, "ищет в интернете"),
    ("websearch: q", True, "ищет в интернете"),
    ("codesearch: q", True, "ищет в интернете"),
    ("read: C:/x.py", True, "читает код"),
    ("list: C:/x", True, "читает код"),
    ("grep: x", True, "ищет в коде"),
    ("glob: *.py", True, "ищет в коде"),
    ("edit: x.py", True, "правит код"),
    ("write: x.py", True, "правит код"),
    ("patch: x.py", True, "правит код"),
    ("bash: ls", True, "запускает команду"),
    ("task: worker", True, "ждёт воркера"),
    ("", True, "думает"),
    ("   ", True, "думает"),
    ("unknowntool: x", True, A.NEUTRAL),
]


@pytest.mark.parametrize("last,busy,expected", OPENCODE_ROWS)
def test_classify_opencode_rows(last, busy, expected):
    assert assert_status(A.classify_opencode(last, busy)) == expected


def test_raw_status_idle_overrides_thinking_and_writing():
    thinking = [{"type": "user", "message": {"role": "user", "content": "hi"}}]
    writing = [{"type": "assistant", "message": {"role": "assistant", "stop_reason": None,
               "content": [{"type": "text", "text": "ответ"}]}}]
    assert A.classify(thinking, kind="chat") == "думает"
    assert A.classify(thinking, kind="chat", raw_status="idle") == "ждёт ответа"
    assert A.classify(writing, kind="chat") == "пишет ответ"
    assert A.classify(writing, kind="chat", raw_status="idle") == "ждёт ответа"
    assert A.classify(writing, kind="orch", raw_status="idle") == "ждёт события"
    assert A.classify(writing, kind="chat", raw_status="idle", running_subagents=2) == "ждёт воркеров"
    assert A.classify([tool("Bash", {"command": "pytest"})], kind="chat", raw_status="idle") == "гоняет тесты"


def test_running_subagents_turns_end_turn_into_waiting_for_workers():
    end_turn = CHAT_END_TURN[-1:]
    assert A.classify(end_turn, kind="chat") == "ждёт ответа"
    assert A.classify(end_turn, kind="chat", running_subagents=2) == "ждёт воркеров"
    assert A.classify(end_turn + [turn_duration(0)], kind="chat", running_subagents=2) == "ждёт воркеров"
    assert A.classify([turn_duration(0)], kind="autopilot", running_subagents=0) == "ждёт события"


def test_subagent_end_turn_is_its_report():
    assert A.classify(CHAT_END_TURN[-1:], kind="subagent") == "сдаёт отчёт"


# ---------------------------------------------------------------- 6. read_tail

def test_read_tail_returns_fixture_records():
    path = FIXTURES / "chat_end_turn.jsonl"
    assert A.read_tail(path) == load_fixture("chat_end_turn")


def test_read_tail_cut_drops_first_line():
    path = FIXTURES / "chat_end_turn.jsonl"
    tail = A.read_tail(path, nbytes=path.stat().st_size - 50)
    assert 0 < len(tail) < 6
    assert tail == load_fixture("chat_end_turn")[-len(tail):]


def test_read_tail_missing_path_is_empty():
    assert A.read_tail(FIXTURES / "no_such_file.jsonl") == []


# ---------------------------------------------------------------- 7. every status returned is well formed

def test_every_listed_status_is_well_formed():
    for word in A.STATUS_WORDS:
        assert_status(word)
