"""Facts PoB cannot compute, found by research, not yet approved by the user (D62, 2026-09-18).

`pending_facts.json` is the store; this module is the only way code reads it. One field decides
what a fact does, and the user's approval is a one-word edit of that field:

- **pending** -- the hook touches the *optimistic* lane only. The conservative number, which is
  the delivered one, never moves on an unapproved fact. Where a fact has no optimistic lane to
  live in (a cost, a floor, an instance count -- things that are not config inputs), the hook
  computes it anyway and reports "would move the conservative number by X%": the note is the
  whole point of the pending state, because it is what the user approves from.
- **approved** -- the hook is binding in both lanes, exactly as a rail is.
- **disputed** -- the sources disagree or one of them answers "not found". The hook is off in
  both lanes and the record carries the range and the disagreement for the user's table.

A fact carries the numbers quoted from a report with its sources; nothing is typed from memory,
and a fact without a source or with an unknown status is a loading error, not a silent default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

PATH = Path(__file__).resolve().parent / "pending_facts.json"
STATUSES = ("pending", "approved", "disputed")
LANES = ("conservative", "optimistic")


@dataclass(frozen=True, slots=True)
class PendingFact:
    id: str
    fact: str
    value: float | None
    unit: str
    sources: tuple[str, ...]
    confidence: str
    status: str
    plug_in: str
    added: str
    params: Mapping[str, Any] = field(default_factory=dict)
    range: tuple[float, float] | None = None
    disagreement: str = ""
    pob_check: str = ""
    moves: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.status == "approved"

    @property
    def pending(self) -> bool:
        return self.status == "pending"

    @property
    def disputed(self) -> bool:
        return self.status == "disputed"

    def applies(self, lane: str) -> bool:
        """Does this fact act on `lane` ("conservative" / "optimistic")? Approved acts on both,
        pending on the optimistic lane only, disputed on neither."""

        if lane not in LANES:
            raise ValueError(f"unknown lane {lane!r}; expected one of {LANES}")
        if self.approved:
            return True
        return self.pending and lane == "optimistic"

    @property
    def binding(self) -> bool:
        """May this fact change the conservative number -- the one we deliver? Only when approved.
        A hook with no lane split (a cost, a floor) asks this and, while pending, reports instead."""

        return self.approved

    def reason(self, detail: str = "") -> str:
        """The line a hook writes into the config reasons / the explanation, so a number can always
        be traced to the fact and its state."""

        head = f"{self.status} fact {self.id} (research {self.added})"
        return f"{head}: {detail or self.fact}"

    def param(self, key: str) -> float | None:
        raw = (self.params or {}).get(key)
        return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None


def _parse(rec: Mapping[str, Any]) -> PendingFact:
    fid = str(rec.get("id") or "")
    if not fid:
        raise ValueError("a pending fact without an id")
    status = str(rec.get("status") or "")
    if status not in STATUSES:
        raise ValueError(f"{fid}: status {status!r} is not one of {STATUSES}")
    sources = tuple(str(s) for s in (rec.get("sources") or ()) if str(s).strip())
    if not sources:
        raise ValueError(f"{fid}: a fact with no source is not a fact")
    rng = rec.get("range")
    if status == "disputed" and not (rng and rec.get("disagreement")):
        raise ValueError(f"{fid}: a disputed fact must carry its range and the disagreement")
    value = rec.get("value")
    return PendingFact(
        id=fid,
        fact=str(rec.get("fact") or ""),
        value=float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None,
        unit=str(rec.get("unit") or ""),
        sources=sources,
        confidence=str(rec.get("confidence") or ""),
        status=status,
        plug_in=str(rec.get("plug_in") or ""),
        added=str(rec.get("added") or ""),
        params=dict(rec.get("params") or {}),
        range=(float(rng[0]), float(rng[1])) if isinstance(rng, Sequence) and not isinstance(rng, str) and len(rng or ()) == 2 else None,
        disagreement=str(rec.get("disagreement") or ""),
        pob_check=str(rec.get("pob_check") or ""),
        moves=tuple(str(m) for m in (rec.get("moves") or ())),
    )


@lru_cache(maxsize=1)
def load_facts(path: str = "") -> dict[str, PendingFact]:
    """Every record of the store, by id. Cached: the store is a small file read in inner loops."""

    raw = json.loads(Path(path or PATH).read_text(encoding="utf-8"))
    out: dict[str, PendingFact] = {}
    for rec in raw.get("facts") or ():
        parsed = _parse(rec)
        if parsed.id in out:
            raise ValueError(f"{parsed.id}: two records with the same id")
        out[parsed.id] = parsed
    return out


def fact(fact_id: str) -> PendingFact | None:
    """The record, or None when the store does not carry it (a hook then does nothing)."""

    return load_facts().get(fact_id)


def applies(fact_id: str, lane: str) -> bool:
    rec = fact(fact_id)
    return bool(rec and rec.applies(lane))


def lane_value(fact_id: str, lane: str, without: float, with_fact: float) -> tuple[float, str]:
    """(value, reason) for a config input a fact changes: `with_fact` on the lanes the fact acts
    on, `without` everywhere else. The reason always names the fact and its state, so an input
    can be read back to the record it came from."""

    rec = fact(fact_id)
    if rec is None:
        return without, ""
    if rec.applies(lane):
        return with_fact, rec.reason(f"{with_fact:g} {rec.unit}")
    if rec.pending:
        return without, rec.reason(f"not on the conservative lane until approved ({with_fact:g} {rec.unit})")
    return without, rec.reason(f"off: {rec.disagreement or 'the sources disagree'}")


def would_move(fact_id: str, before: float, after: float, what: str) -> str:
    """The note a hook with no lane split leaves while its fact is pending: what the conservative
    number would do if the fact were approved. `before` / `after` are the two values of the thing
    the fact prices (recovery per second, DPS, ...); `what` names it."""

    rec = fact(fact_id)
    if rec is None:
        return ""
    if before:
        share = (after - before) / abs(before) * 100.0
        move = f"would move the conservative number by {share:+.1f}% ({what} {before:,.0f} -> {after:,.0f})"
    else:
        move = f"would move the conservative number from nothing ({what} {before:,.0f} -> {after:,.0f})"
    return rec.reason(move)


__all__ = ["LANES", "PATH", "STATUSES", "PendingFact", "applies", "fact", "lane_value", "load_facts", "would_move"]
