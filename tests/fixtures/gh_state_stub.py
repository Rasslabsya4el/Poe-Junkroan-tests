"""Stub for `gh issue view N --json comments` backed by a JSON file (#562).

AGENTOPS_HOOK_GH_STATE names a JSON file `{"comments": [{"id", "body", "url"}, ...]}`; the test
mutates it the way a session would (create appends, edit replaces a body). Printing it is all
this stub does, with `id` as the node id and `url` ending in `#issuecomment-<numeric id>`.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    with open(os.environ["AGENTOPS_HOOK_GH_STATE"], encoding="utf-8") as f:
        sys.stdout.write(f.read())
    return 0


if __name__ == "__main__":
    sys.exit(main())
