"""PoB-free counters of what the search generated and evaluated, by move and option class (#498)."""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Iterator, Mapping, Sequence

UNATTRIBUTED = "(unattributed)"
_CLUSTER = re.compile(r"\b(Large|Medium|Small) Cluster Jewel\b")

# same regex as tree_optimizer.py:35 (importing that module here would pull PobSession and a cycle)
_ATTRIBUTE_REQUIREMENT = re.compile(r"^\+30 to (?:Strength|Dexterity|Intelligence)$", re.IGNORECASE)

_REGISTRY: list[Callable[[dict], Iterable[str]]] = []

# Config inputs the trace counts at the PoB boundary (#702): class = the input's own PoB name. A lane writes one
# (generated); a `PobSession.set_config` that carries it into PoB's config set counts it evaluated.
TRACED_CONFIG_INPUTS = ("conditionShockEffect", "conditionEnemyChilledEffect", "conditionScorchedEffect", "conditionBrittleEffect", "conditionSapEffect")


def register_class(fn: Callable[[dict], Iterable[str]]) -> None:
    """Add a class function; it runs after the built-ins, its exceptions are swallowed."""

    _REGISTRY.append(fn)


@lru_cache(maxsize=1)
def _unique_tiers() -> dict[str, str]:
    """Unique name -> `unique-tier:<n>` (the wiki drop-rate tier of corpus_data/uniques.json; #392); empty when unreadable."""

    try:
        path = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "uniques.json"
        recs = json.loads(path.read_text(encoding="utf-8"))["records"]
        return {str(r["name"]).split(",", 1)[0].strip(): f"unique-tier:{r['tier']}" for r in recs if r.get("tier") is not None and r.get("name")}
    except Exception:
        return {}


_NUM = r"-?\d+(?:\.\d+)?"


@lru_cache(maxsize=1)
def _craft_lines() -> tuple[tuple[bool, re.Pattern, tuple[tuple[float, float], ...]], ...]:
    """Every crafted mod line as (costs Exalted Orb, regex with one group per rolled number, the ranges of those numbers) (#392)."""

    try:
        from junkroan.mechanics.bench_unlocks import data

        mods_path = Path(__file__).resolve().parents[1] / "pob" / "corpus_data" / "bench_mods.json"
        mods = json.loads(mods_path.read_text(encoding="utf-8")).get("mods") or {}
        by_mod = data().get("by_mod_id") or {}
        out = []
        for mod_id, mod in mods.items():
            exalted = "exalted orb" in " ".join(str(c) for c in (by_mod.get(mod_id) or {}).get("cost") or ()).casefold()
            for line in mod["lines"]:
                text = " ".join(str(line).split()).casefold()
                parts = re.split(r"\((" + _NUM + ")-(" + _NUM + r")\)", text)
                literal, bounds = parts[0::3], list(zip(parts[1::3], parts[2::3]))
                regex = re.compile("(" + _NUM + ")").pattern.join(re.escape(x) for x in literal)
                out.append((exalted, re.compile(regex), tuple((min(float(lo), float(hi)), max(float(lo), float(hi))) for lo, hi in bounds)))
        return tuple(out)
    except Exception:
        return ()


def _is_exalt_craft(crafted_line: str) -> bool:
    """A rolled crafted line that fits a bench mod costing Exalted Orb and no cheaper bench mod (value inside the range, +-0.5 for rounding)."""

    text = " ".join(crafted_line.split()).casefold()
    fits = {True: False, False: False}
    for exalted, regex, ranges in _craft_lines():
        m = regex.fullmatch(text)
        if m and all(lo - 0.5 <= float(v) <= hi + 0.5 for v, (lo, hi) in zip(m.groups(), ranges)):
            fits[exalted] = True
    return fits[True] and not fits[False]


def _item_classes(item: dict) -> set[str]:
    out: set[str] = set()
    slot = item.get("slot")
    if isinstance(slot, str) and slot:
        out.add(f"slot:{slot}")
    raw = item.get("raw")
    if not isinstance(raw, str):
        return out
    lines = [ln.strip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln]
    rarity = ""
    rest: list[str] = []
    for ln in lines:
        if not rarity and ln.lower().startswith("rarity:"):
            rarity = ln.split(":", 1)[1].strip().lower()
        else:
            rest.append(ln)
    if rarity:
        out.add(f"rarity:{rarity}")
    base = ""
    if rarity in ("rare", "unique", "relic"):
        if rarity == "unique" and rest:
            out.add(f"unique:{rest[0]}")
        base = rest[1] if len(rest) > 1 else ""
    elif rest:
        base = rest[0]
        if rarity == "magic":
            base = base.split(" of ", 1)[0]
    if base:
        out.add(f"base:{base}")
        m = _CLUSTER.search(base)
        if m:
            out.add(f"cluster:{m.group(1).lower()}")
        if base.endswith("Flask"):
            out.add("flask")
        if "Tincture" in base:
            out.add("tincture")
    for ln in lines:
        if "Allocates " in ln:
            out.add("anoint")
        if ln.startswith("{crafted}"):
            out.add("bench-craft")
            for part in ln[len("{crafted}"):].split(" / "):
                if _is_exalt_craft(part):
                    out.add("bench-craft-exalt")
    return out


def _sockets_of(raw: str) -> str | None:
    for line in raw.splitlines():
        if line.strip().startswith("Sockets:"):
            return line.split(":", 1)[1].strip()
    return None


def _base_type(raw: str) -> str:
    """Item type of the raw's base (second non-Rarity line of a rare, as `_item_classes` reads it); "" when unknown."""

    classes = _item_classes({"raw": raw})
    base = next((c[len("base:"):] for c in classes if c.startswith("base:")), "")
    if not base:
        return ""
    try:
        from junkroan.optimizer.item_bases import type_of

        return type_of(base)
    except Exception:
        return ""


def default_node_kind(node_id: int) -> str:
    """Kind of a tree node for `node-kind:` classes; TreeGraph.load is lru_cached, so loaded once per process."""

    try:
        from junkroan.optimizer.tree_graph import TreeGraph

        node = TreeGraph.load().node(int(node_id))
        if node is None:
            return "unknown"
        if any(_ATTRIBUTE_REQUIREMENT.fullmatch(str(line).strip()) for line in node.stats):
            return "attribute+30"
        return "small" if node.kind == "normal" else str(node.kind)
    except Exception:
        return "unknown"


def classify(trial: dict, node_kind: Callable[[int], str] | None = None) -> set[str]:
    """Option classes of one trial; never raises, anything unparsed gives {"other"}."""

    out: set[str] = set()
    try:
        if isinstance(trial, dict):
            item = trial.get("item")
            if isinstance(item, dict):
                out |= _item_classes(item)
            # add and path (nodes a greedy move allocates on the way) are the add side; remove is its own side
            for key, node_cls, kind_cls in (
                ("add", "node", "node-kind"),
                ("path", "node", "node-kind"),
                ("remove", "node-rm", "node-kind-rm"),
            ):
                ids = trial.get(key)
                if not isinstance(ids, (list, tuple, set, frozenset)):
                    continue
                for nid in ids:
                    out.add(f"{node_cls}:{nid}")
                    try:
                        out.add(f"{kind_cls}:{(node_kind or default_node_kind)(nid)}")
                    except Exception:
                        pass
            if trial.get("mastery"):
                out.add("node-kind:mastery")
            if trial.get("attribute_cap_over"):
                out.add("attribute-cap:over")  # the trial takes the tree past the +30 cap (#516); the rail forbids it
    except Exception:
        pass
    snapshot = trial if isinstance(trial, dict) else {}
    for fn in list(_REGISTRY):
        try:
            out |= set(fn(snapshot))
        except Exception:
            pass
    return out or {"other"}


def _items_of(trial: dict) -> list[dict]:
    out = []
    one = trial.get("item")
    if isinstance(one, dict):
        out.append(one)
    many = trial.get("items")
    if isinstance(many, (list, tuple)):
        out += [i for i in many if isinstance(i, dict)]
    elif isinstance(many, dict):
        out += [{"slot": k, "raw": v} if isinstance(v, str) else v for k, v in many.items() if isinstance(v, (str, dict))]
    return out


def _forced_mastery_missing(mastery: dict, nodes: set[int], holders: dict | None) -> set[str]:
    """`forced-missing:node:<id>` classes of a mastery trial `{mastery node: effect}`. A forced id that is a tree node
    is that node (any effect swap on it counts, as before). A forced id that is a mastery effect id counts when the trial
    puts another effect on the mastery node holding it (`holders`: {node: effect} the build selected, else every mastery
    node that offers the effect); a trial that sets the forced effect is kept."""

    from junkroan.optimizer.tree_graph import TreeGraph

    graph = TreeGraph.load()
    out: set[str] = set()
    for node, effect in mastery.items():
        node, effect = int(node), int(effect)
        if node in nodes:
            out.add(f"forced-missing:node:{node}")
    for forced_id in nodes:
        if forced_id in graph.nodes:
            continue
        held = [n for n, e in (holders or {}).items() if int(e) == forced_id] or graph.mastery_effect_holders(forced_id)
        if any(int(n) in held and int(e) != forced_id for n, e in mastery.items()):
            out.add(f"forced-missing:node:{forced_id}")
    return out


def forced_classes(trial: dict, forced: dict) -> set[str]:
    """`forced-missing:<kind>:<key>` classes of a trial that drops a forced direction, else {"forced:kept"} (#510).
    Only an item trial on a forced slot and a tree trial touching a forced node can drop one."""

    out: set[str] = set()
    try:
        if not isinstance(trial, dict):
            return {"forced:kept"}
        from junkroan.search.forced import raw_has_affix, raw_header_ids

        uniques = forced.get("uniques") or {}
        bases = forced.get("bases") or {}
        affixes = forced.get("affixes") or {}
        forced_slots = set(uniques) | set(bases) | set(affixes)
        for item in _items_of(trial):
            slot = item.get("slot")
            raw = item.get("raw")
            if not isinstance(raw, str) or slot not in forced_slots:
                continue
            classes = _item_classes(item)
            if slot in uniques and f"unique:{uniques[slot]}" not in classes:
                out.add(f"forced-missing:unique:{slot}")
            if slot in bases and f"base:{bases[slot]}" not in classes:
                out.add(f"forced-missing:base:{slot}")
            if slot in affixes:
                # a recraft item (`useful_lines.trial_item`) has no rendered affix text: PoB rebuilds it from the
                # headers left, so a forced line counts as carried when a header of one of its mod ids is there
                ids = (forced.get("affix_mod_ids") or {}).get(slot) or []
                headers = raw_header_ids(raw) if item.get("recraft") and ids else frozenset()
                for i, ln in enumerate(affixes[slot]):
                    if raw_has_affix(raw, ln) or (headers and i < len(ids) and headers & set(ids[i])):
                        continue
                    out.add(f"forced-missing:affix:{slot}")
                    break
        nodes = {int(n) for n in (forced.get("nodes") or [])}
        if nodes:
            removed = trial.get("remove")
            if isinstance(removed, (list, tuple, set, frozenset)):
                out |= {f"forced-missing:node:{n}" for n in removed if int(n) in nodes}
            mastery = trial.get("mastery")
            if isinstance(mastery, dict):
                out |= _forced_mastery_missing(mastery, nodes, forced.get("mastery_holders"))
        # a trial that carries a whole build XML (`trial["xml"]`) must hold `<Spectre id="..."/>` for every forced spectre (#173)
        spectres = forced.get("spectres") or []
        xml = trial.get("xml")
        if spectres and isinstance(xml, str):
            from junkroan.search.forced import xml_spectre_ids

            have = xml_spectre_ids(xml)
            out |= {f"forced-missing:spectre:{s}" for s in spectres if s not in have}
    except Exception:
        pass
    return out or {"forced:kept"}


class Trace:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._local = threading.local()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._moves: dict[str, dict[str, Counter]] = {}
            self._pending: dict[str, Counter] = {}
            self._output: dict[str, int] = {}
            self._forced: dict | None = None
            self._sockets: dict[str, tuple[str, str]] = {}

    def _label(self) -> str | None:
        return getattr(self._local, "label", None)

    def _add(self, kind: str, classes: Iterable[str], n: int) -> None:
        if getattr(self._local, "muted", False):
            return
        label = self._label()
        with self._lock:
            bucket = self._pending if label is None else self._moves.setdefault(label, {})
            for c in classes:
                bucket.setdefault(c, Counter())[kind] += n

    @contextmanager
    def muted(self) -> Iterator[None]:
        """Nothing counted inside: a probe that writes config to read PoB's numbers is no evaluation of the lane (#702)."""

        prev = getattr(self._local, "muted", False)
        self._local.muted = True
        try:
            yield
        finally:
            self._local.muted = prev

    def add_generated(self, classes: Iterable[str], n: int = 1) -> None:
        self._add("generated", classes, n)

    def add_evaluated(self, classes: Iterable[str], n: int = 1) -> None:
        self._add("evaluated", classes, n)

    def _classes(self, trial: dict) -> set[str]:
        classes = classify(trial)
        forced = self._forced
        if forced:
            classes |= forced_classes(trial, forced)
        with self._lock:
            notes = dict(self._sockets)
        if notes and isinstance(trial, dict):
            try:
                for it in _items_of(trial):
                    note = notes.get(it.get("slot"))
                    raw = it.get("raw")
                    if note is None or not isinstance(raw, str):
                        continue
                    line, inc_type = note
                    own_type = _base_type(raw)
                    if own_type and inc_type and own_type != inc_type:
                        classes.add("gear-sockets:other-class")
                    elif (_sockets_of(raw) or "").strip() == line:
                        classes.add("gear-sockets:incumbent")
                    else:
                        classes.add("gear-sockets:missing")
            except Exception:
                # a classification that fails is counted, never silent: `missing = 0` must not pass on a check
                # that never ran (#548 review, principle 5)
                classes.add("gear-sockets:unclassified")
        return classes

    def count_trial(self, trial: dict) -> None:
        self.add_evaluated(self._classes(trial))

    def count_candidates(self, trials: Iterable[dict]) -> None:
        for t in trials:
            self.add_generated(self._classes(t))

    def flush(self, label: str) -> None:
        with self._lock:
            target = self._moves.setdefault(label, {})
            for c, cnt in self._pending.items():
                target.setdefault(c, Counter()).update(cnt)
            self._pending = {}

    @contextmanager
    def move(self, label: str) -> Iterator[None]:
        prev = self._label()
        self._local.label = label
        try:
            yield
        finally:
            self._local.label = prev

    def considered(self) -> dict[str, dict[str, dict[str, int]]]:
        with self._lock:
            moves = dict(self._moves)
            if any(sum(c.values()) for c in self._pending.values()):
                moves[UNATTRIBUTED] = self._pending
            return {
                m: {c: {"generated": cnt["generated"], "evaluated": cnt["evaluated"]} for c, cnt in sorted(classes.items())}
                for m, classes in moves.items()
            }

    def set_forced(self, forced: dict | None) -> None:
        """The forced directions of the build being searched (#510; ``search.forced.forced_of``'s shape),
        or None. ``count_trial`` classes a trial against them."""

        with self._lock:
            self._forced = dict(forced) if forced else None

    def note_forced_mod_ids(self, slot: str, choices: Sequence[Sequence[str]]) -> None:
        """The mod ids that can roll each forced line of ``slot`` (``loot_gear.forced_mod_choices``, one list per
        forced line, in the order of ``forced["affixes"][slot]``): a recraft item of the slot carries a forced
        line when a header of one of these ids is on it. No forced directions set: nothing to note."""

        with self._lock:
            if not self._forced or not choices:
                return
            ids = dict(self._forced.get("affix_mod_ids") or {})
            ids[slot] = [list(group) for group in choices]
            self._forced = {**self._forced, "affix_mod_ids": ids}

    @contextmanager
    def incumbent_sockets(self, slot: str, raw: str | None) -> Iterator[None]:
        """While inside, trials with an item in ``slot`` get a `gear-sockets:*` class against the incumbent's
        Sockets line (#548). No raw or no Sockets line: no note. Notes nest per slot."""

        line = _sockets_of(raw) if isinstance(raw, str) else None
        if not line:
            yield
            return
        note = (line, _base_type(raw))
        with self._lock:
            prev = self._sockets.get(slot)
            self._sockets[slot] = note
        try:
            yield
        finally:
            with self._lock:
                if prev is None:
                    self._sockets.pop(slot, None)
                else:
                    self._sockets[slot] = prev

    def forced(self) -> dict | None:
        with self._lock:
            return self._forced

    def set_output(self, counts: Mapping[str, int]) -> None:
        with self._lock:
            self._output = dict(counts)

    def output(self) -> dict[str, int]:
        with self._lock:
            return dict(self._output)


def _unique_tier_class(trial: dict) -> Iterable[str]:
    """`unique-tier:<n>` for a unique item trial (#392: day 1 allows tier 5 only)."""

    item = trial.get("item") if isinstance(trial, dict) else None
    raw = item.get("raw") if isinstance(item, dict) else None
    if not isinstance(raw, str):
        return ()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if len(lines) < 2 or lines[0].lower() != "rarity: unique":
        return ()
    tier = _unique_tiers().get(lines[1].split(",", 1)[0].strip())
    return (tier,) if tier else ()


register_class(_unique_tier_class)

TRACE = Trace()

MARK_PREFIX = "mark:"


def mark_class(line: str) -> str:
    """The trace class of a red-line mark (#1124): `mark:<line text>`, the held line with its whitespace collapsed
    to single spaces (a node's stat line can carry a newline). Counted by `count_marks_generated` when the lane
    writers write the line's mark into a lane's block, and by `count_marks_evaluated` once that block is in PoB's
    config set (the boundary, the same moment `PobSession.set_config` counts a traced config input evaluated, #702).
    A held line whose record gives it no mark on a lane counts 0 / 0 there, so a zero record is visible as a class
    with `generated == 0 and evaluated == 0`; a line with no record, or not held, has no class at all."""

    return MARK_PREFIX + " ".join(str(line).split())


def _marks_of_trial(trial: dict) -> list[str]:
    """`mark:<line>` of every red line whose mark a tree trial carries (#1124, unit 4): `trial["marks"]` is
    `{"add": {held line: [mark lines]}, "remove": {...}}` as the tree optimizer stamps it and `PobSession.trial_stats`
    hands to the trace; the classes are counted generated by `count_candidates` and evaluated by `count_trial`."""

    marks = trial.get("marks")
    if not isinstance(marks, dict):
        return []
    return [mark_class(line) for side in ("add", "remove") if isinstance(marks.get(side), dict) for line in marks[side]]


register_class(_marks_of_trial)


def count_marks_generated(written: Mapping[str, int]) -> None:
    """`written`: held line -> the number of lanes whose block carries its mark (0 for a zero reading)."""

    for line, lanes in written.items():
        TRACE.add_generated([mark_class(line)], lanes)


def count_marks_evaluated(written: Mapping[str, int]) -> None:
    for line, lanes in written.items():
        TRACE.add_evaluated([mark_class(line)], lanes)


def output_counts(
    items_raw: Iterable[str], nodes: Iterable[int], node_kind: Callable[[int], str] | None = None
) -> dict[str, int]:
    """Count option classes over the final items (as item trials) and tree nodes."""

    counts: Counter = Counter()
    for raw in items_raw:
        counts.update(classify({"item": {"slot": "", "raw": raw}}))
    for nid in nodes:
        counts.update(classify({"add": [nid]}, node_kind))
    return dict(sorted(counts.items()))
