"""The flask step's `FlaskProbe` over a `PobSession` (#436 unit 6, #589).

`flask_step.run_flask_step` drives the build only through the probe; this one answers every question with PoB:

- `put_flask(slot, candidate)` equips `candidate.raw(item_level)` in that Flask slot; `clear_flask` empties it. Both
  leave every other slot as it is (`PobSession.equip` is per slot). The `active` flags are derived by PoB's uptime
  calc on every plain stats read (#575), never set here, except inside `measure_active`.
- `score()` is the lane's objective as a `Score` (one full PoB calc); the step compares Scores, never a scalar.
- `input_flasks()` / `put_input()` are what the slot held when the step started (`equipped_item_raws`, one export)
  and putting it back as its raw (#589 R2).
- `measure_active(slot, candidate)` is the as-if-active read (#589 R3): the candidate in the slot, that slot's flag
  forced on, one stats read that keeps forced flags (`keep_flask_flags=True`); the next plain read re-derives them.
- `snapshot()` / `restore()` are the exported XML and a load of it: exact, the active flags ride in the XML.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Mapping

from junkroan.optimizer.flask_lines import FlaskCandidate
from junkroan.optimizer.objective import Objective, Score
from junkroan.pob.session import PobSession

DEFENCE_KEYS = ("TotalEHP", "PhysicalMaximumHitTaken", "EffectiveMovementSpeedMod")


def _defence(got: Mapping[str, Any]) -> tuple[float, float, float]:
    return (float(got.get("TotalEHP") or 0.0), float(got.get("PhysicalMaximumHitTaken") or 0.0),
            float(got.get("EffectiveMovementSpeedMod") or 0.0))


@dataclass(frozen=True)
class InputFlask:
    """A flask the build came in with: its raw text as PoB holds it, shaped like a `FlaskCandidate` for the step."""

    text: str
    active: bool = False
    is_input = True

    @property
    def base(self) -> Any:
        lines = [ln for ln in self.text.splitlines() if ln.strip()]
        name = lines[1] if len(lines) > 1 and lines[0].startswith("Rarity:") else (lines[0] if lines else "?")
        # a rare/unique raw: name line, then the base line; a magic flask has the name line only (no base line)
        rare = bool(lines) and lines[0].upper().replace(" ", "") in ("RARITY:RARE", "RARITY:UNIQUE")
        base_line = lines[2] if rare and len(lines) > 2 else None
        return SimpleNamespace(name=name, kind="input", drop_level=0, base_line=base_line)

    prefix = None
    suffix = None

    @property
    def id(self) -> tuple[str, str]:
        return ("input", self.text)

    def raw(self, item_level: int) -> str:
        return self.text


class PobFlaskProbe:
    def __init__(self, pob: PobSession, objective: Callable[[], Objective], *, item_level: int) -> None:
        self.pob = pob
        self._objective = objective
        self.item_level = int(item_level)

    def score(self) -> Score:
        objective = self._objective()
        return objective.score(self.pob.stats(objective.stat_keys))

    def snapshot(self) -> str:
        return self.pob.export_xml()

    def restore(self, snap: str) -> None:
        self.pob.load_xml(snap)

    def put_flask(self, slot: str, candidate: FlaskCandidate) -> None:
        self.pob.equip({slot: candidate.raw(self.item_level)}, drop_replaced=True)

    def clear_flask(self, slot: str) -> None:
        self.pob.equip({slot: None}, drop_replaced=True)  # a trial item leaves the item list with its slot, the export stays the build's

    def input_flasks(self) -> dict[str, InputFlask]:
        """The item in each Flask slot right now (one export)."""

        flags = self.pob.flasks_active()
        return {slot: InputFlask(raw, bool(flags.get(slot, False))) for slot, raw in self.pob.equipped_item_raws().items()
                if slot.startswith("Flask ") and raw}

    def put_input(self, slot: str, flask: InputFlask) -> None:
        self.pob.equip({slot: flask.raw(self.item_level)}, drop_replaced=True)
        if flask.active:  # equip drops the flag and a tincture's is never re-derived: hand the author's flag back
            self.pob.set_flasks_active({slot: True})

    def measure_active(self, slot: str, candidate: FlaskCandidate) -> tuple[Score, tuple[float, float, float]]:
        """As if active (#589 R3): equip, force the slot's flag on, read the objective and the defence triple in one stats
        read that keeps the forced flag, empty the slot. The next plain read re-derives every flag."""

        objective = self._objective()
        keys = tuple(dict.fromkeys((*objective.stat_keys, *DEFENCE_KEYS)))
        self.put_flask(slot, candidate)
        self.pob.set_flasks_active({slot: True})
        got = self.pob.stats(keys, keep_flask_flags=True)
        self.clear_flask(slot)
        return objective.score(got), _defence(got)

    def defence(self) -> tuple[float, float, float]:
        """(TotalEHP, PhysicalMaximumHitTaken, EffectiveMovementSpeedMod) from one stats read; a missing stat is 0.0."""

        return _defence(self.pob.stats(DEFENCE_KEYS))
