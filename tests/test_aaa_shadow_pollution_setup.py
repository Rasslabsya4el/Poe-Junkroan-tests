"""Reproduces, deliberately, the `sys.path` shape that causes issue #94: many test files add
`scripts/` to `sys.path` (so they can `import search` / `import benchmark` / ... as top-level
modules) *without* re-inserting `src` after it -- unlike the documented "scripts first, then src
in front of it" pattern in `scripts/benchmark.py:39`. Once such a file is collected, `scripts/`
sits ahead of `src` in `sys.path` for the rest of the pytest session (pytest collects every test
module before running any test body), and `scripts/junkroan.py` -- a plain module, not a package
-- shadows the `junkroan` package for any later spawn-mode child, whose bootstrap inherits that
stale `sys.path` verbatim.

Named to collect before `test_zzz_shadow_regression_94.py` (pytest sorts a directory's test files
alphabetically), so the pollution below is in place, in the *parent* process, before that file's
test runs -- exactly the real-world sequence TEST RUNS found (issue #94).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Deliberately the buggy pattern (scripts, no src re-add) that ~24 existing test files carry.
# Do not "fix" this insert -- it is this regression's setup, not a bug in this file.
sys.path.insert(0, str(ROOT / "scripts"))


def test_scripts_dir_landed_on_sys_path() -> None:
    """Sanity check that the pollution above actually took effect at collection time.

    Not an ordering check: `conftest.py::pytest_runtest_setup` (issue #94) re-pins `src` ahead of
    `scripts` before *every* test body, this one included, so by the time this assertion runs the
    order is already fixed -- exactly the point. The `scripts` entry itself is left in `sys.path`
    (the fix only re-pins `src`, it does not remove `scripts`), which is what
    `test_zzz_shadow_regression_94.py` needs to still find in the *inherited* order.
    """
    assert str(ROOT / "scripts") in sys.path
