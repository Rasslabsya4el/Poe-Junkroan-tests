"""#499: the keymaster installs no package, changes no environment, requeues no job on its own (docs test, no PoB)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYMASTER = ROOT / "docs" / "agents" / "keymaster.md"

PHRASES = ("installs no package", "changes no environment", "requeues no job on its own")


def _flat(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_does_not_do_section_carries_the_rule():
    text = _flat(KEYMASTER)
    section = text[text.index("## What it does not do"):text.index("## Reference")]
    for phrase in PHRASES:
        assert phrase in section, f"keymaster.md 'What it does not do' lacks: {phrase}"
    assert "34fe8e3b" in section and "#499" in section
