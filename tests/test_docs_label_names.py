"""Docs name only labels of the tracker (#320): 19 core (config/core_labels.json: the 16 of #1074 plus flow-fix, priority, hard-push) + 5 program + 4 areas = 28; no `Part of #` instruction."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = set(json.loads((ROOT / "config" / "core_labels.json").read_text(encoding="utf-8")))
PROGRAM = {"pob-free", "in-cloud", "cloud-lane", "core-issue", "core-epic"}
AREAS = {"area:builds", "area:orchestration", "area:crafting", "area:runs"}
GONE = {"documentation", "duplicate", "good first issue", "help wanted", "invalid", "question",
        "fillers", "vetoed"}
NEGATION = re.compile(r"\b(never|not|no)\b", re.I)


def _files():
    files = sorted((ROOT / "docs" / "agents").rglob("*.md"))
    files += sorted((ROOT / ".claude" / "agents").glob("*.md"))
    files.append(ROOT / "CLAUDE.md")
    return files


def _names():
    out = []
    for f in _files():
        for m in re.finditer(r"`([^`\n]+)`", f.read_text(encoding="utf-8")):
            out.append((f, m.group(1)))
    return out


def test_allowed_labels_are_twenty_five():
    assert len(CORE) == 19
    assert CORE & PROGRAM == set()
    assert len(CORE | PROGRAM | AREAS) == 28


def test_no_removed_label_in_backticks():
    names = _names()
    assert len(names) > 100
    print("backticked names read:", len(names))
    bad = [(str(f.relative_to(ROOT)), n) for f, n in names if n in GONE]
    assert bad == []


def test_no_part_of_instruction():
    bad = []
    for f in _files():
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if "Part of #" in line and not NEGATION.search(line):
                bad.append(f"{f.relative_to(ROOT)}:{i}")
    assert bad == []
