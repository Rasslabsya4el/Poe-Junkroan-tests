"""The agent rule documents cite only what exists (issue #1036, unit 3).

Two read-only checks over the agent documents (``docs/agents/**/*.md`` and ``.claude/agents/*.md``).
Neither starts PoB; the parser trees are read from the modules, never run.

(a) Every backticked command the documents name must exist:
    - ``python -m tools.agentops <sub> [<sub2>]``: the argparse tree that ``tools/agentops/cli.py``'s own
      ``main`` builds (captured just before it parses), two levels deep where a subcommand has its own
      subcommands;
    - ``python scripts/runs.py <sub>``: a key of ``SUBCOMMANDS`` in ``scripts/runs.py`` (the table its
      own ``main`` dispatches on);
    - ``python scripts/<x>.py``: the script file exists. A script with no subcommands (flags or
      positionals only) takes no subcommand check; a script that gains argparse subcommands fails this
      test until its subcommands are parsed here;
    - the shorthand ``runs <sub>`` (no ``python scripts/``) for a runs.py subcommand: not a command form,
      so it is refused and the real form is written instead.

(b) Every quoted section reference resolves to a heading (a ``#`` line, or a bold lead-in of a list item)
    of a file in those folders:
    - ``section "X"``: any file in the folders;
    - ``<file>.md "X"`` (the form the documents already use for a section of another file): that file,
      looked up as written, then in docs/agents, docs/agents/local and .claude/agents.

Skipped on purpose, the forms the documents use that a name check cannot resolve from these folders:
- ``CLAUDE.md section "X"`` and ``CLAUDE.md "X"``: CLAUDE.md is outside the folders this test reads;
- ``SKILL.md``: a mattpocock skill file, not in the repo (it is never written as a backticked file name
  followed by a quote, so it is not matched at all; ``EXTERNAL_FILES`` names it for safety);
- unquoted prose ("section above", "Section A", "the sections that carry ...") and line references
  (``orch.md:337-348``): no name to resolve.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIRS = (ROOT / "docs" / "agents", ROOT / ".claude" / "agents")
AGENT_FILES = sorted({path for folder in AGENT_DIRS for path in folder.rglob("*.md")})
EXTERNAL_FILES = {"CLAUDE.md", "SKILL.md"}

AGENTOPS_RE = re.compile(r"`python -m tools\.agentops ([a-z][\w-]*)(?: ([a-z][\w-]*))?")
SCRIPT_RE = re.compile(r"`python scripts/(\w+)\.py(?: ([a-z][\w-]*))?")
SHORTHAND_RE = re.compile(r"`runs ([a-z][\w-]*)")
SECTION_RE = re.compile(r'(?<!CLAUDE\.md )\bsection "([^"]+)"', re.IGNORECASE)
FILE_SECTION_RE = re.compile(r'`([\w./-]+\.md)`\s+(?:section\s+)?"([^"]+)"')
HEADING_RE = re.compile(r"^\s*(?:>\s*)*#{1,6}\s+(.+?)\s*$")
BOLD_LEAD_RE = re.compile(r"^\s*(?:>\s*)*(?:[-*]\s+)?\*\*([^*]+?)\*\*")


def _load_runs_module():
    spec = importlib.util.spec_from_file_location("runs_docs_check", ROOT / "scripts" / "runs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNS_SUBCOMMANDS = frozenset(_load_runs_module().SUBCOMMANDS)


class _TreeCaptured(Exception):
    """Raised by the patched ``parse_args``: the tree is built, parsing stops here."""

    def __init__(self, parser: argparse.ArgumentParser) -> None:
        super().__init__(parser)
        self.parser = parser


def _agentops_tree() -> argparse.ArgumentParser:
    from tools.agentops import cli

    def _stop_at_parse(self, args=None, namespace=None):  # noqa: ARG001
        raise _TreeCaptured(self)

    with mock.patch.object(argparse.ArgumentParser, "parse_args", _stop_at_parse):
        with pytest.raises(_TreeCaptured) as caught:
            cli.main([])
    return caught.value.parser


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser] | None:
    for action in parser._actions:  # noqa: SLF001 - argparse has no public accessor for the tree
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return dict(action.choices)
    return None


AGENTOPS_TOP = _subparsers(_agentops_tree())


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _normal(text: str) -> str:
    text = text.replace("`", "").replace("*", "").strip().rstrip(".:;!").lower()
    return re.sub(r"\s+", " ", text)


def _headings(path: Path) -> list[str]:
    found: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line) or BOLD_LEAD_RE.match(line)
        if match:
            found.append(_normal(match.group(1)))
    return found


def _has_heading(title: str, headings: list[str]) -> bool:
    """A heading equal to the title, or one that opens with it and goes on after a space, ``(`` or ``:``."""
    wanted = _normal(title)
    for heading in headings:
        if heading == wanted:
            return True
        if heading.startswith(wanted) and heading[len(wanted)] in " (:":
            return True
    return False


def _command_refs() -> list[tuple[str, int, str, str, str]]:
    """(file, line, kind, word1, word2) for every backticked command the folders name."""
    refs = []
    for path in AGENT_FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in AGENTOPS_RE.finditer(line):
                refs.append((_rel(path), number, "agentops", match.group(1), match.group(2) or ""))
            for match in SCRIPT_RE.finditer(line):
                refs.append((_rel(path), number, "script", match.group(1), match.group(2) or ""))
            for match in SHORTHAND_RE.finditer(line):
                if match.group(1) in RUNS_SUBCOMMANDS:
                    refs.append((_rel(path), number, "shorthand", match.group(1), ""))
    return refs


def _section_refs() -> list[tuple[str, int, str, str]]:
    """(file, line, target, title): target is the named file, or "" for an unqualified ``section "X"``."""
    refs = []
    for path in AGENT_FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for match in FILE_SECTION_RE.finditer(line):
                refs.append((_rel(path), number, match.group(1), match.group(2)))
            for match in SECTION_RE.finditer(line):
                refs.append((_rel(path), number, "", match.group(1)))
    return refs


def _doc_file(name: str) -> Path | None:
    candidates = (
        ROOT / name,
        ROOT / "docs" / "agents" / name,
        ROOT / "docs" / "agents" / "local" / name,
        ROOT / ".claude" / "agents" / name,
    )
    return next((path for path in candidates if path.is_file()), None)


COMMAND_REFS = _command_refs()
SECTION_REFS = _section_refs()
ALL_HEADINGS = sorted({heading for path in AGENT_FILES for heading in _headings(path)})


def test_the_scanner_finds_the_references() -> None:
    # a scan that matched nothing would pass every case below for free
    assert len(COMMAND_REFS) >= 40, f"only {len(COMMAND_REFS)} command references found"
    assert len(SECTION_REFS) >= 10, f"only {len(SECTION_REFS)} section references found"
    assert AGENTOPS_TOP and "core" in AGENTOPS_TOP and "dispatch" in AGENTOPS_TOP
    assert "submit" in RUNS_SUBCOMMANDS and "requeue" in RUNS_SUBCOMMANDS


@pytest.mark.parametrize(
    ("where", "line", "kind", "word", "word2"),
    COMMAND_REFS,
    ids=[f"{where}:{line} {kind} {word} {word2}".rstrip() for where, line, kind, word, word2 in COMMAND_REFS],
)
def test_command_reference_names_a_real_subcommand(where: str, line: int, kind: str, word: str, word2: str) -> None:
    if kind == "agentops":
        assert word in AGENTOPS_TOP, f"{where}:{line}: `python -m tools.agentops {word}` is not a subcommand"
        if word2:
            nested = _subparsers(AGENTOPS_TOP[word])
            if nested is not None:
                assert word2 in nested, (
                    f"{where}:{line}: `python -m tools.agentops {word} {word2}` is not a subcommand of {word}"
                )
    elif kind == "shorthand":
        pytest.fail(
            f"{where}:{line}: `runs {word}` is the shorthand; write `python scripts/runs.py {word}` "
            "(the real command form)"
        )
    else:
        script = ROOT / "scripts" / f"{word}.py"
        assert script.is_file(), f"{where}:{line}: scripts/{word}.py does not exist"
        if word == "runs":
            assert word2 in RUNS_SUBCOMMANDS or not word2, (
                f"{where}:{line}: `python scripts/runs.py {word2}` is not a runs.py subcommand"
            )
        elif word2:
            source = script.read_text(encoding="utf-8")
            assert "add_subparsers" not in source, (
                f"{where}:{line}: scripts/{word}.py has subcommands; parse them in this test"
            )


@pytest.mark.parametrize(
    ("where", "line", "target", "title"),
    SECTION_REFS,
    ids=[f"{where}:{line} {target or 'section'} {title}".strip() for where, line, target, title in SECTION_REFS],
)
def test_section_reference_resolves_to_a_heading(where: str, line: int, target: str, title: str) -> None:
    if target:
        path = _doc_file(target)
        if path is None:
            assert target in EXTERNAL_FILES, f"{where}:{line}: `{target}` is not a file of the folders"
            pytest.skip(f"{target} is outside the folders this test reads")
        assert _has_heading(title, _headings(path)), (
            f"{where}:{line}: section \"{title}\" is not a heading of {_rel(path)}"
        )
    else:
        assert _has_heading(title, ALL_HEADINGS), f"{where}:{line}: section \"{title}\" is not a heading of any agent file"
