"""Issue #1042: the counted inventory of day-1 reshaping choices, regenerated from PoB's parsed data.

    python scripts/reshaping_inventory.py [--out docs/research/2026-10-14-day1-reshaping-inventory.md] [--artifacts artifacts/keystone_flip]

Inputs (no PoB run here):
- the keystone parse of #1030, `artifacts/keystone_flip/parse.json` (`python -m junkroan.keystone_parse`): the stat
  lines of every keystone of the tree corpus (`src/junkroan/pob/corpus_data/keystones.json`), each with PoB's mods and
  its parse kind (zero / redirect / add / unparsed, rules in `junkroan.keystone_parse`);
- the three step-1 flips of #1030, `artifacts/keystone_flip/{spark,cold_dot,smite}.json` (state 1 / state 2 numbers);
- the rails, `src/junkroan/optimizer/rails_default.json` (floors, `tree.forbidden_text`).

Unit 2 adds two inputs, both tracked corpora (no PoB run, no artifacts):
- `src/junkroan/pob/corpus_data/scaling_vectors.json`: PoB's parse of every unique and notable line, grouped by the stat
  a mod scales "per" (`per:Dex`, `per:Int`, `per:Str`; each payoff carries the parsed stat name and PerStat tag);
- `src/junkroan/pob/corpus_data/uniques.json`: every unique with its lines and the mods PoB parsed per line,
  `passives.json` for the notables' own lines.

The table is a pure function of those files: the same inputs give the same bytes. Unit 1 filled `keystone_rows`; unit 2
adds `stacking_rows` and `unique_rows` to the same `Row` list and the same renderer.

Keystone rules (the ticket's):
- a keystone is a candidate when one of its stat lines parses as `zero` or `redirect`; a keystone with only `add` /
  `unparsed` lines goes to the excluded table (the `add` ones counted);
- "the parsed mod lines": the stat lines of kind zero / redirect, verbatim as PoB receives them;
- "floor it collapses": measured first. A flip where the build did not hold the keystone (`flip` = add) collapses a
  floor stat when its state-1 value is above 0 and the state-2 value is missing, or below half of it (`is_collapsed`
  of `keystone_flip.py`, the same reading). The floor stats are `FLOOR_STATS`; `Mana` is named only when
  `ManaUnreserved` (the floor that pool feeds) did not collapse. A floor collapsed in at least one flip is the row's
  floor. When no flip collapsed one, the floor comes from the parsed mods of the zero / redirect lines (`mod_floors`:
  the pool the mod's own name says, e.g. EnergyShieldProtectsMana -> EnergyShield); no pool in any mod = `none`. The
  flip cell says which of the two it is;
- "in the day-1 pool": `no` when the rails forbid every line of the keystone (`tree.forbidden_text`) or PoB's tree does
  not know the node (every flip refused with "unknown node id"); keystones are otherwise unrestricted by the rails.

Stacking rules (unit 2): one row per attribute direction (Dex, Int, Str). A direction is a candidate when
`scaling_vectors.json` holds >= 1 payoff of family unique or notable whose parsed mod has a `PerStat` tag on that attribute
(`per 10 Dexterity` style, not a `StatThreshold` "at least N") and whose parsed stat is damage or defence by its NAME
(`DAMAGE_STAT_RE`: *Damage, <Type>Min / <Type>Max; `DEFENCE_STAT_RE`: Life, EnergyShield, Armour, Evasion, Ward, block,
LifeRegenPercent, a resistance). The row lists each such line verbatim with its corpus entry (file and key), aligned one to
one; a line of a unique outside the day-1 pool, or of a notable the rails forbid, is flagged `not in pool`. Families
unique, notable, mastery and ascendancy notable are payoffs alike (#1065 rule 1): a mastery line names its mastery
(`masteries.json node_id`), an ascendancy line its node (`ascendancies.json node_id`); each line names its family.
Threshold payoffs and payoffs of another stat go to the excluded counts with their reason.

Unique rules (unit 2): every unique of `uniques.json` (day-1 pool or not: the row says which). A mod is a candidate when it
is `zero` or `redirect` by the same per-mod rules as the keystone parse (`junkroan.keystone_parse.classify_line`, applied
to the one parsed mod) AND its parsed name names a resource or a defence (`RESOURCE_DEFENCE_RE`), with these refinements:
an OVERRIDE counts as a zero only at value 0 ("Chaos Resistance is Zero"); `Multiplier:*` doublings are not zeros. Three more redirect shapes that `classify_line` reads as `add`
and that the issue asks for are read from the parsed name and value, each tagged with its rule in the flip cell:
`Extra{Life,Mana}Reserved` (BASE: "Reserves 30% of Life"), an `ExtraSupport` whose skillId holds `BloodMagic` ("Socketed
Gems Cost and Reserve Life instead of Mana"), and a pool move named `Convert...To<Pool>` / `<Pool>To<Pool>`
(`ConvertArmourESToLife`, `EnergyShieldToWard`). The floor a row collapses is never measured here (no flip of a unique):
`mod_floor` of unit 1 (the pool the mod's own name says), `ChaosResist` / an elemental resistance for an OVERRIDE of it; the
flip cell says `not flipped`. The day-1 pool is `Rails.unique_allowed`: availability, req_level, tier of the rails file.

#1065 unique rules: (2) a Blood Magic support unique takes the floor of the Blood Magic keystone row, read from the
keystone rows at generation time (`blood_magic_keystone_floors`), never a constant; the note says so in the flip cell.
(3) a `StunThreshold*` mod (the stun lines of Valyrium and Skyforth: "Stun Threshold is based on Energy Shield instead of
Life") is no floor stat: it goes to the excluded uniques with the reason `redirect without a floor stat (stun threshold)`
(its parse kind is `add`, read by `classify_line`); Skyforth's zero row stays.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # the package lives in src/ (scripts/junkroan.py would shadow it otherwise)

from junkroan.keystone_parse import classify_line  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402

REPORT_DATE = "2026-10-14"
ARTIFACTS_DIR = ROOT / "artifacts" / "keystone_flip"
BUILDS = ("spark", "cold_dot", "smite")
RAILS_PATH = ROOT / "src" / "junkroan" / "optimizer" / "rails_default.json"
CORPUS_DIR = ROOT / "src" / "junkroan" / "pob" / "corpus_data"
KEYSTONE_CORPUS = CORPUS_DIR / "keystones.json"
UNIQUES_CORPUS = CORPUS_DIR / "uniques.json"
PASSIVES_CORPUS = CORPUS_DIR / "passives.json"
VECTORS_CORPUS = CORPUS_DIR / "scaling_vectors.json"
OUT_PATH = ROOT / "docs" / "research" / "2026-10-14-day1-reshaping-inventory.md"

KINDS = ("keystone", "stacking", "unique")
FLOOR_STATS = ("Life", "ManaUnreserved", "Mana", "EnergyShield", "FireResist", "ColdResist", "LightningResist")
NO_FLOOR = "none"
POOL_TOKEN_RE = re.compile(r"EnergyShield|Life|Mana")
POOL_FLOOR = {"EnergyShield": "EnergyShield", "Life": "Life", "Mana": "ManaUnreserved"}  # the floor stat a pool feeds
COLUMNS = ("choice", "kind", "parsed mod lines (verbatim)", "parse kind", "floor it collapses", "in day-1 pool", "#1030 flip row", "corpus entry")


@dataclass(frozen=True)
class Row:
    choice: str
    kind: str  # keystone | stacking | unique
    lines: tuple[str, ...]
    parse_kind: str  # zero | redirect | "zero, redirect"
    floors: tuple[str, ...]  # floor stats collapsed; () = none
    in_pool: str  # "yes" | "no: <reason>"
    flip: str  # keystones only; "-" otherwise
    corpus: str  # file and key of the corpus entry


@dataclass(frozen=True)
class Excluded:
    choice: str
    kind: str
    parse_kinds: str
    reason: str
    corpus: str


# -- measuring the flips ----------------------------------------------------------------------------------


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def stat_collapsed(before: Any, after: Any) -> bool:
    """A floor stat worth something in state 1 (> 0) whose state-2 value is missing or fell below half."""

    if not _is_number(before) or before <= 0:
        return False
    return not _is_number(after) or after < before / 2.0


def collapsed_floors(state1: Mapping[str, Any], state2: Mapping[str, Any]) -> tuple[str, ...]:
    """The FLOOR_STATS that collapse between two states; `Mana` only when `ManaUnreserved` did not."""

    hit = [s for s in FLOOR_STATS if stat_collapsed(state1.get(s), state2.get(s))]
    if "ManaUnreserved" in hit and "Mana" in hit:
        hit.remove("Mana")
    return tuple(hit)


def mod_floor(kind: str, mod: Mapping[str, Any]) -> str | None:
    """The floor one parsed mod names, or None: Chaos Inoculation's flag (Maximum Life becomes 1), a pool multiplied
    by -100 (`Mana` / `EnergyShield` MORE -100), and, on a redirect line, the first pool word in the mod's own name
    (EnergyShieldProtectsMana -> EnergyShield; DamageTakenFromManaBeforeLife -> Mana -> ManaUnreserved)."""

    name = str(mod.get("name") or "")
    if name == "ChaosInoculation":
        return "Life"
    if name in POOL_FLOOR and mod.get("type") in {"MORE", "BASE", "INC"} and mod.get("value") == -100:
        return POOL_FLOOR[name]
    if kind == "redirect":
        match = POOL_TOKEN_RE.search(name)
        if match:
            return POOL_FLOOR[match.group(0)]
    return None


def mod_floors(lines: Sequence[Mapping[str, Any]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(floors, names of the mods that gave them) over the parsed zero / redirect lines."""

    found: set[str] = set()
    names: set[str] = set()
    for line in lines:
        for mod in line.get("mods") or []:
            floor = mod_floor(str(line.get("kind")), mod)
            if floor:
                found.add(floor)
                names.add(str(mod["name"]))
    return tuple(s for s in FLOOR_STATS if s in found), tuple(sorted(names))


def build_flip_index(flips: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Mapping[str, Any]]]:
    """build -> keystone name -> flip row."""

    return {build: {row["keystone"]: row for row in payload["rows"]} for build, payload in flips.items()}


def _percent(value: Any) -> str:
    return "-" if not _is_number(value) else f"{value:+.1f}%"


def flip_cell(name: str, index: Mapping[str, Mapping[str, Mapping[str, Any]]], floors_from: str, mods: tuple[str, ...]) -> str:
    """One cell: per build the flip status, the CombinedDPS change and the floors it collapsed there; then where
    the row's floor comes from."""

    parts: list[str] = []
    for build in BUILDS:
        row = index.get(build, {}).get(name)
        if row is None:
            parts.append(f"{build}: no row")
            continue
        status = str(row["status"])
        if status == "pob_refused":
            reason = str(row.get("reason") or "")
            parts.append(f"{build}: pob_refused ({reason.split(': ', 1)[-1]})")
            continue
        dps = _percent((row.get("delta_pct") or {}).get("CombinedDPS"))
        note = f"{build}: {status} CombinedDPS {dps}"
        if row["flip"] == "remove":
            note += " (build held it, state 2 removes it)"
        else:
            hit = collapsed_floors(row["state1"], row["state2"])
            note += f", floors collapsed: {', '.join(hit) if hit else 'none'}"
        parts.append(note)
    parts.append(f"floor {floors_from}" + (f" ({', '.join(mods)})" if mods else ""))
    return "<br>".join(parts)


def measured_floors(name: str, index: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> tuple[tuple[str, ...], int]:
    """(floors collapsed in at least one add-flip with a state 2, number of such flips)."""

    found: set[str] = set()
    flips = 0
    for build in BUILDS:
        row = index.get(build, {}).get(name)
        if row is None or row["flip"] != "add" or not row.get("state2"):
            continue
        flips += 1
        found.update(collapsed_floors(row["state1"], row["state2"]))
    return tuple(s for s in FLOOR_STATS if s in found), flips


def not_in_pool_reason(name: str, stats: Sequence[str], index: Mapping[str, Mapping[str, Mapping[str, Any]]], forbidden: Sequence[str]) -> str | None:
    """Why the rails or PoB's tree keep this keystone out of the day-1 pool, or None."""

    regs = [re.compile(p, re.IGNORECASE) for p in forbidden]
    if regs and stats and all(any(r.search(s) for r in regs) for s in stats):
        return "the rails' tree.forbidden_text forbids every line"
    refused = [
        index[b][name] for b in BUILDS if b in index and name in index[b]
    ]
    unknown = [r for r in refused if r["status"] == "pob_refused" and "unknown node id" in str(r.get("reason") or "")]
    if refused and len(unknown) == len(refused):
        ids = sorted({m for r in unknown for m in re.findall(r"\[(\d+)\]", str(r["reason"]))})
        return f"node {', '.join(ids)} unknown to PoB's tree"
    return None


# -- the keystone part ---------------------------------------------------------------------------------------


def corpus_ids(path: Path = KEYSTONE_CORPUS) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    return {str(r["name"]): int(r["node_id"]) for r in records or [] if isinstance(r, Mapping) and r.get("is_keystone")}


def keystone_rows(
    parse: Sequence[Mapping[str, Any]],
    flips: Mapping[str, Mapping[str, Any]],
    rails: Mapping[str, Any],
    node_ids: Mapping[str, int],
) -> tuple[list[Row], list[Excluded]]:
    """Candidates (a zero / redirect line) and the excluded keystones (only add / unparsed lines), in name order."""

    index = build_flip_index(flips)
    forbidden = list((rails.get("tree") or {}).get("forbidden_text") or [])
    rows: list[Row] = []
    excluded: list[Excluded] = []
    for entry in sorted(parse, key=lambda e: e["keystone"]):
        name = entry["keystone"]
        cite = f"keystones.json node_id {node_ids[name]}" if name in node_ids else "keystones.json: no record"
        cand = [line for line in entry["lines"] if line["kind"] in ("zero", "redirect")]
        if not cand:
            kinds = set(entry["kinds"])
            reason = "only add / unparsed lines" if "add" in kinds else "no line parsed (unparsed only)"
            excluded.append(Excluded(name, "keystone", ", ".join(entry["kinds"]), "add" if "add" in kinds else "unparsed", cite))
            continue
        floors, _flips = measured_floors(name, index)
        if floors:
            source, mods = "measured in the flips", ()
        else:
            floors, mods = mod_floors(cand)
            source = "from the parsed mods, no flip collapsed a pool" if floors else "none (no flip collapsed one, no mod names a pool)"
        stats = [line["text"] for line in entry["lines"]]
        why = not_in_pool_reason(name, stats, index, forbidden)
        rows.append(
            Row(
                choice=name,
                kind="keystone",
                lines=tuple(line["text"] for line in cand),
                parse_kind=", ".join(k for k in ("zero", "redirect") if any(line["kind"] == k for line in cand)),
                floors=floors,
                in_pool="yes" if why is None else f"no: {why}",
                flip=flip_cell(name, index, source, mods),
                corpus=cite,
            )
        )
    return rows, excluded


# -- unit 2: the corpora ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Corpora:
    """The tracked corpora unit 2 reads: unique records, notable stat lines by node id, and the `per:` scaling vectors."""

    uniques: tuple[Mapping[str, Any], ...]
    notable_stats: Mapping[int, tuple[str, ...]]
    vectors: Mapping[str, Mapping[str, Any]]


def load_corpora(
    uniques_path: Path = UNIQUES_CORPUS, passives_path: Path = PASSIVES_CORPUS, vectors_path: Path = VECTORS_CORPUS
) -> Corpora:
    uniques = json.loads(uniques_path.read_text(encoding="utf-8"))["records"]
    passives = json.loads(passives_path.read_text(encoding="utf-8"))["records"]
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))["vectors"]
    notables = {int(r["node_id"]): tuple(str(x) for x in r.get("stats") or []) for r in passives if r.get("is_notable")}
    return Corpora(tuple(uniques), notables, vectors)


def pool_rails(rails: Mapping[str, Any]) -> Rails:
    """The day-1 unique pool rule of the rails file, as the optimizer's own `Rails.unique_allowed` reads it."""

    block = rails.get("uniques") or {}
    fields: dict[str, Any] = {}
    if "allowed_availability" in block:
        fields["unique_availability"] = tuple(block["allowed_availability"])
    if "max_req_level" in block:
        fields["unique_max_req_level"] = int(block["max_req_level"])
    if "allowed_tiers" in block:
        fields["unique_allowed_tiers"] = tuple(int(t) for t in block["allowed_tiers"])
    return Rails(**fields)


def unique_pool_reason(record: Mapping[str, Any], pool: Rails) -> str | None:
    """None when the unique passes the rails' pool rule, else why not (every failing part)."""

    if pool.unique_allowed(record):
        return None
    why: list[str] = []
    if record.get("availability", "core") not in pool.unique_availability:
        why.append(f"availability {record.get('availability')}")
    if int(record.get("req_level") or 0) > pool.unique_max_req_level:
        why.append(f"req_level {record.get('req_level')} > {pool.unique_max_req_level}")
    tier = record.get("tier")
    if tier is not None and int(tier) not in pool.unique_allowed_tiers:
        why.append(f"tier {tier}")
    return ", ".join(why)


# -- unit 2: stacking directions ---------------------------------------------------------------------------------

ATTRIBUTES = (("Dex", "Dexterity"), ("Int", "Intelligence"), ("Str", "Strength"))
DAMAGE_STAT_RE = re.compile(r"Damage|^(?:Physical|Fire|Cold|Lightning|Chaos)(?:Min|Max)$")
DEFENCE_STAT_RE = re.compile(
    r"^(?:Life|EnergyShield|Armour|Evasion|Ward|BlockChance|SpellBlockChance|LifeRegenPercent|ElementalResist|(?:Fire|Cold|Lightning|Chaos)Resist)$"
)
STACKING_FAMILIES = ("notable", "unique", "mastery", "ascendancy")
NODE_CORPUS = {"notable": "passives.json", "mastery": "masteries.json", "ascendancy": "ascendancies.json"}  # file of a node id


def scale_kind(stat: str) -> str:
    """damage / defence / other, from the parsed stat NAME of the mod (a unit-2 rule, `DAMAGE_STAT_RE` / `DEFENCE_STAT_RE`)."""

    if DAMAGE_STAT_RE.search(stat):
        return "damage"
    if DEFENCE_STAT_RE.match(stat):
        return "defence"
    return "other"


def _forbidden(lines: Sequence[str], forbidden: Sequence[str]) -> bool:
    regs = [re.compile(p, re.IGNORECASE) for p in forbidden]
    return bool(regs and lines and all(any(r.search(x) for r in regs) for x in lines))


def stacking_rows(corpora: Corpora, rails: Mapping[str, Any]) -> tuple[list[Row], list[Excluded]]:
    """One row per attribute direction with >= 1 unique / notable line that scales damage or defence per point of it."""

    pool = pool_rails(rails)
    forbidden = list((rails.get("tree") or {}).get("forbidden_text") or [])
    by_key = {str(r["key"]): r for r in corpora.uniques}
    rows: list[Row] = []
    excluded: list[Excluded] = []
    for attr, word in ATTRIBUTES:
        vector = f"per:{attr}"
        vector_cite = f"{VECTORS_CORPUS.name} {vector}"
        seen: set[tuple[str, str, str]] = set()
        found: list[tuple[int, str, str, str, str, str, str]] = []  # family order, name, line, scale, pool flag, corpus entry, family
        for payoff in (corpora.vectors.get(vector) or {}).get("payoffs") or []:
            ident = (str(payoff["source"]), str(payoff["line"]), str(payoff["stat"]))
            if ident in seen:
                continue
            seen.add(ident)
            family, name, line, stat = str(payoff["family"]), str(payoff["name"]), str(payoff["line"]), str(payoff["stat"])
            source_id = str(payoff["source"])
            ttype = str((payoff.get("tag") or {}).get("type"))
            if family not in STACKING_FAMILIES:
                excluded.append(Excluded(f"{attr}: {name}", "stacking", ttype, f"family {family}, not a unique, notable, mastery or ascendancy", vector_cite))
                continue
            if ttype != "PerStat":
                excluded.append(Excluded(f"{attr}: {name}", "stacking", ttype, f"{ttype}: a threshold, not per point", vector_cite))
                continue
            scale = scale_kind(stat)
            if scale == "other":
                excluded.append(Excluded(f"{attr}: {name}", "stacking", ttype, "stat is neither damage nor defence", vector_cite))
                continue
            if family == "unique":
                key = source_id.split(":", 1)[1]
                record = by_key.get(key)
                why = unique_pool_reason(record, pool) if record is not None else "no record in uniques.json"
                corpus = f"uniques.json key {key}"
            else:
                # source ids: notable:<node>, mastery:<node>:<effect>, ascendancy:<class>:<node>
                node_id = int(source_id.split(":")[2] if family == "ascendancy" else source_id.split(":")[1])
                stats = corpora.notable_stats.get(node_id, ()) if family == "notable" else (line,)
                why = "the rails' tree.forbidden_text forbids every line" if _forbidden(stats, forbidden) else None
                corpus = f"{NODE_CORPUS[family]} node_id {node_id}"
            found.append((STACKING_FAMILIES.index(family), name, line, scale, "yes" if why is None else f"no: {why}", corpus, family))
        if not found:
            continue
        found.sort(key=lambda f: (f[0], f[1], f[2]))
        lines = tuple(
            f"{name} ({family}, {scale}){'' if flag == 'yes' else ' [not in pool: ' + flag[4:] + ']'}: {line}"
            for _order, name, line, scale, flag, _corpus, family in found
        )
        rows.append(
            Row(
                choice=f"{attr} stacking ({word})",
                kind="stacking",
                lines=lines,
                parse_kind="PerStat: " + ", ".join(sorted({f[3] for f in found})),
                floors=(),
                in_pool="yes" if any(f[4] == "yes" for f in found) else "no: every source is outside the day-1 pool",
                flip="-",
                corpus="<br>".join(f[5] for f in found),
            )
        )
    return rows, excluded


# -- unit 2: uniques ------------------------------------------------------------------------------------------------

EXTRA_FLOORS = ("ChaosResist",)  # a floor a unique's OVERRIDE can name; the keystone floors are FLOOR_STATS
RESOURCE_DEFENCE_RE = re.compile(r"Life|Mana|EnergyShield|Ward|Armour|Evasion|Evade|Resist|Block|Suppress|PhysicalDamageReduction|Reserved|Reservation|Dodge")
RESIST_OVERRIDES = {"FireResist", "ColdResist", "LightningResist", "ChaosResist"}
RESERVE_RE = re.compile(r"^Extra(Life|Mana)Reserved$")
POOL_MOVE_RE = re.compile(r"^(?:Convert\w*To|(?:EnergyShield|Life|Mana)To)(?:Life|Mana|EnergyShield|Ward)")
POOL_MOVE_SOURCE_RE = re.compile(r"EnergyShield|ES|Life|Mana")
POOL_MOVE_TARGET_RE = re.compile(r"To(?:Life|Mana|EnergyShield|Ward)$")
BLOOD_MAGIC_RULE = "unique rule: Blood Magic support, floor from the Blood Magic keystone row"
STUN_RE = re.compile(r"^StunThreshold")
STUN_REASON = "redirect without a floor stat (stun threshold)"


def pool_move_floor(name: str) -> str | None:
    """The floor a pool move leaves: the source pool, the part of the name before `To<Pool>` (ConvertArmourESToLife -> ES)."""

    match = POOL_MOVE_SOURCE_RE.search(POOL_MOVE_TARGET_RE.sub("", name))
    if not match:
        return None
    return POOL_FLOOR["EnergyShield" if match.group(0) == "ES" else match.group(0)]


def unique_mod_effect(mod: Mapping[str, Any]) -> tuple[str, str | None, str] | None:
    """(kind, floor or None, rule) of one parsed unique mod when it redirects or zeroes a resource or a defence, else None."""

    name = str(mod.get("name") or "")
    mod_type = str(mod.get("type") or "")
    value = mod.get("value")
    if name.startswith("Multiplier:"):
        return None
    if name == "ExtraSupport" and isinstance(value, Mapping) and "BloodMagic" in str(value.get("skillId") or ""):
        return "redirect", None, BLOOD_MAGIC_RULE
    reserve = RESERVE_RE.match(name)
    if reserve and mod_type == "BASE":
        return "redirect", POOL_FLOOR[reserve.group(1)], "unique rule: reserves a pool"
    if not RESOURCE_DEFENCE_RE.search(name):
        return None
    kind = classify_line({"line": str(mod.get("line") or ""), "ok": True, "unsupported": False, "extra": "", "mods": [dict(mod)]})
    if kind == "add":
        if POOL_MOVE_RE.match(name):
            return "redirect", pool_move_floor(name), "unique rule: pool move"
        return None
    if kind not in ("zero", "redirect"):
        return None
    if mod_type == "OVERRIDE":
        if _is_number(value) and value == 0:
            return "zero", (name if name in RESIST_OVERRIDES else None), "parse kind, OVERRIDE to 0"
        return None
    return kind, mod_floor(kind, mod), "parse kind"


def order_floors(found: set[str]) -> tuple[str, ...]:
    return tuple(s for s in (*FLOOR_STATS, *EXTRA_FLOORS) if s in found)


def blood_magic_keystone_floors(k_rows: Sequence[Row]) -> tuple[str, ...]:
    """The floors of the Blood Magic keystone row, read from the keystone rows at generation time (#1065 rule 2)."""

    for row in k_rows:
        if row.kind == "keystone" and row.choice == "Blood Magic":
            return row.floors
    raise ValueError("no Blood Magic keystone row: a Blood Magic support unique cannot take its floor")


def unique_rows(
    corpora: Corpora, rails: Mapping[str, Any], blood_magic_floors: Sequence[str] | None = None
) -> tuple[list[Row], list[Excluded]]:
    """Candidates: a unique with a zero / redirect mod on a resource or a defence. Excluded: a unique whose zero /
    redirect lines are all about something else (an ailment, a curse, a socket count ...); counted, not listed.
    `blood_magic_floors` is the floor of the Blood Magic keystone row (`blood_magic_keystone_floors`); a Blood Magic
    support unique takes it. A `StunThreshold*` line is excluded with `STUN_REASON` (#1065 rule 3)."""

    pool = pool_rails(rails)
    rows: list[Row] = []
    excluded: list[Excluded] = []
    for record in sorted(corpora.uniques, key=lambda r: (str(r["name"]), str(r["key"]))):
        by_line: dict[str, list[Mapping[str, Any]]] = {}
        for mod in record.get("mods") or []:
            by_line.setdefault(str(mod.get("line")), []).append(mod)
        cite = f"uniques.json key {record['key']}"
        hits: list[tuple[str, str, tuple[str, ...], str, Mapping[str, Any]]] = []  # line, kind, floors, rule, mod
        zero_or_redirect_elsewhere = False
        stun = False
        for line in dict.fromkeys(str(x) for x in record.get("lines") or []):
            mods = by_line.get(line, [])
            for mod in mods:
                if STUN_RE.match(str(mod.get("name") or "")):
                    stun = True
                    continue
                effect = unique_mod_effect(mod)
                if effect is None:
                    continue
                kind, floor, rule = effect
                if rule == BLOOD_MAGIC_RULE:
                    if blood_magic_floors is None:
                        raise ValueError(f"{record['key']}: a Blood Magic support unique needs the Blood Magic keystone floors")
                    floors = tuple(blood_magic_floors)
                else:
                    floors = (floor,) if floor else ()
                hits.append((line, kind, floors, rule, mod))
            parsed = {"line": line, "ok": True, "unsupported": False, "extra": "", "mods": [dict(m) for m in mods]}
            if mods and classify_line(parsed) in ("zero", "redirect"):
                zero_or_redirect_elsewhere = True
        if stun:
            excluded.append(Excluded(str(record["name"]), "unique", "add (StunThreshold*)", STUN_REASON, cite))
        if not hits:
            if zero_or_redirect_elsewhere:
                excluded.append(Excluded(str(record["name"]), "unique", "zero / redirect", "zero / redirect line on no resource or defence", cite))
            continue
        why = unique_pool_reason(record, pool)
        mod_text = "; ".join(dict.fromkeys(f"{m['name']} {m['type']} {m.get('value')} ({rule})" for _l, _k, _f, rule, m in hits))
        rows.append(
            Row(
                choice=str(record["name"]),
                kind="unique",
                lines=tuple(dict.fromkeys(line for line, *_rest in hits)),
                parse_kind=", ".join(k for k in ("zero", "redirect") if any(h[1] == k for h in hits)),
                floors=order_floors({f for _l, _k, fs, _r, _m in hits for f in fs}),
                in_pool="yes" if why is None else f"no: {why}",
                flip=f"not flipped; parsed mods: {mod_text}",
                corpus=cite,
            )
        )
    return rows, excluded


# -- the document ------------------------------------------------------------------------------------------------


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _table_row(cells: Sequence[str]) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def row_cells(row: Row) -> list[str]:
    return [
        row.choice,
        row.kind,
        "<br>".join(row.lines),
        row.parse_kind,
        ", ".join(row.floors) if row.floors else NO_FLOOR,
        row.in_pool,
        row.flip,
        row.corpus,
    ]


def header_line(rows: Sequence[Row], excluded: Sequence[Excluded]) -> str:
    """Counts per kind and per collapsed floor, one line."""

    per_kind = []
    for kind in KINDS:
        mine = [r for r in rows if r.kind == kind]
        out = [e for e in excluded if e.kind == kind]
        in_pool = sum(1 for r in mine if r.in_pool == "yes")
        per_kind.append(f"{kind} {len(mine)} candidates ({in_pool} in the day-1 pool, {len(mine) - in_pool} not), {len(out)} excluded")
    floors = Counter(f for r in rows if r.kind != "stacking" for f in (r.floors or (NO_FLOOR,)))
    order = [*FLOOR_STATS, *EXTRA_FLOORS, NO_FLOOR]
    per_floor = ", ".join(f"{f} {floors[f]}" for f in order if floors.get(f))
    return "counts: " + "; ".join(per_kind) + ". Per collapsed floor, keystone and unique rows (a row with two floors counts in both; stacking rows have no floor): " + per_floor


def excluded_counts(excluded: Sequence[Excluded]) -> str:
    per = Counter((e.kind, e.reason) for e in excluded)
    return ", ".join(f"{kind} / {reason}: {n}" for (kind, reason), n in sorted(per.items())) or "none"


def render(
    parse: Sequence[Mapping[str, Any]],
    flips: Mapping[str, Mapping[str, Any]],
    rails: Mapping[str, Any],
    node_ids: Mapping[str, int],
    corpora: Corpora | None = None,
) -> str:
    k_rows, k_excluded = keystone_rows(parse, flips, rails, node_ids)
    corpora = corpora or load_corpora()
    s_rows, s_excluded = stacking_rows(corpora, rails)
    u_rows, u_excluded = unique_rows(corpora, rails, blood_magic_keystone_floors(k_rows))
    rows = [*k_rows, *s_rows, *u_rows]
    excluded = [*k_excluded, *s_excluded, *u_excluded]
    life_floor = rails["floors"]["Life"]
    out: list[str] = [
        "# Day-1 reshaping inventory (#1042)",
        "",
        f"- date: {REPORT_DATE}",
        "- parent: map #1040; this table: #1042 (keystones, stacking, uniques)",
        "- regenerated by `python scripts/reshaping_inventory.py` (a pure function of the files below)",
        "- parse JSON (#1030): `artifacts/keystone_flip/parse.json`; flips: " + ", ".join(f"`artifacts/keystone_flip/{b}.json`" for b in BUILDS),
        f"- rails: `src/junkroan/optimizer/rails_default.json` (floors.Life {life_floor:,}; tree.forbidden_text; `uniques` = the day-1 unique pool)",
        "- corpus: `src/junkroan/pob/corpus_data/keystones.json` (every keystone record: node_id, name, stats)",
        "",
        "## Counts",
        "",
        header_line(rows, excluded),
        "",
        f"Excluded (no zero / redirect line): {excluded_counts(excluded)}.",
        "",
        "## Columns",
        "",
        "- `parsed mod lines`: the stat lines PoB parsed as zero or redirect, as it receives them (`junkroan.keystone_parse`).",
        "- `parse kind`: the kinds of those lines.",
        "- `floor it collapses`: the floor stats (Life, ManaUnreserved, Mana, EnergyShield, FireResist, ColdResist, LightningResist) that fell below half or went missing when the keystone was allocated, in at least one of the three #1030 flips; where none did, the pool the parsed mods name; `none` = neither. The flip cell says which.",
        "- `in day-1 pool`: yes unless the rails forbid every line of it or PoB's tree does not know its node.",
        "- `#1030 flip row`: per build the flip status, the CombinedDPS change and the floors that flip collapsed.",
        "",
        "## Keystones: candidates (a zero or redirect line)",
        "",
        _table_row(COLUMNS),
        _table_row(["---"] * len(COLUMNS)),
        *[_table_row(row_cells(r)) for r in k_rows],
        "",
        "## Keystones: excluded (only add or unparsed lines)",
        "",
        _table_row(("choice", "kind", "parse kinds", "excluded as", "corpus entry")),
        _table_row(["---"] * 5),
        *[_table_row((e.choice, e.kind, e.parse_kinds, e.reason, e.corpus)) for e in k_excluded],
        "",
        "## Stacking directions (Dex, Int, Str)",
        "",
        "One row per direction; each line is a unique or notable mod of `scaling_vectors.json` (`per:<Attr>`, PerStat tag) that scales damage or defence, with its corpus entry at the same position.",
        "",
        _table_row(COLUMNS),
        _table_row(["---"] * len(COLUMNS)),
        *[_table_row(row_cells(r)) for r in s_rows],
        "",
        "## Uniques (parsed zero or redirect mod on a resource or a defence)",
        "",
        "All uniques of `uniques.json`, in the day-1 pool or flagged `no: ...`. Floors are read from the parsed mod (no flip of a unique was run).",
        "",
        _table_row(COLUMNS),
        _table_row(["---"] * len(COLUMNS)),
        *[_table_row(row_cells(r)) for r in u_rows],
        "",
    ]
    return "\n".join(out)


def load_inputs(artifacts: Path = ARTIFACTS_DIR) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any], dict[str, int]]:
    parse = json.loads((artifacts / "parse.json").read_text(encoding="utf-8"))
    flips = {b: json.loads((artifacts / f"{b}.json").read_text(encoding="utf-8")) for b in BUILDS}
    rails = json.loads(RAILS_PATH.read_text(encoding="utf-8"))
    return parse, flips, rails, corpus_ids()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the day-1 reshaping inventory table.")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--artifacts", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args(argv)
    parse, flips, rails, node_ids = load_inputs(args.artifacts)
    text = render(parse, flips, rails, node_ids)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(header_line(*_counts_for_print(parse, flips, rails, node_ids)))
    return 0


def _counts_for_print(parse, flips, rails, node_ids):  # noqa: ANN001
    k_rows, k_excluded = keystone_rows(parse, flips, rails, node_ids)
    corpora = load_corpora()
    s_rows, s_ex = stacking_rows(corpora, rails)
    u_rows, u_ex = unique_rows(corpora, rails, blood_magic_keystone_floors(k_rows))
    return [*k_rows, *s_rows, *u_rows], [*k_excluded, *s_ex, *u_ex]


if __name__ == "__main__":
    raise SystemExit(main())
