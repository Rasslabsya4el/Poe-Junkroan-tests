"""A transparent PobSession proxy that records every call it forwards (issue #35, M1).

The proof instrument of a refactor that must reproduce builds to the digit: the same build run
before and after the refactor must make the same PoB calls in the same order with the same
arguments. `RecordingPob` forwards every attribute read, write and call to the session it wraps and
appends one JSON line per call -- sequence number, method name and a stable hash of the arguments --
so two transcripts are compared with a plain diff. Without the scripts' `--record-calls` option
nothing wraps the session and nothing changes.

It lives outside `junkroan.pob` on purpose: the inherited runtime stays untouched.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping

LONG_STRING = 256  # a longer string (an XML, an item's raw text) enters the canonical form as its hash
PREVIEW_CHARS = 160  # how much of the canonical arguments a line shows for a human reading a diff
TRACE_ONLY_TRIAL_KEYS = frozenset({"path"})  # read by the trace counter only, never sent to PoB (#511)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()[:16]


# Elements whose children PoB writes from a Lua table keyed by name, so their order changes from one
# process to the next (#534, read on the smoke six: the root's sections, Calcs' inputs and sections,
# a ConfigSet's inputs and placeholders, an ItemSet's slots). Every other child order is the build's own.
# #897: and a Spec's Sockets (PassiveSpec.lua:215 `pairs(self.jewels)`).
UNORDERED_CHILDREN = frozenset({"PathOfBuilding", "Calcs", "ConfigSet", "ItemSet", "Sockets"})


def _child_key(element: ET.Element) -> tuple:
    return element.tag, sorted(element.attrib.items()), element.text or ""


def _canonical_xml(text: str) -> str:
    """#534: an XML text with the attributes of every element sorted, and the children of the
    elements PoB writes in table order (`UNORDERED_CHILDREN`) sorted too, so two serialisations of
    one build give one digest. Text that does not parse as XML is returned as it is."""

    if not text.lstrip().startswith("<"):
        return text
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return text
    for element in root.iter():
        element.attrib = dict(sorted(element.attrib.items()))
        if element.tag in UNORDERED_CHILDREN:
            element[:] = sorted(element, key=_child_key)
            for child in element:  # a moved child would carry the indentation of its old place
                child.tail = None
    return ET.tostring(root, encoding="unicode")


def canonical(value: Any) -> Any:
    """A JSON-ready form of `value` that is equal for equal arguments on every run: sets sorted,
    tuples as lists, mapping keys as strings (sorted by the dump), long strings hashed, and an
    object without a stable form reduced to its type name (never a repr with a memory address)."""

    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= LONG_STRING:
            return value
        return {"sha256": _digest(_canonical_xml(value)), "len": len(value)}
    if isinstance(value, (bytes, bytearray)):
        return {"sha256": hashlib.sha256(bytes(value)).hexdigest()[:16], "len": len(value)}
    if isinstance(value, Mapping):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [canonical(item) for item in value]
        return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=str))
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {"__type__": type(value).__name__,
                **{field.name: canonical(getattr(value, field.name)) for field in dataclasses.fields(value)}}
    if callable(value):
        return f"<callable {type(value).__name__}>"
    text = repr(value)
    return f"<{type(value).__name__}>" if " at 0x" in text else text


def call_line(seq: int, method: str, args: tuple, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """One transcript line: what was called, in which position, with which arguments (hashed)."""

    if method == "trial_stats" and args and isinstance(args[0], (list, tuple)):
        # a trial's trace-only keys never reach PoB (`PobSession.trial_stats` builds its payload
        # without them), so the transcript leaves them out too (#511: a greedy trial's `path`)
        args = ([{k: v for k, v in t.items() if k not in TRACE_ONLY_TRIAL_KEYS} if isinstance(t, Mapping) else t
                 for t in args[0]], *args[1:])
    dumped = json.dumps(canonical({"args": list(args), "kwargs": dict(kwargs)}), sort_keys=True,
                        separators=(",", ":"), default=str)
    return {"seq": seq, "method": method, "args": _digest(dumped), "preview": dumped[:PREVIEW_CHARS]}


class RecordingPob:
    """Forwards everything to `pob`; every call through it becomes one line of `path` (JSONL).

    Attribute writes (`pob.mean_parts = ...`, `pob.fulldps_shortcut = ...`) land on the wrapped
    session, so code that sets them behaves exactly as without the proxy. A call the session makes
    on itself is not seen: the transcript is what the optimizer asked of PoB.
    """

    def __init__(self, pob: Any, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "_rec_pob", pob)
        object.__setattr__(self, "_rec_path", target)
        object.__setattr__(self, "_rec_file", target.open("w", encoding="utf-8"))
        object.__setattr__(self, "_rec_seq", 0)

    def _rec_write(self, method: str, args: tuple, kwargs: Mapping[str, Any]) -> None:
        seq = self._rec_seq + 1
        object.__setattr__(self, "_rec_seq", seq)
        handle = self._rec_file
        if handle is not None:
            handle.write(json.dumps(call_line(seq, method, args, kwargs), sort_keys=True) + "\n")

    def __getattr__(self, name: str) -> Any:
        value = getattr(object.__getattribute__(self, "_rec_pob"), name)
        if not callable(value) or isinstance(value, type):
            return value

        def recorded(*args: Any, **kwargs: Any) -> Any:
            self._rec_write(name, args, kwargs)
            return value(*args, **kwargs)

        recorded.__name__ = name
        return recorded

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._rec_pob, name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._rec_pob, name)

    @property
    def recorded_calls(self) -> int:
        return int(self._rec_seq)

    def close_recording(self) -> None:
        """Flush and close the transcript; the wrapped session stays open (its owner closes it)."""

        handle = self._rec_file
        if handle is not None:
            handle.close()
            object.__setattr__(self, "_rec_file", None)


__all__ = ["RecordingPob", "call_line", "canonical"]
