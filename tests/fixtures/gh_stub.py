"""Stub for `gh` used by test_brain_reset_nudge.py via AGENTOPS_HOOK_GH.

Reads the label names to return (comma-separated) from
AGENTOPS_HOOK_GH_LABELS and prints them as `gh issue view N --json labels`
would.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    labels_env = os.environ.get("AGENTOPS_HOOK_GH_LABELS", "")
    names = [n for n in labels_env.split(",") if n]
    print(json.dumps({"labels": [{"name": n} for n in names]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
