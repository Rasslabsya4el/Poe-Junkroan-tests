"""Facts about active skills read straight from the pinned PoB skill data
(`vendor/pob/source/src/Data/Skills/*.lua`): cooldown and base buff duration.

PoB applies a skill's self-buff whenever the gem is in the build, with no
uptime: Ambush (cooldown 5 s, buff 1.5 s, consumed by the next melee attack)
counted as 100% critical strike chance all the time and tripled a Smite build.
The utility picker uses `buff_uptime` to leave such gems alone (D46).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOCK = PROJECT_ROOT / "locks" / "pob.lock.json"


def _runtime_skill_dir() -> Path | None:
    """The pinned runtime's own copy of the skill data (`var/cache/pob/<tag>/app/Data/Skills`):
    the same files as the vendored source at the pinned tag, and the only copy a checkout that
    never cloned `vendor/pob/source` (it is gitignored) has."""

    try:
        lock = json.loads(_LOCK.read_text(encoding="utf-8"))
        return PROJECT_ROOT / "var" / "cache" / "pob" / str(lock["tag"]) / str(lock["extract_subdir"]) / "Data" / "Skills"
    except Exception:
        return None


SKILL_DATA_DIRS = tuple(d for d in (PROJECT_ROOT / "vendor" / "pob" / "source" / "src" / "Data" / "Skills", _runtime_skill_dir()) if d is not None)
_BLOCK = re.compile(r'^skills\["(?P<id>[^"]+)"\]\s*=\s*\{', re.M)


@lru_cache(maxsize=1)
def _blocks() -> dict[str, str]:
    out: dict[str, str] = {}
    for d in SKILL_DATA_DIRS:
        if not d.is_dir():
            continue
        for path in sorted(d.glob("*.lua")):
            text = path.read_text(encoding="utf-8", errors="replace")
            starts = list(_BLOCK.finditer(text))
            for i, m in enumerate(starts):
                end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
                out.setdefault(m.group("id"), text[m.start():end])
    return out


def cooldown_seconds(granted_effect_id: str) -> float | None:
    """The skill's own cooldown at level 1 (PoB `levels[1].cooldown`), None if it has none."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    m = re.search(r"\[1\]\s*=\s*\{[^}]*?\bcooldown\s*=\s*([0-9.]+)", block, re.S)
    return float(m.group(1)) if m else None


def buff_duration_seconds(granted_effect_id: str) -> float | None:
    """Base skill effect duration (`base_skill_effect_duration`, ms), None if the skill has none."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    m = re.search(r'\{\s*"base_skill_effect_duration",\s*([0-9.]+)\s*\}', block)
    return float(m.group(1)) / 1000.0 if m else None


@lru_cache(maxsize=1)
def _limit_keys() -> dict[str, str]:
    """PoB stat keys that set a minion limit -> the limit stat (`Data/SkillStatMap.lua`:
    base_number_of_zombies_allowed -> ActiveZombieLimit)."""

    out: dict[str, str] = {}
    for d in SKILL_DATA_DIRS:
        path = d.parent / "SkillStatMap.lua"
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'\["([a-z0-9_]+)"\]\s*=\s*\{\s*mod\("(Active\w+Limit)"', text):
                out.setdefault(m.group(1), m.group(2))
    return out


def minion_limit_stat(granted_effect_id: str) -> str | None:
    """The PoB stat holding how many of this skill's minions can be active
    (Raise Zombie -> ActiveZombieLimit, Absolution -> ActiveSentinelOfAbsolutionLimit),
    None for skills that summon nothing."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    for key, stat in _limit_keys().items():
        if f'"{key}"' in block:
            return stat
    return None


def is_duration_minion(granted_effect_id: str) -> bool:
    """A minion that expires: the block carries `duration = true`, a `base_skill_effect_duration`
    and a minion limit stat (Summon Raging Spirit: 5000 ms, 20 allowed). Zombies and spectres carry
    `infinite_minion_duration` and stand until they die, so they are not duration minions however
    their block flags duration; a block with no base duration (Searing Bond) is not one either,
    because there is nothing to multiply the cast rate by."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return False
    if not re.search(r"^\s*duration\s*=\s*true,", block, re.M):
        return False
    if "infinite_minion_duration" in block or buff_duration_seconds(granted_effect_id) is None:
        return False
    return minion_limit_stat(granted_effect_id) is not None


def is_cast_copy_duration_minion(granted_effect_id: str) -> bool:
    """A duration minion whose copy is made by the cast itself and lives on the skill's own `Duration` (#967 check C:
    `count x Time / Duration` is then the share of time spent recasting). PoB's datum for the other kind: the block
    carries `base_secondary_skill_effect_duration`, the copy's own life, apart from `base_skill_effect_duration`
    (Absolution: `Duration` is the 3 s debuff, a Sentinel is summoned when an enemy dies under it and lives 15 s;
    act_str.lua:42-45, minion.lua:1189). Summon Raging Spirit has `base_skill_effect_duration` 5000 ms alone
    (act_int.lua:19370). PoB has no structured flag for a copy made by a kill or a hit without a secondary
    duration (Herald of Purity, Holy Strike: their text only), so those are not told apart here."""

    block = _blocks().get(granted_effect_id)
    return bool(block) and is_duration_minion(granted_effect_id) and "base_secondary_skill_effect_duration" not in block


_SUMMON_COUNT_STAT = re.compile(r"[a-z0-9_]*number_of_[a-z0-9_]*_to_summon")


def _level_stat_list(block: str) -> list[str]:
    """The positional stat list the level table's rows are written in: the last
    `stats = { ... }` before `levels = {` (PoB writes one `stats` list per skill block)."""

    levels_at = block.find("levels = {")
    out: list[str] = []
    for m in re.finditer(r"^\s*stats\s*=\s*\{(?P<body>[^{}]*)\}", block, re.M | re.S):
        if levels_at >= 0 and m.start() > levels_at:
            break
        # every entry, whatever characters the stat name carries: the row values are positional,
        # so dropping a name (`..._damage_taken_+%`) shifts every stat after it
        out = re.findall(r'"([^"]+)"', m.group("body"))
    return out


def _level_row_values(block: str, level: int) -> list[float]:
    """The positional values of `levels[level]`: everything before the first named key
    (`[18] = { 3, 7, 66, levelRequirement = 66, ... }` -> [3, 7, 66])."""

    levels_at = block.find("levels = {")
    if levels_at < 0:
        return []
    m = re.search(r"^\s*\[%d\]\s*=\s*\{(?P<body>.*)$" % level, block[levels_at:], re.M)
    if not m:
        return []
    out: list[float] = []
    for part in m.group("body").split(","):
        part = part.strip()
        if not part or "=" in part:
            break
        try:
            out.append(float(part))
        except ValueError:
            break
    return out


def minions_per_cast(granted_effect_id: str) -> int:
    """Minions one cast summons: 1 unless the block names a `number_of_..._to_summon` stat
    (Summon Skeletons: `number_of_melee_skeletons_to_summon`), whose value is either a constant
    in the block or the level table's entry at that stat's position (row 18, the rails' gem level)."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return 1
    const = re.search(r'\{\s*"[a-z0-9_]*number_of_[a-z0-9_]*_to_summon",\s*([0-9]+)\s*\}', block)
    if const:
        return max(1, int(const.group(1)))
    stats = _level_stat_list(block)
    idx = next((i for i, s in enumerate(stats) if _SUMMON_COUNT_STAT.fullmatch(s)), None)
    if idx is None:
        return 1
    values = _level_row_values(block, 18) or _level_row_values(block, 20)
    if not values:
        for level in range(40, 0, -1):
            values = _level_row_values(block, level)
            if values:
                break
    if idx >= len(values):
        return 1
    return max(1, int(values[idx]))


def brand_attach_base(granted_effect_id: str) -> int | None:
    """Brands this skill attaches to one enemy by its own stats (`base_number_of_sigils_allowed_per_target`,
    the base PoB caps BrandsAttachedToEnemy by), None for a skill that is not a brand."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    m = re.search(r'\{\s*"base_number_of_sigils_allowed_per_target",\s*([0-9]+)\s*\}', block)
    return int(m.group(1)) if m else None


@lru_cache(maxsize=1)
def _brand_skills() -> tuple[frozenset[str], frozenset[str]]:
    ids: set[str] = set()
    names: set[str] = set()
    for gid in _blocks():
        if brand_attach_base(gid) is None:
            continue
        ids.add(gid)
        m = re.search(r'^\s*name = "([^"]*)"', _blocks()[gid], re.M)
        if m:
            names.add(m.group(1).lower())
    return frozenset(ids), frozenset(names)


def brand_skill_ids() -> frozenset[str]:
    """Every granted effect id of a Brand-type skill (all ten carry `base_number_of_sigils_allowed_per_target`,
    Arcanist Brand `BrandSupport` and the quality variants `PenanceBrandAltX` included); empty without skill data."""

    return _brand_skills()[0]


def brand_skill_names() -> frozenset[str]:
    """The lower-cased gem names of `brand_skill_ids` (a PoB gem's `nameSpec`)."""

    return _brand_skills()[1]


def corpses_consumed_per_cast(granted_effect_id: str) -> int | None:
    """Corpses one cast of this skill consumes (`*number_of_corpses_to_consume`: Volatile Dead 3),
    None for a skill that eats no corpse. PoB fires one instance of the skill per corpse consumed."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    m = re.search(r'\{\s*"[A-Za-z0-9_]*number_of_corpses_to_consume",\s*([0-9]+)\s*\}', block)
    return int(m.group(1)) if m else None


def corpses_created_per_cast(granted_effect_id: str) -> tuple[int, int | None] | None:
    """(corpses one cast creates, the cap on them) for a corpse creator, None for anything else:
    Desecrate (`desecrate_number_of_corpses_to_create` 5, `desecrate_maximum_number_of_corpses` 10),
    Unearth (a `corpseMonsterVariety` skill with no create count: one corpse per cast, and the same
    `desecrate_maximum_number_of_corpses` cap its block carries, 10)."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    m = re.search(r'\{\s*"desecrate_number_of_corpses_to_create",\s*([0-9]+)\s*\}', block)
    cap = re.search(r'\{\s*"desecrate_maximum_number_of_corpses",\s*([0-9]+)\s*\}', block)
    if m:
        return int(m.group(1)), (int(cap.group(1)) if cap else None)
    if "corpseMonsterVariety" in block:
        return 1, (int(cap.group(1)) if cap else None)
    return None


def cascade_areas(granted_effect_id: str) -> int:
    """Areas the supported skill hits per cast: Spell Cascade's
    `support_spell_cascade_number_of_cascades_per_side` K is K areas on each side plus the
    original one, so 1 + 2K (K = 1 -> 3). Any other gem leaves the skill at its own single area."""

    block = _blocks().get(granted_effect_id) if granted_effect_id else None
    if not block:
        return 1
    m = re.search(r'\{\s*"support_spell_cascade_number_of_cascades_per_side",\s*([0-9]+)\s*\}', block)
    return 1 + 2 * int(m.group(1)) if m else 1


def cast_time_seconds(granted_effect_id: str) -> float | None:
    """The skill's own base cast time (PoB `castTime`; Wither 0.28, one Withered stack per pulse),
    None when the block has none."""

    block = _blocks().get(granted_effect_id)
    m = re.search(r"^\s*castTime\s*=\s*([0-9.]+)\s*,", block, re.M) if block else None
    return float(m.group(1)) if m else None


def part_names(granted_effect_id: str) -> tuple[str, ...]:
    """The skill's PoB parts in order (Elemental Hit: "Fire Attack", "Fire AoE", "Cold Attack", ...;
    Wild Strike: "Fire hit", "Fire explosion", ...), () when the skill has one part."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return ()
    section = re.search(r"^\tparts\s*=\s*\{(?P<body>.*?)^\t\},", block, re.M | re.S)
    if not section:
        return ()
    return tuple(re.findall(r'name\s*=\s*"([^"]+)"', section.group("body")))


def constant_stat(granted_effect_id: str, stat: str) -> float | None:
    """A value from the skill's `constantStats` (Perforate: `blood_spears_base_number_of_spears` 7,
    Sigil of Power: `circle_of_power_max_stages` 4), None when the skill has no such stat."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    section = re.search(r"^\s*constantStats\s*=\s*\{(?P<body>.*?)^\s*\},", block, re.M | re.S)
    if not section:  # `qualityStats` writes the same {name, value} pairs: only the constants count
        return None
    m = re.search(r'\{\s*"%s",\s*(-?[0-9.]+)\s*\}' % re.escape(stat), section.group("body"))
    return float(m.group(1)) if m else None


def constant_stats_matching(granted_effect_id: str, pattern: str) -> tuple[tuple[str, float], ...]:
    """Every constant stat whose id matches ``pattern``, from PoB's skill data."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return ()
    section = re.search(r"^\s*constantStats\s*=\s*\{(?P<body>.*?)^\s*\},", block, re.M | re.S)
    if not section:
        return ()
    matcher = re.compile(pattern)
    return tuple(
        (stat, float(value))
        for stat, value in re.findall(r'\{\s*"([A-Za-z0-9_%+\-]+)",\s*(-?[0-9.]+)\s*\}', section.group("body"))
        if matcher.search(stat)
    )


def level_stat(granted_effect_id: str, stat: str, level: int) -> float | None:
    """The value of a named stat at a gem level, read off the level table's positional row
    (Pride 18: `physical_damage_aura_nearby_enemies_physical_damage_taken_+%` 19 and its `_max` 38;
    Sigil of Power 18: `base_circle_of_power_mana_spend_per_upgrade` 379). A constant stat of the
    same name answers first. None when the skill, the stat or the level is not in PoB's data."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    const = constant_stat(granted_effect_id, stat)
    if const is not None:
        return const
    stats = _level_stat_list(block)
    if stat not in stats:
        return None
    values = _level_row_values(block, level)
    idx = stats.index(stat)
    return values[idx] if idx < len(values) else None


@lru_cache(maxsize=1)
def _game_constants() -> dict[str, float]:
    """PoB's `data.gameConstants` (Data/Misc.lua): the two damage-effectiveness constants every
    damage-scaled gem stat is interpolated with."""

    out: dict[str, float] = {}
    for d in SKILL_DATA_DIRS:
        path = d.parent / "Misc.lua"
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r'\["(\w+)"\]\s*=\s*(-?[0-9.]+)\s*,', text):
                out.setdefault(m.group(1), float(m.group(2)))
    return out


def _level_row_keys(block: str, level: int) -> dict[str, str]:
    """The named keys of `levels[level]` (`levelRequirement = 70`, `statInterpolation = { 3, 1 }`)."""

    levels_at = block.find("levels = {")
    if levels_at < 0:
        return {}
    m = re.search(r"^\s*\[%d\]\s*=\s*\{(?P<body>.*)$" % level, block[levels_at:], re.M)
    if not m:
        return {}
    body = m.group("body")
    out = {k: v for k, v in re.findall(r"(\w+)\s*=\s*([0-9.]+)\s*,", body)}
    si = re.search(r"statInterpolation\s*=\s*\{([^}]*)\}", body)
    if si:
        out["statInterpolation"] = si.group(1)
    return out


def effectiveness_stat(granted_effect_id: str, stat: str, level: int) -> float | None:
    """A gem stat PoB writes as a *damage effectiveness* multiplier rather than a flat number
    (`statInterpolation = 3`), resolved with PoB's own arithmetic (CalcTools.lua):

        availableEffectiveness = (SkillDamageBaseEffectiveness + SkillDamageIncrementalEffectiveness
                                  x (actorLevel - 1)) x baseEffectiveness
                                 x (1 + incrementalEffectiveness) ^ (actorLevel - 1)
        value = round(availableEffectiveness x levels[level][index])

    with `actorLevel` the level's own requirement, which is what PoB uses for a gem nobody has
    given an actor level. Trauma Support level 20 -> 146 physical damage per stack, the number the
    research quotes. None when the skill, the stat or the level is missing, or when the stat is
    not effectiveness-interpolated at that level (then `level_stat` is the right reader)."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return None
    stats = _level_stat_list(block)
    if stat not in stats:
        return None
    idx = stats.index(stat)
    values = _level_row_values(block, level)
    if idx >= len(values):
        return None
    keys = _level_row_keys(block, level)
    interpolation = [s.strip() for s in str(keys.get("statInterpolation") or "").split(",") if s.strip()]
    if idx >= len(interpolation) or interpolation[idx] != "3":
        return None
    actor = float(keys.get("levelRequirement") or 1)
    base = re.search(r"^\s*baseEffectiveness\s*=\s*([0-9.]+)", block, re.M)
    incremental = re.search(r"^\s*incrementalEffectiveness\s*=\s*([0-9.]+)", block, re.M)
    constants = _game_constants()
    c0, c1 = constants.get("SkillDamageBaseEffectiveness"), constants.get("SkillDamageIncrementalEffectiveness")
    if c0 is None or c1 is None:
        return None
    available = (c0 + c1 * (actor - 1)) * (float(base.group(1)) if base else 1.0) * (1.0 + (float(incremental.group(1)) if incremental else 0.0)) ** (actor - 1)
    return float(round(available * values[idx]))


def buff_uptime(granted_effect_id: str) -> float | None:
    """duration / cooldown for a skill with both; None when there is no cooldown
    (aura, herald, Blood Rage: PoB's always-on is right) or no duration."""

    cd, dur = cooldown_seconds(granted_effect_id), buff_duration_seconds(granted_effect_id)
    if cd is None or cd <= 0 or dur is None:
        return None
    return min(1.0, dur / cd)


_SKILL_TYPES = re.compile(r"skillTypes\s*=\s*\{(?P<body>.*?)\}\s*,\s*\n", re.S)


def skill_types(granted_effect_id: str) -> frozenset[str]:
    """PoB's own `skillTypes` for the skill, lower-cased ("buff", "guard", "damage",
    "aura", "banner", "hasreservation" ...). What kind of thing a skill is comes from
    PoB, never from a list of gem names."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return frozenset()
    return _skill_types_from_block(block)


def _skill_types_from_block(block: str) -> frozenset[str]:
    m = _SKILL_TYPES.search(block)
    return frozenset(t.lower() for t in re.findall(r"SkillType\.(\w+)", m.group("body"))) if m else frozenset()


_RESERVATION_FIELD = re.compile(r"\b(?P<pool>mana|life)Reservation(?:Percent|Flat)\s*=\s*(?P<n>[0-9.]*[1-9][0-9.]*)\b")


def reservation_pools_from_block(block: str) -> frozenset[str]:
    """The pools a skill block reserves from, read off PoB's level data: a non-zero `manaReservationPercent/Flat` is Mana,
    a non-zero `lifeReservationPercent/Flat` is Life. A support's `skill("lifeReservationFlat", 0)` constant is no
    level field and reserves nothing."""

    return frozenset(m.group("pool").capitalize() for m in _RESERVATION_FIELD.finditer(block))


def reservation_pools(granted_effect_id: str) -> frozenset[str]:
    """`reservation_pools_from_block` of the skill's own block; empty for a skill with no block or no reservation."""

    block = _blocks().get(granted_effect_id)
    return reservation_pools_from_block(block) if block else frozenset()


def flat_reservation_aura_effect_ids(blocks: Mapping[str, str] | None = None) -> frozenset[str]:
    """The active, non-mine reservation skills whose PoB level data carries a flat mana reservation.

    ``manaReservationFlat`` is the data distinction: a player can deliberately leave one of these
    auras below the ordinary gem rail to retain enough mana.  Skill types exclude mine skills that
    happen to use the same level-data field.  ``blocks`` makes the derivation testable without a
    checked-out PoB runtime.
    """

    if blocks is None:
        return _flat_reservation_aura_effect_ids()
    return _flat_reservation_aura_effect_ids_from(blocks)


@lru_cache(maxsize=1)
def _flat_reservation_aura_effect_ids() -> frozenset[str]:
    return _flat_reservation_aura_effect_ids_from(_blocks())


def _flat_reservation_aura_effect_ids_from(blocks: Mapping[str, str]) -> frozenset[str]:
    return frozenset(
        effect_id
        for effect_id, block in blocks.items()
        if "manaReservationFlat" in block
        and "hasreservation" in (types := _skill_types_from_block(block))
        and not {"mine", "remotemined"} & types
    )


# -- the skill's own text, as PoB renders it -------------------------------------
# `build_text` carries only gem *names*, so a skill whose charge generation is part of
# the skill itself (Frenzy: "gives the character a frenzy charge if it hits") never
# reached the config proofs. The text below is PoB's: the skill's description string and
# its stats rendered through PoB's stat descriptions, at the rails' gem level, quality 0.
_STAT_DESCRIPTIONS_DIR = SKILL_DATA_DIRS[0].parent / "StatDescriptions"
_DESC_ENTRY = re.compile(r"^\t\[\d+\]=\{$", re.M)
_DESC_STATS = re.compile(r"stats=\{(?P<body>[^{}]*)\}", re.S)
_DESC_TEXT = re.compile(
    r'(?:limit=\{\s*\[1\]=\{\s*\[1\]=(?P<lo>"#"|-?\d+),\s*\[2\]=(?P<hi>"#"|-?\d+)\s*\}\s*\},\s*)?'
    r'text="(?P<text>(?:[^"\\]|\\.)*)"', re.S)
_PLACEHOLDER = re.compile(r"\{0(?::[^}]*)?\}")
_DESCRIPTION = re.compile(r'\n\tdescription = "(?P<text>(?:[^"\\]|\\.)*)"')
_CONSTANT_STATS = re.compile(r"constantStats\s*=\s*\{(?P<body>.*?)\n\t\}", re.S)


@lru_cache(maxsize=4)
def _stat_descriptions(scope: str) -> dict[str, tuple[tuple[str, str, str], ...]]:
    """stat id -> its text variants (low limit, high limit, template), for the entries
    that describe exactly one stat (a multi-stat line cannot be rendered from one value)."""

    path = _STAT_DESCRIPTIONS_DIR / f"{scope}.lua"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r", "")
    out: dict[str, tuple[tuple[str, str, str], ...]] = {}
    starts = list(_DESC_ENTRY.finditer(text))
    for i, m in enumerate(starts):
        body = text[m.end(): starts[i + 1].start() if i + 1 < len(starts) else len(text)]
        sm = _DESC_STATS.search(body)
        if not sm:
            continue
        ids = re.findall(r'\[\d+\]="([^"]+)"', sm.group("body"))
        variants = tuple((x.group("lo"), x.group("hi"), x.group("text")) for x in _DESC_TEXT.finditer(body))
        if len(ids) == 1 and variants:
            out[ids[0]] = variants
    return out


def _render_stat(scope: str, stat_id: str, value: float) -> list[str]:
    for lo, hi, template in _stat_descriptions(scope).get(stat_id, ()):
        if (lo != '"#"' and value < float(lo)) or (hi != '"#"' and value > float(hi)):
            continue
        shown = f"{value:g}"
        return [line for line in _PLACEHOLDER.sub(shown, template).replace("\\n", "\n").splitlines() if line.strip()]
    return []


@lru_cache(maxsize=1024)
def granted_effect_lines(granted_effect_id: str, *, level: int = 18) -> tuple[str, ...]:
    """Everything PoB's own data says the skill does, as text: its description sentence
    and each of its stats rendered through PoB's stat descriptions at `level` (quality 0,
    the rails' gems). Frenzy -> "...gives the character a frenzy charge if it hits.";
    Flicker Strike -> "15% chance to gain a Frenzy Charge on Hit"."""

    block = _blocks().get(granted_effect_id)
    if not block:
        return ()
    out: list[str] = []
    desc = _DESCRIPTION.search(block)
    if desc:
        out.append(desc.group("text").replace("\\n", " "))
    scope = (re.search(r'statDescriptionScope = "([^"]+)"', block) or [None, "skill_stat_descriptions"])[1]
    values: dict[str, float] = {}
    cm = _CONSTANT_STATS.search(block)
    if cm:
        for stat_id, raw in re.findall(r'\{\s*"([a-z0-9_%+\-]+)",\s*(-?[0-9.]+)\s*\}', cm.group("body")):
            values.setdefault(stat_id, float(raw))
    row = _level_row_values(block, level) or _level_row_values(block, 20)
    for stat_id, raw in zip(_level_stat_list(block), row):
        values.setdefault(stat_id, float(raw))
    for stat_id, value in values.items():
        out.extend(_render_stat(scope, stat_id, value))
    return tuple(dict.fromkeys(out))


__all__ = ["brand_attach_base", "brand_skill_ids", "brand_skill_names", "buff_duration_seconds", "buff_uptime", "cascade_areas", "cast_time_seconds",
            "constant_stat", "constant_stats_matching", "cooldown_seconds", "corpses_consumed_per_cast", "corpses_created_per_cast", "effectiveness_stat",
            "flat_reservation_aura_effect_ids", "granted_effect_lines", "is_cast_copy_duration_minion", "is_duration_minion", "level_stat", "minion_limit_stat", "minions_per_cast", "part_names",
            "skill_types"]
