"""Issue #1067 (rules): the Pocock skills are hard steps in the role files and protocols.

Reads the files from the repo root and checks the wording the steps owe: the researchers'
`tools:` lines, the `research` skill in researcher-how only, the `diagnosing-bugs` step in
the keymaster's Diagnose step, the merge-conflict rule in the four files that resolve merges
(#1080: no skill is named there any more), and the list of skills PORTING.md names."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def _tools_line(rel: str) -> str:
    for line in _read(rel).splitlines():
        if line.startswith("tools:"):
            return line
    raise AssertionError(f"{rel} has no tools: frontmatter line")


def _keymaster_diagnose_step() -> str:
    lines = _read("docs/agents/keymaster.md").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("2. Diagnose"))
    end = next(i for i, line in enumerate(lines) if i > start and line.startswith("3. Fix"))
    return "\n".join(lines[start:end])


def test_researchers_have_the_skill_tool_and_how_can_write_one_file():
    find_tools = _tools_line(".claude/agents/researcher-find.md")
    how_tools = _tools_line(".claude/agents/researcher-how.md")
    assert "Skill" in find_tools.split(":", 1)[1].replace(",", " ").split()
    assert "Skill" in how_tools.split(":", 1)[1].replace(",", " ").split()
    assert "Write" in how_tools.split(":", 1)[1].replace(",", " ").split()


def test_research_skill_is_a_rule_of_researcher_how_only():
    how = _read(".claude/agents/researcher-how.md")
    find = _read(".claude/agents/researcher-find.md")
    assert how.count("mattpocock-skills:research") == 1
    assert find.count("mattpocock-skills:research") == 0


def test_keymaster_diagnose_step_calls_diagnosing_bugs_and_closing_line_starts_diagnosis():
    step = _keymaster_diagnose_step()
    assert "mattpocock-skills:diagnosing-bugs" in step
    assert "diagnosis:" in step


def test_removed_resolving_merge_conflicts_skill_is_named_in_no_resolving_file():
    # #1080: the plugin dropped the skill; the four files that resolve merges no longer name it
    for rel in (
        "docs/agents/core-block.md",
        "docs/agents/orch.md",
        ".claude/agents/worker.md",
        ".claude/agents/worker-strong.md",
    ):
        assert "resolving-merge-conflicts" not in _read(rel), rel


def test_porting_names_the_seven_skills_with_research():
    porting = _read("docs/agents/PORTING.md")
    assert "resolving-merge-conflicts" not in porting
    assert "research" in porting
