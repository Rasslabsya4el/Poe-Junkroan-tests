"""#873: refuse a delegation prompt that asks for CPU-load processes on the PC by day.

The one place where the wording lives. A line ASKS when it has a load word (spinner, burner, stress loop,
busy loop, "load the CPU") together with a request verb, and carries no allowed route (`scripts/burner.py`,
laptop, night window, queue) and no negation/quote marker (never, not, no, a quoted rule). A line that only
mentions the words passes. The refusal at the burner itself is `junkroan.burner.refusal` (#842, #869).
"""
from __future__ import annotations

import re

_LOAD = re.compile(r"\b(spinners?|burners?|stress[- ]loops?|busy[- ]loops?|load the cpu)\b", re.I)
_ASK = re.compile(r"\b(start|starts|run|runs|spawn|launch|fire up|use|create|put|load|need|give|make)\b", re.I)
_ROUTE = re.compile(r"burner\.py|laptop|night|01:00|through the queue|runs submit", re.I)
_NEG = re.compile(r"\b(never|not|no|without|don't|do not|refus\w*|forbidden)\b|[\"`'“”]", re.I)

ALLOWED_FORM = "scripts/burner.py on the laptop (through the queue) or in the night window 01:00-08:00"


def check_prompt(text: str) -> str | None:
    """A refusal line naming the allowed form, or None."""
    for line in re.split(r"(?<=[.;!?])\s+|\n", text):
        if not _LOAD.search(line) or not _ASK.search(line):
            continue
        if _ROUTE.search(line) or _NEG.search(line):
            continue
        return (f"refused: the prompt asks for load processes on the PC by day ({line.strip()[:120]!r}); "
                f"a 'busy machine' row is {ALLOWED_FORM}, never a count of spinners")
    return None
