"""`junkroan.pob.no_pob_switch` (#114, #198): the `JUNKROAN_NO_POB` flag, the guard at the one
place that starts the real PoB worker process, and its launch-attempt counter."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from junkroan.pob import no_pob_switch

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_counter():
    no_pob_switch.reset_launch_attempts()
    yield
    no_pob_switch.reset_launch_attempts()


def test_pob_disabled_reads_the_env_var(monkeypatch):
    monkeypatch.delenv(no_pob_switch.ENV_VAR, raising=False)
    assert no_pob_switch.pob_disabled() is False
    monkeypatch.setenv(no_pob_switch.ENV_VAR, "0")
    assert no_pob_switch.pob_disabled() is False
    monkeypatch.setenv(no_pob_switch.ENV_VAR, "1")
    assert no_pob_switch.pob_disabled() is True


def test_guard_raises_and_counts_the_attempt_when_disabled(monkeypatch):
    monkeypatch.setenv(no_pob_switch.ENV_VAR, "1")
    assert no_pob_switch.launch_attempts() == 0
    with pytest.raises(RuntimeError, match="refusing to launch"):
        no_pob_switch.guard_pob_launch()
    assert no_pob_switch.launch_attempts() == 1
    with pytest.raises(RuntimeError):
        no_pob_switch.guard_pob_launch()
    assert no_pob_switch.launch_attempts() == 2


def test_guard_is_a_noop_and_counts_nothing_when_not_disabled(monkeypatch):
    monkeypatch.delenv(no_pob_switch.ENV_VAR, raising=False)
    no_pob_switch.guard_pob_launch()  # does not raise
    assert no_pob_switch.launch_attempts() == 0


# -- a test that carries the `pob` mark but no matching `skipif` reason is still skipped ----------

_SYNTHETIC_TEST = textwrap.dedent(
    """
    import pytest

    @pytest.mark.pob
    def test_would_open_a_pob_session():
        raise AssertionError("this body must never run under JUNKROAN_NO_POB")
    """
)


def test_a_pob_marked_test_with_no_pob_reason_is_still_skipped_under_the_switch():
    import os

    # Written inside tests/ (not tmp_path) so tests/conftest.py's hook actually applies to it;
    # removed again in `finally` whatever the outcome.
    synthetic = PROJECT_ROOT / "tests" / "test_synthetic_pob_marked_198.py"
    synthetic.write_text(_SYNTHETIC_TEST, encoding="utf-8")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:faulthandler", "-m", "pob",
             "tests/test_synthetic_pob_marked_198.py"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            env={**os.environ, no_pob_switch.ENV_VAR: "1"},
        )
    finally:
        synthetic.unlink(missing_ok=True)

    assert "1 skipped" in result.stdout, result.stdout
    assert "1 passed" not in result.stdout
    assert "AssertionError" not in result.stdout
