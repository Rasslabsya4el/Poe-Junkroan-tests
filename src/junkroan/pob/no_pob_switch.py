"""The `JUNKROAN_NO_POB` switch (#114).

`veto`'s default test gate (`tools/agentops/provisional.py`) has to finish inside its 10 min
timeout on the main checkout, which still has `var/cache/pob` and `vendor/pob/source` (the
pinned PoB runtime and its vendored skill data, reached through junctions a worktree never
gets). Skipping PoB-needing tests by checking whether those paths exist would make the veto's
result depend on which checkout happened to run it; this switch makes it explicit instead.

Two uses:

- `pob_disabled()`: `tests/conftest.py`'s `pytest_collection_modifyitems` reads it to force
  every PoB-gated test (identified by its existing `skipif` reason, or the `pob` mark, see that
  hook) to SKIP, regardless of what is actually present on disk.
- `guard_pob_launch()`: called at the one place that spawns the real headless PoB worker
  process (`PinnedPoBHeadlessRuntimeAdapter.launch_session`), so a test that slips past every
  marker still cannot start `lua51.dll` while the switch is on -- it raises instead. Each refusal
  also bumps a process-wide counter (`launch_attempts()`, issue #198): a mis-marked `pob` test
  that starts PoB under the switch fails at once (the raise) AND leaves a number > 0 behind for
  whoever wants to confirm, after a whole suite ran, that PoB was never started outside the queue.
"""

from __future__ import annotations

import os

ENV_VAR = "JUNKROAN_NO_POB"

_launch_attempts = 0


def pob_disabled() -> bool:
    """True when the switch is on: `JUNKROAN_NO_POB` set to anything but `""`/`"0"`."""

    return os.environ.get(ENV_VAR, "").strip() not in ("", "0")


def guard_pob_launch() -> None:
    """Raise instead of letting the caller start the real PoB worker process.

    Call this at the top of any function that would spawn it -- currently just
    `PinnedPoBHeadlessRuntimeAdapter.launch_session`.
    """

    if pob_disabled():
        global _launch_attempts
        _launch_attempts += 1
        raise RuntimeError(
            f"{ENV_VAR} is set: refusing to launch the PoB worker process (issue #114)."
        )


def launch_attempts() -> int:
    """How many times `guard_pob_launch` has refused a launch in this process so far."""

    return _launch_attempts


def reset_launch_attempts() -> None:
    """Tests only: start a fresh count."""

    global _launch_attempts
    _launch_attempts = 0


__all__ = [
    "ENV_VAR",
    "guard_pob_launch",
    "launch_attempts",
    "pob_disabled",
    "reset_launch_attempts",
]
