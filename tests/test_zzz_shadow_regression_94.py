"""Regression test for issue #94: a spawn-mode child inheriting a `sys.path` where `scripts/`
precedes `src` (left behind by `test_aaa_shadow_pollution_setup.py`, collected first -- the same
shape dozens of real test files leave, see that file's docstring) must still resolve
`import junkroan` to the package, not to `scripts/junkroan.py`.

This module does no `sys.path` surgery of its own (unlike the pollution file): the point is that a
spawned child re-importing *this* module to unpickle `_target` must not redo any pollution itself
-- its `sys.path` is exactly whatever the parent process handed it at `Process()` time. Before the
fix (`conftest.py::pytest_runtest_setup` pinning `src` back to index 0 before every test body), that
inherited order is the polluted one and the child dies at:

    from junkroan.runs.store import Store
    ...
    File ".../scripts/junkroan.py", line 18, in <module>
        from junkroan.cli import main
    ModuleNotFoundError: No module named 'junkroan.cli'; 'junkroan' is not a package

(the exact shape TEST RUNS quoted from `artifacts/runs/suite-main-24c.out`, 2026-09-27) --
`scripts/junkroan.py` registers itself in `sys.modules["junkroan"]` as a plain module before its own
body runs, so its own `sys.path.insert(0, .../src)` cannot save it: `junkroan` is already claimed as
a non-package.

Bounded to max(15 s, 300 x a timed CPU spin) (tests/timing_bound.py): a dead child never posts to the queue, so an unbounded `queue.get()` would hang
forever -- exactly the hang TEST RUNS observed.
"""

from __future__ import annotations

import multiprocessing

from timing_bound import bound


def _target(queue: "multiprocessing.Queue[tuple[str, str]]") -> None:
    try:
        from junkroan.runs.store import Store
    except Exception as exc:  # pragma: no cover - exercised only on the buggy path
        queue.put(("error", repr(exc)))
        return
    queue.put(("ok", Store.__module__))


def test_spawned_child_resolves_junkroan_as_the_package() -> None:
    ctx = multiprocessing.get_context("spawn")
    queue: "multiprocessing.Queue[tuple[str, str]]" = ctx.Queue()
    proc = ctx.Process(target=_target, args=(queue,))
    limit = bound(15, 300)  # load-scaled (#857): a spawn child's import took >15 s in a 54 min loaded full run
    proc.start()
    try:
        status, payload = queue.get(timeout=limit)
    finally:
        proc.join(timeout=limit)

    assert status == "ok", payload
    assert payload == "junkroan.runs.store"
