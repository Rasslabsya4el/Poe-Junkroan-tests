"""#1005 U1: one fixed Russian status (at most 3 words) for a Claude Code session, read from the tail of its
own transcript.

Pure: no process, no file write. `read_tail` is the only function that touches the disk, and only to read.
PoB, game and tool names stay English ("запускает PoB"); every return is in `STATUS_WORDS`.

The rules, in the order the code applies them, are written in the docstrings of `classify` and
`_tool_status`. The test is `tests/test_agent_status.py`:

    python -m pytest -q tests/test_agent_status.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NEUTRAL = "работает"

_BASH_TOOLS = ("Bash", "PowerShell")
_EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
_KNOWN_BLOCKS = ("text", "thinking", "redacted_thinking")
_SIGNIFICANT = ("assistant", "user", "system")

_SIMPLE_TOOLS = {
    "Grep": "ищет в коде",
    "Glob": "ищет в коде",
    "WebSearch": "ищет в интернете",
    "WebFetch": "ищет в интернете",
    "SendMessage": "пишет агенту",
    "ListAgents": "смотрит агентов",
    "TaskStop": "останавливает задачу",
    "ToolSearch": "ищет инструмент",
    "Skill": "читает инструкцию",
    "Monitor": "ждёт события",
    "ScheduleWakeup": "ждёт события",
    "CronCreate": "ждёт события",
    "AskUserQuestion": "ждёт ответа",
    "TodoWrite": "ведёт план",
    "TaskCreate": "ведёт план",
    "TaskUpdate": "ведёт план",
}

STATUS_WORDS: frozenset[str] = frozenset({
    NEUTRAL,
    # Bash / PowerShell
    "мерджит", "гоняет тесты", "пишет тикет", "читает тикет", "работает с git", "запускает PoB",
    "смотрит очередь runs", "смотрит логи", "ждёт процесс", "читает код", "запускает команду",
    # Read / Edit / Write
    "читает доки", "пишет доки", "правит код",
    # search, browser, agents, misc tools
    "ищет в коде", "ищет в интернете", "работает в браузере", "запускает воркера", "ждёт воркера",
    "пишет агенту", "смотрит агентов", "останавливает задачу", "ищет инструмент", "читает инструкцию",
    "ждёт события", "ждёт ответа", "ведёт план",
    # no tool
    "думает", "пишет ответ", "ждёт воркеров", "сдаёт отчёт",
    # ended
    "завершён", "остановлен", "упал",
})


# ---------------------------------------------------------------- kind

def session_kind(raw_kind: str | None, name: str | None) -> str:
    """`claude agents` kind + name -> chat / autopilot / orch / keymaster / agent."""
    if raw_kind == "interactive":
        return "chat"
    if raw_kind == "background":
        lowered = (name or "").strip().lower()
        for prefix, kind in (("autopilot", "autopilot"), ("orch", "orch"), ("keymaster", "keymaster")):
            if lowered.startswith(prefix):
                return kind
    return "agent"


# ---------------------------------------------------------------- read

def read_tail(path, nbytes: int = 96_000) -> list[dict]:
    """The last `nbytes` of a transcript as records. A file longer than `nbytes` loses its first line (it may be
    cut mid-record). Bad JSON lines and non-object lines are skipped. [] when the file cannot be read."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            cut = size > nbytes
            fh.seek(max(0, size - nbytes))
            raw = fh.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return []
    if cut:
        raw = raw[1:]
    records: list[dict] = []
    for line in raw:
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


# ---------------------------------------------------------------- classify

def classify(records: list[dict], *, kind: str, raw_status: str | None = None, running_subagents: int = 0) -> str:
    """The last SIGNIFICANT record decides: an `assistant`, `user`, or `system` record whose subtype (for system)
    is `turn_duration`. Noise records are skipped. No significant record -> NEUTRAL.

    - system turn_duration: idle(max(its pendingBackgroundAgentCount, running_subagents)).
    - user: "думает".
    - assistant: a `tool_use` block anywhere -> the LAST one decides (`_tool_status`). Else a block of a type the
      rules do not know -> NEUTRAL. Else stop_reason end_turn -> idle(running_subagents), or "сдаёт отчёт" for a
      subagent. Else a last `text` block -> "пишет ответ". Else "думает".
    - raw_status "idle" turns "думает" or "пишет ответ" into idle(running_subagents).

    idle(pending): pending > 0 -> "ждёт воркеров"; chat -> "ждёт ответа"; any other kind -> "ждёт события"."""
    running = _count(running_subagents)
    record = _last_significant(records)
    if record is None:
        return NEUTRAL
    result = _decide(record, kind=kind, running=running)
    if raw_status == "idle" and result in ("думает", "пишет ответ"):
        return _idle(running, kind)
    return result


def _last_significant(records: list[dict]) -> dict | None:
    for record in reversed(records):
        if not isinstance(record, dict):
            continue
        kind = record.get("type")
        if kind not in _SIGNIFICANT:
            continue
        if kind == "system" and record.get("subtype") != "turn_duration":
            continue
        return record
    return None


def _decide(record: dict, *, kind: str, running: int) -> str:
    rtype = record.get("type")
    if rtype == "system":
        return _idle(max(_count(record.get("pendingBackgroundAgentCount")), running), kind)
    if rtype == "user":
        return "думает"
    message = record.get("message")
    if not isinstance(message, dict):
        message = {}
    content = message.get("content")
    if isinstance(content, str):
        blocks: list = [{"type": "text", "text": content}]
    elif isinstance(content, list):
        blocks = content
    else:
        blocks = []
    tool_uses = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]
    if tool_uses:
        return _tool_status(tool_uses[-1])
    if any(not isinstance(b, dict) or b.get("type") not in _KNOWN_BLOCKS for b in blocks):
        return NEUTRAL
    if message.get("stop_reason") == "end_turn":
        return "сдаёт отчёт" if kind == "subagent" else _idle(running, kind)
    if blocks and blocks[-1].get("type") == "text":
        return "пишет ответ"
    return "думает"


def _idle(pending: int, kind: str) -> str:
    if pending > 0:
        return "ждёт воркеров"
    if kind == "chat":
        return "ждёт ответа"
    return "ждёт события"


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


# ---------------------------------------------------------------- tools

def _tool_status(block: dict) -> str:
    """The tool table. An unknown tool name -> NEUTRAL."""
    name = str(block.get("name") or "")
    inp = block.get("input")
    if not isinstance(inp, dict):
        inp = {}
    if name in _BASH_TOOLS:
        command = inp.get("command")
        if not isinstance(command, str):
            return "запускает команду"
        return classify_bash(command)
    if name == "Read":
        path = _path(inp).lower()
        if path.endswith((".log", ".out", ".err", ".jsonl")):
            return "смотрит логи"
        if path.endswith((".md", ".txt", ".rst")):
            return "читает доки"
        return "читает код"
    if name in _EDIT_TOOLS:
        path = _path(inp).lower()
        if path.endswith((".md", ".txt")):
            return "пишет доки"
        return "правит код"
    if name == "Agent":
        return "запускает воркера" if inp.get("run_in_background") is True else "ждёт воркера"
    if name.startswith("mcp__"):
        lowered = name.lower()
        if any(word in lowered for word in ("browser", "chrome", "computer")):
            return "работает в браузере"
        return NEUTRAL
    return _SIMPLE_TOOLS.get(name, NEUTRAL)


def _path(inp: dict) -> str:
    for key in ("file_path", "notebook_path", "path"):
        value = inp.get(key)
        if isinstance(value, str):
            return value
    return ""


_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')

# (regex, status), first match wins; applied to the lower-cased command after quotes and heredocs are removed.
_BASH_RULES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bagentops\s+merge(?![\w-])|\bgit\b.*\bmerge(?![\w-])"), "мерджит"),
    (re.compile(r"\bpytest\b|\bnpm\s+(?:run\s+)?test\b|\bjest\b|\bvitest\b|\btsc\b|\bbun\s+test\b|\bplugin\s+test\b"),
     "гоняет тесты"),
    (re.compile(r"\bgh\s+issue\s+(?:create|edit|comment|close|reopen)\b"), "пишет тикет"),
    (re.compile(r"\bgh\s+(?:issue|pr|api|search)\b"), "читает тикет"),
    (re.compile(r"\bagentops\s+(?:worktree|commit)\b|\bgit\b.*\b(?:commit|push|add|checkout|switch|branch|rebase"
                r"|stash|reset|worktree|cherry-pick)\b"), "работает с git"),
    (re.compile(r"\bbenchmark\.py|\breplay_bench\b|\bpobsession\b|\bdescribe_build\b|\baudit_build\b"),
     "запускает PoB"),
    (re.compile(r"\bruns\.py\b|\bmachine_load\b"), "смотрит очередь runs"),
    (None, "смотрит логи"),  # a token that ends in .log / .out / .err, checked by `_ends_in_log`
    (re.compile(r"\b(?:sleep|start-sleep|timeout|until)\b"), "ждёт процесс"),
    (re.compile(r"\b(?:rg|grep|find|ls|cat|head|tail|sed|awk|get-content|select-string|get-childitem)\b"
                r"|\bgit\b.*\b(?:log|diff|show|status|blame)\b"), "читает код"),
)


def classify_bash(command: str) -> str:
    """A Bash / PowerShell command in plain words. Quoted text and everything after a heredoc marker `<<` are not
    read. The first matching row of the priority list wins; no row -> "запускает команду"."""
    text = command.split("<<", 1)[0]
    text = _QUOTED.sub(" ", text).lower()
    for pattern, status in _BASH_RULES:
        if pattern is None:
            if _ends_in_log(text):
                return status
            continue
        if pattern.search(text):
            return status
    return "запускает команду"


def _ends_in_log(text: str) -> bool:
    for token in re.split(r"[\s|;&()<>]+", text):
        if token.strip("'\"").endswith((".log", ".out", ".err")):
            return True
    return False


# ---------------------------------------------------------------- ended / opencode

def classify_ended(state: str | None) -> str:
    """A finished session's state: done / stopped / failed; anything else -> NEUTRAL."""
    return {"done": "завершён", "stopped": "остановлен", "failed": "упал"}.get(state or "", NEUTRAL)


_OPENCODE_TOOLS = {
    "webfetch": "ищет в интернете",
    "websearch": "ищет в интернете",
    "codesearch": "ищет в интернете",
    "read": "читает код",
    "list": "читает код",
    "grep": "ищет в коде",
    "glob": "ищет в коде",
    "edit": "правит код",
    "write": "правит код",
    "patch": "правит код",
    "bash": "запускает команду",
    "task": "ждёт воркера",
}


def classify_opencode(last: str, busy: bool) -> str:
    """An opencode session: not busy -> "завершён"; busy -> by the tool named before the first ':' of `last`."""
    if not busy:
        return "завершён"
    if not last.strip():
        return "думает"
    tool = last.split(":", 1)[0].strip().lower()
    return _OPENCODE_TOOLS.get(tool, NEUTRAL)
