"""The forbidden vocabulary of GLOSSARY.md stays out of the agent documents (#1035).

GLOSSARY.md lists `_Avoid_` words per term. Most of them are English words in other senses (job, review, pair,
direction, hand-off, floor), so checking them all would flag ordinary prose. CHECKED_WORDS names the ones the
domain-modeling audit of 14.10 found in use where the glossary forbids them: "gate".

A whole-word match inside a backtick code span is the literal text of a program or a folder name (the daemon's own
log prefix, a run folder), not the term in prose, so code spans are removed before the check.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GLOSSARY = ROOT / "GLOSSARY.md"
CHECKED_WORDS = ("gate",)
CODE_SPAN = re.compile(r"`[^`]*`")  # may run over a line break; the newlines are kept below


def _avoid_words() -> set[str]:
    words: set[str] = set()
    for line in GLOSSARY.read_text(encoding="utf-8").splitlines():
        if not line.startswith("_Avoid_:"):
            continue
        for part in line[len("_Avoid_:"):].split(","):
            head = part.split("(")[0].strip().lower()
            if head:
                words.add(head)
    return words


def _scope_files() -> list[Path]:
    files = [ROOT / "CLAUDE.md", ROOT / "docs" / "TESTING.md"]
    files.extend(sorted((ROOT / "docs" / "agents").rglob("*.md")))
    return files


def test_checked_words_are_forbidden_by_the_glossary():
    avoid = _avoid_words()
    missing = [word for word in CHECKED_WORDS if word not in avoid]
    assert not missing, f"checked words not in any _Avoid_ line of GLOSSARY.md: {missing}"


def test_forbidden_words_are_absent_from_agent_documents():
    patterns = {word: re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE) for word in CHECKED_WORDS}
    hits: list[str] = []
    for path in _scope_files():
        text = path.read_text(encoding="utf-8")
        prose = CODE_SPAN.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
        for number, (line, prose_line) in enumerate(zip(text.splitlines(), prose.splitlines()), start=1):
            for word, pattern in patterns.items():
                if pattern.search(prose_line):
                    hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {word}: {line.strip()[:120]}")
    assert not hits, "forbidden words in agent documents:\n" + "\n".join(hits)
