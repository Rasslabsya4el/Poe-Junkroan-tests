"""The agent rules name no fixed worker or slot count (issue #1126, rows 1-2 of its acceptance).

The owner, 2026-10-05: "Не надо хардкодить 6 воркеров, система должна сама выбирать". The rules say the
system picks the count from the free slots (`runs.py submit --workers auto`, the free-slot formula of #570 /
#684, the budget keys in `var/machine_budget.json`), never a copied number.

Read-only: greps three documents, starts nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DOCS = (
    ROOT / "CLAUDE.md",
    ROOT / "docs" / "agents" / "machine.md",
    ROOT / "docs" / "agents" / "runs.md",
)

# The three forms the issue names: `--workers <digit>`, "<digit> workers", "<digit> PoB slots".
FIXED_COUNT = re.compile(r"--workers \d|\d+ workers|\d+ PoB slots")


def _hits(path: Path) -> list[str]:
    hits = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if FIXED_COUNT.search(line):
            hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}")
    return hits


def test_pattern_catches_the_three_forms():
    # Guards against a vacuous test: each form the issue names must match.
    assert FIXED_COUNT.search("benches run with `--workers 2`")
    assert FIXED_COUNT.search("the queue owns 5 workers")
    assert FIXED_COUNT.search("gets at most 4 PoB slots")
    assert not FIXED_COUNT.search("`--workers auto` (the daemon sizes it)")


def test_agent_rules_name_no_fixed_worker_count():
    hits = [hit for path in DOCS for hit in _hits(path)]
    assert hits == [], "fixed worker/slot counts left in the agent rules:\n" + "\n".join(hits)
