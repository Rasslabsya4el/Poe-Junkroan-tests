"""#1031: a begun, expired pass guard left by an earlier test must not skip a later test's origin calls (PoB-free).

The guard is poisoned at IMPORT time (collection), before any test body runs, as a `daemon.tick()` of an earlier test
in the same worker leaves it; the autouse fixture in conftest.py has to have made it fresh by the time this body runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from junkroan.runs import pin_ref  # noqa: E402
from junkroan.runs.pass_guard import GUARD, PASS_BUDGET_SECONDS  # noqa: E402
from test_issue756_pin_travels import world  # noqa: E402

GUARD.begin()
GUARD._started -= PASS_BUDGET_SECONDS + 1
GUARD.mark_down("git:origin", "left by an earlier test")


def test_the_guard_a_test_starts_with_is_fresh():
    assert not GUARD.budget_spent()
    assert not GUARD.down("git:origin")


def test_push_pin_is_not_skipped_by_an_earlier_tests_guard(tmp_path):
    origin, pc, laptop, pin = world(tmp_path)
    ok, message = pin_ref.push_pin(pc, pin)
    assert ok, message
