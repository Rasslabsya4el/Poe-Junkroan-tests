"""Every line of the day-1 surfaces that the day-1 rails allow, with how PoB parses it (#1119, unit 1).

A row is `{line, surface, source, outcome}`:
- surface: notable | mastery | ascendancy | keystone | unique | unique_jewel | gear_affix | flask
- source: the node id (tree), the unique's name (unique, unique_jewel) or the mod id (gear_affix, flask)
- outcome: full | partial | none | missing, the PoB parse outcome of the line

Rules (what the day-1 rails allow):
- tree: every notable, keystone, mastery effect and ascendancy node of PoB's own corpora (no rail narrows it).
- unique: `Rails.unique_allowed` (availability, max_req_level, drop tier); Jewel and Tincture records are not here.
- unique_jewel: a Jewel record whose slug (the name before its first comma) is in the owner's form with the
  `day1` loadout; the form has no such row yet, so the surface is empty until the owner sets one.
- gear_affix: regular affixes (ModExplicit, Prefix/Suffix, level <= the highest wishlist item level, some spawn
  weight > 0) and bench crafts (ModMaster, level <= that item level, `Rails.bench_allowed` on the recipe unlock).
- flask: magic Flask mods (ModFlask) with level <= that item level on a Flask base the rails allow (drop level
  <= `wishlist.base_level_max`). Tinctures are out.

Outcome of a line: `parse_outcomes.json` by exact line when that file exists (`ok`/`unsupported`/`extra`/`mod_types`:
no mod types = none, extra text = partial, else full); else PoB's `Data/ModCache.lua` by exact line; a rolled
affix or flask line that the cache does not hold exactly is looked up by its form (numbers replaced by #, cache keys
with a range excluded). A line in neither is `missing`.

Run: `python scripts/day1_lines.py` prints the count per surface x outcome. Reads files only; no PobSession.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from junkroan.mechanics import bench_unlocks  # noqa: E402
from junkroan.pob.bench_mod_ids import bench_mod_id  # noqa: E402
from junkroan.optimizer.flask_lines import flask_bases, flask_mods  # noqa: E402
from junkroan.optimizer.jewel_lines import roll_line  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.pob.game_corpus import DEFAULT_SOURCE_ROOT  # noqa: E402
from junkroan.pob.lua_tables import parse_lua_return_value  # noqa: E402

SURFACES = ("notable", "mastery", "ascendancy", "keystone", "unique", "unique_jewel", "gear_affix", "flask")
OUTCOMES = ("full", "partial", "none", "missing")
DAY1_LOADOUTS = frozenset({"day1"})
CORPUS_ROOT = ROOT / "src" / "junkroan" / "pob" / "corpus_data"
UNIQUE_JEWEL_FORM = ROOT / "docs" / "rulebook" / "2026-09-19-unique-jewels.json"
MODCACHE = DEFAULT_SOURCE_ROOT / "src" / "Data" / "ModCache.lua"
PARSE_OUTCOMES = CORPUS_ROOT / "parse_outcomes.json"

_RANGE = re.compile(r"\((-?\d+(?:\.\d+)?)-(-?\d+(?:\.\d+)?)\)")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_MC_ROW = re.compile(r'c\["((?:[^"\\]|\\.)*)"\]=\{(.*)\}\s*$')
_EXTRA = re.compile(r',"((?:[^"\\]|\\.)*)"$')
_PRIORITY = {"full": 0, "partial": 1, "none": 2}


@dataclass(frozen=True, slots=True)
class Day1Corpus:
    """Everything the rows are read from. Each field is plain data, so a test passes a tiny one."""

    passives: Sequence[Mapping[str, Any]] = ()  # passives.json records: is_notable, node_id, stats
    keystones: Sequence[Mapping[str, Any]] = ()  # keystones.json records
    masteries: Sequence[Mapping[str, Any]] = ()  # masteries.json records: node_id, mastery_effects[].stats
    ascendancies: Sequence[Mapping[str, Any]] = ()  # ascendancies.json records: nodes[] with node_id, stats
    uniques: Sequence[Mapping[str, Any]] = ()  # uniques.json records: name, type, availability, req_level, tier, lines
    unique_jewel_form: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # slug -> {"loadout": ...}
    explicit: Sequence[Mapping[str, Any]] = ()  # {id, type, level, template, spawns}
    bench: Sequence[Mapping[str, Any]] = ()  # {id, type, level, template, unlock}
    flasks: Sequence[Mapping[str, Any]] = ()  # {id, type, level, lines}
    modcache: Mapping[str, str] = field(default_factory=dict)  # exact line -> full | partial | none
    parse_outcomes: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)  # exact line -> {ok, unsupported, extra, mod_types}


def _unescape(text: str) -> str:
    return text.replace('\\"', '"').replace("\\\\", "\\")


def _form(line: str) -> str:
    return _NUM.sub("#", _RANGE.sub("#", line))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_modcache(text: str) -> dict[str, str]:
    """`c["line"]={mods|nil, extra|nil}` rows of PoB's ModCache.lua -> {line: full | partial | none}."""

    out: dict[str, str] = {}
    for raw in text.splitlines():
        m = _MC_ROW.search(raw)
        if not m:
            continue
        key, body = _unescape(m.group(1)), m.group(2)
        if body.startswith("nil,") or body.startswith("{},"):
            outcome = "none"
        elif body.endswith(",nil"):
            outcome = "full"
        else:
            extra = _EXTRA.search(body)
            outcome = "partial" if extra and extra.group(1).strip() else "full"
        out[key] = outcome
    return out


def _parse_outcome(entry: Mapping[str, Any]) -> str:
    if not entry.get("mod_types"):
        return "none"
    return "partial" if entry.get("extra") else "full"


class _Outcomes:
    def __init__(self, corpus: Day1Corpus) -> None:
        self._parsed = {line: _parse_outcome(entry) for line, entry in corpus.parse_outcomes.items()}
        self._exact = dict(corpus.modcache)
        self._forms: dict[str, str] = {}
        for key, outcome in corpus.modcache.items():
            if _RANGE.search(key):  # PoB caches a range line unsubstituted: no evidence for a rolled line
                continue
            form = _form(key)
            if form not in self._forms or _PRIORITY[outcome] < _PRIORITY[self._forms[form]]:
                self._forms[form] = outcome

    def of(self, line: str, *, by_form: bool) -> str:
        if line in self._parsed:
            return self._parsed[line]
        if line in self._exact:
            return self._exact[line]
        if by_form:
            return self._forms.get(_form(line), "missing")
        return "missing"


def _row(surface: str, source: Any, line: str, outcomes: _Outcomes, *, by_form: bool = False) -> dict[str, Any]:
    return {"line": line, "surface": surface, "source": source, "outcome": outcomes.of(line, by_form=by_form)}


def _tree_stats(node: Mapping[str, Any]) -> list[str]:
    return [str(s) for s in node.get("stats") or ()]


def day1_rows(rails: Rails, corpus: Day1Corpus) -> Iterator[dict[str, Any]]:
    outcomes = _Outcomes(corpus)
    item_level = max(rails.gear.wishlist.item_level.values())

    for node in corpus.passives:
        if node.get("is_notable"):
            for line in _tree_stats(node):
                yield _row("notable", node["node_id"], line, outcomes)
    for node in corpus.masteries:
        effects = [s for e in node.get("mastery_effects") or () for s in e.get("stats") or ()]
        for line in effects or _tree_stats(node):
            yield _row("mastery", node["node_id"], str(line), outcomes)
    for asc in corpus.ascendancies:
        for node in asc.get("nodes") or ():
            for line in _tree_stats(node):
                yield _row("ascendancy", node["node_id"], line, outcomes)
    for node in corpus.keystones:
        for line in _tree_stats(node):
            yield _row("keystone", node["node_id"], line, outcomes)

    for rec in corpus.uniques:
        if rec.get("type") in ("Jewel", "Tincture") or not rails.unique_allowed(rec):
            continue
        for line in rec.get("lines") or ():
            yield _row("unique", rec["name"], str(line), outcomes)

    for rec in corpus.uniques:
        if rec.get("type") != "Jewel":
            continue
        entry = corpus.unique_jewel_form.get(_slug(str(rec["name"]).split(",")[0]))
        if entry is None or entry.get("loadout") not in DAY1_LOADOUTS:
            continue
        for line in rec.get("lines") or ():
            yield _row("unique_jewel", rec["name"], str(line), outcomes)

    for rec in corpus.explicit:
        if rec.get("type") in ("Prefix", "Suffix") and rec.get("spawns", True) and int(rec["level"]) <= item_level:
            for template in rec["template"]:
                yield _row("gear_affix", rec["id"], roll_line(template), outcomes, by_form=True)
    for rec in corpus.bench:
        if rec.get("type") in ("Prefix", "Suffix") and int(rec["level"]) <= item_level and rails.bench_allowed({"unlock": rec.get("unlock")}):
            for template in rec["template"]:
                yield _row("gear_affix", rec["id"], roll_line(template), outcomes, by_form=True)

    for rec in corpus.flasks:
        if rec.get("type") in ("Prefix", "Suffix") and int(rec["level"]) <= item_level:
            for line in rec["lines"]:
                yield _row("flask", rec["id"], roll_line(str(line)), outcomes, by_form=True)


def _records(path: Path) -> list[dict[str, Any]]:
    return list(json.loads(path.read_text(encoding="utf-8"))["records"])


def _mod_records(rails: Rails, source_root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Explicit and bench mods from PoB's Data files; flask mods through the flask step's own readers."""

    data = source_root / "src" / "Data"
    explicit, bench = [], []
    for mod_id, mod in parse_lua_return_value((data / "ModExplicit.lua").read_text(encoding="utf-8")).items():
        explicit.append({
            "id": mod_id, "type": mod.get("type"), "level": int(mod.get("level") or 0),
            "template": [str(mod[i]) for i in range(1, 10) if i in mod],
            "spawns": any(float(w) > 0 for w in mod.get("weightVal") or ()),
        })
    # ModMaster.lua is an unkeyed list of bench rows (PoB gives them no mod id), so the parser returns a list;
    # a row is labelled by its 1-based position, and its RePoE mod id (bench_mod_id) joins it to the unlock.
    for index, mod in enumerate(parse_lua_return_value((data / "ModMaster.lua").read_text(encoding="utf-8")), start=1):
        row = {"type": mod.get("type"), "group": mod.get("group"), "level": int(mod.get("level") or 0),
               "lines": [str(mod[i]) for i in range(1, 10) if i in mod]}
        bench.append({
            "id": f"ModMaster#{index}", "type": row["type"], "level": row["level"], "template": row["lines"],
            "unlock": bench_unlocks.lookup(mod_id=bench_mod_id(row)),
        })
    item_level = max(rails.gear.wishlist.item_level.values())
    flasks: dict[str, dict] = {}
    for base in flask_bases(rails.gear.wishlist.base_level_max, source_root):
        if base.item_class != "Flask":
            continue
        for fm in flask_mods(base, item_level, source_root):
            flasks.setdefault(fm.id, {"id": fm.id, "type": fm.affix.capitalize(), "level": fm.level, "lines": list(fm.lines)})
    return explicit, bench, list(flasks.values())


def load_corpus(rails: Rails, *, source_root: Path = DEFAULT_SOURCE_ROOT) -> Day1Corpus:
    explicit, bench, flasks = _mod_records(rails, source_root)
    return Day1Corpus(
        passives=_records(CORPUS_ROOT / "passives.json"),
        keystones=_records(CORPUS_ROOT / "keystones.json"),
        masteries=_records(CORPUS_ROOT / "masteries.json"),
        ascendancies=_records(CORPUS_ROOT / "ascendancies.json"),
        uniques=_records(CORPUS_ROOT / "uniques.json"),
        unique_jewel_form=json.loads(UNIQUE_JEWEL_FORM.read_text(encoding="utf-8")),
        explicit=explicit,
        bench=bench,
        flasks=flasks,
        modcache=parse_modcache(MODCACHE.read_text(encoding="utf-8", errors="replace")),
        parse_outcomes=json.loads(PARSE_OUTCOMES.read_text(encoding="utf-8")) if PARSE_OUTCOMES.exists() else {},
    )


def main() -> int:
    rails = Rails.load()
    corpus = load_corpus(rails)
    counts = Counter((r["surface"], r["outcome"]) for r in day1_rows(rails, corpus))
    print(f"parse_outcomes.json: {'present' if corpus.parse_outcomes else 'absent'} ({len(corpus.parse_outcomes)} lines)")
    print(f"{'surface':<14}" + "".join(f"{o:>10}" for o in OUTCOMES) + f"{'total':>10}")
    for surface in SURFACES:
        cells = [counts[(surface, o)] for o in OUTCOMES]
        print(f"{surface:<14}" + "".join(f"{c:>10}" for c in cells) + f"{sum(cells):>10}")
    totals = [sum(counts[(s, o)] for s in SURFACES) for o in OUTCOMES]
    print(f"{'total':<14}" + "".join(f"{c:>10}" for c in totals) + f"{sum(totals):>10}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
