"""Stub for `gh` used by test_autopilot_checkpoint.py via AGENTOPS_HOOK_GH.

Reads comment bodies to return from AGENTOPS_HOOK_GH_COMMENTS (separated by
the ASCII unit separator, chr(31), so a body may contain any other
character) and prints them as `gh issue view N --json comments` would.
"""

from __future__ import annotations

import json
import os
import sys


def main() -> int:
    raw = os.environ.get("AGENTOPS_HOOK_GH_COMMENTS", "")
    bodies = raw.split("\x1f") if raw else []
    url = "https://github.com/o/r/issues/1#issuecomment-"
    print(json.dumps({"comments": [{"body": b, "url": f"{url}{1000 + i}"} for i, b in enumerate(bodies)]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
