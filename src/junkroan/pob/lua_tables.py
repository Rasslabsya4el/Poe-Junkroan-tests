"""Restricted Lua literal parsing helpers for PoB-derived corpus extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_NUMBER_PATTERN = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")


class LuaParseError(ValueError):
    """Raised when a Lua literal surface cannot be parsed safely."""


@dataclass(slots=True)
class _Entry:
    key: Any | None
    value: Any


class _LuaParser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.pos = 0

    def parse(self) -> Any:
        self._skip_ignored()
        value = self._parse_value()
        self._skip_ignored()
        return value

    def parse_after_keyword(self, keyword: str) -> Any:
        self._skip_ignored()
        if not self.text.startswith(keyword, self.pos):
            raise LuaParseError(f"Expected keyword {keyword!r} at position {self.pos}.")
        end = self.pos + len(keyword)
        if end < self.length and (self.text[end].isalnum() or self.text[end] == "_"):
            raise LuaParseError(f"Keyword {keyword!r} is followed by an identifier character.")
        self.pos = end
        return self.parse()

    def _peek(self) -> str | None:
        if self.pos >= self.length:
            return None
        return self.text[self.pos]

    def _skip_ignored(self) -> None:
        while self.pos < self.length:
            char = self.text[self.pos]
            if char.isspace():
                self.pos += 1
                continue
            if self.text.startswith("--", self.pos):
                self.pos += 2
                while self.pos < self.length and self.text[self.pos] not in "\r\n":
                    self.pos += 1
                continue
            break

    def _parse_value(self) -> Any:
        self._skip_ignored()
        char = self._peek()
        if char is None:
            raise LuaParseError("Unexpected end of input while parsing a value.")
        if char == "{":
            return self._parse_table()
        if char in {'"', "'"}:
            return self._parse_string()
        if self.text.startswith("[[", self.pos):
            return self._parse_long_string()
        if char == "-" or char.isdigit():
            return self._parse_number()
        if char.isalpha() or char == "_":
            identifier = self._parse_identifier()
            if identifier == "true":
                return True
            if identifier == "false":
                return False
            if identifier == "nil":
                return None
            raise LuaParseError(f"Unsupported bare identifier value {identifier!r}.")
        raise LuaParseError(f"Unexpected character {char!r} at position {self.pos}.")

    def _parse_table(self) -> Any:
        self._expect("{")
        entries: list[_Entry] = []
        implicit_index = 1
        while True:
            self._skip_ignored()
            if self._peek() == "}":
                self.pos += 1
                break

            key: Any | None = None
            checkpoint = self.pos
            if self._peek() == "[":
                self.pos += 1
                key = self._parse_value()
                self._skip_ignored()
                self._expect("]")
                self._skip_ignored()
                self._expect("=")
                value = self._parse_value()
                entries.append(_Entry(key=key, value=value))
            elif self._peek() and (self._peek().isalpha() or self._peek() == "_"):
                identifier = self._parse_identifier()
                self._skip_ignored()
                if self._peek() == "=":
                    self.pos += 1
                    value = self._parse_value()
                    entries.append(_Entry(key=identifier, value=value))
                else:
                    self.pos = checkpoint
                    value = self._parse_value()
                    entries.append(_Entry(key=None, value=value))
            else:
                value = self._parse_value()
                entries.append(_Entry(key=None, value=value))

            self._skip_ignored()
            if self._peek() in {",", ";"}:
                self.pos += 1

        normalized: list[tuple[Any, Any]] = []
        for entry in entries:
            if entry.key is None:
                key = implicit_index
            else:
                key = entry.key
            normalized.append((key, entry.value))
            if isinstance(key, int) and key >= implicit_index:
                implicit_index = key + 1

        if normalized and all(isinstance(key, int) and key >= 1 for key, _ in normalized):
            ordered_keys = [key for key, _ in normalized]
            if sorted(ordered_keys) == list(range(1, len(normalized) + 1)):
                lookup = {key: value for key, value in normalized}
                return [lookup[index] for index in range(1, len(normalized) + 1)]

        return {key: value for key, value in normalized}

    def _parse_string(self) -> str:
        quote = self._peek()
        if quote is None:
            raise LuaParseError("Unexpected end of input before string literal.")
        self.pos += 1
        parts: list[str] = []
        while self.pos < self.length:
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                return "".join(parts)
            if char == "\\":
                if self.pos >= self.length:
                    raise LuaParseError("Unterminated escape sequence in string literal.")
                escaped = self.text[self.pos]
                self.pos += 1
                parts.append(
                    {
                        "n": "\n",
                        "r": "\r",
                        "t": "\t",
                        "\\": "\\",
                        '"': '"',
                        "'": "'",
                    }.get(escaped, escaped)
                )
                continue
            parts.append(char)
        raise LuaParseError("Unterminated string literal.")

    def _parse_long_string(self) -> str:
        if not self.text.startswith("[[", self.pos):
            raise LuaParseError("Expected Lua long string start '[['.")
        start = self.pos + 2
        end = self.text.find("]]", start)
        if end == -1:
            raise LuaParseError("Unterminated Lua long string literal.")
        self.pos = end + 2
        return self.text[start:end]

    def _parse_number(self) -> int | float:
        match = _NUMBER_PATTERN.match(self.text, self.pos)
        if not match:
            raise LuaParseError(f"Invalid number literal at position {self.pos}.")
        token = match.group(0)
        self.pos = match.end()
        if "." in token or "e" in token.lower():
            return float(token)
        return int(token)

    def _parse_identifier(self) -> str:
        start = self.pos
        if self.pos >= self.length or not (self.text[self.pos].isalpha() or self.text[self.pos] == "_"):
            raise LuaParseError(f"Expected identifier at position {self.pos}.")
        self.pos += 1
        while self.pos < self.length and (self.text[self.pos].isalnum() or self.text[self.pos] == "_"):
            self.pos += 1
        return self.text[start:self.pos]

    def _expect(self, token: str) -> None:
        self._skip_ignored()
        if not self.text.startswith(token, self.pos):
            raise LuaParseError(f"Expected {token!r} at position {self.pos}.")
        self.pos += len(token)


def parse_lua_return_value(text: str) -> Any:
    """Parse a PoB Lua file that returns a literal table."""

    parser = _LuaParser(text)
    return parser.parse_after_keyword("return")


def parse_lua_assignment_table(text: str, variable_name: str) -> dict[str, Any]:
    """Parse repeated ``var["key"] = { ... }`` assignments from a PoB Lua file."""

    parser = _LuaParser(text)
    parsed: dict[str, Any] = {}
    needle = f"{variable_name}["
    while True:
        index = text.find(needle, parser.pos)
        if index == -1:
            break
        parser.pos = index + len(variable_name)
        parser._skip_ignored()
        parser._expect("[")
        key = parser._parse_value()
        parser._skip_ignored()
        parser._expect("]")
        parser._skip_ignored()
        parser._expect("=")
        value = parser._parse_value()
        if not isinstance(key, str):
            raise LuaParseError(f"Assignment key for {variable_name} must be a string, got {type(key).__name__}.")
        parsed[key] = value
    return parsed


def parse_lua_local_value(text: str, variable_name: str) -> Any:
    """Parse a literal assigned to ``variable_name`` in Lua source."""

    match = re.search(rf"\b{re.escape(variable_name)}\s*=", text)
    if match is None:
        raise LuaParseError(f"Variable {variable_name!r} not found.")
    parser = _LuaParser(text)
    parser.pos = match.end()
    return parser.parse()
