"""Day-1 flask step: fill flask slots by measured score (#436, #589). PoB (the probe) judges every pick.

Candidates are compared by the whole `objective.Score` (D88's key, a total order), then by the defence gain over the
empty slot, (TotalEHP, PhysicalMaximumHitTaken, EffectiveMovementSpeedMod) lexicographically (R1).

Per slot: the flask the build came in with (the slot's input) is the first candidate, trialled as its raw (R2). The
search screens every allowed base bare, keeps the top 3, per kept base the best prefix then the best suffix; a
replacement must beat the input strictly (Score, then defence gain), a tie keeps the input. An empty input slot
takes the best candidate even below the empty slot (no slot stays empty while something can be trialled). When
every candidate ties with the empty slot on Score and on the defence gain (all inactive, #575), the same search is
run with the slot's `active` flag forced on for each trial only (R3, `probe.measure_active`); a tie that survives
is broken by the lower LevelReq (base `drop_level`), then file order, and the log says which (R4). Among candidates of
one base that tie on every measure, a mod variant (prefix, suffix or both) ranks above the bare base (R5); the bare
base is placed only when it has no variant in the trial, and the log says `(bare: no variant)`. A slot named in
`fixed` screens only that base and replaces whatever is there, unless its input already is that base (`_is_base`:
by the base, not a substring of the name line): then the input is kept as in R2, a replacement must beat it strictly
on the plain measure, and the as-if-active ranking is never run against an input (R5); a fixed base is offered in no
other slot.

R6 (#616): an input that is a bare base (`_is_bare_input`, read from the raw) is kept only when no trialled candidate
ties or beats it: a candidate of the same base with a prefix, a suffix or both that ties it on every measure replaces
it, and the log says `(input bare: variant placed)`; a candidate of another base still needs a strict win (R2). An
input with a mod keeps R2/R5.

R7 (#616): two flasks of one UTILITY base (`kind == "utility"`) add nothing PoB sees, so on a full tie a candidate whose
base is already worn in another Flask slot (that slot's pick if decided, else the item it came in with) loses to one of a
base not yet worn: the tie key is (has a mod variant, base not worn), in that priority, then LevelReq (R4). A tie-break,
not a ban: a duplicate that strictly beats every rival stays; Life, Mana, Hybrid flasks and tinctures are not ruled.
The log says `(tie: worn base)` when it decided.
R7 also orders the R3 forced search: a worn base goes after every new one ahead of the forced measure, and a new
final beats a worn final whatever their forced measures, because a forced read turns on one slot only (the worn twin
is inactive there) and a non-stacking duplicate would otherwise measure a win. A worn base is placed there only when no
new candidate is left.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cmp_to_key
from typing import Any, Protocol

from junkroan.optimizer.jewel_probe import scalar
from junkroan.optimizer import yield_probe
from junkroan.optimizer.objective import Score
from junkroan.report_format import human_duration

SLOTS: tuple[str, ...] = tuple(f"Flask {k}" for k in range(1, 6))
KEEP_BASES = 3

Defence = tuple[float, float, float]
Meas = tuple[Score, Defence]  # (Score, defence gain over the empty slot)
_ZERO: Defence = (0.0, 0.0, 0.0)


class FlaskProbe(Protocol):
    def score(self) -> Score: ...
    def snapshot(self) -> Any: ...
    def restore(self, snap: Any) -> None: ...
    def put_flask(self, slot: str, candidate: Any) -> None: ...
    def clear_flask(self, slot: str) -> None: ...
    def defence(self) -> Defence: ...

    def input_flasks(self) -> Mapping[str, Any]:
        """What is equipped in each Flask slot when the step starts (read once): slot -> flask-like."""
        ...

    def put_input(self, slot: str, flask: Any) -> None:
        """Equip one of `input_flasks()` back, as it was."""
        ...

    def measure_active(self, slot: str, candidate: Any) -> tuple[Score, Defence]:
        """`candidate` in `slot` with that slot's flag forced active for this read only: (Score, defence)."""
        ...


@dataclass(frozen=True)
class FlaskSlotResult:
    slot: str
    chosen: Any | None
    score_before: float
    score_after: float
    measured: int
    seconds: float
    tie: str | None = None  # "LevelReq" | "file order" (R4), "worn base" (R7): the pick tied with another base
    bare: str | None = None  # "no variant": the bare base was placed because no mod variant of it was trialled (R5)
    input_bare: bool = False  # R6: the input was a bare base and a same-base mod variant that ties it took its place


@dataclass(frozen=True)
class FlaskStepResult:
    slots: tuple[FlaskSlotResult, ...]
    score_before: float
    score_after: float
    measured: int
    seconds: float


def flask_log_line(r: FlaskSlotResult) -> str:
    c = r.chosen
    if c is None:
        what = "empty"
    elif getattr(c, "is_input", False):
        what = f"'{c.base.name}' (input)"
    else:
        p = c.prefix.id if c.prefix is not None else "-"
        s = c.suffix.id if c.suffix is not None else "-"
        what = f"'{c.base.name}' + {p} / {s}"
    if r.tie:
        what += f" (tie: {r.tie})"
    if r.bare:
        what += f" (bare: {r.bare})"
    if r.input_bare:
        what += " (input bare: variant placed)"
    return (
        f"flask: {r.slot} {what}, score {r.score_before:.6g} -> {r.score_after:.6g}, "
        f"{r.measured} measured, {human_duration(r.seconds)}"
    )


def _gain(d: Defence, d0: Defence) -> Defence:
    return (d[0] - d0[0], d[1] - d0[1], d[2] - d0[2])


def _beats(a: Meas, b: Meas) -> bool:
    """`a` is strictly better than `b`: the whole Score first, then the defence gain."""

    if a[0] > b[0]:
        return True
    if b[0] > a[0]:
        return False
    return a[1] > b[1]


def _same(a: Meas, b: Meas) -> bool:
    return not _beats(a, b) and not _beats(b, a)


def _is_base(flask: Any, base: Any, bases: Sequence[Any] = ()) -> bool:
    """`flask` is of `base`. An input is recognised by its base: the raw's base line (rare, unique), else the longest
    known flask base name that occurs in the name line as whole words (a magic flask has the name line only)."""
    if flask.base == base:
        return True
    want = getattr(base, "name", "")
    if not want:
        return False
    info = flask.base
    line = getattr(info, "base_line", None)
    if line:
        return line.strip() == want
    name = getattr(info, "name", "")
    names = {getattr(b, "name", "") for b in (*bases, base)} - {""}
    found = [n for n in names if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", name)]
    return bool(found) and max(found, key=len) == want


def _worn_utility_names(items: Sequence[Any], known: Sequence[Any]) -> frozenset[str]:
    """R7: the names of the utility bases among `known` that any of `items` (the other slots' flasks) is of."""

    return frozenset(
        b.name for b in known
        if getattr(b, "kind", None) == "utility" and any(_is_base(it, b, known) for it in items)
    )


def _is_bare_input(flask: Any, bases: Sequence[Any]) -> bool:
    """R6: the input is a bare base, read from its raw: rarity Normal or Magic, the name line exactly a known flask
    base name, and no mod line (the lines after `Implicits: N`'s N implicit lines) and no named `Prefix:`/`Suffix:`.
    Never from missing `Prefix:` lines: a game-imported magic flask carries none (#596)."""
    text = getattr(flask, "text", None)
    if not isinstance(text, str):
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rarity = lines[0].partition(":")[2].strip().upper() if lines and lines[0].startswith("Rarity:") else ""
    if rarity not in ("NORMAL", "MAGIC") or len(lines) < 2:
        return False
    if lines[1] not in {getattr(b, "name", "") for b in bases}:
        return False
    for i, ln in enumerate(lines):
        head, sep, val = ln.partition(":")
        if sep and head in ("Prefix", "Suffix") and val.strip() not in ("", "None"):
            return False
        if head == "Implicits" and sep and val.strip().isdigit():
            if len(lines[i + 1 + int(val.strip()):]) > 0:
                return False
            break
    return True


def run_flask_step(
    probe: FlaskProbe,
    bases: Sequence[Any],
    mods_for: Callable[[Any], Sequence[Any]],
    make_candidate: Callable[[Any, Any, Any], Any],
    *,
    slots: Sequence[str] = SLOTS,
    item_level: int,
    base_level_max: int,
    fixed: Mapping[str, Any] | None = None,
) -> FlaskStepResult:
    t_all = time.monotonic()
    fixed = dict(fixed or {})
    allowed = [b for b in bases if b.drop_level <= base_level_max and not any(b == f for f in fixed.values())]
    inputs = dict(probe.input_flasks())
    results: list[FlaskSlotResult] = []
    used: set[Any] = set()
    decided: dict[str, Any] = {}  # slot -> the flask the step left there (None: empty)
    total = 0
    first_before: float | None = None
    last_after = 0.0

    for slot in slots:
        yield_probe.check("flasks")  # #621
        t0 = time.monotonic()
        n = 0
        probe.clear_flask(slot)
        empty_sc = probe.score()
        d0 = probe.defence()
        empty: Meas = (empty_sc, _ZERO)
        inp = inputs.get(slot)
        input_meas: Meas | None = None
        if inp is not None:
            probe.put_input(slot, inp)
            sc, d = probe.score(), probe.defence()
            probe.clear_flask(slot)
            n += 1
            input_meas = (sc, _gain(d, d0))
        before = input_meas[0] if input_meas is not None else empty_sc
        if first_before is None:
            first_before = scalar(before)
        is_fixed = slot in fixed
        pool = [fixed[slot]] if is_fixed else allowed
        known = [*bases, *fixed.values()]
        input_is_fixed_base = (
            is_fixed and inp is not None and _is_base(inp, fixed[slot], known)
        )
        keeps_input = inp is not None and (not is_fixed or input_is_fixed_base)
        widen = inp if keeps_input and _is_bare_input(inp, known) else None
        # R7: the other slots' flasks as they stand now: this step's pick where decided, else what the build came in with
        others = [it for s, it in {**inputs, **decided}.items() if s != slot and it is not None]
        worn = _worn_utility_names(others, known)

        def is_worn(cand: Any) -> bool:
            return getattr(cand.base, "kind", None) == "utility" and cand.base.name in worn

        def rank(cand: Any) -> tuple[bool, bool]:
            """R5/R7 tie key, larger is better: has a mod variant, then base not worn in another slot."""
            return (cand.prefix is not None or cand.suffix is not None, not is_worn(cand))

        def plain(cand: Any) -> Meas:
            nonlocal n
            probe.put_flask(slot, cand)
            sc = probe.score()
            d = probe.defence()
            probe.clear_flask(slot)
            n += 1
            return (sc, _gain(d, d0))

        def forced(cand: Any) -> Meas:
            nonlocal n
            sc, d = probe.measure_active(slot, cand)
            n += 1
            return (sc, _gain(d, d0))

        def search(
            measure: Callable[[Any], Meas],
            widen: Any | None = None,
            worn_first: bool = False,
        ) -> tuple[Any | None, Meas | None, str | None, list[Meas], list[Any], list[tuple[Any, Meas]]]:
            tried: list[Meas] = []
            with_variant: list[Any] = []  # bases of which a mod variant was trialled

            def trial(cand: Any) -> Meas:
                m = measure(cand)
                tried.append(m)
                return m

            screened: list[tuple[Meas | None, Any, Any]] = []
            for b in pool:
                yield_probe.check("flasks")  # #621
                cand = make_candidate(b, None, None)
                if cand.id in used and not is_fixed:
                    # the bare base is taken: its mod variants are still trialled, ranked after the free bases
                    screened.append((None, b, cand))
                    continue
                screened.append((trial(cand), b, cand))

            def order(x: tuple[Meas | None, Any, Any], y: tuple[Meas | None, Any, Any]) -> int:
                if x[0] is None or y[0] is None:
                    return (x[0] is None) - (y[0] is None)
                if worn_first and worn:  # R7 in the forced search: a worn base ranks after a new one before the measure
                    wx, wy = is_worn(x[2]), is_worn(y[2])
                    if wx != wy:
                        return wx - wy
                if _beats(x[0], y[0]):
                    return -1
                if _beats(y[0], x[0]):
                    return 1
                if worn:  # R7: a base already worn elsewhere ranks after a new one
                    wx, wy = is_worn(x[2]), is_worn(y[2])
                    if wx != wy:
                        return wx - wy
                return x[1].drop_level - y[1].drop_level  # R4: the lower LevelReq first; the sort is stable (file order)

            screened.sort(key=cmp_to_key(order))
            finals: list[tuple[Any, Meas]] = []

            def variants(m0: Meas | None, b: Any, cand0: Any) -> None:
                cur, cm, pre = cand0, m0, None
                mods = [m for m in mods_for(b) if m.level <= item_level]
                for kind in ("prefix", "suffix"):
                    pick = None
                    for m in (m for m in mods if m.affix == kind):
                        cand = make_candidate(b, m if kind == "prefix" else pre, None if kind == "prefix" else m)
                        if cand.id in used:
                            continue
                        mm = trial(cand)
                        if b not in with_variant:
                            with_variant.append(b)
                        # R5: a variant that ties the bare base takes its place; among variants only a strict win does
                        if cm is None or _beats(mm, cm) or (cur is cand0 and _same(mm, cm)):
                            cm, cur, pick = mm, cand, m
                    if kind == "prefix":
                        pre = pick
                if cm is not None:
                    finals.append((cur, cm))

            top = screened[:KEEP_BASES]
            for entry in top:
                variants(*entry)
            if widen is not None:
                # R6 (#616): on a bare input every candidate ties on the plain measure and the screen's order falls to
                # LevelReq; the input's own base is trialled with variants even when it ranks below the top
                for entry in screened[KEEP_BASES:]:
                    if _is_base(widen, entry[1], known):
                        variants(*entry)
            best: Any | None = None
            bm: Meas | None = None
            for cur, cm in finals:
                if worn_first and best is not None and is_worn(cur) != is_worn(best):
                    if not is_worn(cur):  # a new base beats a worn one whatever their forced measures
                        best, bm = cur, cm
                    continue
                if bm is None or _beats(cm, bm) or (
                    _same(cm, bm) and (rank(cur), -cur.base.drop_level) > (rank(best), -best.base.drop_level)
                ):
                    best, bm = cur, cm
            tie = None
            if best is not None:
                rivals = [c for c, m in finals if c is not best and _same(m, bm)]
                if any(is_worn(c) and rank(c)[0] == rank(best)[0] for c in rivals) and not is_worn(best):
                    tie = "worn base"  # R7: a rival of the same step on a base already worn lost the tie
                elif worn_first and not is_worn(best) and any(is_worn(c) and not _beats(bm, m) for c, m in finals):
                    tie = "worn base"  # R7 in the forced search: a worn final would have won or tied on the forced measure
                elif rivals:
                    tie = "LevelReq" if any(c.base.drop_level != best.base.drop_level for c in rivals) else "file order"
            return best, bm, tie, tried, with_variant, finals

        best, bm, tie, tried, with_variant, finals = search(plain, widen)
        chosen: Any | None
        input_bare = False
        # a fixed slot whose input already is the fixed base (any prefix/suffix) keeps it like any input (R2)
        if keeps_input:
            # R2/R5: a replacement must beat the input strictly on the plain measure; a tie keeps the input's flask.
            # R6: a BARE input gives way to a same-base variant (prefix, suffix or both) that ties it on every measure
            replace = best is not None and _beats(bm, input_meas)
            variant: tuple[Any, Meas] | None = None
            if not replace and widen is not None:
                for cur, cm in finals:
                    if (cur.prefix is not None or cur.suffix is not None) and _is_base(inp, cur.base, known)                             and _same(cm, input_meas) and (variant is None or _beats(cm, variant[1])):
                        variant = (cur, cm)
            if replace:
                chosen, after_sc = best, bm[0]
                probe.put_flask(slot, best)
            elif variant is not None:
                chosen, after_sc, tie, input_bare = variant[0], variant[1][0], None, True
                probe.put_flask(slot, chosen)
            else:
                chosen, after_sc, tie = inp, input_meas[0], None
                probe.put_input(slot, inp)
        else:
            all_tie = best is not None and all(_same(m, empty) for m in tried)
            if all_tie:
                # R3: every candidate is inactive; rank them as if the slot's flag were on, for each trial only
                best, bm, tie, _, with_variant, _ = search(forced, worn_first=True)
            chosen = best
            if chosen is None:
                after_sc = empty_sc
            else:
                probe.put_flask(slot, chosen)
                # a plain read re-derives the flags (#575): no forced flag stays set in the build that leaves the step
                after_sc = probe.score() if all_tie else bm[0]
        bare = None
        if chosen is not None and chosen is not inp:
            if chosen.prefix is None and chosen.suffix is None and chosen.base not in with_variant:
                bare = "no variant"
        decided[slot] = chosen
        if chosen is not None:
            used.add(chosen.id)
        total += n
        last_after = scalar(after_sc)
        results.append(FlaskSlotResult(slot, chosen, scalar(before), last_after, n, time.monotonic() - t0, tie, bare, input_bare))

    return FlaskStepResult(
        tuple(results), first_before if first_before is not None else 0.0, last_after, total,
        time.monotonic() - t_all,
    )
