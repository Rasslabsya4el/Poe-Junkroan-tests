"""The gear rejection's one question about a red line (#1124, unit 3 of 5): which of an item's `unsupported_lines`
still block it.

`craft_rare` prints every explicit mod line PoB does not read as `unsupported_lines`. A line with a record in the
red-line marks that is non-empty on a lane is a marked line: the lane writers put it into the build as a custom
modifier, so the item stays a candidate. A line with no record, or a zero record, still blocks. Legality `problems`
(illegal mod combinations) are a different list and never pass through here: the caller keeps dropping on them.

With no marks (no file, or an empty one) the answer is the input, so every call site behaves as before.
"""

from __future__ import annotations

from typing import Iterable

from junkroan.optimizer.red_line_marks import LANES, RedLineMarks, load_marks

__all__ = ["red_lines_blocking"]


def red_lines_blocking(
    unsupported_lines: Iterable[str],
    lane: str | None = None,
    marks: RedLineMarks | None = None,
) -> list[str]:
    """The lines with no usable mark, in their given order.

    `lane` is the lane being built ("boss" or "optimistic"). A caller that does not know its lane passes None:
    a line then counts as allowed when it is marked on EITHER lane. `marks` defaults to `load_marks()`.
    """

    lines = list(unsupported_lines)
    if not lines:
        return lines
    marks = load_marks() if marks is None else marks
    if lane is not None and lane not in LANES:
        raise ValueError(f"lane must be one of {LANES} or None, got {lane!r}")
    lanes = LANES if lane is None else (lane,)
    return [line for line in lines if not any(marks.is_marked(line, one) for one in lanes)]
