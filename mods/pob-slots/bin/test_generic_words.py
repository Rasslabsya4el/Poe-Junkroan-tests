"""Row 1 guard (#796): the generic collector holds no word of the project it serves. Lines of `collect.py` matching
`pob|build|laptop|junkroan|poe` (case-insensitive) are counted and must be 0; the count is printed.

    python -m pytest -q -s bin/test_generic_words.py
"""
import re
from pathlib import Path

WORDS = re.compile(r"pob|build|laptop|junkroan|poe", re.I)


def test_collect_py_has_no_project_words():
    lines = (Path(__file__).resolve().parent / "collect.py").read_text(encoding="utf-8").splitlines()
    hits = [(n, line.strip()) for n, line in enumerate(lines, 1) if WORDS.search(line)]
    print(f"collect.py: {len(lines)} lines, {len(hits)} match pob|build|laptop|junkroan|poe")
    assert not hits, hits
