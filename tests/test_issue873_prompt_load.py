"""#873: a delegation prompt asking for load on the PC by day is refused; mentions and routed rows pass."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.agentops import delegation_load_check as chk  # noqa: E402

ASKING = [
    "Start 12 spinners on the PC and measure the slots.",
    "Start spinners on the PC and measure the slots.",
    "Run a stress loop with 8 workers here to fill the machine.",
    "Run a stress loop here to fill the machine.",
    "Load the CPU on the PC with 6 processes while the test runs.",
    "Load the CPU on the PC while the test runs.",
]
PASSING = [
    "Busy machine row: submit scripts/burner.py through the queue for the laptop.",
    "Start 12 spinners on the laptop, never on the PC.",
    "Between 01:00 and 08:00 run 12 burners for the busy row.",
    "The ticket is about the burner test in tests/test_issue842_burner.py.",
    'The rule says: "no CPU burner on the PC between 08:00 and 01:00".',
    "Rule: a delegation prompt never asks for 12 spinners on the PC by day; the row goes to `scripts/burner.py`.",
]


def test_asking_prompts_refused():
    refused = [p for p in ASKING if chk.check_prompt(p)]
    print(f"asking refused {len(refused)} of {len(ASKING)}")
    assert len(refused) == 6
    assert "scripts/burner.py" in chk.check_prompt(ASKING[0])


def test_passing_prompts_pass():
    refused = [p for p in PASSING if chk.check_prompt(p)]
    print(f"passing refused {len(refused)} of {len(PASSING)}")
    assert refused == []


def _templates():
    files = sorted((ROOT / ".claude" / "agents").glob("*.md"))
    files += [ROOT / "docs/agents/orch.md", ROOT / "docs/agents/local/orch.md"]
    return files


@pytest.mark.parametrize("path", _templates(), ids=lambda p: p.name)
def test_templates_pass(path):
    assert chk.check_prompt(path.read_text(encoding="utf-8")) is None


def test_template_line_names_burner():
    s = (ROOT / "docs/agents/local/orch.md").read_text(encoding="utf-8")
    line = next(l for l in s.splitlines() if l.startswith("Local addition (#842"))
    assert "scripts/burner.py" in line and "never as a count of spinners" in line
