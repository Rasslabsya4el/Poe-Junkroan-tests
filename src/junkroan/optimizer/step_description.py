"""The plain-words description every build step and loop move carries (#713). Pure data, imports nothing."""

from __future__ import annotations

import re
from dataclasses import dataclass

MOVE_PREFIX = "move: "  # the key of a loop move in a TEXT dict: "move: refine"


@dataclass(frozen=True)
class Description:
    what_it_changes: str  # what part of the build this step rewrites
    what_it_tries: str  # the candidates and where they come from
    how_judged: str  # which PoB numbers, in which order (floors, DPS, the priced score of D116)
    what_it_keeps: str  # what survives and what is rolled back
    when_skipped: str  # when the step does not run ("never skipped" is an answer)
    where: str  # the code that does it, `file.py:function`, so a reader can check the words

    def fields(self) -> tuple[str, ...]:
        return (self.what_it_changes, self.what_it_tries, self.how_judged, self.what_it_keeps, self.when_skipped)

    def sentence_count(self) -> int:
        return sum(len([s for s in re.split(r"(?<=[.!?])\s+", f.strip()) if s]) for f in self.fields())

    def is_complete(self) -> bool:
        return all(f.strip() for f in self.fields()) and bool(self.where.strip()) and self.sentence_count() >= 3
