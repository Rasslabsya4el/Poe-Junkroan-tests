"""Day-1 gear as loot simulation (DECISIONS D19).

Per rare slot: roll N random rares on the base with PoB's own spawn weights,
evaluate each through an item trial, keep the one the objective prefers, then
add the single best crafting-bench mod (the one deterministic step a day-1
player has). Equip and move to the next slot; a second pass re-picks each slot
with every other slot already filled.

N is the realism knob (`Rails.gear.loot_best_of_n`, calibrated to reproduce
the reference builds' gear at N=300).
"""

from __future__ import annotations

from junkroan.optimizer.seeds import PURPOSE_LOOT_FILL_SLOT, derive_seed

import math
import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Iterable, Mapping, Sequence
from xml.etree import ElementTree as ET

from junkroan.optimizer.anoint_line import apply_anoint
from junkroan.optimizer.gear_interface import GearInterface
from junkroan.optimizer.objective import Objective, Score, ScoreOrder, better_score, loop_key, score_key
from junkroan.optimizer.rails import Rails
from junkroan.optimizer.trace import TRACE, register_class
from junkroan.mechanics.bench_unlocks import legal as bench_unlock_legal
from junkroan.pob.mod_families import families_of
from junkroan.pob.session import PobSession
from junkroan.search.forced import affix_template

WEAPON_SLOTS = ("Weapon 1", "Weapon 2")  # "Weapon 2" is also the shield / quiver slot, whatever the skeleton holds
# The weapon slots come first (measured 2026-09-18 on bleed_bow): an attack build with an empty
# main hand deals no damage at all, so every candidate for the eight other slots scored the same
# infinite violation and the same missing DPS, and the filler spent them on whatever PoB could
# still tell apart ("Reflects Physical Damage" on the body armour). With the weapon in hand first
# every later slot is judged against a real number. A spell is unaffected -- PoB scores it without
# a weapon -- so the order is unconditional. The rest is the old order, so older logs still read
# the same.
RARE_SLOT_ORDER = (*WEAPON_SLOTS, "Body Armour", "Helmet", "Gloves", "Boots", "Belt", "Amulet", "Ring 1", "Ring 2")
_AFFIX_LINE = re.compile(r"^(Prefix|Suffix): ")
_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")  # a mod record's "(10-15)"
_LINE_TAGS = re.compile(r"^(?:\{[^}]*\})+")  # PoB's "{tags:..}{prefix}", "{range:..}", "{crafted}" in front of an item line


def ordered_slots(slots: Iterable[str]) -> list[str]:
    """The slots a caller holds, in the fill order: `RARE_SLOT_ORDER` first (weapons, then the
    rest), then anything the constant does not name, in the caller's own order. One definition,
    read by both fillers, the pipeline's per-slot moves and `scripts/gear_bestofn.py`."""

    held = list(slots)
    return [s for s in RARE_SLOT_ORDER if s in held] + [s for s in held if s not in RARE_SLOT_ORDER]


def weapons_first(slots: Iterable[str]) -> list[str]:
    """The same rule for a caller that has its own ordering to keep (the joint kick ranks its
    slots by damage headroom): the weapon slots move to the front, everything else keeps its
    place -- the sort is stable."""

    return sorted(slots, key=lambda s: WEAPON_SLOTS.index(s) if s in WEAPON_SLOTS else len(WEAPON_SLOTS))


_WEAPON_PARTNER = {"Weapon 1": "Weapon 2", "Weapon 2": "Weapon 1"}


def restore_weapon_partner(pob: PobSession, uniques: Mapping[str, str], slot: str) -> None:
    """Put the skeleton's unique back in the paired weapon slot after ``slot`` is refilled.

    PoB's own ``ItemSlotClass:Populate()`` (``vendor/pob/source/src/Classes/ItemSlotControl.lua:94``)
    clears a slot whose item is not valid for it -- silently, at the end of every equip
    (``PopulateSlots``, ``headless_runtime_worker.py:843``). A pass that empties Weapon 1
    therefore drops a unique quiver in Weapon 2, and the fill that follows puts the bow back
    without it; the skeleton's own base choice keeps the pair compatible (a quiver implies a bow,
    a shield a one-hander), so restoring it once the enabler is on the build always lands.
    """

    pair = _WEAPON_PARTNER.get(slot)
    raw = uniques.get(pair) if pair else None
    if raw:
        pob.equip({pair: raw})


@dataclass(slots=True)
class LootSlotResult:
    slot: str
    base: str
    raw: str = ""
    mod_ids: list[str] = field(default_factory=list)
    bench_line: str | None = None
    before: Score | None = None
    after_loot: Score | None = None
    after_bench: Score | None = None
    rolled: int = 0
    seconds: float = 0.0
    after_count: Score | None = None  # the delivered (counted) item's score, set when counting removed a line
    lines_total: int = 0  # lines of the winner before counting
    lines_counted: int = 0  # useful lines kept (the drawbacks are on top of this)
    dropped: list[str] = field(default_factory=list)  # text of the neutral / surplus lines removed from the item
    drawbacks: list[str] = field(default_factory=list)  # text of the drawback lines kept


def forced_mod_choices(pob: PobSession, base: str, lines: Iterable[str], ilvl: int | None, pool: str = "explicit") -> list[list[str]]:
    """Per forced mod line, the ids of the mods that can roll it on ``base`` (its tiers).

    A mod record carries its text with ranges ("+(10-15)% to ..."); the line matches on
    `affix_template` once a range is read as one number, so every tier of the line is a choice.
    A hybrid mod matches through any of its lines. No match raises: the request names a line the
    base cannot roll, and there is no item without it to fall back on.
    """

    mods = pob.list_item_mods(base, ilvl=ilvl, pool=pool)["mods"]
    by_template: dict[str, list[str]] = {}
    for mod in mods:
        for text in mod.get("lines") or []:
            ids = by_template.setdefault(affix_template(_RANGE.sub("1", str(text))), [])
            if mod["mod_id"] not in ids:
                ids.append(mod["mod_id"])
    choices: list[list[str]] = []
    for line in lines:
        ids = by_template.get(affix_template(line))
        if not ids:
            raise ValueError(f"mod line {line!r} cannot roll on {base}")
        choices.append(list(ids))
    return choices


def _forced_indices(valued: Sequence[tuple[Any, Any]], forced: Sequence[str], choices: Sequence[Sequence[str]]) -> frozenset[int]:
    """The `ItemLine.index` of the item lines that are the slot's forced mod lines (#510): an affix header whose mod
    id is one of the forced lines' candidate ids (`forced_mod_choices`), or a plain / crafted line whose text is one
    of the forced lines (`affix_template`). Counting never drops these."""

    ids = {mod_id for group in choices for mod_id in group}
    want = {affix_template(line) for line in forced}
    out: set[int] = set()
    for ln, _v in valued:
        if ln.kind in ("prefix", "suffix"):
            hit = ln.text in ids
        else:  # "explicit", or the one "craft" line that joins every {crafted} line with " / "
            hit = any(affix_template(part.strip()) in want for part in ln.text.split(" / "))
        if hit:
            out.add(ln.index)
    return frozenset(out)


def raw_carries(raw: str, line: str) -> bool:
    """Whether the item text carries the mod line, as PoB writes an item: each line may start with
    "{tags:..}{prefix}", "{range:..}" or "{crafted}" groups, which are not part of the text
    (`junkroan.search.forced.raw_has_affix` compares the whole line and misses those)."""

    want = affix_template(line)
    return any(affix_template(_LINE_TAGS.sub("", row.strip())) == want for row in str(raw).splitlines())


def _mod_families(mod_id: object | None, group: object | None, families: object | None = None) -> frozenset[str]:
    """The game mod families a mod occupies, plus PoB's own group as a pseudo-family.

    An item can carry only one mod of a family, and PoB's ``group`` is not the family
    (it splits 185 of the 512 families and 10 of its groups span two), so the craft is
    judged on the families. ``families`` is the answer a caller already has: a bench
    row carries no mod id of its own, so `PobSession.list_bench_mods` recognises the
    craft by its text and puts its families on the row. The group rides along as
    "pob:<group>" for the rows whose mod is still not pinned down; every PoB group's
    mods share a family, so the pseudo-family blocks nothing extra.
    """

    fams = set(str(f) for f in families) if families else set()
    if not fams and mod_id:
        fams = set(families_of(str(mod_id)))
    if group:
        fams.add("pob:" + str(group))
    return frozenset(fams)


def bench_candidates(
    bench_rows: Iterable[Mapping[str, object]],
    item_mod_ids: Iterable[str],
    item_families_of: Callable[[str], frozenset[str]],
    pre: int,
    suf: int,
    rails: Rails,
) -> list[Mapping[str, object]]:
    """The bench crafts still legal on an item, best rank first.

    A craft is out when the item has no room for its affix, or when it shares a
    family with a mod the item already carries. A bench row's own families come
    from `bench_mod_ids` (PoB's bench table has no mod id); "pob:<group>" rides
    along for the rows whose id is not unique, exactly as before.

    Highest bench rank first: the caller keeps the first candidate at an equal
    score, and PoB lists a bench group lowest level first, so a tie used to take
    the weakest craft.
    """

    used: set[str] = set()
    for mod_id in item_mod_ids:
        used |= item_families_of(mod_id)
    room = {"Prefix": pre < rails.gear.max_prefixes, "Suffix": suf < rails.gear.max_suffixes}
    legal = [
        row
        for row in bench_rows
        if room.get(str(row.get("type")), False)
        and not (_mod_families(row.get("mod_id"), row.get("group"), row.get("families")) & used)
        and bench_unlock_legal(row.get("unlock"), max_map_tier=rails.gear.bench.max_map_tier, unknown_tier_allowed=rails.gear.bench.unknown_tier_allowed, excluded_cost_currencies=rails.gear.bench.excluded_cost_currencies)
    ]
    return sorted(legal, key=lambda m: -int(m.get("level") or 0))


def _rank(current: Score, trial: Score, *, violation_first: bool = False, order: ScoreOrder = "floors") -> tuple[float, ...]:
    """How much better than `current` the trial is: violation removed first, then value gained.

    Both differences can be inf - inf = nan, and nan neither wins nor loses a comparison, so a
    ranking that keeps it picks by accident (`>` is False against every candidate, so the first
    one stays whatever the rest are worth). It happens on a real build: an attack build whose
    weapon slot is still empty has infinite violation and no DPS at all, and so has every
    candidate for another slot. Such a candidate is worth the least, not an unordered amount,
    so nan becomes -inf and the caller's own tie-break decides.

    `violation_first` (#179, rule 2) ranks by the trial's own `Score` order -- the lower violation
    first, the value second -- the order of the first round's change (b7bdcf1). `LootGear.fill`
    asks for it only on a slot whose `current` reads violation inf; the default is the order
    `gear_filler.py` and `wishlist_gear.py` always had.

    `order="priced"` (D116 / #553, the improvement loop's gear moves) ranks by `objective.loop_key` of
    the trial (the priced score first), whatever `current` and `violation_first` say: a candidate is as
    good as the value it keeps after the floors it misses are charged.
    """

    if order == "priced":
        return tuple(-math.inf if math.isnan(part) else part for part in loop_key(trial))
    if violation_first:
        return (trial.neg_violation, trial.value)
    if not current.feasible:
        key = (current.violation - trial.violation, trial.value - current.value)
    else:
        key = (1.0 if trial.feasible else -trial.violation, trial.value - current.value)
    return (-math.inf if math.isnan(key[0]) else key[0], -math.inf if math.isnan(key[1]) else key[1])


def _affix_counts(raw: str) -> tuple[int, int, set[str]]:
    """(prefixes, suffixes, mod ids) of a PoB rare written with Prefix:/Suffix: lines."""

    pre = suf = 0
    ids: set[str] = set()
    for line in raw.splitlines():
        m = _AFFIX_LINE.match(line)
        if not m:
            continue
        mod_id = re.sub(r"^\{[^}]*\}", "", line.split(": ", 1)[1]).strip()
        if mod_id == "None":
            continue
        ids.add(mod_id)
        if m.group(1) == "Prefix":
            pre += 1
        else:
            suf += 1
    return pre, suf, ids


@dataclass(slots=True)
class GearSet:
    """One whole gear set the fill held, with the `Score` PoB gave it as equipped (#179).

    `equipped` is the item of every slot the fill may change -- the slots it fills and the
    weapon slot `restore_weapon_partner` writes -- (None = empty), `current_raw` the filler's own
    per-slot record, so a restored set leaves PoB and `current_raw` describing the same items.
    The judge reads only `label` and `score`.
    """

    label: str
    score: Score
    equipped: dict[str, str | None] = field(default_factory=dict)
    current_raw: dict[str, str] = field(default_factory=dict)

    @property
    def log_line(self) -> str:
        return f"{self.label} viol {self.score.violation:.4f} value {self.score.value:,.1f}"


def best_gear_set(sets: Sequence[GearSet]) -> GearSet:
    """The set a fill ends on: the best of the labelled sets it held, in the order given.

    Ordered by `better_score` (`objective.py`, D58): violation first, value second. A tie keeps the
    later set, and a set whose maximized stat has fallen to nothing never wins over one that still
    has a number (the reading `better_score` writes down, applied to either side).
    """

    best = sets[0]
    for candidate in sets[1:]:
        if better_score(candidate.score, best.score) or candidate.score == best.score or best.score.value <= 0.0 < candidate.score.value:
            best = candidate
    return best


def _equipped_raws(xml: str, slots: Iterable[str]) -> dict[str, str | None]:
    """slot -> the item text PoB wears there now (None = empty), read off an exported build."""

    items = ET.fromstring(xml).find("Items")
    by_slot: dict[str, str] = {}
    if items is not None:
        by_id = {i.get("id"): (i.text or "").strip() for i in items.findall("Item")}
        item_set = next((s for s in items.findall("ItemSet") if s.get("id") == (items.get("activeItemSet") or "1")), None)
        for slot in (item_set.findall("Slot") if item_set is not None else items.findall("Slot")):
            raw = by_id.get(slot.get("itemId") or "")
            if raw:
                by_slot[slot.get("name") or ""] = raw
    return {slot: by_slot.get(slot) for slot in slots}


class LootGear(GearInterface):
    def __init__(
        self,
        pob: PobSession,
        objective: Objective,
        rails: Rails | None = None,
        *,
        log: Callable[[str], None] | None = None,
        uniques: Mapping[str, str] | None = None,
    ) -> None:
        self.pob = pob
        self.objective = objective
        self.rails = rails or Rails.load()
        self.log = log or (lambda _m: None)
        self.uniques = dict(uniques or {})  # slot -> raw, the skeleton's unique gear; its weapon pair is restored after a refill
        self._bench_cache: dict[str, list[dict]] = {}
        self.current_raw: dict[str, str] = {}  # slot -> raw of the item this filler equipped last; competes in later passes
        self._mod_families: dict[str, dict[str, frozenset[str]]] = {}
        self.anoint: str | None = None  # the notable the Amulet carries as its enchant (#432); set by the pipeline
        self.forced_lines: dict[str, list[str]] = {}  # slot -> mod lines the request forces; set by the pipeline
        self._forced_choices: dict[tuple[str, tuple[str, ...]], list[list[str]]] = {}
        # slot -> (raw before counting, Counted, the delivered raw): what the extra-resistance step of `fill` reads
        self._counting: dict[str, tuple[str, Any, str]] = {}

    def item_level_for(self, slot: str) -> int:
        return self.rails.gear.item_level

    def other_weapon_bases(self, base: str) -> list[str]:
        from junkroan.optimizer.item_bases import bases_of_type, type_of, without_excluded

        item_type = type_of(base)
        if not item_type:
            return []
        return [name for name in without_excluded(bases_of_type(item_type, max_level=self.rails.gear.item_level), self.rails) if name != base]  # #1154: the loadout's excluded bases are never swapped in

    def _forced_for(self, slot: str, base: str) -> tuple[list[str], list[list[str]]]:
        """(the slot's forced lines, their candidate mod ids on ``base``); both empty when none is forced."""

        lines = list(self.forced_lines.get(slot) or [])
        if not lines:
            return [], []
        key = (base, tuple(lines))
        if key not in self._forced_choices:
            self._forced_choices[key] = forced_mod_choices(self.pob, base, lines, self.rails.gear.item_level)
        TRACE.note_forced_mod_ids(slot, self._forced_choices[key])  # the trace counts a recraft item by these headers
        return lines, self._forced_choices[key]

    def _bench_mods(self, base: str) -> list[dict]:
        if base not in self._bench_cache:
            self._bench_cache[base] = self.pob.list_bench_mods(base, ilvl=self.rails.gear.item_level)["mods"]
        return self._bench_cache[base]

    def _families(self, base: str) -> dict[str, frozenset[str]]:
        """{mod id: families} for every mod PoB allows on the base."""

        if base not in self._mod_families:
            listed = self.pob.list_item_mods(base)
            self._mod_families[base] = {m["mod_id"]: _mod_families(m["mod_id"], m.get("group")) for m in listed["mods"]}
        return self._mod_families[base]

    def fill_slot(self, slot: str, base: str, *, n: int | None = None, sockets: str | None = None, seed: int = 1, bench: bool = True, violation_first: bool = False, order: ScoreOrder = "floors") -> LootSlotResult:
        """Roll, trial, count: the `g-useful-n` rule of #437 (`useful_lines`). All rolled rares (and the
        incumbent) are trialled; the best `TOP_K` by raw Score each get their best legal bench craft and
        are counted -- exactly `n_slot` useful lines (the craft competes as a line), every drawback kept,
        neutral and surplus lines removed from the item text -- and the best counted item wins. Each of
        the three follow-up batches (crafts, line values, counted items) is one `trial_stats` call.

        `order` is the Score order the candidates are chosen by: "floors" (the default) is the ranking
        every caller had, "priced" the improvement loop's (D116 / #553), threaded to every choice here
        (the roll ranking, the bench craft, the counted re-rank). The count of useful lines
        (`useful_lines.line_values_many`) measures a line against its item and keeps `_rank`'s
        default order."""

        from junkroan.optimizer import useful_lines as ul  # useful_lines imports `_rank` from this module

        t0 = time.perf_counter()
        n = n or self.rails.gear.loot_best_of_n
        keys = self.objective.stat_keys
        result = LootSlotResult(slot=slot, base=base)
        current = self.objective.score(self.pob.stats(keys))
        result.before = current

        forced, choices = self._forced_for(slot, base)
        extra = {"forced": choices} if choices else {}  # nothing forced: the call is the one it always was
        rolled = self.pob.random_rares(base, n=n, ilvl=self.rails.gear.item_level, quality=self.rails.gear.quality, sockets=sockets, seed=seed, **extra)
        if forced and rolled:
            carrying = [r for r in rolled if all(raw_carries(r["raw"], line) for line in forced)]
            if not carrying:
                raise RuntimeError(f"no roll on {base} carries the forced lines {forced}: the roll or the line match is broken")
            rolled = carrying
        rolled = drop_weapon_all_gems(rolled, slot, self.rails, forced)  # #1152
        rolled = drop_shield_gem_with_other(rolled, slot)  # #1155
        result.rolled = len(rolled)
        if slot == "Amulet":
            rolled = [{**r, "raw": apply_anoint(r["raw"], self.anoint)} for r in rolled]
        incumbent = self.current_raw.get(slot)
        if incumbent and slot == "Amulet":
            incumbent = apply_anoint(incumbent, self.anoint)
        # #1155: an incumbent the shield rule forbids does not compete; #1152: nor one a weapon slot's forbidden line (a recorded build's roll) rides
        if incumbent and all(raw_carries(incumbent, line) for line in forced) and drop_shield_gem_with_other([{"raw": incumbent}], slot) and drop_weapon_all_gems([{"raw": incumbent}], slot, self.rails, forced):
            # the item from the previous pass competes; a pass never trades down
            rolled = [{"raw": incumbent, "mod_ids": _affix_counts(incumbent)[2], "incumbent": True}, *rolled]
        rolled_trials = [{"item": {"slot": slot, "raw": r["raw"]}} for r in rolled]
        TRACE.count_candidates(rolled_trials)
        outcomes = self.pob.trial_stats(rolled_trials, keys, mode="fast")
        scored: list[tuple[tuple[float, float], dict, Score]] = []
        for r, o in zip(rolled, outcomes):
            if not o.get("ok") or not o.get("stats"):
                continue
            s = self.objective.score(o["stats"])
            scored.append((_rank(current, s, violation_first=violation_first, order=order), r, s))
        if not scored:
            result.seconds = time.perf_counter() - t0
            return result
        scored.sort(key=lambda t: t[0], reverse=True)  # stable: of equal keys the first stays first, as the strict `>` pick did

        entries = [
            {"item": item, "loot_score": s, "raw": item["raw"], "score": s, "bench_line": None, "bench_score": None}
            for _k, item, s in scored[: ul.TOP_K]
        ]
        if bench:
            self._add_bench_crafts(slot, base, entries, forced, order=order)
        self._count_entries(slot, base, entries, ul)
        win = ul.rerank_top_k(entries, ul.TOP_K, lambda e: (_rank(current, e["counted_score"], violation_first=violation_first, order=order), e["counted_raw"], e)).extra
        item, counted = win["item"], win["counted"]
        delivered = self.pob.recraft(win["counted_raw"]) if win["recraft"] else win["counted_raw"]  # rendered text, once
        lost = [line for line in forced if not raw_carries(delivered, line)]
        if lost:
            raise RuntimeError(f"[{slot}] the delivered item lost the forced lines {lost}: counting must never drop a forced line")
        result.raw, result.after_loot = delivered, win["loot_score"]
        result.bench_line, result.after_bench = win["bench_line"], win["bench_score"]
        dropped_ids = {ln.text for ln in counted.dropped_lines if ln.kind in ("prefix", "suffix")} if counted else set()
        result.mod_ids = [m for m in item["mod_ids"] if m not in dropped_ids]
        result.lines_total = win["lines"]
        if counted is not None:
            result.dropped = [ln.text for ln in counted.dropped_lines]
            result.drawbacks = [ln.text for ln, _v in counted.drawbacks]
            result.lines_counted = len(counted.kept) - len(counted.drawbacks)
        if win["counted_raw"] != win["raw"]:
            result.after_count = win["counted_score"]
        prior = self._counting.get(slot)
        if item.get("incumbent") and prior is not None and prior[2] == delivered and not result.dropped:
            # the incumbent was counted by an earlier pass: what that pass dropped is what the item gave up
            result.dropped = [ln.text for ln in prior[1].dropped_lines]
            result.lines_total = len(ul.item_lines(prior[0]))
        elif counted is not None and counted.dropped:
            self._counting[slot] = (win["raw"], counted, delivered)
        else:
            self._counting.pop(slot, None)

        self.pob.equip({slot: result.raw})
        self.current_raw[slot] = result.raw
        restore_weapon_partner(self.pob, self.uniques, slot)
        result.seconds = time.perf_counter() - t0
        loot_end = result.after_bench or result.after_loot
        final = result.after_count or loot_end
        self.log(
            f"[{slot}] best of {result.rolled}: {current.value:,.0f} -> {result.after_loot.value:,.0f} (viol {current.violation:.3f} -> {result.after_loot.violation:.3f})"
            + (f"; bench {result.bench_line}: -> {loot_end.value:,.0f} (viol {loot_end.violation:.3f})" if result.bench_line else "")
            + (
                f"; counted {result.lines_counted} of {result.lines_total}: dropped [{', '.join(result.dropped)}], drawback kept [{', '.join(result.drawbacks)}]: -> {final.value:,.0f} (viol {final.violation:.3f})"
                if result.dropped or result.drawbacks
                else ""
            )
            + f" [{result.seconds:.1f}s]"
        )
        return result

    def _add_bench_crafts(self, slot: str, base: str, entries: list[dict], forced: Sequence[str] = (), *, order: ScoreOrder = "floors") -> None:
        """Each entry (but the incumbent, which carries its craft) gets its best legal bench craft as
        today: the highest rank by the entry's own loot score, kept only when it beats it. All the
        entries' craft trials go out in one `trial_stats` call. A craft whose raw does not carry every
        `forced` line of the slot (#510) is never a candidate: a forced line is never lost."""

        keys = self.objective.stat_keys
        score_order = score_key(order)
        plans: list[tuple[dict, list[tuple[Mapping[str, object], str]], int]] = []
        trials: list[dict] = []
        known: dict[str, frozenset[str]] | None = None
        for e in entries:
            if e["item"].get("incumbent"):
                continue
            known = self._families(base) if known is None else known
            pre, suf, ids = _affix_counts(e["raw"])
            candidates = bench_candidates(self._bench_mods(base), ids, lambda mod_id: known.get(mod_id) or frozenset(families_of(mod_id)), pre, suf, self.rails)
            if slot in WEAPON_SLOTS:  # #1152: PoB's bench table (ModMaster.lua) has no such craft today; the rail keeps it so
                banned = unforced_forbidden(self.rails.gear.weapon_forbidden_lines, forced)
                candidates = [m for m in candidates if not any(weapon_line_forbidden(line, banned) for line in m["rolled_lines"])]
            crafted = [(m, e["raw"] +"\n" + "\n".join("{crafted}" + line for line in m["rolled_lines"])) for m in candidates]
            crafted = [(m, raw) for m, raw in crafted if all(raw_carries(raw, line) for line in forced)]
            crafted = [(m, raw) for m, raw in crafted if drop_shield_gem_with_other([{"raw": raw}], slot)]  # #1155: a craft never joins a gem-level shield
            if crafted:
                plans.append((e, crafted, len(trials)))
                trials.extend({"item": {"slot": slot, "raw": raw}} for _m, raw in crafted)
        if not trials:
            return
        TRACE.count_candidates(trials)
        outcomes = self.pob.trial_stats(trials, keys, mode="fast")
        for e, crafted, start in plans:
            best_bench = None
            for (m, raw), o in zip(crafted, outcomes[start : start + len(crafted)]):
                if not o.get("ok") or not o.get("stats"):
                    continue
                s = self.objective.score(o["stats"])
                key = _rank(e["loot_score"], s, order=order)
                if best_bench is None or key > best_bench[0]:
                    best_bench = (key, m, raw, s)
            if best_bench is not None and score_order(best_bench[3]) > score_order(e["loot_score"]):
                _k, m, raw, s = best_bench
                e["raw"], e["bench_line"], e["bench_score"], e["score"] = raw, " / ".join(m["rolled_lines"]), s, s

    def _count_entries(self, slot: str, base: str, entries: list[dict], ul: Any) -> None:
        """Count every entry (`useful_lines.count_item` at `n_slot`) and score the counted item: one
        call for all the line values, one for all the counted items that lost a line. An entry that
        loses nothing keeps its raw byte for byte and the score it already has."""

        forced, choices = self._forced_for(slot, base)
        raws = [e["raw"] for e in entries]
        # a forced line gets no removal trial: no item without it reaches PoB, and its value is never needed (#510)
        protected = [_forced_indices([(ln, None) for ln in ul.item_lines(raw)], forced, choices) for raw in raws] if forced else None
        values = ul.line_values_many(self.pob, self.objective, slot, raws, protected=protected)
        limit = ul.n_slot(base, slot, self.rails) if any(values) else 0
        trials: list[dict] = []
        for e, vals in zip(entries, values):
            e["lines"] = len(vals)
            # a forced line of the slot is never dropped and is one of the slot's `limit` lines (#510)
            e["counted"] = (ul.count_item(vals, limit, protected=_forced_indices(vals, forced, choices)) if forced else ul.count_item(vals, limit)) if vals else None
            dropped = e["counted"].dropped_lines if e["counted"] else []
            item = ul.trial_item(slot, e["raw"], dropped)
            e["counted_raw"] = item["raw"]
            e["recraft"] = bool(item.get("recraft"))  # PoB re-renders the affix text of the delivered item
            e["counted_score"] = e["score"]
            e["counted_at"] = None
            if e["counted_raw"] != e["raw"]:
                e["counted_at"] = len(trials)
                trials.append({"item": item})
        if not trials:
            return
        TRACE.count_candidates(trials)
        TRACE.add_generated(["useful-lines:counted"], len(trials))
        outcomes = self.pob.trial_stats(trials, self.objective.stat_keys, mode="fast")
        TRACE.add_evaluated(["useful-lines:counted"], sum(1 for o in outcomes if o.get("ok")))
        for e in entries:
            if e["counted_at"] is None:
                continue
            o = outcomes[e["counted_at"]]
            if not o.get("ok") or not o.get("stats"):
                raise RuntimeError(f"[{slot}] PoB trial failed for the counted item: {o.get('error')}")
            e["counted_score"] = self.objective.score(o["stats"])

    def fill(self, bases_by_slot: Mapping[str, str], *, sockets_by_slot: Mapping[str, str] | None = None, passes: int = 2, n: int | None = None, seed: int = 1, bench: bool = True) -> list[LootSlotResult]:
        order = ordered_slots(bases_by_slot)
        results: list[LootSlotResult] = []
        # every slot the fill may change: its own, and the weapon slot a refill puts the skeleton's unique back in
        touched = [*order, *(pair for slot in order if (pair := _WEAPON_PARTNER.get(slot)) and self.uniques.get(pair) and pair not in order)]
        equipped = _equipped_raws(self.pob.export_xml(), touched)  # the start set, whoever equipped it
        base = self._gear_set("start", equipped)  # the set the next pass starts from, and what PoB wears between passes
        sets = [base]
        for p in range(passes):
            label = f"pass {p + 1}"
            last = p == passes - 1  # the extra-resistance step (`i-day1-templates`) belongs to the final pass: a set is recorded with its items on
            built, inf_slots = self._pass(p, order, bases_by_slot, sockets_by_slot, equipped, n=n, seed=seed, bench=bench)
            if not inf_slots:
                if last:
                    self._extra_resistance(order, equipped)
                base = self._gear_set(label, equipped)
                sets.append(base)
                results += built
                continue
            # an emptied slot read violation inf (rule 2 of #179): the pass is built twice from the same starting set,
            # in main's order and with the violation first on that slot; both complete sets go to the judge
            if last:
                self._extra_resistance(order, equipped)
            by_value = self._gear_set(f"{label} by value", equipped)
            self._restore_set(base, by_value)
            equipped = dict(base.equipped)
            built_v, _ = self._pass(p, order, bases_by_slot, sockets_by_slot, equipped, n=n, seed=seed, bench=bench, violation_first=inf_slots)
            if last:
                self._extra_resistance(order, equipped)
            by_violation = self._gear_set(f"{label} by violation", equipped)
            sets += [by_value, by_violation]
            chosen = best_gear_set([by_value, by_violation])  # the next pass, if any, goes on from the better of the two
            if chosen is not by_violation:
                self._restore_set(chosen, by_violation)
            equipped = dict(chosen.equipped)
            base = chosen
            results += built if chosen is by_value else built_v
        self._keep_best_gear_set(sets, now=base)
        return results

    def _pass(self, p: int, order: Sequence[str], bases_by_slot: Mapping[str, str], sockets_by_slot: Mapping[str, str] | None, equipped: dict[str, str | None], *, n: int | None, seed: int, bench: bool, violation_first: frozenset[str] = frozenset()) -> tuple[list[LootSlotResult], frozenset[str]]:
        """One internal pass over `order` (pass 2 empties each slot first); `equipped` is updated in place.

        Returns the slot results and the slots whose `current` read violation inf at the start of
        their fill (an emptied weapon of an attack build: no DPS, `inf` from the missing stats).
        `violation_first` names the slots filled with `_rank`'s violation-first order.
        """

        results: list[LootSlotResult] = []
        inf_slots: set[str] = set()
        for i, slot in enumerate(order):
            if p > 0:
                self.pob.equip({slot: None})
                equipped[slot] = None
            results.append(self.fill_slot(slot, bases_by_slot[slot], n=n, sockets=(sockets_by_slot or {}).get(slot), seed=derive_seed(seed, PURPOSE_LOOT_FILL_SLOT, p, i), bench=bench, violation_first=slot in violation_first))
            if results[-1].before is not None and math.isinf(results[-1].before.violation) and results[-1].before.violation > 0:
                inf_slots.add(slot)
            if results[-1].raw:  # a slot with no candidate stays as it was (emptied in a later pass)
                equipped[slot] = results[-1].raw
            pair = _WEAPON_PARTNER.get(slot)
            if pair in equipped and self.uniques.get(pair):
                equipped[pair] = self.uniques[pair]
        return results, frozenset(inf_slots)

    def _gear_set(self, label: str, equipped: Mapping[str, str | None]) -> GearSet:
        """The set as equipped now: PoB's own `Score` plus what a restore needs."""

        return GearSet(label, self.objective.score(self.pob.stats(self.objective.stat_keys)), dict(equipped), dict(self.current_raw))

    def _restore_set(self, target: GearSet, now: GearSet) -> None:
        """Put PoB and `current_raw` from the set `now` back to the set `target`."""

        updates = {slot: raw for slot, raw in target.equipped.items() if now.equipped.get(slot) != raw}
        if updates:
            self.pob.equip(updates)
            for slot in updates:
                restore_weapon_partner(self.pob, self.uniques, slot)  # PoB drops a paired unique a moved weapon no longer fits
        self.current_raw = dict(target.current_raw)

    def _keep_best_gear_set(self, sets: Sequence[GearSet], *, now: GearSet | None = None) -> GearSet:
        """End the fill on the best set it held and say so in one line (#179). `now` is the set PoB
        wears (the last one, unless a pass built twice ended on its other set)."""

        now = now or sets[-1]
        best = best_gear_set(sets)
        restored = best is not now
        self.log("loot fill sets: " + " | ".join(s.log_line for s in sets) + f" -> kept {best.label}" + (" (restored)" if restored else ""))
        if restored:
            self._restore_set(best, now)
        return best

    def _extra_resistance(self, slots: Iterable[str], equipped: dict[str, str | None] | None = None) -> None:
        """`i-day1-templates`: up to `extra_resistance_items` items of the build carry one more line, a
        resistance of an element still under its cap after counting. The candidates are the resistance
        lines the slots' counting dropped (their values as measured when they were counted); an
        element is under cap when PoB's `<Element>Resist` is below its `<Element>ResistMax`.
        `useful_lines.extra_resistance_keep` picks the lines; a chosen slot gets its counted item plus
        that one line back (its item before counting minus the other dropped lines). `equipped`, when given, is
        updated with the items put on (the gear set about to be recorded must hold them)."""

        from dataclasses import replace

        from junkroan.optimizer import useful_lines as ul

        dropped_res: dict[str, list[tuple[str, Any, Any]]] = {}
        for slot in slots:
            state = self._counting.get(slot)
            if state is None or state[2] != self.current_raw.get(slot):
                continue  # not counted, or the slot holds something else now
            rows = [(el, ln, v) for ln, v in state[1].dropped if (el := ul.resistance_element(ln.text))]
            if rows:
                dropped_res[slot] = rows
        if not dropped_res:
            return
        names = ("Fire", "Cold", "Lightning")
        read = self.pob.stats([f"{e}Resist{suffix}" for e in names for suffix in ("", "Max")])
        under = [
            e for e in names
            if isinstance(read.get(f"{e}Resist"), (int, float)) and isinstance(read.get(f"{e}ResistMax"), (int, float)) and read[f"{e}Resist"] < read[f"{e}ResistMax"]
        ]
        for slot, line in ul.extra_resistance_keep(dropped_res, under, max_items=self.rails.gear.wishlist.extra_resistance_items):
            raw_before, counted, _delivered = self._counting[slot]
            others = [ln for ln, _v in counted.dropped if ln.index != line.index]
            raw = ul.without_lines(raw_before, others)
            if ul.needs_recraft(raw_before, others):
                raw = self.pob.recraft(raw)
            self.pob.equip({slot: raw})
            self.current_raw[slot] = raw
            if equipped is not None:
                equipped[slot] = raw
            restore_weapon_partner(self.pob, self.uniques, slot)
            chosen = next((ln, v) for ln, v in counted.dropped if ln.index == line.index)
            self._counting[slot] = (raw_before, replace(counted, kept=(*counted.kept, chosen), dropped=tuple(d for d in counted.dropped if d[0].index != line.index)), raw)
            self.log(f"[{slot}] extra resistance kept: {line.text} ({ul.resistance_element(line.text)} under its cap)")


# -- #1152: the lines a weapon slot never carries (rails gear.weapon_forbidden_lines) -----------------------------------

_LEADING_TAGS = re.compile(r"^(?:\{[^}]*\})+")
_LEADING_NUMBER = re.compile(r"^[+-]?(?:\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)|\d+(?:\.\d+)?)\s*")
_RAW_IMPLICITS = re.compile(r"^Implicits:\s*(\d+)$")
_RAW_HEADER = re.compile(r"^[A-Z][A-Za-z ]*:\s")
_ELEMENT_GEMS_LINE = re.compile(r"^to level of all .+ gems$")
_WEAPON_BASE_TYPES = frozenset({"Bow", "Claw", "Dagger", "One Handed Sword", "One Handed Axe", "One Handed Mace", "Sceptre", "Staff",
                                "Two Handed Sword", "Two Handed Axe", "Two Handed Mace", "Wand", "Shield", "Quiver"})


def _line_tail(line: str) -> str:
    """A mod line without its leading `{tags}` and its `+N` / `+(a-b)`, whitespace-collapsed and case-folded."""

    text = _LEADING_NUMBER.sub("", _LEADING_TAGS.sub("", str(line).strip()).strip(), count=1)
    return " ".join(text.split()).casefold()


def weapon_line_forbidden(line: str, forbidden: Iterable[str]) -> bool:
    """True when `line` is, after its number, exactly one of the forbidden texts ("to Level of all Spell Skill Gems")."""

    tail = _line_tail(line)
    return any(tail == " ".join(str(text).split()).casefold() for text in forbidden)


def rare_mod_lines(lines: Sequence[str]) -> list[str]:
    """The mod lines of a rare's raw after its base line: past the `Implicits: N` block when the raw has one, else every non-header line."""

    at = next((i for i, ln in enumerate(lines) if _RAW_IMPLICITS.match(ln)), None)
    if at is not None:
        body = lines[at + 1 + int(_RAW_IMPLICITS.match(lines[at]).group(1)):]
    else:
        body = [ln for ln in lines[3:] if not _RAW_HEADER.match(ln)]
    return [ln for ln in body if _LEADING_TAGS.sub("", ln).strip() not in {"Corrupted", "Mirrored", "Split", "Unidentified", "Crafted"}]


def _weapon_rare_lines(slot: object, raw: object) -> list[str] | None:
    """The mod lines of a rare weapon raw (None for any other item). A trial names its slot; a delivered item (the output count) has none and is told by its base."""

    if not isinstance(raw, str):
        return None
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 3 or lines[0].lower() != "rarity: rare":
        return None
    if slot:
        if slot not in WEAPON_SLOTS:
            return None
    else:
        from junkroan.optimizer.item_bases import type_of

        if type_of(lines[2]) not in _WEAPON_BASE_TYPES:
            return None
    return rare_mod_lines(lines)


def weapon_all_gems_raw(slot: str, raw: str, forbidden: Iterable[str]) -> bool:
    """True for a rare weapon raw (Weapon 1 / Weapon 2) that carries a forbidden line."""

    forbidden = tuple(forbidden)
    mods = _weapon_rare_lines(slot, raw)
    return bool(forbidden) and mods is not None and any(weapon_line_forbidden(ln, forbidden) for ln in mods)


def unforced_forbidden(forbidden: Iterable[str], forced: Iterable[str] | None) -> tuple[str, ...]:
    """The forbidden texts minus those a forced line of the slot is itself: the request's own line is the only exemption."""

    forced = tuple(forced or ())
    return tuple(text for text in forbidden if not any(weapon_line_forbidden(line, (text,)) for line in forced))


def drop_weapon_all_gems(rolls: Sequence[Mapping[str, Any]], slot: str, rails: Rails, forced: Iterable[str] | None = ()) -> list[Mapping[str, Any]]:
    """The random rolls of `slot` that may be tried: none with a forbidden line on a weapon slot. A forbidden line the request itself forces keeps every roll."""

    forbidden = unforced_forbidden(getattr(rails.gear, "weapon_forbidden_lines", ()), forced)  # a rails stand-in without the key forbids nothing
    if slot not in WEAPON_SLOTS or not forbidden:
        return rolls if isinstance(rolls, list) else list(rolls)
    return [r for r in rolls if not weapon_all_gems_raw(slot, r["raw"], forbidden)]


def drop_shield_gem_with_other(rolls: Sequence[Mapping[str, Any]], slot: str) -> list[Mapping[str, Any]]:
    """The random rolls of `slot` that may be tried (#1155): none that is a Shield with a gem-level line AND another mod (#601: the gem line takes the whole shield)."""

    from junkroan.optimizer.wishlist_gear import is_shield_gem_level_with_other  # lazy: wishlist_gear imports this module

    if slot != "Weapon 2":
        return rolls if isinstance(rolls, list) else list(rolls)
    return [r for r in rolls if not is_shield_gem_level_with_other(slot, r["raw"])]


def base_refused(rails: Any, base: str, *, forced_base: str | None = None) -> bool:
    """True when the loadout never offers `base` (`gear.bases_excluded_by_loadout`, Prismatic Ring on day 1, #1154) and the request does not name it (`forced_base`)."""

    from junkroan.optimizer.item_bases import excluded_of

    name = str(base).strip().casefold()
    return bool(name) and name in excluded_of(rails) and name != str(forced_base or "").strip().casefold()


def raw_refused(loot: Any, slot: str, raw: str | None, *, forced_base: str | None = None) -> bool:
    """The one question "does a current restriction refuse this item for this slot" (#1152 restore-clean): a rare weapon with a
    forbidden line (`gear.weapon_forbidden_lines`, a forced line of the slot exempt), a shield the gem-level rule forbids (#1155),
    a base the loadout excludes (`forced_base` exempt). The filler's own rails and forced lines answer it."""

    from junkroan.optimizer.item_bases import raw_base_of

    if not raw:
        return False
    rails = getattr(loot, "rails", None)
    forbidden = unforced_forbidden(getattr(getattr(rails, "gear", None), "weapon_forbidden_lines", ()), (getattr(loot, "forced_lines", None) or {}).get(slot, ()))
    if weapon_all_gems_raw(slot, raw, forbidden) or not drop_shield_gem_with_other([{"raw": raw}], slot):
        return True
    return base_refused(rails, raw_base_of(raw), forced_base=forced_base)


def replaced_refused(loot: Any, before: Mapping[str, str | None], forced_bases: Mapping[str, str] | None = None) -> bool:
    """The restore decision (#1152): True when a trial moved a slot off an item a current restriction refuses (`before`: slot -> the
    raw it held). Its revert must not put that item back: the trial's item stays, the best clean candidate even when it scores
    lower (an empty slot when the filler had none). The incumbent restore of the `gear <slot>` move and of the joint kick ask this."""

    forced_bases = forced_bases or {}
    return any(raw and loot.current_raw.get(slot) != raw and raw_refused(loot, slot, raw, forced_base=forced_bases.get(slot)) for slot, raw in before.items())


@lru_cache(maxsize=1)
def _day1_forbidden() -> tuple[str, ...]:
    return Rails.load().gear.weapon_forbidden_lines


def _weapon_gems_class(trial: dict) -> Iterable[str]:
    """`weapon-all-gems-level` for a rare weapon carrying a forbidden line (must stay 0 at the PoB boundary and in the output),
    `weapon-element-gems-level` for one carrying another "to Level of all ... Gems" line (the allowed ones, counted > 0)."""

    item = trial.get("item") if isinstance(trial, dict) else None
    if not isinstance(item, dict):
        return ()
    mods = _weapon_rare_lines(item.get("slot"), item.get("raw"))
    if not mods:
        return ()
    forbidden = _day1_forbidden()
    out: list[str] = []
    if any(weapon_line_forbidden(ln, forbidden) for ln in mods):
        out.append("weapon-all-gems-level")
    if any(_ELEMENT_GEMS_LINE.match(_line_tail(ln)) and not weapon_line_forbidden(ln, forbidden) for ln in mods):
        out.append("weapon-element-gems-level")
    return out


register_class(_weapon_gems_class)

__all__ = ["GearSet", "LootGear", "LootSlotResult", "RARE_SLOT_ORDER", "WEAPON_SLOTS", "bench_candidates", "best_gear_set", "drop_shield_gem_with_other", "drop_weapon_all_gems", "forced_mod_choices", "ordered_slots", "rare_mod_lines", "raw_carries", "restore_weapon_partner", "unforced_forbidden", "weapon_all_gems_raw", "weapon_line_forbidden", "weapons_first"]

import junkroan.optimizer.useful_lines  # noqa: E402,F401  registers the rare-lines trace class whenever LootGear is imported
