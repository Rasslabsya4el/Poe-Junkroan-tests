"""Cheap checkpoints ("probes") where a benchmark worker may drop the build it is running (#621).

Disarmed (the default) `check` reads one module global and returns: no PoB call, no number changes.
A worker process arms its own callback; the callback may raise `BuildDeferred` to abandon the build.
`BuildDeferred` is a BaseException on purpose: no `except Exception` in the pipeline may swallow it."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator


class BuildDeferred(BaseException):
    """The running build is dropped at a probe; `stage` is the probe that raised it."""

    def __init__(self, stage: str, note: str = "") -> None:
        super().__init__(stage, note)
        self.stage = stage
        self.note = note


_callback: Callable[[str], None] | None = None


def arm(callback: Callable[[str], None]) -> None:
    global _callback
    _callback = callback


def disarm() -> None:
    global _callback
    _callback = None


def armed() -> bool:
    return _callback is not None


@contextmanager
def armed_with(callback: Callable[[str], None]) -> Iterator[None]:
    """Armed for the block; the previous state (armed or not) comes back even on an exception."""

    global _callback
    previous = _callback
    _callback = callback
    try:
        yield
    finally:
        _callback = previous


def check(stage: str) -> None:
    cb = _callback
    if cb is not None:
        cb(stage)
