"""The `g-useful-n` rule for a loot rare (issue #437): an item counts exactly N_slot useful lines.

The N_slot useful lines of largest value count (the bench craft competes as a line), every drawback
line always stays, neutral lines and surplus useful lines are removed from the item text. A line's
value is measured in PoB, never authored: the lane's Score of the candidate WITH the line against
WITHOUT it (`loot_gear._rank`). This module is the pure logic plus the one PoB probe, `line_values`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Collection, Iterable, Mapping, Sequence, TypeVar

from junkroan.optimizer.loot_gear import _rank
from junkroan.optimizer.objective import Objective
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE, register_class

TOP_K = 10  # how many of the best-by-raw-score candidates are counted and re-ranked
NEUTRAL_TOLERANCE = 1e-9  # relative to the score's own magnitude (absolute against a bare value tuple)

Value = tuple[float, float]  # `_rank`: (violation removed, value gained)
_AFFIX = re.compile(r"^(Prefix|Suffix): ")
_TAG = re.compile(r"^\{[^}]*\}")
_ELEMENT_ID = re.compile(r"^(Fire|Cold|Lightning)Resist\d+$")
_ELEMENT_TEXT = re.compile(r"^\+?[\d.()\-–]+% to (Fire|Cold|Lightning) Resistance$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ItemLine:
    index: int  # position among the item's lines (the order `item_lines` returns)
    kind: str  # "prefix" | "suffix" | "explicit" | "craft"
    text: str  # the mod id of an affix, the text of an explicit line, the {crafted} lines joined by " / "
    positions: tuple[int, ...] = field(default=(), compare=False)  # indices into the raw's own lines


def _pieces(raw: str) -> list[str]:
    return raw.splitlines(keepends=True)


_TAG_RUN = re.compile(r"^(?:\{[^}]*\})+")
_TAG_NAME = re.compile(r"\{([^}:]*)")


def _flags(text: str) -> set[str]:
    """The names of the leading `{...}` tags of a text line (`{tags:x}{suffix}` -> {"tags", "suffix"})."""

    m = _TAG_RUN.match(text)
    return set(_TAG_NAME.findall(m.group(0))) if m else set()


@dataclass(frozen=True, slots=True)
class _Scan:
    lines: list[ItemLine]
    rendered: tuple[int, ...]  # positions of the affix-rendered text lines (`{prefix}` / `{suffix}`): not lines
    plain: tuple[int, ...]  # positions of the plain explicit text lines


def _scan(raw: str) -> _Scan:
    pieces = _pieces(raw)
    lines: list[ItemLine] = []
    rendered: list[int] = []
    plain: list[int] = []
    craft_positions: list[int] = []
    craft_text: list[str] = []
    craft_slot = -1  # where the craft sits among the lines: it takes its place at its first {crafted} line
    implicit_left = 0
    in_body = False
    for pos, piece in enumerate(pieces):
        text = piece.rstrip("\r\n")
        m = _AFFIX.match(text)
        if m and not in_body:
            mod_id = _TAG.sub("", text.split(": ", 1)[1]).strip()
            if mod_id != "None":
                lines.append(ItemLine(len(lines), m.group(1).lower(), mod_id, (pos,)))
            continue
        if not in_body:
            if text.startswith("Implicits:"):
                in_body = True
                implicit_left = int(text.split(":", 1)[1].strip() or 0)
            continue
        if implicit_left > 0:
            implicit_left -= 1
            continue
        if not text.strip():
            continue
        flags = _flags(text)
        if "crafted" in flags:
            if craft_slot < 0:
                craft_slot = len(lines)
                lines.append(ItemLine(len(lines), "craft", "", ()))  # filled below
            craft_positions.append(pos)
            craft_text.append(_TAG_RUN.sub("", text))
            continue
        if flags & {"prefix", "suffix"}:
            rendered.append(pos)  # the rendered text of an affix header, not a line of its own
            continue
        plain.append(pos)
        lines.append(ItemLine(len(lines), "explicit", _TAG_RUN.sub("", text), (pos,)))
    if craft_slot >= 0:
        lines[craft_slot] = ItemLine(craft_slot, "craft", " / ".join(craft_text), tuple(craft_positions))
    return _Scan(lines, tuple(rendered), tuple(plain))


def item_lines(raw: str) -> list[ItemLine]:
    """The lines of a PoB rolled rare that can be counted: one per non-None Prefix:/Suffix: header (its
    rendered `{prefix}`/`{suffix}` text is not a line of its own), one per plain explicit text line after
    the implicit block, and one "craft" for all `{crafted}` lines."""

    return _scan(raw).lines


def needs_recraft(raw: str, lines: Iterable[ItemLine]) -> bool:
    """True when `without_lines(raw, lines)` removes an affix header of a raw that carries the rendered
    text of its affixes: PoB must re-render the text (`Item:Craft()`), see `without_lines`."""

    scan = _scan(raw)
    return bool(scan.rendered) and any(ln.kind in ("prefix", "suffix") for ln in lines)


def without_lines(raw: str, lines: Iterable[ItemLine]) -> str:
    """The raw with exactly those lines deleted; every other byte is kept.

    A raw rolled by PoB carries each affix twice: the `Prefix:`/`Suffix:` header and, after the implicit
    block, its rendered text (PoB takes the stats from the text, not the header). When an affix header is
    removed, every rendered affix text line goes too, every remaining plain explicit line is written as
    `{custom}<text>` and a `{crafted}` line stays, so that PoB's own `Item:Craft()` (`needs_recraft`:
    the trial's `recraft` flag, `PobSession.recraft`) re-renders the text from the remaining headers.
    A raw without rendered affix text (headers only) is cut line by line."""

    chosen = list(lines)
    pieces = _pieces(raw)
    drop = {pos for line in chosen for pos in line.positions}
    if not drop:
        return raw
    rewrite: set[int] = set()
    if needs_recraft(raw, chosen):
        scan = _scan(raw)
        drop |= set(scan.rendered)
        rewrite = {pos for pos in scan.plain if pos not in drop and "custom" not in _flags(pieces[pos])}
    unterminated_tail = bool(pieces) and not pieces[-1].endswith(("\n", "\r"))
    kept = [("{custom}" + p if i in rewrite else p) for i, p in enumerate(pieces) if i not in drop]
    if unterminated_tail and (len(pieces) - 1) in drop and kept:
        kept[-1] = kept[-1].rstrip("\r\n")  # the raw had no trailing newline; the new last line must not gain one
    return "".join(kept)


def trial_item(slot: str, raw: str, removed: Sequence[ItemLine]) -> dict[str, Any]:
    """The item dict of a trial of `raw` without `removed`: `recraft` is set when PoB must re-render the
    affix text first (`needs_recraft`); an item with nothing dropped is `raw` itself."""

    item: dict[str, Any] = {"slot": slot, "raw": without_lines(raw, removed)}
    if needs_recraft(raw, removed):
        item["recraft"] = True
    return item


def _rare_line_classes(trial: dict) -> list[str]:
    """Trace class (#498) of a rolled rare item trial: `rare-lines:<k>`, k = the lines of the counting model."""

    item = trial.get("item")
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, str) or not any(ln.strip().lower() == "rarity: rare" for ln in raw.splitlines()[:1]):
        return []
    return [f"rare-lines:{len(item_lines(raw))}"]


register_class(_rare_line_classes)


def n_slot(base: str, slot: str, rails: Rails) -> int:
    """How many useful lines the slot's template holds (Ring 3, weapon = weapon_open_lines + 1 craft)."""

    from junkroan.optimizer.wishlist_gear import template_for  # lazy: wishlist_gear imports loot_gear, which imports this module

    wl = rails.gear.wishlist
    return len(template_for(base, slot, weapon_open_lines=wl.weapon_open_lines, quiver_weapon_shape=wl.quiver_weapon_shape))


def _snap(x: float, scale: float) -> float:
    if math.isfinite(x) and math.isfinite(scale) and abs(x) <= NEUTRAL_TOLERANCE * max(scale, 1.0):
        return 0.0
    return x


def line_values(pob: Any, objective: Objective, slot: str, raw: str) -> list[tuple[ItemLine, Value]]:
    """The value of every line of `raw` in `slot`: one `trial_stats` call with the full candidate plus
    one trial per line removed. Raises when a trial is not ok, naming the slot and the line."""

    return line_values_many(pob, objective, slot, [raw])[0]


def line_values_many(
    pob: Any, objective: Objective, slot: str, raws: Sequence[str], protected: Sequence[Collection[int]] | None = None
) -> list[list[tuple[ItemLine, Value | None]]]:
    """`line_values` of several candidates for one slot in ONE `trial_stats` call (a round trip is what
    costs, not a trial). A raw without lines gets [] and no trial. Same errors as `line_values`.

    `protected` (#510, one collection of `ItemLine.index` per raw: the slot's forced lines) gets no removal
    trial, so no item without a forced line is sent to PoB; the value of such a line is `None` (never needed:
    `count_item` keeps it and it takes one of the slot's lines). No `protected`: every line is measured."""

    per_raw = [item_lines(raw) for raw in raws]
    skip = [set(p) for p in protected] if protected is not None else [set() for _ in raws]
    trials: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []  # per raw: [start, start + 1 + lines) in `trials`; (0, 0) for none
    for raw, lines, keep in zip(raws, per_raw, skip):
        if not lines:
            spans.append((0, 0))
            continue
        probed = [ln for ln in lines if ln.index not in keep]
        spans.append((len(trials), len(trials) + 1 + len(probed)))
        trials.append({"item": {"slot": slot, "raw": raw}})
        trials.extend({"item": trial_item(slot, raw, [ln])} for ln in probed)
    if not trials:
        return [[] for _ in raws]
    TRACE.count_candidates(trials)
    TRACE.add_generated(["useful-lines:line-value"], len(trials))
    outcomes = pob.trial_stats(trials, objective.stat_keys, mode="fast")
    TRACE.add_evaluated(["useful-lines:line-value"], sum(1 for o in outcomes if o.get("ok")))
    if len(outcomes) != len(trials):
        raise RuntimeError(f"[{slot}] trial_stats returned {len(outcomes)} outcomes for {len(trials)} trials")

    def score(o: Mapping[str, Any], what: str):
        if not o.get("ok") or not o.get("stats"):
            raise RuntimeError(f"[{slot}] PoB trial failed for {what}: {o.get('error')}")
        return objective.score(o["stats"])

    result: list[list[tuple[ItemLine, Value | None]]] = []
    for lines, keep, (a, b) in zip(per_raw, skip, spans):
        if not lines:
            result.append([])
            continue
        full = score(outcomes[a], "the full candidate")
        out: list[tuple[ItemLine, Value | None]] = []
        measured = iter(outcomes[a + 1 : b])
        for ln in lines:
            if ln.index in keep:
                out.append((ln, None))
                continue
            o = next(measured)
            without = score(o, f"the item without line {ln.index} ({ln.kind} {ln.text!r})")
            # `_rank(current, trial)` is how much better `trial` is: without -> with
            v0, v1 = _rank(without, full)
            if without.feasible and full.feasible:
                v0 = 0.0  # `_rank` answers 1.0 here ("the trial is feasible"), a flag and not an amount: nothing was removed
            s0 = max(abs(without.violation), abs(full.violation))
            s1 = max(abs(without.value), abs(full.value))
            out.append((ln, (_snap(v0, s0), _snap(v1, s1))))
        result.append(out)
    return result


def classify(value: Value) -> str:
    """"useful" (value > (0, 0)), "neutral" (both components 0 within the tolerance), or "drawback"."""

    v = (_snap(value[0], 0.0), _snap(value[1], 0.0))
    if v == (0.0, 0.0):
        return "neutral"
    return "useful" if v > (0.0, 0.0) else "drawback"


@dataclass(frozen=True, slots=True)
class Counted:
    kept: tuple[tuple[ItemLine, Value], ...]  # the n_slot best useful lines and every drawback, in item order
    dropped: tuple[tuple[ItemLine, Value], ...]  # neutral lines and surplus useful lines, in item order
    drawbacks: tuple[tuple[ItemLine, Value], ...]  # the kept negatives

    @property
    def dropped_lines(self) -> list[ItemLine]:
        """What the caller hands to `without_lines` to build the counted raw."""

        return [ln for ln, _v in self.dropped]


def count_item(valued_lines: Sequence[tuple[ItemLine, Value | None]], n_slot: int, protected: Collection[int] = ()) -> Counted:
    """Keep the `n_slot` useful lines of largest value (the craft competes as a line) and every drawback.
    A tie goes to the earlier line of the item.

    `protected` (#510: the slot's forced lines, by `ItemLine.index`) are never dropped, whatever their value;
    each one that is not a drawback is one of the slot's `n_slot` lines, so the others compete for what is
    left. No protected line: the rule above, unchanged."""

    keep_always = set(protected)
    # an unmeasured protected line (value None, `line_values_many`) is kept and is one of the n_slot lines
    taken = sum(1 for ln, v in valued_lines if ln.index in keep_always and (v is None or classify(v) != "drawback"))
    useful = [(ln, v) for ln, v in valued_lines if ln.index not in keep_always and v is not None and classify(v) == "useful"]
    winners = sorted(useful, key=lambda lv: (-lv[1][0], -lv[1][1], lv[0].index))[: max(0, n_slot - taken)]
    win_ids = {ln.index for ln, _v in winners}
    kept, dropped, drawbacks = [], [], []
    for ln, v in valued_lines:
        if v is None:
            if ln.index not in keep_always:
                raise ValueError(f"line {ln.index} has no value and is not protected")
            kept.append((ln, v))
            continue
        kind = classify(v)
        if kind == "drawback":
            kept.append((ln, v))
            drawbacks.append((ln, v))
        elif ln.index in keep_always:
            kept.append((ln, v))
        elif kind == "useful" and ln.index in win_ids:
            kept.append((ln, v))
        else:
            dropped.append((ln, v))
    return Counted(tuple(kept), tuple(dropped), tuple(drawbacks))


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Reranked:
    candidate: Any
    rank_key: Any
    counted_raw: Any
    extra: Any


def rerank_top_k(candidates: Sequence[T], k: int, count_and_score: Callable[[T], tuple[Any, Any, Any]]) -> Reranked:
    """`candidates` are sorted best-first by raw score; only the first `k` are counted and scored.
    The winner is the largest `rank_key`; the first wins a tie."""

    if k < 1:
        raise ValueError(f"rerank_top_k needs k >= 1, got {k}")
    if not candidates:
        raise ValueError("rerank_top_k got no candidates")
    best: Reranked | None = None
    for cand in candidates[:k]:
        key, counted_raw, extra = count_and_score(cand)
        if best is None or key > best.rank_key:
            best = Reranked(cand, key, counted_raw, extra)
    assert best is not None
    return best


def resistance_element(line_text_or_mod_id: str) -> str | None:
    """"Fire" / "Cold" / "Lightning" for a single-element resistance line (mod id `FireResist3` or text
    `+X% to Fire Resistance`); a hybrid, all-elemental or Chaos line is None."""

    s = _TAG.sub("", line_text_or_mod_id.strip()).strip()
    m = _ELEMENT_ID.match(s) or _ELEMENT_TEXT.match(s)
    return m.group(1).capitalize() if m else None


def extra_resistance_keep(
    dropped_res_lines: Mapping[str, Sequence[tuple[str, Any, Any]]],
    under_cap: Iterable[str],
    max_items: int = 2,
) -> list[tuple[str, Any]]:
    """Which surplus resistance lines a counted slot gets back: greedily by value, largest first, over
    lines whose element is under cap after counting; at most one line per slot, at most `max_items`."""

    under = set(under_cap)
    if not under or max_items <= 0:
        return []
    best_per_slot: list[tuple[str, Any, Any]] = []  # (slot, line, value), one per slot
    for slot, rows in dropped_res_lines.items():
        eligible = [(line, value) for element, line, value in rows if element in under]
        if eligible:
            line, value = max(eligible, key=lambda lv: lv[1])  # max keeps the first of equal values
            best_per_slot.append((slot, line, value))
    best_per_slot.sort(key=lambda t: t[2], reverse=True)  # stable: equal values keep the caller's slot order
    return [(slot, line) for slot, line, _v in best_per_slot[:max_items]]
