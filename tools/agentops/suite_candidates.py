"""Candidate list from a (laptop) pytest run: node ids and collection-error files (#685).

A red laptop suite is only a candidate list; the PC re-runs these targets.
Pure parser, no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LIMIT = 40

_FAILED_RE = re.compile(r"^FAILED\s+(\S+)", re.MULTILINE)
_ERROR_RE = re.compile(r"^ERROR\s+(?!collecting\b)(\S+)", re.MULTILINE)
_COLLECTING_RE = re.compile(r"^_*\s*ERROR collecting\s+(\S+?)\s*_*\s*$", re.MULTILINE)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Candidates:
    ids: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.ids) + len(self.files)

    def targets(self) -> list[str]:
        return [*self.ids, *self.files]

    @property
    def too_many(self) -> bool:
        return self.count > LIMIT


def _add(lst: list[str], item: str) -> None:
    if item not in lst:
        lst.append(item)


def parse_candidates(text: str) -> Candidates:
    text = _ANSI_RE.sub("", text or "")
    # a test's captured output can hold lines that look like a result line (a test of the merge prints
    # `FAILED tests/test_x.py::test_boom`): the real list is the "short test summary info" section
    marker = text.rfind("short test summary info")
    if marker >= 0:
        text = text[marker:]
    ids: list[str] = []
    files: list[str] = []
    for m in _FAILED_RE.finditer(text):
        _add(ids, m.group(1))
    for m in _ERROR_RE.finditer(text):
        tok = m.group(1)
        if "::" in tok:
            _add(ids, tok)
        else:
            _add(files, tok)
    for m in _COLLECTING_RE.finditer(text):
        _add(files, m.group(1))
    return Candidates(ids=ids, files=files)


def too_many_message(c: Candidates) -> str:
    return f"{c.count} candidates > {LIMIT}"
