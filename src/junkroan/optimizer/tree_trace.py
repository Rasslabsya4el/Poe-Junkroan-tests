"""Tree-stage counters of two rails the trace counted nowhere (#1038): forbidden node text and the +30 attribute cap.

A tree trial is stamped by `TreeOptimizer._flag_trace` (trace-only keys, never in the PoB payload) when it adds a node
whose text the rails forbid, or takes the tree past the +30 attribute cap; `trace.classify` turns the stamps into the
classes below through the registry. Both rails are search-space rules: `evaluated(class) = 0` is the proof. The seed
stage writes them 0/0 first, so an unarmed or never-run stage shows as 0, not as absent (as cluster_trace does).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from junkroan.optimizer.trace import TRACE, register_class

FORBIDDEN_NODE_TEXT = "forbidden_node_text"
ATTRIBUTE_CAP_EXCEEDED = "attribute_cap_exceeded"
STAMP_KEYS: tuple[str, ...] = (FORBIDDEN_NODE_TEXT, ATTRIBUTE_CAP_EXCEEDED)  # the trial keys, equal to the class names

SEED_MOVE = "tree seed"  # the TRACE.move label of the seed stage (`BuildPipeline._seed_scaling`)


def stamps_of(trial: Any) -> dict[str, bool]:
    """The trace-only stamps a trial carries, to be copied beside the PoB payload where it is counted."""

    if not isinstance(trial, Mapping):
        return {}
    return {key: True for key in STAMP_KEYS if trial.get(key)}


def _classes(trial: dict) -> Iterable[str]:
    return [key for key in STAMP_KEYS if trial.get(key)]


def count_zero() -> None:
    """Both classes as 0/0 under the caller's `TRACE.move`."""

    for cls in STAMP_KEYS:
        TRACE.add_generated([cls], 0)
        TRACE.add_evaluated([cls], 0)


register_class(_classes)
