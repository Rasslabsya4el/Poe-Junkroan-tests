from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tools" / "agentops" / "core_manifest.txt"
SHELL_TOOLS = {"Bash", "PowerShell"}
MARKS = (
    "A permission-guard refusal",
    "A permission-guard refusal (its reason starts \"permission guard, red line\") is final",
    "A worker git or process guard refusal names the allowed form itself",
)
# The core's own sentence (docs/agents/core-block.md and the core role files carry it verbatim).
CORE_SENTENCE = (
    "A permission-guard refusal (its reason starts \"permission guard, red line\") is final: never retry it in another "
    "form or as separate calls; write the exact call and the red line into the issue (a subagent names them in its "
    "report). A worker git or process guard refusal names the allowed form itself: follow it."
)


def _files():
    files = sorted((ROOT / ".claude" / "agents").glob("*.md"))
    assert files
    return files + [ROOT / "docs" / "agents" / "orch.md"]


def _core_paths():
    lines = MANIFEST.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def _tools(text):
    """The frontmatter `tools:` of a role file as a set; None for a file with no frontmatter tools line."""
    if not text.startswith("---"):
        return None
    for line in text.split("---", 2)[1].splitlines():
        if line.startswith("tools:"):
            return {tool.strip() for tool in line.split(":", 1)[1].split(",")}
    return None


def test_every_agent_file_and_orch_doc_carries_the_guard_rule():
    core = _core_paths()
    for f in _files():
        text = f.read_text(encoding="utf-8")
        if f.relative_to(ROOT).as_posix() not in core:
            # this repo's own file (keymaster.md): every mark
            for mark in MARKS:
                assert mark in text, f"{f.name} lacks: {mark}"
            continue
        tools = _tools(text)
        if tools is not None and not tools & SHELL_TOOLS:
            # a core reviewer has no shell, so no permission-guard refusal can reach it (the guard reads Bash
            # command text); the core states no guard line in reviewer-spec.md or reviewer-standards.md
            continue
        # a core file that can run a shell carries the core's sentence verbatim (docs/agents/orch.md included)
        assert CORE_SENTENCE in text, f"{f.name} lacks the core guard sentence"
