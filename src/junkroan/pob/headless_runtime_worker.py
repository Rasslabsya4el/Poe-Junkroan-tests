"""Child-process worker that boots pinned PoB through the local headless wrapper."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

EXPECTED_GEAR_SLOT_ORDER: tuple[str, ...] = (
    "Weapon 1",
    "Weapon 2",
    "Helmet",
    "Body Armour",
    "Gloves",
    "Boots",
    "Amulet",
    "Ring 1",
    "Ring 2",
    "Ring 3",
    "Belt",
    "Graft 1",
    "Graft 2",
    "Flask 1",
    "Flask 2",
    "Flask 3",
    "Flask 4",
    "Flask 5",
)
EXPECTED_BOOTS_SLOT = "Boots"
EXPECTED_EXPLICIT_AFFIX = "30% increased Movement Speed"

_CANONICAL_BLANK_CLASS_ID = 3
_CANONICAL_BLANK_ASCENDANCY_ID = 0
_CANONICAL_BLANK_SECONDARY_ASCENDANCY_ID = 0
_CANONICAL_ITEM_SET_ID = "itemset.main"
_CANONICAL_SPEC_ID = "spec.main"
_CANONICAL_SKILLS_ID = "skills.main"
_CANONICAL_CONFIG_ID = "config.main"
_SUPPORTED_BANDIT_CHOICES = frozenset({"None", "Oak", "Kraityn", "Alira"})
_SUPPORTED_MAJOR_PANTHEONS = frozenset({"None", "TheBrineKing", "Lunaris", "Solaris", "Arakaali"})
_SUPPORTED_MINOR_PANTHEONS = frozenset(
    {"None", "Gruthkul", "Yugul", "Abberath", "Tukohama", "Garukhan", "Ralakesh", "Ryslatha", "Shakari"}
)
_SUPPORTED_ENEMY_BOSS_STATES = frozenset({"None", "Boss", "Pinnacle", "Uber"})
_CONFIG_DEFAULT_INPUTS: dict[str, str | bool | int | None] = {
    "bandit": "None",
    "pantheonMajorGod": "None",
    "pantheonMinorGod": "None",
    "enemyIsBoss": "Pinnacle",
    "buffOnslaught": False,
    "buffFortification": False,
    "conditionUsingFlask": False,
    "conditionEnemyShocked": False,
    "conditionEnemyIgnited": False,
    "conditionShockEffect": None,
}
_CONFIG_ENABLED_CONDITION_IDS = {
    "buffOnslaught": "buff.onslaught",
    "buffFortification": "buff.fortification",
    "conditionUsingFlask": "combat.using_flask",
    "conditionEnemyShocked": "enemy.shocked",
    "conditionEnemyIgnited": "enemy.ignited",
}
_CONFIG_CUSTOM_VALUE_KEYS = {
    "enemyIsBoss": "enemy_is_boss",
    "conditionEnemyIgnited": "enemy_ignited",
    "conditionShockEffect": "enemy_shock_effect",
}
_SUPPORTED_GEM_LEVEL_MODES = frozenset(
    {
        "normalMaximum",
        "corruptedMaximum",
        "awakenedMaximum",
        "characterLevel",
        "levelOne",
    }
)
_SUPPORTED_SUPPORT_GEM_TYPES = frozenset({"ALL", "NORMAL", "EXCEPTIONAL"})
_SUPPORTED_SORT_GEM_FIELDS = frozenset(
    {
        "FullDPS",
        "CombinedDPS",
        "TotalDPS",
        "AverageDamage",
        "TotalDot",
        "BleedDPS",
        "IgniteDPS",
        "TotalPoisonDPS",
        "TotalEHP",
    }
)
_POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION = "1.0.0"
_POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND = "pob_headless_node_power_report"
_POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND = "pob_native_node_power_report"
_POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH = "pob_native_node_power_report_hint_v1"
_DEFAULT_NODE_POWER_METRIC_STAT = "FullDPS"
_DEFAULT_NODE_POWER_METRIC_LANE = "baseline"
_DEFAULT_NODE_POWER_MAX_DEPTH = 5
_DEFAULT_NODE_POWER_MAX_ROWS = 200
_NODE_POWER_DEFENSE_STATS = frozenset(
    {
        "Life",
        "LifeRegen",
        "LifeLeechRate",
        "Armour",
        "Evasion",
        "EnergyShield",
        "EnergyShieldRecoveryCap",
        "EnergyShieldRegen",
        "EnergyShieldLeechRate",
        "Mana",
        "ManaRegen",
        "ManaLeechRate",
        "Ward",
        "BlockChance",
        "SpellBlockChance",
        "SpellSuppressionChance",
        "MeleeAvoidChance",
        "SpellAvoidChance",
        "ProjectileAvoidChance",
        "TotalEHP",
        "SecondMinimalMaximumHitTaken",
        "PhysicalTakenHit",
        "LightningTakenHit",
        "ColdTakenHit",
        "FireTakenHit",
        "ChaosTakenHit",
    }
)
_CALC_DISPLAY_FAMILY_ORDER = (
    "offense",
    "requirements",
    "defense",
    "resources",
    "resistances",
    "movement",
    "utility",
    "other",
)
_CALC_DISPLAY_FAMILY_BY_STAT = {
    "ActiveMinionLimit": "utility",
    "Str": "requirements",
    "ReqStr": "requirements",
    "Dex": "requirements",
    "ReqDex": "requirements",
    "Int": "requirements",
    "ReqInt": "requirements",
    "Omni": "requirements",
    "ReqOmni": "requirements",
    "Devotion": "requirements",
    "TotalEHP": "defense",
    "PhysicalMaximumHitTaken": "defense",
    "FireMaximumHitTaken": "defense",
    "ColdMaximumHitTaken": "defense",
    "LightningMaximumHitTaken": "defense",
    "ChaosMaximumHitTaken": "defense",
    "MainHand": "defense",
    "OffHand": "defense",
    "Evasion": "defense",
    "MeleeEvadeChance": "defense",
    "ProjectileEvadeChance": "defense",
    "Armour": "defense",
    "PhysicalDamageReduction": "defense",
    "EffectiveBlockChance": "defense",
    "EffectiveSpellBlockChance": "defense",
    "AttackDodgeChance": "defense",
    "SpellDodgeChance": "defense",
    "EffectiveSpellSuppressionChance": "defense",
    "Life": "resources",
    "LifeUnreserved": "resources",
    "LifeRecoverable": "resources",
    "LifeUnreservedPercent": "resources",
    "LifeRegenRecovery": "resources",
    "LifeRecharge": "resources",
    "LifeLeechGainRate": "resources",
    "LifeLeechGainPerHit": "resources",
    "Mana": "resources",
    "ManaUnreserved": "resources",
    "ManaUnreservedPercent": "resources",
    "ManaRegenRecovery": "resources",
    "ManaLeechGainRate": "resources",
    "ManaLeechGainPerHit": "resources",
    "EnergyShield": "resources",
    "EnergyShieldRecoveryCap": "resources",
    "EnergyShieldRegenRecovery": "resources",
    "EnergyShieldLeechGainRate": "resources",
    "EnergyShieldLeechGainPerHit": "resources",
    "Ward": "resources",
    "Rage": "resources",
    "RageRegenRecovery": "resources",
    "TotalBuildDegen": "resources",
    "TotalNetRegen": "resources",
    "NetLifeRegen": "resources",
    "NetManaRegen": "resources",
    "NetEnergyShieldRegen": "resources",
    "FireResist": "resistances",
    "FireResistOverCap": "resistances",
    "ColdResist": "resistances",
    "ColdResistOverCap": "resistances",
    "LightningResist": "resistances",
    "LightningResistOverCap": "resistances",
    "ChaosResist": "resistances",
    "ChaosResistOverCap": "resistances",
    "EffectiveMovementSpeedMod": "movement",
    "AreaOfEffectRadiusMetres": "utility",
    "BrandAttachmentRangeMetre": "utility",
    "BrandTicks": "utility",
    "Cooldown": "utility",
    "SealCooldown": "utility",
    "SealMax": "utility",
    "TimeMaxSeals": "utility",
}
_PROOF_RUNTIME_ITEM_RAW = (
    "Rarity: Rare\n"
    "Run Spur\n"
    "Rawhide Boots\n"
    "--------\n"
    "30% increased Movement Speed"
)


class WorkerContractError(RuntimeError):
    """Raised when the headless worker cannot satisfy a command."""

    def __init__(self, failure_state: str, message: str) -> None:
        super().__init__(message)
        self.failure_state = failure_state


def _lua_long_string(value: str) -> str:
    delimiter = "="
    while f"]{delimiter}]" in value:
        delimiter += "="
    return f"[{delimiter}[{value}]{delimiter}]"


def _lua_json_literal(payload: Any) -> str:
    try:
        return _lua_long_string(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise WorkerContractError("runtime_protocol_failed", "Lua JSON literal payload must be JSON-serializable.") from exc


def _slot_order_literal() -> str:
    return "{" + ", ".join(_lua_long_string(slot) for slot in EXPECTED_GEAR_SLOT_ORDER) + "}"


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be an object.")
    return dict(value)


def _require_array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be an array.")
    return list(value)


def _require_families(value: Any, field_name: str) -> dict[str, list[str]]:
    """{mod id: [game mod family, ...]} — the constraint PoB's own `group` field does not express."""

    if value is None:
        return {}
    return {
        str(mod_id): [str(family) for family in _require_array(families, f"{field_name}.{mod_id}")]
        for mod_id, families in _require_mapping(value, field_name).items()
    }


def _require_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be a boolean.")
    return value


def _require_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be a non-empty string.")
    return value.strip()


def _require_optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty_string(value, field_name)


def _require_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be an integer.")
    return value


def _normalize_skill_set_index(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must reference skills.main or skills.<positive-index>.")
    if isinstance(value, int):
        index = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value == _CANONICAL_SKILLS_ID:
            return 1
        match = re.fullmatch(r"skills\.(\d+)", raw_value)
        if match is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"{field_name} must reference skills.main or skills.<positive-index>.",
            )
        index = int(match.group(1))
    else:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference skills.main or skills.<positive-index>.",
        )
    if index < 1:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference skills.main or skills.<positive-index>.",
        )
    return index


def _normalize_skill_set_id(index: int) -> str:
    return _CANONICAL_SKILLS_ID if index == 1 else f"skills.{index}"


def _normalize_item_set_index(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must reference itemset.main or itemset.<positive-index>.")
    if isinstance(value, int):
        index = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value == _CANONICAL_ITEM_SET_ID:
            return 1
        match = re.fullmatch(r"itemset\.(\d+)", raw_value)
        if match is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"{field_name} must reference itemset.main or itemset.<positive-index>.",
            )
        index = int(match.group(1))
    else:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference itemset.main or itemset.<positive-index>.",
        )
    if index < 1:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference itemset.main or itemset.<positive-index>.",
        )
    return index


def _normalize_config_set_index(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must reference config.main or config.<positive-index>.")
    if isinstance(value, int):
        index = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value == _CANONICAL_CONFIG_ID:
            return 1
        match = re.fullmatch(r"config\.(\d+)", raw_value)
        if match is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"{field_name} must reference config.main or config.<positive-index>.",
            )
        index = int(match.group(1))
    else:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference config.main or config.<positive-index>.",
        )
    if index < 1:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference config.main or config.<positive-index>.",
        )
    return index


def _normalize_config_set_id(index: int) -> str:
    return _CANONICAL_CONFIG_ID if index == 1 else f"config.{index}"


def _normalize_socket_group_index(
    value: Any,
    *,
    field_name: str,
    expected_skill_set_id: str,
) -> int:
    if isinstance(value, bool):
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must reference {expected_skill_set_id}.socket_group.<positive-index>.")
    if isinstance(value, int):
        index = value
    elif isinstance(value, str):
        raw_value = value.strip()
        if raw_value.isdigit():
            index = int(raw_value)
        else:
            match = re.fullmatch(r"(skills\.(?:main|\d+))\.socket_group\.(\d+)", raw_value)
            if match is None or match.group(1) != expected_skill_set_id:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"{field_name} must reference {expected_skill_set_id}.socket_group.<positive-index>.",
                )
            index = int(match.group(2))
    else:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference {expected_skill_set_id}.socket_group.<positive-index>.",
        )
    if index < 1:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} must reference {expected_skill_set_id}.socket_group.<positive-index>.",
        )
    return index


def _bool_xml(value: bool) -> str:
    return "true" if value else "false"


def _set_optional_attr(node: ElementTree.Element, key: str, value: Any) -> None:
    if value is None:
        node.attrib.pop(key, None)
        return
    node.set(key, str(value))


def _serialize_xml(root: ElementTree.Element) -> str:
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True).decode("utf-8")


def _json_clone(payload: Any, *, field_name: str) -> Any:
    try:
        return json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True))
    except (TypeError, ValueError) as exc:
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be JSON-serializable.") from exc


def _normalize_node_power_report_request(value: Any) -> dict[str, Any]:
    payload = {} if value is None else _require_mapping(value, "node_power_request")
    allowed_keys = {
        "report_id",
        "metric_stat",
        "metric_lane",
        "config_set_id",
        "max_depth",
        "max_rows",
    }
    extra_keys = sorted(set(payload) - allowed_keys)
    if extra_keys:
        raise WorkerContractError(
            "runtime_protocol_failed",
            "Unsupported node_power_request field(s): " + ", ".join(extra_keys),
        )

    report_id = _require_optional_string(payload.get("report_id"), "node_power_request.report_id")
    metric_stat = _require_optional_string(payload.get("metric_stat"), "node_power_request.metric_stat")
    metric_lane = _require_optional_string(payload.get("metric_lane"), "node_power_request.metric_lane")
    config_set_id = _require_optional_string(payload.get("config_set_id"), "node_power_request.config_set_id")
    if metric_lane is not None and metric_lane not in {"baseline", "conditional", "active"}:
        raise WorkerContractError("runtime_protocol_failed", "node_power_request.metric_lane must be baseline, conditional, or active.")

    max_depth = payload.get("max_depth", _DEFAULT_NODE_POWER_MAX_DEPTH)
    if max_depth is not None:
        max_depth = _require_int(max_depth, "node_power_request.max_depth")
        if max_depth < 1:
            raise WorkerContractError("runtime_protocol_failed", "node_power_request.max_depth must be >= 1.")
    max_rows = payload.get("max_rows", _DEFAULT_NODE_POWER_MAX_ROWS)
    if max_rows is not None:
        max_rows = _require_int(max_rows, "node_power_request.max_rows")
        if max_rows < 1:
            raise WorkerContractError("runtime_protocol_failed", "node_power_request.max_rows must be >= 1.")

    return {
        "report_id": report_id or "pob.headless.node-power.active",
        "metric_stat": metric_stat or _DEFAULT_NODE_POWER_METRIC_STAT,
        "metric_lane": metric_lane or _DEFAULT_NODE_POWER_METRIC_LANE,
        "config_set_id": config_set_id,
        "max_depth": max_depth,
        "max_rows": max_rows,
    }


def _slug_warning_code(line: str) -> str | None:
    lowered = re.sub(r"[^a-z0-9]+", "_", line.lower()).strip("_")
    return lowered or None


def _warning_code_from_line(line: str) -> str | None:
    lowered = line.strip().lower()
    if not lowered:
        return None
    if lowered.startswith("you do not meet the strength requirement"):
        return "unmet_strength_requirement"
    if lowered.startswith("you do not meet the dexterity requirement"):
        return "unmet_dexterity_requirement"
    if lowered.startswith("you do not meet the intelligence requirement"):
        return "unmet_intelligence_requirement"
    if lowered.startswith("you do not meet the omniscience requirement"):
        return "unmet_omniscience_requirement"
    if lowered.startswith("you do not have enough energy shield and mana to use:"):
        return "mana_cost_pool_exhausted"
    if lowered.startswith("you do not have enough mana to use:"):
        return "mana_cost_pool_exhausted"
    if lowered.startswith("you do not have enough life to use:"):
        return "life_cost_pool_exhausted"
    if lowered.startswith("you do not have enough rage to use:"):
        return "rage_cost_pool_exhausted"
    if lowered.startswith("you do not have enough energy shield to use:"):
        return "energy_shield_cost_pool_exhausted"
    if lowered.startswith("you do not have enough unreserved life% to use:"):
        return "life_percent_cost_pool_exhausted"
    if lowered.startswith("you do not have enough unreserved mana% to use:"):
        return "mana_percent_cost_pool_exhausted"
    if "your unreserved life is below 1" in lowered:
        return "life_unreserved_below_one"
    if "your unreserved mana is negative" in lowered:
        return "mana_unreserved_negative"
    if lowered.startswith("you are exceeding jewel limit with the jewel "):
        return "jewel_limit_exceeded"
    if lowered.startswith("you have too many gems in your "):
        return "socket_limit_exceeded"
    if "you have eligible items missing an anoint" in lowered:
        return "missing_anoint_warning"
    if "you have more than one aspect skill active" in lowered:
        return "multiple_aspects_active"
    if "too much cast speed or too little cooldown reduction" in lowered:
        return "vixens_cooldown_warning"
    if "vixen's calculation mode" in lowered:
        return "vixens_gloves_missing"
    if "accuracy for precise technique" in lowered:
        return "precise_technique_accuracy_unmet"
    if "bleed dps exceeds in game limit" in lowered:
        return "bleed_dps_exceeds_game_limit"
    if "corrupting blood dps exceeds in game limit" in lowered:
        return "corrupting_blood_dps_exceeds_game_limit"
    if "ignite dps exceeds in game limit" in lowered:
        return "ignite_dps_exceeds_game_limit"
    if "burning ground dps exceeds in game limit" in lowered:
        return "burning_ground_dps_exceeds_game_limit"
    if "caustic ground dps exceeds in game limit" in lowered:
        return "caustic_ground_dps_exceeds_game_limit"
    if "poison dps exceeds in game limit" in lowered:
        return "poison_dps_exceeds_game_limit"
    if "dot dps exceeds in game limit" in lowered:
        return "dot_dps_exceeds_game_limit"
    return _slug_warning_code(lowered)


def _warning_codes_from_lines(lines: list[str]) -> list[str]:
    codes = {code for line in lines if (code := _warning_code_from_line(line)) is not None}
    return sorted(codes)


def _parse_positive_int_attr(raw_value: str | None, *, field_name: str, default: int = 1) -> int:
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be an integer.") from exc
    if value < 1:
        raise WorkerContractError("runtime_protocol_failed", f"{field_name} must be >= 1.")
    return value


_PARSE_MODS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local function flag_names(flags, table_)',
    '  local out = {}',
    "  if type(flags) ~= 'number' or flags == 0 then return out end",
    '  for name, bit in pairs(table_ or {}) do',
    "    if type(bit) == 'number' and bit ~= 0 and bit % 1 == 0 and (math.floor(flags / bit) % 2) == 1 then table.insert(out, name) end",
    '  end',
    '  table.sort(out)',
    '  return out',
    'end',
    'local function encode_value(v)',
    '  local t = type(v)',
    "  if t == 'number' or t == 'string' or t == 'boolean' then return v end",
    "  if t == 'table' then",
    "    local o = setmetatable({}, { __jsontype = 'object' })",
    '    for k, x in pairs(v) do',
    '      local xt = type(x)',
    "      if xt == 'number' or xt == 'string' or xt == 'boolean' then o[tostring(k)] = x",
    "      elseif xt == 'table' then o[tostring(k)] = encode_value(x) end",
    '    end',
    '    return o',
    '  end',
    '  return tostring(v)',
    'end',
    'local results = {}',
    'for i, line in ipairs(req.lines) do',
    '  local ok, mods, extra = pcall(modLib.parseMod, line)',
    '  local row = { line = line, ok = ok and mods ~= nil, unsupported = (not ok) or (mods == nil) or (extra ~= nil), extra = extra, mods = {} }',
    "  if ok and type(mods) == 'table' then",
    '    for _, mod in ipairs(mods) do',
    '      local tags = {}',
    '      for _, tag in ipairs(mod) do',
    "        if type(tag) == 'table' then table.insert(tags, encode_value(tag)) end",
    '      end',
    '      table.insert(row.mods, { name = mod.name, type = mod.type, value = encode_value(mod.value), flags = flag_names(mod.flags, ModFlag), keyword_flags = flag_names(mod.keywordFlags, KeywordFlag), tags = tags })',
    '    end',
    '  end',
    '  results[i] = row',
    'end',
    'return json.encode({ results = results })',
)


_UNIQUES_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local db = main and main.uniqueDB',
    "if not db or not db.list then error('PoB unique database is not available') end",
    'if req.name then',
    '  local item = db.list[req.name]',
    '  if not item then',
    "    local prefix = req.name .. ', '",
    '    for key, candidate in pairs(db.list) do',
    '      if key == req.name or key:sub(1, #prefix) == prefix then item = candidate break end',
    '    end',
    '  end',
    "  if not item then error('unknown unique: ' .. tostring(req.name)) end",
    '  local mods = {}',
    '  for _, ml in ipairs(item.explicitModLines or {}) do table.insert(mods, { line = ml.line, unsupported = ml.extra and true or false }) end',
    '  local implicits = {}',
    '  for _, ml in ipairs(item.implicitModLines or {}) do table.insert(implicits, ml.line) end',
    '  return json.encode({ name = item.name, base = item.baseName, type = item.type, raw = item:BuildRaw(), req_level = item.requirements and item.requirements.level or nil, explicit_lines = mods, implicit_lines = implicits })',
    'end',
    'local rows = {}',
    'for key, item in pairs(db.list) do',
    '  local mods = {}',
    '  for _, ml in ipairs(item.explicitModLines or {}) do table.insert(mods, itemLib.applyRange(ml.line, 0.5)) end',
    '  local templates = {}',
    '  for _, ml in ipairs(item.explicitModLines or {}) do table.insert(templates, ml.line) end',
    '  table.insert(rows, { key = key, name = item.name, base = item.baseName, type = item.type, req_level = item.requirements and item.requirements.level or 0, lines = mods, templates = templates, source = item.source, league = item.league })',
    'end',
    'table.sort(rows, function(a, b) return a.key < b.key end)',
    'return json.encode({ uniques = rows })',
)


_CONFIG_OPTIONS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    "if build.buildFlag then runCallback('OnFrame') end",
    'local env = build.calcsTab.mainEnv',
    "if not env then error('PoB main env is not available (build not calculated yet)') end",
    'local conditionFlagVars = {}',
    'for _, var in ipairs(req.condition_flag_vars or {}) do conditionFlagVars[var] = true end',
    'local function sources_of(map, key)',
    '  local out = {}',
    '  local mods = map and map[key]',
    "  if type(mods) == 'table' then",
    '    for _, mod in ipairs(mods) do',
    "      local src = tostring(mod.source or '?')",
    '      local seen = false',
    '      for _, s in ipairs(out) do if s == src then seen = true end end',
    '      if not seen and #out < 8 then table.insert(out, src) end',
    '    end',
    '  end',
    '  return out',
    'end',
    'local function condition_flags_for(var)',
    "  local option = nil for _, candidate in ipairs(LoadModule('Modules/ConfigOptions')) do if candidate.var == var then option = candidate break end end",
    '  if not option or not option.apply then return {} end',
    "  local modList, enemyModList = new('ModList'), new('ModList')",
    '  local ok = pcall(option.apply, true, modList, enemyModList, build)',
    '  if not ok then return {} end',
    '  local flags = {}',
    '  for _, mod in ipairs(modList) do',
    "    if mod.source == 'Config' and mod.type == 'FLAG' and type(mod.name) == 'string' and mod.name:sub(1, 10) == 'Condition:' then",
    '      local conditions = {}',
    '      for _, tag in ipairs(mod) do',
    "        if type(tag) == 'table' and tag.type == 'Condition' then",
    '          if tag.var then table.insert(conditions, tostring(tag.var)) end',
    '          for _, value in ipairs(tag.varList or {}) do table.insert(conditions, tostring(value)) end',
    '        end',
    '      end',
    '      table.sort(conditions)',
    '      table.insert(flags, { name = mod.name:sub(11), conditions = conditions })',
    '    end',
    '  end',
    '  table.sort(flags, function(a, b) return a.name < b.name end)',
    '  return flags',
    'end',
    'local rows = {}',
    'for var, control in pairs(build.configTab.varControls or {}) do',
    '  local shown = true',
    '  if control.shown then local ok, v = pcall(control.shown) shown = ok and (v and true or false) end',
    '  local value = build.configTab.input[var]',
    '  if value == nil then value = json.null end',
    '  local refs = {}',
    '  local preds = req.predicates and req.predicates[var]',
    "  if type(preds) == 'table' then",
    '    for kind, key in pairs(preds) do',
    "      local keys = type(key) == 'table' and key or { key }",
    '      for _, k in ipairs(keys) do',
    '        local srcs = {}',
    "        if kind == 'ifCond' then srcs = sources_of(env.conditionsUsed, k)",
    "        elseif kind == 'ifEnemyCond' then srcs = sources_of(env.enemyConditionsUsed, k)",
    "        elseif kind == 'ifMinionCond' then srcs = sources_of(env.minionConditionsUsed, k)",
    "        elseif kind == 'ifMult' then srcs = sources_of(env.multipliersUsed, k)",
    "        elseif kind == 'ifEnemyMult' then srcs = sources_of(env.enemyMultipliersUsed, k)",
    "        elseif kind == 'ifStat' then srcs = sources_of(env.perStatsUsed, k)",
    '        end',
    '        if #srcs > 0 then table.insert(refs, { kind = kind, key = tostring(k), sources = srcs }) end',
    '      end',
    '    end',
    '  end',
    '  table.insert(rows, { var = var, shown = shown, value = value, refs = refs, condition_flags = conditionFlagVars[var] and condition_flags_for(var) or {} })',
    'end',
    'table.sort(rows, function(a, b) return a.var < b.var end)',
    'return json.encode({ options = rows })',
)


_LIST_BENCH_MODS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local base = data.itemBases[req.base]',
    "if not base then error('unknown item base: ' .. tostring(req.base)) end",
    'local rows = {}',
    'for index, mod in ipairs(data.masterMods or {}) do',
    '  local allowed = mod.types and mod.types[base.type]',
    "  if allowed and (mod.type == 'Prefix' or mod.type == 'Suffix') and (not req.ilvl or (mod.level or 0) <= req.ilvl) then",
    '    local lines, rolled = {}, {}',
    '    for i, line in ipairs(mod) do lines[i] = line rolled[i] = itemLib.applyRange(line, req.range or 0.5) end',
    '    local tags = {}',
    '    for i, t in ipairs(mod.modTags or {}) do tags[i] = t end',
    '    table.insert(rows, { index = index, name = mod.name, type = mod.type, affix = mod.affix, lines = lines, rolled_lines = rolled, level = mod.level or 0, group = mod.group, mod_tags = tags })',
    '  end',
    'end',
    'return json.encode({ base = req.base, type = base.type, mods = rows })',
)


_RANDOM_RARES_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local base = data.itemBases[req.base]',
    "if not base then error('unknown item base: ' .. tostring(req.base)) end",
    "local probe = new('Item', 'Rarity: RARE\\nProbe\\n' .. req.base)",
    "if not probe.base then error('PoB could not resolve base: ' .. tostring(req.base)) end",
    'local pool = { Prefix = {}, Suffix = {} }',
    "local source = (req.pool == 'all') and (probe.affixes or {}) or data.itemMods.Explicit",
    'local families = req.families or {}',
    'local byId = {}',
    'for modId, mod in pairs(source) do',
    "  if (mod.type == 'Prefix' or mod.type == 'Suffix') and (mod.level or 0) <= req.ilvl then",
    '    local w = probe:GetModSpawnWeight(mod)',
    '    if w > 0 then',
    '      local fams = families[modId]',
    "      if not fams or #fams == 0 then fams = { 'pob:' .. tostring(mod.group) } end",
    '      local entry = { id = modId, w = w, group = mod.group, fams = fams, type = mod.type }',
    '      byId[modId] = entry',
    '      table.insert(pool[mod.type], entry)',
    '    end',
    '  end',
    'end',
    'table.sort(pool.Prefix, function(a, b) return a.id < b.id end)',
    'table.sort(pool.Suffix, function(a, b) return a.id < b.id end)',
    'math.randomseed(req.seed or 1)',
    'local function blocked(e, used)',
    '  for _, f in ipairs(e.fams) do if used[f] then return true end end',
    '  return false',
    'end',
    'local function mark(e, used)',
    '  for _, f in ipairs(e.fams) do used[f] = true end',
    'end',
    'local function pick(list, used)',
    '  local total = 0',
    '  for _, e in ipairs(list) do if not blocked(e, used) then total = total + e.w end end',
    '  if total <= 0 then return nil end',
    '  local r = math.random() * total',
    '  for _, e in ipairs(list) do',
    '    if not blocked(e, used) then',
    '      r = r - e.w',
    '      if r <= 0 then return e end',
    '    end',
    '  end',
    '  return nil',
    'end',
    'local counts = req.mod_counts or { 4, 4, 4, 5, 5, 6 }',
    'local forced = req.forced or {}',
    'local items = {}',
    'for i = 1, req.n do',
    '  local n_mods = counts[math.random(#counts)]',
    '  local n_pre = math.random(math.max(1, n_mods - 3), math.min(3, n_mods - 1))',
    '  local n_suf = n_mods - n_pre',
    '  local used = {}',
    "  local lines = { 'Rarity: RARE', 'Random ' .. tostring(i), req.base, 'Crafted: true', 'Item Level: ' .. tostring(req.ilvl), 'Quality: ' .. tostring(req.quality or 20) }",
    "  if req.sockets then table.insert(lines, 'Sockets: ' .. tostring(req.sockets)) end",
    '  local chosen = {}',
    '  local forced_pre, forced_suf = 0, 0',
    '  for _, ids in ipairs(forced) do',
    '    local cands = {}',
    '    for _, id in ipairs(ids) do if byId[id] then table.insert(cands, byId[id]) end end',
    '    table.sort(cands, function(a, b) return a.id < b.id end)',
    '    local e = pick(cands, used)',
    "    if not e then error('forced mod line cannot roll on ' .. tostring(req.base) .. ' at item level ' .. tostring(req.ilvl) .. ' (candidates: ' .. table.concat(ids, ', ') .. ')') end",
    '    mark(e, used)',
    "    table.insert(lines, e.type .. ': {range:' .. string.format('%.3f', math.random()) .. '}' .. e.id)",
    '    table.insert(chosen, e.id)',
    "    if e.type == 'Prefix' then forced_pre = forced_pre + 1 else forced_suf = forced_suf + 1 end",
    '  end',
    "  if forced_pre > 3 or forced_suf > 3 then error('forced mod lines need more than three prefixes or suffixes on ' .. tostring(req.base)) end",
    '  local rest_pre = math.max(0, n_pre - forced_pre)',
    '  local rest_suf = math.max(0, n_suf - forced_suf)',
    '  if forced_pre > n_pre then rest_suf = math.max(0, rest_suf - (forced_pre - n_pre)) end',
    '  if forced_suf > n_suf then rest_pre = math.max(0, rest_pre - (forced_suf - n_suf)) end',
    "  for _ = 1, rest_pre do local e = pick(pool.Prefix, used) if e then mark(e, used) table.insert(lines, 'Prefix: {range:' .. string.format('%.3f', math.random()) .. '}' .. e.id) table.insert(chosen, e.id) end end",
    "  for _ = 1, rest_suf do local e = pick(pool.Suffix, used) if e then mark(e, used) table.insert(lines, 'Suffix: {range:' .. string.format('%.3f', math.random()) .. '}' .. e.id) table.insert(chosen, e.id) end end",
    '  local implicit_lines = {}',
    "  if base.implicit then for l in tostring(base.implicit):gmatch('[^\\n]+') do table.insert(implicit_lines, itemLib.applyRange(l, 0.5)) end end",
    "  table.insert(lines, 'Implicits: ' .. tostring(#implicit_lines))",
    '  for _, l in ipairs(implicit_lines) do table.insert(lines, l) end',
    "  local item = new('Item', table.concat(lines, '\\n'))",
    '  item:Craft()',
    '  item:BuildAndParseRaw()',
    '  table.insert(items, { raw = item:BuildRaw(), mod_ids = chosen })',
    'end',
    'return json.encode({ base = req.base, items = items })',
)


_EQUIP_ITEMS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local results = {}',
    '-- drop_replaced: an item nobody else points at leaves the item list (PoB keeps orphans otherwise)',
    'local replaced = {}',
    'local function drop_if_unused(item_id)',
    '  if not item_id or item_id == 0 then return end',
    '  for _, other in pairs(build.treeTab.specList) do',
    '    for _, id in pairs(other.jewels) do if id == item_id then return end end',
    '  end',
    '  for _, itemSet in pairs(build.itemsTab.itemSets) do',
    '    for _, slot in pairs(itemSet) do if type(slot) == "table" and slot.selItemId == item_id then return end end',
    '  end',
    '  build.itemsTab.items[item_id] = nil',
    '  for index, id in pairs(build.itemsTab.itemOrderList) do',
    '    if id == item_id then table.remove(build.itemsTab.itemOrderList, index) break end',
    '  end',
    'end',
    'for _, e in ipairs(req.items) do',
    '  local slot = build.itemsTab.slots[e.slot]',
    "  if not slot or slot.nodeId then error('unsupported item slot ' .. tostring(e.slot)) end",
    "  if req.drop_replaced and slot.selItemId and slot.selItemId ~= 0 then table.insert(replaced, slot.selItemId) end",
    "  if e.raw == nil or e.raw == json.null or e.raw == '' then",
    '    slot:SetSelItemId(0)',
    '    table.insert(results, { slot = e.slot, item_id = 0 })',
    '  else',
    '    build.itemsTab:CreateDisplayItemFromRaw(e.raw, true)',
    '    local item = build.itemsTab.displayItem',
    "    if not item then error('PoB could not parse the item for slot ' .. tostring(e.slot)) end",
    '    build.itemsTab:AddItem(item, true)',
    '    build.itemsTab:SetDisplayItem()',
    "    if not build.itemsTab:IsItemValidForSlot(item, e.slot, build.itemsTab.activeItemSet) then error('item is not valid for slot ' .. tostring(e.slot)) end",
    '    slot:SetSelItemId(item.id)',
    '    table.insert(results, { slot = e.slot, item_id = item.id, name = item.name })',
    '  end',
    'end',
    'for _, old_id in ipairs(replaced) do drop_if_unused(old_id) end',
    'build.itemsTab:PopulateSlots()',
    'build.buildFlag = true',
    "runCallback('OnFrame')",
    'return json.encode({ equipped = results })',
)


_SOCKET_JEWELS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local spec = build.spec',
    'local function is_cluster(item)',
    "  return item and (item.clusterJewel or (item.jewelData and item.jewelData.clusterJewelValid)) and true or false",
    'end',
    '-- an item nobody else points at leaves the item list (PoB keeps orphans otherwise)',
    'local function drop_if_unused(item_id)',
    '  if not item_id or item_id == 0 then return end',
    '  for _, other in pairs(build.treeTab.specList) do',
    '    for _, id in pairs(other.jewels) do if id == item_id then return end end',
    '  end',
    '  for _, itemSet in pairs(build.itemsTab.itemSets) do',
    '    for _, slot in pairs(itemSet) do if type(slot) == "table" and slot.selItemId == item_id then return end end',
    '  end',
    '  build.itemsTab.items[item_id] = nil',
    '  for index, id in pairs(build.itemsTab.itemOrderList) do',
    '    if id == item_id then table.remove(build.itemsTab.itemOrderList, index) break end',
    '  end',
    'end',
    'build.itemsTab:UpdateSockets()',
    '-- the jewels in the inner sockets of the cluster jewel held by `node_id` (nested clusters too) leave with it',
    'local function clear_cluster_children(node_id)',
    '  local children = {}',
    '  for _, subGraph in pairs(spec.subGraphs or {}) do',
    '    if subGraph.parentSocket and subGraph.parentSocket.id == node_id then',
    '      for _, node in ipairs(subGraph.nodes) do',
    "        if node.type == 'Socket' then table.insert(children, node.id) end",
    '      end',
    '    end',
    '  end',
    '  for _, child_id in ipairs(children) do',
    '    clear_cluster_children(child_id)',
    '    local child_item = spec.jewels[child_id]',
    '    if child_item and child_item ~= 0 then',
    '      local child_socket = build.itemsTab.sockets[child_id]',
    '      if child_socket then child_socket:SetSelItemId(0) else spec.jewels[child_id] = nil end',
    '      drop_if_unused(child_item)',
    '    end',
    '  end',
    'end',
    'local function socket_of(node_id, what)',
    '  local socket = build.itemsTab.sockets[node_id]',
    "  if not socket then error(what .. ': node ' .. tostring(node_id) .. ' is not a jewel socket') end",
    '  return socket',
    'end',
    'for _, node_id in ipairs(req.remove or {}) do',
    "  local socket = socket_of(node_id, 'remove')",
    '  local old_id = socket.selItemId or 0',
    '  clear_cluster_children(node_id)',
    '  socket:SetSelItemId(0)',
    '  drop_if_unused(old_id)',
    'end',
    'for _, entry in ipairs(req.put or {}) do',
    '  local node_id = entry.node_id',
    "  local socket = socket_of(node_id, 'put')",
    "  if not spec.allocNodes[node_id] then error('put: socket ' .. tostring(node_id) .. ' is not allocated') end",
    '  local old_id = socket.selItemId or 0',
    '  build.itemsTab:CreateDisplayItemFromRaw(entry.raw, true)',
    '  local item = build.itemsTab.displayItem',
    "  if not item then error('put: PoB could not parse the item for socket ' .. tostring(node_id)) end",
    "  if item.type ~= 'Jewel' then",
    '    build.itemsTab:SetDisplayItem()',
    "    error('put: socket ' .. tostring(node_id) .. ' takes a Jewel, got ' .. tostring(item.type))",
    '  end',
    '  clear_cluster_children(node_id)',
    '  build.itemsTab:AddItem(item, true)',
    '  build.itemsTab:SetDisplayItem()',
    '  socket:SetSelItemId(item.id)  -- a cluster jewel: PoB rebuilds the socket subgraph here (a replaced one is dropped first)',
    '  drop_if_unused(old_id)',
    'end',
    'build.itemsTab:UpdateSockets()',
    'build.buildFlag = true',
    "runCallback('OnFrame')",
    'local jewels = {}',
    'for node_id, item_id in pairs(spec.jewels or {}) do',
    "  if type(item_id) == 'number' and item_id > 0 then",
    '    local item = build.itemsTab.items[item_id]',
    '    if item then',
    '      table.insert(jewels, { node_id = node_id, allocated = spec.allocNodes[node_id] ~= nil, name = item.name, raw = item:BuildRaw() })',
    '    end',
    '  end',
    'end',
    'table.sort(jewels, function(a, b) return a.node_id < b.node_id end)',
    "return json.encode({ jewels = setmetatable(jewels, { __jsontype = 'array' }) })",
)


_CLUSTER_GRAPH_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local spec = build.spec',
    'local nodes = {}',
    'for _, subGraph in pairs(spec.subGraphs or {}) do',
    '  if subGraph.parentSocket and subGraph.parentSocket.id == req.socket_id then',
    '    for _, node in ipairs(subGraph.nodes) do',
    "      if node.type ~= 'Mastery' then",
    "        local kind = ({ Normal = 'small', Notable = 'notable', Socket = 'socket', Keystone = 'keystone' })[node.type] or tostring(node.type)",
    "        if node == subGraph.entranceNode and node.type ~= 'Keystone' then kind = 'entry' end",
    '        local linked = {}',
    '        for _, other in ipairs(node.linked or {}) do table.insert(linked, other.id) end',
    '        table.sort(linked)',
    "        table.insert(nodes, { id = node.id, kind = kind, name = node.dn, linked = setmetatable(linked, { __jsontype = 'array' }), allocated = spec.allocNodes[node.id] ~= nil })",
    '      end',
    '    end',
    '  end',
    'end',
    'table.sort(nodes, function(a, b) return a.id < b.id end)',
    "return json.encode({ nodes = setmetatable(nodes, { __jsontype = 'array' }) })",
)


_LIST_ITEM_MODS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local base = data.itemBases[req.base]',
    "if not base then error('unknown item base: ' .. tostring(req.base)) end",
    "local item = new('Item', 'Rarity: RARE\\nProbe\\n' .. req.base)",
    "if not item.base then error('PoB could not resolve base: ' .. tostring(req.base)) end",
    'local rows = {}',
    "local pool = (req.pool == 'all') and (item.affixes or {}) or data.itemMods.Explicit",
    'for modId, mod in pairs(pool) do',
    "  if (mod.type == 'Prefix' or mod.type == 'Suffix') and (not req.ilvl or (mod.level or 0) <= req.ilvl) then",
    '    local weight = item:GetModSpawnWeight(mod)',
    '    if weight > 0 then',
    '      local lines = {}',
    '      for i, line in ipairs(mod) do lines[i] = line end',
    '      local tags = {}',
    '      for i, t in ipairs(mod.modTags or {}) do tags[i] = t end',
    '      table.insert(rows, { mod_id = modId, type = mod.type, affix = mod.affix, lines = lines, level = mod.level or 0, group = mod.group, weight = weight, mod_tags = tags })',
    '    end',
    '  end',
    'end',
    'table.sort(rows, function(a, b) if a.group ~= b.group then return tostring(a.group) < tostring(b.group) end if a.level ~= b.level then return a.level > b.level end return a.mod_id < b.mod_id end)',
    'local btags = {}',
    'for k, _ in pairs(base.tags or {}) do table.insert(btags, k) end',
    'table.sort(btags)',
    'return json.encode({ base = req.base, type = base.type, sub_type = base.subType, base_tags = btags, implicit = base.implicit, mods = rows })',
)


_CRAFT_RARE_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    'local base = data.itemBases[req.base]',
    "if not base then error('unknown item base: ' .. tostring(req.base)) end",
    "local lines = { 'Rarity: RARE', req.name or 'Crafted Item', req.base, 'Crafted: true' }",
    "if req.ilvl then table.insert(lines, 'Item Level: ' .. tostring(req.ilvl)) end",
    "if req.quality then table.insert(lines, 'Quality: ' .. tostring(req.quality)) end",
    "if req.sockets then table.insert(lines, 'Sockets: ' .. tostring(req.sockets)) end",
    "for _, p in ipairs(req.prefixes or {}) do table.insert(lines, 'Prefix: {range:' .. tostring(p.range or 0.5) .. '}' .. p.mod_id) end",
    "for _, s in ipairs(req.suffixes or {}) do table.insert(lines, 'Suffix: {range:' .. tostring(s.range or 0.5) .. '}' .. s.mod_id) end",
    'local implicit_lines = {}',
    "if base.implicit then for l in tostring(base.implicit):gmatch('[^\\n]+') do table.insert(implicit_lines, itemLib.applyRange(l, req.implicit_range or 0.5)) end end",
    "table.insert(lines, 'Implicits: ' .. tostring(#implicit_lines))",
    'for _, l in ipairs(implicit_lines) do table.insert(lines, l) end',
    'for _, l in ipairs(req.extra_lines or {}) do table.insert(lines, l) end',
    "local item = new('Item', table.concat(lines, '\\n'))",
    "if not item.base then error('PoB could not resolve base: ' .. tostring(req.base)) end",
    'item:Craft()',
    'item:BuildAndParseRaw()',
    'local problems = {}',
    'local function check(list, kind)',
    '  for _, a in ipairs(list or {}) do',
    '    local mod = item.affixes and item.affixes[a.mod_id]',
    "    if not mod then table.insert(problems, kind .. ' ' .. tostring(a.mod_id) .. ': unknown mod for this base')",
    "    elseif mod.type ~= kind then table.insert(problems, kind .. ' ' .. tostring(a.mod_id) .. ': is a ' .. tostring(mod.type))",
    "    elseif item:GetModSpawnWeight(mod) <= 0 then table.insert(problems, kind .. ' ' .. tostring(a.mod_id) .. ': cannot spawn on ' .. req.base)",
    "    elseif req.ilvl and (mod.level or 0) > req.ilvl then table.insert(problems, kind .. ' ' .. tostring(a.mod_id) .. ': requires ilvl ' .. tostring(mod.level))",
    '    end',
    '  end',
    'end',
    "check(req.prefixes, 'Prefix')",
    "check(req.suffixes, 'Suffix')",
    "if #(req.prefixes or {}) > (item.prefixes.limit or 3) then table.insert(problems, 'too many prefixes') end",
    "if #(req.suffixes or {}) > (item.suffixes.limit or 3) then table.insert(problems, 'too many suffixes') end",
    'local families = req.families or {}',
    'local seen_families = {}',
    'for _, list in ipairs({ req.prefixes or {}, req.suffixes or {} }) do',
    '  for _, a in ipairs(list) do',
    '    local mod = item.affixes and item.affixes[a.mod_id]',
    '    local fams = families[a.mod_id]',
    "    if (not fams or #fams == 0) and mod and mod.group then fams = { 'pob:' .. tostring(mod.group) } end",
    '    for _, f in ipairs(fams or {}) do',
    '      if seen_families[f] then',
    "        if f:sub(1, 4) == 'pob:' then table.insert(problems, 'duplicate mod group ' .. f:sub(5))",
    "        else table.insert(problems, 'duplicate mod family ' .. f) end",
    '      end',
    '      seen_families[f] = true',
    '    end',
    '  end',
    'end',
    'local unsupported = {}',
    'local explicit = {}',
    'for _, ml in ipairs(item.explicitModLines or {}) do',
    '  table.insert(explicit, ml.line)',
    '  if ml.extra then table.insert(unsupported, ml.line) end',
    'end',
    'return json.encode({ raw = item:BuildRaw(), name = item.name, explicit_lines = explicit, unsupported_lines = unsupported, problems = problems, level_req = item.requirements and item.requirements.level or nil })',
)


_RECRAFT_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local req = json.decode(REQUEST_JSON, 1, nil)',
    "local item = new('Item', req.raw)",
    "if not item.base then error('recraft: PoB could not parse the item base') end",
    'item:Craft()',
    'item:BuildAndParseRaw()',
    'return json.encode({ raw = item:BuildRaw() })',
)


# A node carries PoB's *internal* ascendancy id in `node.ascendancyName`, never the display
# name. The two differ for renamed ascendancies: Ranger's first ascendancy is
# `id = "Raider", name = "Warden"` in TreeData/3_29/tree.lua (Warden replaced Raider in 3.24 but
# kept the internal id), and PassiveSpec.lua:605-606 stores them apart:
#     self.curAscendClassName     = ascendClass.name   -- "Warden"
#     self.curAscendClassBaseName = ascendClass.id     -- "Raider"
# Matching allocated nodes against curAscendClassName therefore found nothing for the Warden
# (its nodes say "Raider"), so every ascendancy readback came back empty and set_tree reported
# "ascendancy_node_ids did not materialize". Match on the id, which is what nodes carry.
_ASCENDANCY_MATCH_LUA: tuple[str, ...] = (
    'local function node_ascendancy_name(node)',
    '  local value = node.ascendancyName or node.ascendancy_name',
    "  if type(value) == 'string' and value ~= '' then",
    '    return value',
    '  end',
    '  return nil',
    'end',
    'local function current_ascendancy_names()',
    '  local names = {}',
    '  local base = build.spec.curAscendClassBaseName',
    "  if type(base) ~= 'string' or base == '' then",
    '    base = build.spec.curAscendClass and build.spec.curAscendClass.id or nil',
    '  end',
    "  if type(base) == 'string' and base ~= '' then",
    '    names[base] = true',
    '  end',
    '  local display = build.spec.curAscendClassName',
    "  if next(names) == nil and type(display) == 'string' and display ~= '' then",
    '    names[display] = true',
    '  end',
    '  return names',
    'end',
    'local function node_in_current_ascendancy(node, names)',
    '  local value = node_ascendancy_name(node)',
    '  if value == nil then',
    '    return false',
    '  end',
    '  return (names or current_ascendancy_names())[value] == true',
    'end',
)


_TREE_LIGHT_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local spec = build.spec',
    'local skip = {}',
    'local function mark(id) if id and spec.allocNodes[id] then skip[id] = true end end',
    'mark(spec.curClass and spec.curClass.startNodeId or nil)',
    'mark(spec.curAscendClass and spec.curAscendClass.startNodeId or nil)',
    'mark(spec.curSecondaryAscendClass and spec.curSecondaryAscendClass.startNodeId or nil)',
    'local nodes = {}',
    'for node_id, _ in pairs(spec.allocNodes) do if not skip[node_id] then table.insert(nodes, node_id) end end',
    'table.sort(nodes)',
    'local effects = {}',
    "for node_id, effect_id in pairs(spec.masterySelections or {}) do table.insert(effects, tostring(node_id) .. ':' .. tostring(effect_id)) end",
    'table.sort(effects)',
    'return json.encode({ class_id = spec.curClassName or json.null, tree_version = tostring(spec.treeVersion), latest_tree_version = tostring(latestTreeVersion), user_allocated_node_ids = nodes, mastery_effect_ids = effects })',
)


# PoB's own tree conversion (TreeTab:ConvertToVersion), which builds a fresh PassiveSpec at the
# target version and replays the active spec's hash list, mastery selections, tattoos and jewels
# onto it (PassiveSpec:CreateUndoState / RestoreUndoState). Ids that no longer exist are dropped,
# and BuildAllDependsAndPaths prunes whatever lost its path to the class start -- both show up as
# `lost_node_ids` here. The target defaults to PoB's own `latestTreeVersion`; nothing is hardcoded.
_CONVERT_TREE_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local payload = json.decode(PAYLOAD_JSON, 1, nil)',
    'local target = payload.version',
    "if target == nil or target == '' then target = latestTreeVersion end",
    'target = tostring(target)',
    'if not isValueInTable(treeVersionList, target) then',
    "  error('Unknown passive tree version: ' .. target)",
    'end',
    'local function user_nodes(spec)',
    '  local out = {}',
    '  for node_id, node in pairs(spec.allocNodes) do',
    "    if node.type ~= 'ClassStart' and node.type ~= 'AscendClassStart' then out[node_id] = true end",
    '  end',
    '  return out',
    'end',
    'local function count(set)',
    '  local n = 0',
    '  for _ in pairs(set) do n = n + 1 end',
    '  return n',
    'end',
    'local from = tostring(build.spec.treeVersion)',
    'local before = user_nodes(build.spec)',
    'local converted = false',
    'if from ~= target then',
    '  build.treeTab:ConvertToVersion(target, true, false, false)',
    '  converted = true',
    'end',
    'local after = user_nodes(build.spec)',
    'local lost = {}',
    'for node_id, _ in pairs(before) do',
    '  if not after[node_id] then table.insert(lost, node_id) end',
    'end',
    'table.sort(lost)',
    'if converted then',
    '  build.itemsTab:UpdateSockets()',
    '  build.buildFlag = true',
    "  runCallback('OnFrame')",
    'end',
    'return json.encode({ from = from, to = tostring(build.spec.treeVersion), converted = converted, nodes_before = count(before), nodes_after = count(after), lost_node_ids = lost })',
)


# The active config set's inputs as ConfigTab:Save would write them (ConfigTab.lua:919: every var
# whose value differs from GetDefaultState), read straight off build.configTab.input instead of
# exporting the whole build and parsing <Config> back out of it.
_CONFIG_INPUTS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local ct = build.configTab',
    "local out = setmetatable({}, { __jsontype = 'object' })",
    'for name, value in pairs(ct.input) do',
    '  local kind = type(value)',
    "  if (kind == 'number' or kind == 'boolean' or kind == 'string') and value ~= ct:GetDefaultState(name, kind) then",
    '    out[name] = value',
    '  end',
    'end',
    'return json.encode({ inputs = out })',
)


_UNSUPPORTED_GEMS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    "if build.buildFlag then runCallback('OnFrame') end",
    'local rows = {}',
    'local judged = 0',
    'for gi, socket_group in ipairs(build.skillsTab.socketGroupList or {}) do',
    '  local shown = #(socket_group.displaySkillList or {})',
    '  if socket_group.enabled and socket_group.slotEnabled ~= false then',
    '    for _, g in ipairs(socket_group.gemList or {}) do',
    '      local ge = g.gemData and g.gemData.grantedEffect',
    '      if g.enabled and ge and ge.support then',
    '        judged = judged + 1',
    '        local eff = g.supportEffect',
    '        local reason = nil',
    "        if eff and eff.superseded then reason = 'superseded'",
    "        elseif (not eff or not eff.isSupporting or not next(eff.isSupporting)) and shown > 0 then reason = 'cannot apply to any of the active skills' end",
    '        if reason then',
    '          table.insert(rows, { group = gi, label = socket_group.label or json.null, slot = socket_group.slot or json.null, gem = g.nameSpec or ge.name, reason = reason })',
    '        end',
    '      end',
    '    end',
    '  end',
    'end',
    'return json.encode({ unsupported = rows, judged = judged })',
)


# Skills written straight into build.skillsTab, the way PoB's own SkillsTab:Load does it
# (SkillsTab.lua:496), instead of exporting the build, rewriting <Skills> and reloading the
# whole build from XML (~470 ms of which ~420 ms is loadBuildFromXML). The gem list is filled
# with exactly the fields SkillsTab:LoadSkill sets from the XML attributes, skillId is left nil so
# ProcessSocketGroup resolves the gem (the same code path the XML route takes), and
# SetActiveSkillSet does the rest (socketGroupList alias, controls, display group, buildFlag,
# SyncLoadouts).
#
# Gem-name -> gemId memo. Given only a `nameSpec`, `SkillsTab:ProcessSocketGroup` (SkillsTab.lua:1166)
# resolves the gem through `SkillsTab:FindSkillGem`, a linear scan of the whole gem database under up
# to five Lua patterns. With `gemId` already set the same function takes the branch at `:1142`
# instead: `gemData = data.gems[gemId]`, the very object `FindSkillGem` returns, and it then writes
# the same `nameSpec` (normalised to `gemData.name`), the same `skillId` and the same nil `errMsg`.
# Nothing else in that function reads the build, so the two branches are interchangeable. The memo is
# per gem database (keyed by its table identity, static inside a worker) and only remembers a
# resolution PoB completed: an ambiguous or unknown name keeps falling through to `FindSkillGem`,
# `errMsg` and all. Worth 5-7% of a skills write; the rest of one is PoB's own recalc, which grows
# with the number of socket groups (min of 8 on stormbrand's surface: 1 group / 5 gems 26.1 -> 24.7 ms,
# 6 groups / 18 gems 74.1 -> 69.2 ms).
_GEM_ID_MEMO_SETUP: tuple[str, ...] = (
    'local gem_id_memo = rawget(_G, "__junkroan_gem_ids")',
    'if not gem_id_memo then gem_id_memo = {} rawset(_G, "__junkroan_gem_ids", gem_id_memo) end',
    'local gem_db_key = tostring((build.data and build.data.gems) or "")',
    'local gem_ids = gem_id_memo[gem_db_key]',
    'if not gem_ids then gem_ids = {} gem_id_memo[gem_db_key] = gem_ids end',
)
_GEM_ID_MEMO_GROUP: tuple[str, ...] = ('    local specs = {}',)
_GEM_ID_MEMO_LOOKUP: tuple[str, ...] = (
    '      specs[#specs + 1] = gi.nameSpec',
    '      gi.gemId = gem_ids[gi.nameSpec]',
)
_GEM_ID_MEMO_RECORD: tuple[str, ...] = (
    '    for i, gi in ipairs(sg.gemList) do',
    '      if gi.gemId and gi.gemData and specs[i] then gem_ids[specs[i]] = gi.gemId end',
    '    end -- gem id memo',  # the comment keeps this line distinct from the writer's other "end"s,
)                              # so _APPLY_SKILLS_LUA_NO_GEM_ID_MEMO can drop it by text

# The build's spectreList, written in place (the skills tab's minion lists hold the same table) and only
# for a payload that carries `spectre_list`; an id outside data.minions is an error here, where Build.lua's
# own loader drops it silently. Inserted before `local s = p.settings` by `_apply_skill_state_inplace`.
_SET_SPECTRE_LIST_LUA: tuple[str, ...] = (
    'for k in pairs(build.spectreList) do build.spectreList[k] = nil end',
    'for _, id in ipairs(p.spectre_list) do',
    "  if not data.minions[id] then error('spectre_list: unknown spectre id ' .. tostring(id)) end",
    '  table.insert(build.spectreList, id)',
    'end',
)

# #1022: a skills write keeps the main active skill the build held, by identity: the name of the granted effect the main
# socket group's main active skill ran before the write, looked up again among the active skills the NEW first gem of the
# main group provides (a Vaal gem provides ['Vaal Spark', 'Spark']; position 1 is the Vaal skill, the saved build's main
# was position 2). Only a payload that sets `keep_main_active_skill` asks for it; a name the new first gem does not
# provide leaves the payload's own index.
_KEEP_MAIN_SKILL_CAPTURE_LUA: tuple[str, ...] = (
    'local kept_main',
    'if p.keep_main_active_skill then',
    '  local og = st.socketGroupList and st.socketGroupList[build.mainSocketGroup or 1]',
    '  local oe = og and og.displaySkillList and og.displaySkillList[og.mainActiveSkill or 1]',
    '  kept_main = oe and oe.activeEffect and oe.activeEffect.grantedEffect and oe.activeEffect.grantedEffect.name or nil',
    'end',
)
_KEEP_MAIN_SKILL_RESTORE_LUA: tuple[str, ...] = (
    'if kept_main then',
    '  local sg = st.socketGroupList and st.socketGroupList[p.main_socket_group]',
    '  local first = sg and sg.gemList and sg.gemList[1]',
    '  local at',
    '  for i, ds in ipairs(sg and sg.displaySkillList or {}) do',
    '    local e = ds.activeEffect',
    '    if e and e.srcInstance == first and e.grantedEffect and e.grantedEffect.name == kept_main then at = i break end',
    '  end',
    '  if at and at ~= (tonumber(sg.mainActiveSkill) or 1) then',
    '    sg.mainActiveSkill = at',
    '    sg.mainActiveSkillCalcs = at',
    '    build.buildFlag = true',
    "    runCallback('OnFrame')",
    '  end',
    'end',
)

_APPLY_SKILLS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local p = json.decode(PAYLOAD_JSON, 1, nil)',
    'local st = build.skillsTab',
    'local sane = sanitiseText or function(s) return s end',
    'local function opt(v) if v == nil or v == json.null then return nil end return v end',
    *_GEM_ID_MEMO_SETUP,
    *_KEEP_MAIN_SKILL_CAPTURE_LUA,
    'local s = p.settings',
    'st.activeSkillSetId = 0',
    'st.skillSets = {}',
    'st.skillSetOrderList = {}',
    'st.defaultGemLevel = s.defaultGemLevel',
    'st.defaultGemQuality = s.defaultGemQuality',
    'st.sortGemsByDPS = s.sortGemsByDPS',
    'st.sortGemsByDPSField = s.sortGemsByDPSField',
    'st.showLegacyGems = s.showLegacyGems',
    'st.showSupportGemTypes = s.showSupportGemTypes',
    'if st.controls then',
    "  if st.controls.defaultLevel then st.controls.defaultLevel:SelByValue(s.defaultGemLevel, 'gemLevel') end",
    '  if st.controls.defaultQuality then st.controls.defaultQuality:SetText(tostring(s.defaultGemQuality)) end',
    '  if st.controls.sortGemsByDPS then st.controls.sortGemsByDPS.state = s.sortGemsByDPS end',
    '  if st.controls.showLegacyGems then st.controls.showLegacyGems.state = s.showLegacyGems end',
    "  if st.controls.showSupportGemTypes then st.controls.showSupportGemTypes:SelByValue(s.showSupportGemTypes, 'show') end",
    "  if st.controls.sortGemsByDPSFieldControl then st.controls.sortGemsByDPSFieldControl:SelByValue(s.sortGemsByDPSField, 'type') end",
    'end',
    'for _, set in ipairs(p.skill_sets) do',
    '  local skillSet = st:NewSkillSet(set.id)',
    '  skillSet.title = opt(set.title)',
    '  table.insert(st.skillSetOrderList, skillSet.id)',
    '  for _, g in ipairs(set.socket_groups) do',
    '    local sg = {}',
    '    sg.enabled = g.enabled',
    '    sg.includeInFullDPS = g.include_in_full_dps',
    '    sg.groupCount = opt(g.group_count)',
    '    sg.label = opt(g.label)',
    '    sg.slot = opt(g.slot)',
    '    sg.source = nil',
    '    sg.mainActiveSkill = g.main_active_skill',
    '    sg.mainActiveSkillCalcs = g.main_active_skill',
    '    sg.gemList = {}',
    *_GEM_ID_MEMO_GROUP,
    '    for _, gem in ipairs(g.gems) do',
    '      local gi = {}',
    '      gi.nameSpec = sane(sane(gem.nameSpec))',
    *_GEM_ID_MEMO_LOOKUP,
    '      gi.level = gem.level',
    '      gi.quality = gem.quality',
    '      gi.enabled = gem.enabled',
    '      gi.enableGlobal1 = gem.enableGlobal1',
    '      gi.enableGlobal2 = gem.enableGlobal2',
    '      gi.count = gem.count',
    '      gi.skillPart = opt(gem.skillPart)',
    '      gi.skillPartCalcs = opt(gem.skillPart)',
    '      gi.skillStageCount = opt(gem.skillStageCount)',
    '      gi.skillStageCountCalcs = opt(gem.skillStageCount)',
    '      gi.skillMineCount = opt(gem.skillMineCount)',
    '      gi.skillMineCountCalcs = opt(gem.skillMineCount)',
    '      gi.skillMinion = opt(gem.skillMinion)',
    '      gi.skillMinionCalcs = opt(gem.skillMinion)',
    '      gi.skillMinionItemSet = opt(gem.skillMinionItemSet)',
    '      gi.skillMinionItemSetCalcs = opt(gem.skillMinionItemSet)',
    '      gi.skillMinionSkill = opt(gem.skillMinionSkill)',
    '      gi.skillMinionSkillCalcs = opt(gem.skillMinionSkill)',
    '      table.insert(sg.gemList, gi)',
    '    end',
    '    st:ProcessSocketGroup(sg)',
    *_GEM_ID_MEMO_RECORD,
    '    table.insert(skillSet.socketGroupList, sg)',
    '  end',
    'end',
    'st:SetActiveSkillSet(s.activeSkillSet)',
    'build.mainSocketGroup = p.main_socket_group',
    'if st.ResetUndo then st:ResetUndo() end',
    'build.buildFlag = true',
    "runCallback('OnFrame')",
    *_KEEP_MAIN_SKILL_RESTORE_LUA,
    "return '1'",
)

# The same writer without the memo: the code as it stood before it, kept as the equivalence
# reference `_apply_skill_state_xml` is, and as the "before" side of scripts/picks_speed_proof.py
# (JUNKROAN_GEM_ID_MEMO=0 in the worker's environment).
_MEMO_LINES = frozenset((*_GEM_ID_MEMO_SETUP, *_GEM_ID_MEMO_GROUP, *_GEM_ID_MEMO_LOOKUP, *_GEM_ID_MEMO_RECORD))
_APPLY_SKILLS_LUA_NO_GEM_ID_MEMO: tuple[str, ...] = tuple(line for line in _APPLY_SKILLS_LUA if line not in _MEMO_LINES)

# Config written straight into build.configTab, the way ConfigTab:Load (ConfigTab.lua:788) and
# ConfigTab:RestoreUndoState (:1194) do it. NewConfigSet seeds every ConfigOptions var with its
# default, so the input table's layout - and therefore the pairs() order ConfigTab:Save writes
# the <Input> elements in - is identical to the reloaded build's.
_APPLY_CONFIG_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local p = json.decode(PAYLOAD_JSON, 1, nil)',
    'local ct = build.configTab',
    'local function title_case(v)',
    "  return (tostring(v):lower():gsub('(%l)(%w*)', function(a, b) return a:upper() .. b end))",
    'end',
    'local function decode_input(name, value)',
    "  if type(value) ~= 'string' then return value end",
    "  if name == 'enemyIsBoss' then",
    "    return (title_case(value):gsub('Uber Atziri', 'Boss'):gsub('Shaper', 'Pinnacle'):gsub('Sirus', 'Pinnacle'))",
    '  end',
    "  if name == 'presetBossSkills' then return (value:gsub('^Uber ', '')) end",
    '  return value',
    'end',
    'ct.activeConfigSetId = 1',
    'ct.configSets = {}',
    'ct.configSetOrderList = {}',
    'for index, cs in ipairs(p.config_sets) do',
    '  ct:NewConfigSet(cs.id, cs.title)',
    '  ct.configSetOrderList[index] = cs.id',
    '  local target = ct.configSets[cs.id]',
    '  target.customModsList = {}',
    '  for _, entry in ipairs(cs.inputs) do',
    '    target.input[entry[1]] = decode_input(entry[1], entry[2])',
    '  end',
    'end',
    'for _, config_set_id in ipairs(ct.configSetOrderList) do',
    '  local cs = ct.configSets[config_set_id]',
    "  local legacy = cs.input and cs.input.customMods or ''",
    "  if legacy ~= '' then",
    "    cs.customModsList = { { title = 'Default', enabled = true, text = legacy } }",
    '  elseif not cs.customModsList or #cs.customModsList == 0 then',
    "    cs.customModsList = { { title = 'Default', enabled = true, text = '' } }",
    '  end',
    '  if cs.input then cs.input.customMods = nil end',
    'end',
    'ct:SetActiveConfigSet(p.active_config_set)',
    'if ct.ResetUndo then ct:ResetUndo() end',
    # Build:Save reads bandit / pantheon off configTab.input (Build.lua:1005) and Build:Load
    # copies the build-level attributes back into the active set's input (Build.lua:630).
    'build.bandit = p.build_attrs.bandit',
    'build.pantheonMajorGod = p.build_attrs.pantheonMajorGod',
    'build.pantheonMinorGod = p.build_attrs.pantheonMinorGod',
    "for _, key in ipairs({ 'bandit', 'pantheonMajorGod', 'pantheonMinorGod' }) do ct.input[key] = build[key] end",
    'ct:BuildModList()',
    'build.buildFlag = true',
    "runCallback('OnFrame')",
    "return '1'",
)

# D78's ailment-stack surfaces lifted out of the live Baseline config set for one read: the native bleed /
# ignite stack-potential overrides, `multiplierBleedsOnEnemy` when one of them is there, and the custom
# modifier block titled "junkroan: poison stacks ...". Exactly what `ramp_inputs.uncapped_ailment_stack_xml`
# strips from the exported XML (an input counts as present when ConfigTab:Save would write it: its value
# differs from GetDefaultState), written into `build.configTab` in place instead of two whole-build XML
# loads. The epilogue puts the very same values back and recalculates, so the build the next call sees is
# the one this call started from.
_UNCAPPED_PRELUDE_LUA: tuple[str, ...] = (
    'local ct = build.configTab',
    'local base',
    'for _, id in ipairs(ct.configSetOrderList) do',
    '  local cs = ct.configSets[id]',
    "  if cs and cs.title == 'Baseline' then base = cs break end",
    'end',
    "if not base then return '{\"changed\":false}' end",
    'local function present(name)',
    '  local v = base.input[name]',
    '  local kind = type(v)',
    "  return (kind == 'number' or kind == 'boolean' or kind == 'string') and v ~= ct:GetDefaultState(name, kind)",
    'end',
    'local removed = {}',
    "local has_native = present('overrideBleedStackPotential') or present('overrideIgniteStackPotential')",
    'if has_native then',
    "  for _, name in ipairs({ 'overrideBleedStackPotential', 'overrideIgniteStackPotential', 'multiplierBleedsOnEnemy' }) do",
    '    if present(name) then removed[name] = base.input[name] end',
    '  end',
    'end',
    "local prefix = 'junkroan: poison stacks'",
    'local orig_mods = base.customModsList',
    'local kept, dropped = {}, false',
    'for _, block in ipairs(orig_mods or {}) do',
    "  if string.sub(block.title or 'Default', 1, #prefix) == prefix then dropped = true else kept[#kept + 1] = block end",
    'end',
    "if not has_native and not dropped then return '{\"changed\":false}' end",
    'local live = ct.configSets[ct.activeConfigSetId] == base',
    'local function rebuild()',
    '  if live then',
    '    ct:BuildModList()',
    '    build.buildFlag = true',
    "    runCallback('OnFrame')",
    '  end',
    'end',
    'for name in pairs(removed) do base.input[name] = nil end',
    'if dropped then base.customModsList = kept end',
    'rebuild()',
)
# #540: the whole config state of the live build, copied out (`_CONFIG_CHECKPOINT_LUA`) before a probe writes
# config sets over it and put back after (`_CONFIG_ROLLBACK_LUA`): every config set with its inputs,
# placeholders and custom modifier blocks, their order, the active one and the build-level bandit / pantheon
# attributes. What a `load_xml` of the build's own export gave back, without the whole-build load.
_CONFIG_CHECKPOINT_LUA: tuple[str, ...] = (
    'local ct = build.configTab',
    'local function copy(v)',
    "  if type(v) ~= 'table' then return v end",
    '  local out = {}',
    '  for k, x in pairs(v) do out[k] = copy(x) end',
    '  return out',
    'end',
    "rawset(_G, '__junkroan_config_checkpoint', {",
    '  sets = copy(ct.configSets), order = copy(ct.configSetOrderList), active = ct.activeConfigSetId,',
    '  bandit = build.bandit, major = build.pantheonMajorGod, minor = build.pantheonMinorGod,',
    '})',
    "return '1'",
)
_CONFIG_ROLLBACK_LUA: tuple[str, ...] = (
    'local ct = build.configTab',
    "local snap = rawget(_G, '__junkroan_config_checkpoint')",
    "if not snap then error('no config checkpoint to roll back to') end",
    "rawset(_G, '__junkroan_config_checkpoint', nil)",
    'ct.configSets = snap.sets',
    'ct.configSetOrderList = snap.order',
    'ct:SetActiveConfigSet(snap.active)',
    'if ct.ResetUndo then ct:ResetUndo() end',
    'build.bandit = snap.bandit',
    'build.pantheonMajorGod = snap.major',
    'build.pantheonMinorGod = snap.minor',
    'ct:BuildModList()',
    'build.buildFlag = true',
    "runCallback('OnFrame')",
    "return '1'",
)
_UNCAPPED_EPILOGUE_LUA: tuple[str, ...] = (
    'local ok, res = pcall(read_body)',
    'for name, value in pairs(removed) do base.input[name] = value end',
    'if dropped then base.customModsList = orig_mods end',
    'rebuild()',
    'if not ok then error(res, 0) end',
    "return '{\"changed\":true,\"stats\":' .. res .. '}'",
)


# A readback averaged over skill parts (optimizer/random_parts.py: a random-element skill is scored
# as the mean over its element parts). The main skill's gem instance is shared by the main
# environment and every what-if environment (CalcActiveSkill reads `srcInstance.skillPart` when a
# CALCULATOR env is built), so the part is switched on that instance around each evaluation and
# put back; `evaluate` returns one stats table per part and every numeric key is averaged.
_MEAN_PARTS_LUA: tuple[str, ...] = (
    'local function scalar(v)',
    '  local t = type(v)',
    "  if t == 'number' then if v ~= v or v == math.huge or v == -math.huge then return nil end return v end",
    "  if t == 'string' or t == 'boolean' then return v end",
    '  return nil',
    'end',
    'local function main_instance()',
    '  local env = build.calcsTab.mainEnv',
    '  local skill = env and env.player and env.player.mainSkill',
    '  local eff = skill and skill.activeEffect',
    '  return eff and eff.srcInstance',
    'end',
    'local function mean_over_parts(parts, evaluate)',
    '  local inst = main_instance()',
    "  if not inst then error('mean over parts: the main skill has no gem instance') end",
    '  local saved, savedCalcs = inst.skillPart, inst.skillPartCalcs',
    '  local sums, counts, first = {}, {}, nil',
    '  local ok, err = pcall(function()',
    '    for _, p in ipairs(parts) do',
    '      inst.skillPart = p',
    '      inst.skillPartCalcs = p',
    '      local r = evaluate()',
    '      if not first then first = r end',
    "      for k, v in pairs(r) do if type(v) == 'number' then sums[k] = (sums[k] or 0) + v counts[k] = (counts[k] or 0) + 1 end end",
    '    end',
    '  end)',
    '  inst.skillPart = saved',
    '  inst.skillPartCalcs = savedCalcs',
    '  if not ok then error(err, 0) end',
    "  local result = setmetatable({}, { __jsontype = 'object' })",
    "  for k, v in pairs(first or {}) do if type(v) == 'number' then result[k] = sums[k] / counts[k] else result[k] = v end end",
    '  return result',
    'end',
)


_CALCULATOR_OUTPUT_LUA: tuple[str, ...] = (
    'local function calculator_output(override, use_full_dps)',
    '  local calcs = build.calcsTab.calcs',
    "  local env, cachedPlayerDB, cachedEnemyDB, cachedMinionDB = calcs.initEnv(build, 'CALCULATOR', override)",
    '  calcs.perform(env)',
    '  if use_full_dps then',
    "    local fullDPS = calcs.calcFullDPS(build, 'CALCULATOR', override, { cachedPlayerDB = cachedPlayerDB, cachedEnemyDB = cachedEnemyDB, cachedMinionDB = cachedMinionDB, env = nil })",
    '    env.player.output.SkillDPS = fullDPS.skills',
    '    env.player.output.FullDPS = fullDPS.combinedDPS',
    '    env.player.output.FullDotDPS = fullDPS.TotalDotDPS',
    '  end',
    '  return env.player.output, env',
    'end',
)


# #575: a Flask slot is `active` only when PoB's own flask-uptime calculation prints "Flask uptime: 100%".
# PoB computes that only for the item tooltip (ItemsTab.lua:4916-4993, inside AddItemTooltip, which also runs a
# what-if calc per flask); this is the same arithmetic from `item.flaskData` + the calc env's modDB, so a read
# costs a few modDB sums per flask instead of five calcs. `flask_uptime_calc` is pure (numbers in, table out);
# tests/test_flask_uptime_formula.py runs these very lines in a plain Lua (lupa), and
# tests/test_flask_uptime_pob.py checks the flags against PoB's tooltip on real builds.
# The chunk expects the worker's globals `build` and `runCallback`; it defines locals only.
_FLASK_UPTIME_LUA: tuple[str, ...] = tuple(
    r"""
local FLASK_SLOT_NAMES = { 'Flask 1', 'Flask 2', 'Flask 3', 'Flask 4', 'Flask 5' }
-- ItemsTab.lua:4979-4995. duration / chargesUsed: after the duration / charges-used mods; generated /
-- perFlask: charges per second after the gain modifier; notConsume: percent, capped at 100.
-- nil when PoB prints no uptime line for such inputs, else { full = true } or { full = false, avg, min }.
local function flask_uptime_calc(p)
  if not (p.chargesUsed > 0 and p.duration > 0) then return nil end
  local per3 = p.duration - (p.duration % 3)
  local per5 = p.duration - (p.duration % 5)
  local minimum = per3 * p.generated + per5 * p.perFlask
  local percentageMin = math.min(minimum / p.chargesUsed * 100, 100)
  if percentageMin < 100 and p.notConsume < 100 then
    local averageGenerated = (p.generated + p.perFlask) * p.duration
    local averageUsed = p.chargesUsed * (100 - p.notConsume) / 100
    local percentageAvg = math.min(averageGenerated / averageUsed * 100, 100)
    return { full = false, avg = percentageAvg, min = percentageMin }
  end
  return { full = true }
end
local function flask_uptime_line(r)
  if not r then return nil end
  if r.full then return 'Flask uptime: 100%' end
  return string.format('Flask uptime: %d%% average, %d%% minimum', math.floor(r.avg), math.floor(r.min))
end
-- ItemsTab.lua:4818-4906 reduced to what decides `lifeDur` / `manaDur` (zero = an instant-only recovery, no uptime)
local function flask_recovery_durations(item, modDB, output, durInc)
  local flaskData, kind = item.flaskData, item.base.flask
  local effectInc = modDB:Sum('INC', { actor = 'player' }, 'FlaskEffect')
  local rateInc = modDB:Sum('INC', nil, 'FlaskRecoveryRate')
  local lifeDur, manaDur = 0, 0
  if kind.life then
    local lifeInc = modDB:Sum('INC', nil, 'FlaskLifeRecovery')
    local lifeMore = modDB:More(nil, 'FlaskLifeRecovery')
    local lifeRateInc = modDB:Sum('INC', nil, 'FlaskLifeRecoveryRate')
    local instantPerc = flaskData.instantPerc + modDB:Sum('BASE', nil, 'LifeFlaskInstantRecovery')
    local lifeMoreOnLowLife = modDB:More(nil, 'FlaskLifeRecoveryLowLife')
    local lowLifeMulti = (lifeMoreOnLowLife > 1 and ((lifeMoreOnLowLife - 1) / (1 + effectInc / 100)) + 1 or 1)
    local inst = flaskData.lifeBase * instantPerc / 100 * (1 + lifeInc / 100) * lifeMore * (1 + effectInc / 100) * lowLifeMulti
    local gradBase = flaskData.lifeBase * (1 - instantPerc / 100) * (1 + lifeInc / 100) * lifeMore * (1 + effectInc / 100) * (1 + durInc / 100) * lowLifeMulti
    local grad = gradBase * output.LifeRecoveryRateMod
    lifeDur = flaskData.duration * (1 + durInc / 100) / (1 + rateInc / 100) / (1 + lifeRateInc / 100)
    if flaskData.lifeAdditional > 0 and not build.configTab.input.conditionFullLife then
      if inst > 0 and not (grad > 0) then lifeDur = 0 end
    elseif inst > 0 and grad > 0 then
      -- kept
    elseif inst + grad ~= flaskData.lifeTotal or (inst == 0 and lifeDur ~= flaskData.duration) then
      if inst > 0 then lifeDur = 0 end
    end
  end
  if kind.mana then
    local manaInc = modDB:Sum('INC', nil, 'FlaskManaRecovery')
    local manaRateInc = modDB:Sum('INC', nil, 'FlaskManaRecoveryRate')
    local instantPerc = flaskData.instantPerc + modDB:Sum('BASE', nil, 'ManaFlaskInstantRecovery')
    local inst = flaskData.manaBase * instantPerc / 100 * (1 + manaInc / 100) * (1 + effectInc / 100)
    local gradBase = flaskData.manaBase * (1 - instantPerc / 100) * (1 + manaInc / 100) * (1 + effectInc / 100) * (1 + durInc / 100)
    local grad = gradBase * output.ManaRecoveryRateMod
    manaDur = flaskData.duration * (1 + durInc / 100) / (1 + rateInc / 100) / (1 + manaRateInc / 100)
    if inst > 0 and grad > 0 then
      -- kept
    elseif inst + grad ~= flaskData.manaTotal or (inst == 0 and manaDur ~= flaskData.duration) then
      if inst > 0 then manaDur = 0 end
    end
  end
  return lifeDur, manaDur
end
-- ItemsTab.lua:4809-4995 for one flask item: nil (no uptime line) or the flask_uptime_calc table.
-- `emptySlots` = Flask slots holding nothing (ItemsTab.lua:4942-4949).
local function flask_uptime_of(item, modDB, output, emptySlots)
  local kind, flaskData = item.base.flask, item.flaskData
  local durInc = modDB:Sum('INC', nil, 'FlaskDuration')
  local usedInc = modDB:Sum('INC', nil, 'FlaskChargesUsed')
  local gainMod = flaskData.gainMod * (1 + modDB:Sum('INC', nil, 'FlaskChargesGained') / 100)
  local generated = modDB:Sum('BASE', nil, 'FlaskChargesGenerated')
  if kind.life then generated = generated + modDB:Sum('BASE', nil, 'LifeFlaskChargesGenerated') end
  if kind.mana then generated = generated + modDB:Sum('BASE', nil, 'ManaFlaskChargesGenerated') end
  if not kind.mana and not kind.life then generated = generated + modDB:Sum('BASE', nil, 'UtilityFlaskChargesGenerated') end
  local perFlask = modDB:Sum('BASE', nil, 'FlaskChargesGeneratedPerEmptyFlask') * emptySlots
  generated = generated * gainMod
  perFlask = perFlask * gainMod
  local notConsume = math.min(modDB:Sum('BASE', nil, 'FlaskChanceNotConsumeCharges'), 100)
  local hasUptime = not kind.life and not kind.mana
  local duration = flaskData.duration * (1 + durInc / 100)
  if kind.life and (flaskData.lifeEffectNotRemoved or modDB:Flag(nil, 'LifeFlaskEffectNotRemoved')) then
    hasUptime = true
    local lifeDur = flask_recovery_durations(item, modDB, output, durInc)
    duration = lifeDur
  elseif kind.mana and (flaskData.manaEffectNotRemoved or modDB:Flag(nil, 'ManaFlaskEffectNotRemoved')) then
    hasUptime = true
    local _, manaDur = flask_recovery_durations(item, modDB, output, durInc)
    duration = manaDur
  end
  if not hasUptime then return nil end
  return flask_uptime_calc({
    duration = duration, chargesUsed = flaskData.chargesUsed * (1 + usedInc / 100),
    generated = generated, perFlask = perFlask, notConsume = notConsume,
  })
end
-- { [slot name] = { line = <uptime line or nil>, full = <bool> } } for every Flask slot holding a flask,
-- `itemOf(slotName)` giving the item in the slot (nil = empty).
local function flask_uptimes_for(modDB, output, itemOf)
  local emptySlots = 0
  for _, name in ipairs(FLASK_SLOT_NAMES) do
    if not itemOf(name) then emptySlots = emptySlots + 1 end
  end
  local result = {}
  for _, name in ipairs(FLASK_SLOT_NAMES) do
    local item = itemOf(name)
    if item and item.base and item.base.flask and item.flaskData then
      local r = flask_uptime_of(item, modDB, output, emptySlots)
      result[name] = { line = flask_uptime_line(r), full = (r ~= nil and r.full) and true or false }
    end
  end
  return result
end
local function flask_live_item(name)
  local slot = build.itemsTab.slots[name]
  if not slot or not slot.selItemId or slot.selItemId == 0 then return nil end
  return build.itemsTab.items[slot.selItemId]
end
local function flask_slot_active(name)
  return build.itemsTab.slots[name].active and true or false
end
-- the three places the checkbox writes (ItemSlotControl.lua:33-38), as set_flasks_active does
local function flask_set_flag(name, state)
  local slot = build.itemsTab.slots[name]
  slot.active = state
  if slot.controls and slot.controls.activate then slot.controls.activate.state = state end
  local row = build.itemsTab.activeItemSet[name]
  if row then row.active = state end
end
local function flask_flags_snapshot()
  local snap = {}
  for _, name in ipairs(FLASK_SLOT_NAMES) do
    if build.itemsTab.slots[name] then snap[name] = flask_slot_active(name) end
  end
  return snap
end
local function flask_flags_restore(snap)
  local changed = false
  for name, state in pairs(snap) do
    if flask_slot_active(name) ~= state then flask_set_flag(name, state) changed = true end
  end
  if changed then build.buildFlag = true end
end
-- Slots whose flag differs from the uptime derived on the given calc (modDB / output as the calc left them).
local function flask_flips(modDB, output, itemOf)
  local flips, any = {}, false
  for name, r in pairs(flask_uptimes_for(modDB, output, itemOf)) do
    if flask_slot_active(name) ~= r.full then flips[name] = r.full any = true end
  end
  return flips, any
end
-- The fixed point of #575: derive from the calc as the flags stand; when a flag changed, set it and recalc
-- once; zero extra calcs when nothing changed. Leaves the derived flags in the slots (and so in the export).
local function derive_flask_flags()
  if build.buildFlag then runCallback('OnFrame') end
  local env = build.calcsTab.mainEnv
  if not env then return end
  local flips, any = flask_flips(env.modDB, build.calcsTab.mainOutput or env.player.output, flask_live_item)
  if not any then return end
  for name, state in pairs(flips) do flask_set_flag(name, state) end
  build.buildFlag = true
  runCallback('OnFrame')
end
""".strip().splitlines()
)


# What-if evaluations (fast trials): the flags are derived on the trial's own environment; when one differs
# from the slot's, it is set for one more calculator pass and put back, so a trial that brings a charge source
# is credited with the flask in the same evaluation and nothing is kept.
_FLASK_FLASKED_LUA: tuple[str, ...] = (
    'local function trial_item_of(override)',
    '  return function(name)',
    '    if override and override.repSlotName == name and override.repItem then return override.repItem end',
    '    return flask_live_item(name)',
    '  end',
    'end',
    'local function calculator_flasked(override, use_full_dps)',
    '  local out, env = calculator_output(override, use_full_dps)',
    '  local flips, any = flask_flips(env.modDB, out, trial_item_of(override))',
    '  if not any then return out, env end',
    '  local saved = {}',
    '  for name, state in pairs(flips) do saved[name] = { build.itemsTab.slots[name].active } build.itemsTab.slots[name].active = state end',
    '  local ok, out2, env2 = pcall(calculator_output, override, use_full_dps)',
    '  for name, was in pairs(saved) do build.itemsTab.slots[name].active = was[1] end',
    '  if not ok then error(out2, 0) end',
    '  return out2, env2',
    'end',
)


_TRIAL_STATS_FAST_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local payload = json.decode(PAYLOAD_JSON, 1, nil)',
    'local spec = build.spec',
    "if build.buildFlag then runCallback('OnFrame') end",
    'local use_full_dps = false',
    "for _, k in ipairs(payload.keys) do if k == 'FullDPS' then use_full_dps = true end end",
    *_MEAN_PARTS_LUA,
    *_CALCULATOR_OUTPUT_LUA,
    *_FLASK_UPTIME_LUA,
    *_FLASK_FLASKED_LUA,
    "local function lookup(out, env, key)",
    "  if key == 'EnergyShieldProtectsMana' then return env.modDB:Flag(nil, 'EnergyShieldProtectsMana') and 1 or 0 end",
    "  if key == 'MainSkillPermanentMinion' then return (env.player.mainSkill and env.player.mainSkill.skillFlags and env.player.mainSkill.skillFlags.permanentMinion) and 1 or 0 end",
    "  local elem = key == 'FireResistMax' and 'Fire' or (key == 'ColdResistMax' and 'Cold' or (key == 'LightningResistMax' and 'Lightning' or nil))",
    "  if elem and out[elem .. 'Resist'] ~= nil and out['Missing' .. elem .. 'Resist'] ~= nil then",
    "    return out[elem .. 'Resist'] + out['Missing' .. elem .. 'Resist']",
    "  end",
    "  if not string.find(key, '%.') then return out[key] end",
    "  local node = out",
    "  for part in string.gmatch(key, '[^%.]+') do",
    "    if type(node) ~= 'table' then return nil end",
    "    node = node[part]",
    "  end",
    "  return node",
    "end",
    'local function pick(out, env)',
    "  local r = setmetatable({}, { __jsontype = 'object' })",
    '  for _, k in ipairs(payload.keys) do local v = scalar(lookup(out, env, k)) if v ~= nil then r[k] = v end end',
    '  return r',
    'end',
    # A what-if item is never in its slot, but `gemInstance.matchesSocket` (read by CalcSetup.lua:1578,
    # CalcActiveSkill.lua:545) is a persistent flag PoB sets from the item the slot HOLDS
    # (SkillsTab:UpdateSocketGroups, SkillsTab.lua:1230-1237): on an emptied slot it is false for every
    # gem socketed there, so the trial lost the matching-socket quality bonus (#398). Set it from the
    # trial item the way PoB does (the item put in the slot for the call), and set it back after the trial.
    'local TRIAL_ITEM_ID = -398',
    'local function match_sockets_for(slot, item)',
    '  local prev = slot.selItemId',
    '  build.itemsTab.items[TRIAL_ITEM_ID] = item',
    '  slot.selItemId = TRIAL_ITEM_ID',
    '  local ok, err = pcall(build.skillsTab.UpdateSocketGroups, build.skillsTab)',
    '  slot.selItemId = prev',
    '  build.itemsTab.items[TRIAL_ITEM_ID] = nil',
    '  if not ok then error(err, 0) end',
    'end',
    # #1124 unit 4: the red-line marks of a trial (`trial.marks = {add = {mod lines}, remove = {mod lines}}`). The config
    # tab's mod list is what the what-if calculation reads (CalcSetup.lua:579, `env.modDB:AddList(build.configTab.modList)`),
    # so a trial with marks swaps it for a copy without the parsed `remove` mods and with the parsed `add` mods (lines parsed
    # exactly as ConfigTab:BuildModList parses a custom block, ConfigTab.lua:1113-1125), runs the calculator, and the
    # original list is put back after the guarded body, error or not. No extra PoB call; a trial without marks is untouched.
    'local function mark_mods(lines)',
    '  local out = {}',
    '  for _, line in ipairs(lines or {}) do',
    "    local stripped = StripEscapes(line):match('^%s*(.-)%s*$')",
    '    local mods, extra = modLib.parseMod(stripped)',
    '    if mods and not extra then',
    "      for _, m in ipairs(mods) do out[#out + 1] = modLib.setSource(m, 'Custom:junkroan marks') end",
    '    end',
    '  end',
    '  return out',
    'end',
    'local function value_equal(a, b)',
    "  if type(a) ~= 'table' or type(b) ~= 'table' then return a == b end",
    '  for k, v in pairs(a) do if not value_equal(v, b[k]) then return false end end',
    '  for k in pairs(b) do if a[k] == nil then return false end end',
    '  return true',
    'end',
    'local function mod_equal(a, b)',
    '  return modLib.compareModParams(a, b) and value_equal(a.value, b.value)',
    'end',
    'local function marked_modlist(orig, marks)',
    "  local copy = new('ModList')",
    '  local drop = mark_mods(marks.remove)',
    '  for _, m in ipairs(orig) do',
    '    local skip = false',
    '    for j, d in ipairs(drop) do',
    '      if mod_equal(d, m) then table.remove(drop, j) skip = true break end',
    '    end',
    '    if not skip then copy:AddMod(m) end',
    '  end',
    '  for _, m in ipairs(mark_mods(marks.add)) do copy:AddMod(m) end',
    '  return copy',
    'end',
    'derive_flask_flags()',
    'local results = {}',
    'for i, trial in ipairs(payload.trials) do',
    '  local restore = {}',
    '  local added, removed = {}, {}',
    '  local matched = false',
    '  local orig_modlist = nil',
    '  local ok, err = pcall(function()',
    '    if trial.marks then',
    '      orig_modlist = build.configTab.modList',
    '      build.configTab.modList = marked_modlist(orig_modlist, trial.marks)',
    '    end',
    '    local add_nodes, remove_nodes = {}, {}',
    '    for _, id in ipairs(trial.remove or {}) do',
    '      local node = spec.nodes[id]',
    "      if not node then error('unknown node ' .. tostring(id)) end",
    "      if node.alloc and node.type ~= 'ClassStart' and node.type ~= 'AscendClassStart' then remove_nodes[node] = true table.insert(removed, id) end",
    '    end',
    '    for _, id in ipairs(trial.add) do',
    '      local node = spec.nodes[id]',
    "      if not node then error('unknown node ' .. tostring(id)) end",
    '      if not node.alloc then',
    "        if not node.path then error('unreachable node ' .. tostring(id)) end",
    "        if node.type == 'Mastery' then",
    '          local eid = trial.mastery[tostring(id)]',
    '          local eff = eid and spec.tree.masteryEffects[eid]',
    "          if not eff then error('mastery ' .. tostring(id) .. ' needs an effect id') end",
    '          table.insert(restore, { node = node, sd = node.sd, all = node.allMasteryOptions, reminder = node.reminderText })',
    '          node.sd = eff.sd',
    '          node.allMasteryOptions = false',
    '          spec.tree:ProcessStats(node)',
    '        end',
    '        for _, pn in ipairs(node.path) do',
    '          if not pn.alloc and not add_nodes[pn] then add_nodes[pn] = true table.insert(added, pn.id) end',
    '        end',
    '      end',
    '    end',
    "    local override = { addNodes = add_nodes, removeNodes = remove_nodes }",
    "    if trial.item and trial.item.raw then",
    "      local it = new('Item', trial.item.raw)",
    "      if not it.base then error('item trial: PoB could not parse the item base') end",
    "      if trial.item.recraft then it:Craft() it:BuildAndParseRaw() end",
    "      build.itemsTab:CopyAnointsAndEldritchImplicits(it, main.migrateEldritchImplicits, false)",
    "      it:NormaliseQuality()",
    "      it:BuildModList()",
    "      override.repSlotName = trial.item.slot",
    "      override.repItem = it",
    "      local item_slot = build.itemsTab.slots[trial.item.slot]",
    "      if item_slot and not item_slot.nodeId then matched = true match_sockets_for(item_slot, it) end",
    "    end",
    "    local stats",
    "    if payload.parts and #payload.parts > 0 then",
    "      stats = mean_over_parts(payload.parts, function() local out, env = calculator_flasked(override, use_full_dps) return pick(out, env) end)",
    "    else",
    "      local out, env = calculator_flasked(override, use_full_dps)",
    "      stats = pick(out, env)",
    "    end",
    '    table.sort(added)',
    '    table.sort(removed)',
    '    results[i] = { ok = true, added_node_ids = added, removed_node_ids = removed, stats = stats }',
    '  end)',
    '  if orig_modlist then build.configTab.modList = orig_modlist end',
    '  if matched then build.skillsTab:UpdateSocketGroups() end',
    '  for _, r in ipairs(restore) do',
    '    r.node.sd = r.sd',
    '    r.node.allMasteryOptions = r.all',
    '    r.node.reminderText = r.reminder',
    '    spec.tree:ProcessStats(r.node)',
    '  end',
    '  if not ok then results[i] = { ok = false, error = tostring(err), added_node_ids = {}, removed_node_ids = {} } end',
    'end',
    'return json.encode(results)',
)


_TRIAL_STATS_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    *_FLASK_UPTIME_LUA,
    'local payload = json.decode(PAYLOAD_JSON, 1, nil)',
    'local spec = build.spec',
    'local before_alloc = {}',
    'for id, _ in pairs(spec.allocNodes) do before_alloc[id] = true end',
    'local before_mastery = {}',
    'for id, e in pairs(spec.masterySelections) do before_mastery[id] = e end',
    'local function scalar(v)',
    '  local t = type(v)',
    "  if t == 'number' then if v ~= v or v == math.huge or v == -math.huge then return nil end return v end",
    "  if t == 'string' or t == 'boolean' then return v end",
    '  return nil',
    'end',
    'local function read_keys()',
    '  build.buildFlag = true',
    "  runCallback('OnFrame')",
    '  derive_flask_flags()',
    '  local out = build.calcsTab.mainOutput or {}',
    '  local env = build.calcsTab.mainEnv',
    "  local r = setmetatable({}, { __jsontype = 'object' })",
    '  for _, k in ipairs(payload.keys) do',
    "    local v",
    "    if k == 'EnergyShieldProtectsMana' then v = env and env.modDB:Flag(nil, 'EnergyShieldProtectsMana') and 1 or 0",
    "    elseif k == 'MainSkillPermanentMinion' then v = (env and env.player.mainSkill and env.player.mainSkill.skillFlags and env.player.mainSkill.skillFlags.permanentMinion) and 1 or 0",
    "    else",
    "      local elem = k == 'FireResistMax' and 'Fire' or (k == 'ColdResistMax' and 'Cold' or (k == 'LightningResistMax' and 'Lightning' or nil))",
    "      v = (elem and out[elem .. 'Resist'] ~= nil and out['Missing' .. elem .. 'Resist'] ~= nil) and (out[elem .. 'Resist'] + out['Missing' .. elem .. 'Resist']) or out[k]",
    "    end",
    '    v = scalar(v) if v ~= nil then r[k] = v end',
    '  end',
    '  return r',
    'end',
    'local function select_mastery(node, eid)',
    '  local eff = spec.tree.masteryEffects[eid]',
    "  if not eff then error('mastery ' .. tostring(node.id) .. ' has no effect ' .. tostring(eid)) end",
    '  spec.masterySelections[node.id] = eid',
    '  node.sd = eff.sd',
    '  node.allMasteryOptions = false',
    "  node.reminderText = { 'Tip: Right click to select a different effect' }",
    '  spec.tree:ProcessStats(node)',
    'end',
    'local function restore()',
    '  for id, node in pairs(spec.allocNodes) do',
    '    if not before_alloc[id] then spec:DeallocSingleNode(node) end',
    '  end',
    '  for id, _ in pairs(before_alloc) do',
    '    if not spec.allocNodes[id] then local n = spec.nodes[id] n.alloc = true spec.allocNodes[id] = n end',
    '  end',
    '  for id, e in pairs(before_mastery) do',
    '    if spec.masterySelections[id] ~= e then select_mastery(spec.nodes[id], e) end',
    '  end',
    '  for id, _ in pairs(spec.masterySelections) do',
    '    if not before_mastery[id] then spec.masterySelections[id] = nil spec:AddMasteryEffectOptionsToNode(spec.nodes[id]) end',
    '  end',
    '  spec:BuildAllDependsAndPaths()',
    'end',
    # An item trial in full mode is a real equip of the item into its slot (the way `equip` does it),
    # read, and put back: every slot's selected item as it was, the trial item deleted again (#398).
    'local slot_before = {}',
    'for name, slot in pairs(build.itemsTab.slots) do if not slot.nodeId then slot_before[name] = slot.selItemId end end',
    'local function unequip_trial_item(item)',
    '  build.itemsTab:DeleteItem(item, true)',
    '  for name, id in pairs(slot_before) do',
    '    local slot = build.itemsTab.slots[name]',
    '    if slot.selItemId ~= id then slot:SetSelItemId(id) end',
    '  end',
    '  build.itemsTab:PopulateSlots()',
    '  build.buildFlag = true',
    'end',
    'derive_flask_flags()',
    'local flask_snapshot = flask_flags_snapshot()',
    'local results = {}',
    'for i, trial in ipairs(payload.trials) do',
    '  local equipped_item = nil',
    '  local ok, err = pcall(function()',
    '    for _, id in ipairs(trial.remove or {}) do',
    '      local node = spec.nodes[id]',
    "      if node and node.alloc and node.type ~= 'ClassStart' and node.type ~= 'AscendClassStart' then spec:DeallocNode(node) end",
    '    end',
    '    for _, id in ipairs(trial.add) do',
    '      local node = spec.nodes[id]',
    "      if not node then error('unknown node ' .. tostring(id)) end",
    '      if not node.alloc then',
    "        if not node.path then error('unreachable node ' .. tostring(id)) end",
    "        if node.type == 'Mastery' then",
    '          local eid = trial.mastery[tostring(id)]',
    "          if not eid then error('mastery ' .. tostring(id) .. ' needs an effect id') end",
    '          select_mastery(node, eid)',
    '        end',
    '        spec:AllocNode(node)',
    '      end',
    '    end',
    '    if trial.item and trial.item.raw then',
    '      local slot = build.itemsTab.slots[trial.item.slot]',
    "      if not slot or slot.nodeId then error('unsupported item slot ' .. tostring(trial.item.slot)) end",
    '      build.itemsTab:CreateDisplayItemFromRaw(trial.item.raw, true)',
    '      local item = build.itemsTab.displayItem',
    "      if not item then error('item trial: PoB could not parse the item') end",
    '      build.itemsTab:AddItem(item, true)',
    '      build.itemsTab:SetDisplayItem()',
    '      equipped_item = item',
    "      if not build.itemsTab:IsItemValidForSlot(item, trial.item.slot, build.itemsTab.activeItemSet) then error('item is not valid for slot ' .. tostring(trial.item.slot)) end",
    '      slot:SetSelItemId(item.id)',
    '      build.itemsTab:PopulateSlots()',
    '    end',
    '  end)',
    '  local added = {}',
    '  for id, _ in pairs(spec.allocNodes) do if not before_alloc[id] then table.insert(added, id) end end',
    '  table.sort(added)',
    '  local removed = {}',
    '  for id, _ in pairs(before_alloc) do if not spec.allocNodes[id] then table.insert(removed, id) end end',
    '  table.sort(removed)',
    '  local stats = nil',
    '  if ok then stats = read_keys() end',
    '  results[i] = { ok = ok, error = (not ok) and tostring(err) or nil, added_node_ids = added, removed_node_ids = removed, stats = stats }',
    '  if equipped_item then unequip_trial_item(equipped_item) end',
    '  restore()',
    '  flask_flags_restore(flask_snapshot)',
    'end',
    'build.buildFlag = true',
    'return json.encode(results)',
)


_MUTATE_TREE_LUA: tuple[str, ...] = (
    "local json = require('dkjson')",
    'local payload = json.decode(PAYLOAD_JSON, 1, nil)',
    'local spec = build.spec',
    'local before = {}',
    'for node_id, node in pairs(spec.allocNodes) do before[node_id] = true end',
    'local unreachable = {}',
    'local missing = {}',
    'local missing_mastery_effect = {}',
    'local mastery_before = {}',
    # PoB rebuilds every path and dependency itself at the end of AllocNode (PassiveSpec.lua:799)
    # and of DeallocNode (:818); a trailing BuildAllDependsAndPaths() after either would recompute
    # the same answer for ~40 ms. It is kept only for the branch where nothing was allocated or
    # deallocated at all (unknown / unreachable / mastery-without-effect ids), where the tree is
    # untouched and the call is the cheap insurance it always was.
    'local touched = false',
    'for node_id, effect_id in pairs(spec.masterySelections) do mastery_before[node_id] = effect_id end',
    'for _, node_id in ipairs(payload.remove) do',
    '  local node = spec.nodes[node_id]',
    '  if not node then table.insert(missing, node_id)',
    "  elseif node.alloc and node.type ~= 'ClassStart' and node.type ~= 'AscendClassStart' then spec:DeallocNode(node) touched = true end",
    'end',
    'for _, node_id in ipairs(payload.add) do',
    '  local node = spec.nodes[node_id]',
    '  if not node then table.insert(missing, node_id)',
    '  elseif not node.alloc then',
    '    if not node.path then table.insert(unreachable, node_id)',
    "    elseif node.type == 'Mastery' then",
    '      local effect_id = payload.mastery[tostring(node_id)]',
    '      local effect = effect_id and spec.tree.masteryEffects[effect_id]',
    '      if not effect then table.insert(missing_mastery_effect, node_id)',
    '      else',
    '        spec.masterySelections[node_id] = effect_id',
    '        node.sd = effect.sd',
    '        node.allMasteryOptions = false',
    "        node.reminderText = { 'Tip: Right click to select a different effect' }",
    '        spec.tree:ProcessStats(node)',
    '        spec:AllocNode(node)',
    '        touched = true',
    '      end',
    '    else spec:AllocNode(node) touched = true end',
    '  end',
    'end',
    'if not touched then spec:BuildAllDependsAndPaths() end',
    'build.itemsTab:UpdateSockets()',
    'build.buildFlag = true',
    'local used, asc_used = spec:CountAllocNodes()',
    'local allocated = {}',
    'for node_id, node in pairs(spec.allocNodes) do',
    "  if node.type ~= 'ClassStart' and node.type ~= 'AscendClassStart' and not node.ascendancyName then table.insert(allocated, node_id) end",
    'end',
    'table.sort(allocated)',
    'local added, removed = {}, {}',
    'for node_id, _ in pairs(spec.allocNodes) do if not before[node_id] then table.insert(added, node_id) end end',
    'for node_id, _ in pairs(before) do if not spec.allocNodes[node_id] then table.insert(removed, node_id) end end',
    'table.sort(added)',
    'table.sort(removed)',
    'local removed_mastery = {}',
    'for node_id, effect_id in pairs(mastery_before) do',
    "  if not spec.masterySelections[node_id] then table.insert(removed_mastery, tostring(node_id) .. ':' .. tostring(effect_id)) end",
    'end',
    'table.sort(removed_mastery)',
    'return json.encode({ allocated_node_ids = allocated, added_node_ids = added, removed_node_ids = removed, removed_mastery_effects = removed_mastery, points_used = used, ascendancy_points_used = asc_used, missing = missing, unreachable = unreachable, missing_mastery_effect = missing_mastery_effect })',
)

# The pre-2026-09-18 chunk, kept only as the equivalence reference of
# tests/test_pob_inplace_writes.py: it rebuilt every path a second time after PoB had
# already done it. Nothing in the product calls it.
_MUTATE_TREE_LUA_ALWAYS_REBUILD: tuple[str, ...] = tuple(
    'spec:BuildAllDependsAndPaths()' if line == 'if not touched then spec:BuildAllDependsAndPaths() end' else line
    for line in _MUTATE_TREE_LUA
)


class LuaJITBridge:
    """Very small Lua 5.1 / LuaJIT bridge over the pinned `lua51.dll`."""

    def __init__(self, dll_path: Path) -> None:
        if not dll_path.is_file():
            raise WorkerContractError("runtime_dependency_missing", f"Missing lua runtime DLL: {dll_path}")

        self._dll = ctypes.CDLL(str(dll_path))
        self._state = self._configure_api()

    def _configure_api(self) -> ctypes.c_void_p:
        lua_state_p = ctypes.c_void_p
        size_ptr = ctypes.POINTER(ctypes.c_size_t)

        self._dll.luaL_newstate.restype = lua_state_p
        self._dll.luaL_openlibs.argtypes = [lua_state_p]
        self._dll.lua_close.argtypes = [lua_state_p]
        self._dll.luaL_loadstring.argtypes = [lua_state_p, ctypes.c_char_p]
        self._dll.luaL_loadstring.restype = ctypes.c_int
        self._dll.luaL_loadfile.argtypes = [lua_state_p, ctypes.c_char_p]
        self._dll.luaL_loadfile.restype = ctypes.c_int
        self._dll.lua_pcall.argtypes = [lua_state_p, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self._dll.lua_pcall.restype = ctypes.c_int
        self._dll.lua_tolstring.argtypes = [lua_state_p, ctypes.c_int, size_ptr]
        self._dll.lua_tolstring.restype = ctypes.c_void_p
        self._dll.lua_settop.argtypes = [lua_state_p, ctypes.c_int]

        state = self._dll.luaL_newstate()
        if not state:
            raise WorkerContractError("runtime_launch_failed", "Could not allocate a Lua state for the pinned PoB runtime.")
        self._dll.luaL_openlibs(state)
        return state

    def _clear_stack(self) -> None:
        self._dll.lua_settop(self._state, 0)

    def _stack_string(self, index: int) -> str | None:
        size = ctypes.c_size_t()
        raw = self._dll.lua_tolstring(self._state, index, ctypes.byref(size))
        if not raw:
            return None
        return ctypes.string_at(raw, size.value).decode("utf-8", "replace")

    def execute(self, code: str, *, nret: int = 0) -> list[str | None]:
        self._clear_stack()
        rc = self._dll.luaL_loadstring(self._state, code.encode("utf-8"))
        if rc != 0:
            message = self._stack_string(-1) or "Unknown Lua load error."
            self._clear_stack()
            raise WorkerContractError("runtime_protocol_failed", message)

        rc = self._dll.lua_pcall(self._state, 0, nret, 0)
        if rc != 0:
            message = self._stack_string(-1) or "Unknown Lua execution error."
            self._clear_stack()
            raise WorkerContractError("runtime_protocol_failed", message)

        results = [self._stack_string(index) for index in range(1, nret + 1)]
        self._clear_stack()
        return results

    def load_file(self, path: Path) -> None:
        self._clear_stack()
        rc = self._dll.luaL_loadfile(self._state, str(path).encode("utf-8"))
        if rc != 0:
            message = self._stack_string(-1) or f"Could not load Lua file {path}."
            self._clear_stack()
            raise WorkerContractError("runtime_launch_failed", message)

        rc = self._dll.lua_pcall(self._state, 0, 0, 0)
        if rc != 0:
            message = self._stack_string(-1) or f"Could not execute Lua file {path}."
            self._clear_stack()
            raise WorkerContractError("runtime_launch_failed", message)

    def close(self) -> None:
        if self._state:
            self._dll.lua_close(self._state)
            self._state = ctypes.c_void_p()


_JIT_MIN_MAXTRACE = 4000
_JIT_MIN_MAXMCODE = 8192


def check_jit_guard(raw: str | None) -> dict[str, Any]:
    """The pinned runtime's LuaJIT state, read back at boot ("status|version|maxtrace|maxmcode").

    LuaJIT's trace cache is what makes PoB's calc affordable: measured 2026-09-18 on
    stormbrand, one fast trial is 5.2-5.4 ms under Launch.lua's
    `jit.opt.start('maxtrace=4000','maxmcode=8192')` and 12.4-13.8 ms under LuaJIT's
    defaults (maxtrace=1000), where the live trace count collapses from ~1,500 to
    158-620 between runs: the cache thrashes. A PoB bump that drops that line, or a
    lua51.dll built without the JIT, would cost +140% on every one of a build's ~123,000
    trials in silence. So it fails the boot instead, naming the value it found.
    """

    parts = (raw or "").split("|")
    if len(parts) != 4:
        raise WorkerContractError(
            "runtime_launch_failed",
            f"Could not read LuaJIT's state back from the headless wrapper (got {raw!r}).",
        )
    status_text, version, maxtrace_text, maxmcode_text = (part.strip() for part in parts)
    if status_text != "true":
        raise WorkerContractError(
            "runtime_launch_failed",
            f"LuaJIT's JIT compiler is off in the pinned runtime (jit.status() = {status_text or 'nil'}, {version or 'unknown build'}).",
        )

    def _applied(name: str, text: str, minimum: int) -> int:
        if not text.isdigit():
            raise WorkerContractError(
                "runtime_launch_failed",
                f"Launch.lua applied no jit.opt {name} in the pinned runtime ({version}); "
                f"expected {name}={minimum} or more (LuaJIT's default costs +140% per trial).",
            )
        value = int(text)
        if value < minimum:
            raise WorkerContractError(
                "runtime_launch_failed",
                f"Launch.lua applied jit.opt {name}={value} in the pinned runtime ({version}); "
                f"expected {minimum} or more: a trace cache this small thrashes on PoB's calc "
                f"(measured 12.4-13.8 ms per fast trial against 5.2-5.4 ms).",
            )
        return value

    return {
        "status": True,
        "version": version,
        "maxtrace": _applied("maxtrace", maxtrace_text, _JIT_MIN_MAXTRACE),
        "maxmcode": _applied("maxmcode", maxmcode_text, _JIT_MIN_MAXMCODE),
    }


class HeadlessLuaRuntime:
    """Persistent headless PoB runtime living inside one worker process."""

    def __init__(self, *, runtime_root: Path, session_root: Path, wrapper_path: Path) -> None:
        self.runtime_root = runtime_root
        self.session_root = session_root
        self.wrapper_path = wrapper_path
        self._previous_cwd = Path.cwd()
        self._bridge = LuaJITBridge(runtime_root / "lua51.dll")

        self._validate_runtime()
        self._bootstrap()

    def _validate_runtime(self) -> None:
        required_paths = (
            self.runtime_root / "Launch.lua",
            self.runtime_root / "manifest.xml",
            self.runtime_root / "lua51.dll",
            self.wrapper_path,
        )
        missing = [str(path) for path in required_paths if not path.is_file()]
        if missing:
            raise WorkerContractError(
                "runtime_dependency_missing",
                "Pinned PoB runtime is missing required files: " + ", ".join(missing),
            )

    def _bootstrap(self) -> None:
        os.chdir(self.runtime_root)
        bootstrap = "\n".join(
            (
                "print = function(...) end",
                "arg = {}",
                "package.path = package.path"
                f" .. ';{self.runtime_root.as_posix()}/?.lua'"
                f" .. ';{self.runtime_root.as_posix()}/?/init.lua'"
                f" .. ';{self.runtime_root.as_posix()}/lua/?.lua'"
                f" .. ';{self.runtime_root.as_posix()}/lua/?/init.lua'"
                f" .. ';{self.runtime_root.as_posix()}/lua/?/?.lua'",
                f"package.cpath = package.cpath .. ';{self.runtime_root.as_posix()}/?.dll'",
            )
        )
        self._bridge.execute(bootstrap)
        self._bridge.load_file(self.wrapper_path)
        prompt_message = self._bridge.execute("return mainObject and mainObject.promptMsg or nil", nret=1)[0]
        if prompt_message:
            raise WorkerContractError("runtime_launch_failed", prompt_message)
        self.jit_guard = check_jit_guard(self._bridge.execute("return headlessJitState()", nret=1)[0])

    def create_blank_build(self) -> None:
        self._bridge.execute(
            "\n".join(
                (
                    "newBuild()",
                    f"build.spec:SelectClass({_CANONICAL_BLANK_CLASS_ID})",
                    "runCallback('OnFrame')",
                )
            )
        )

    def apply_identity_state(self, identity_payload: dict[str, Any]) -> None:
        payload = _require_mapping(identity_payload, "identity_payload")
        allowed_keys = {"level", "character_level_auto_mode"}
        extra_keys = sorted(set(payload) - allowed_keys)
        if extra_keys:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Unsupported identity_payload field(s): " + ", ".join(extra_keys),
            )
        level = _require_int(payload.get("level"), "identity_payload.level")
        if level < 1 or level > 100:
            raise WorkerContractError("runtime_protocol_failed", "identity_payload.level must be between 1 and 100.")
        character_level_auto_mode = payload.get("character_level_auto_mode", False)
        if character_level_auto_mode is not None:
            character_level_auto_mode = _require_bool(
                character_level_auto_mode,
                "identity_payload.character_level_auto_mode",
            )
        else:
            character_level_auto_mode = False

        self._bridge.execute(
            "\n".join(
                (
                    f"build.characterLevel = {level}",
                    f"build.characterLevelAutoMode = {_bool_xml(character_level_auto_mode)}",
                    "if build.controls and build.controls.characterLevel then",
                    f"  build.controls.characterLevel:SetText({level})",
                    "end",
                    "if build.controls and build.controls.levelScalingButton then",
                    "  build.controls.levelScalingButton.label = build.characterLevelAutoMode and 'Auto' or 'Manual'",
                    "end",
                    "runCallback('OnFrame')",
                )
            )
        )

    def read_stats(self, keys: list[str] | None, parts: list[int] | None = None, keep_flask_flags: bool = False) -> dict[str, Any]:
        """Fast path: recalc if dirty and return scalar mainOutput stats.

        Skips the config-state XML export, display families, and the second
        lane that the full calc snapshot produces. ``keys`` limits the result;
        None returns every scalar stat. ``parts`` (skill part indices of the
        main skill) averages the numbers over those parts: each part is run
        through PoB's what-if calculator on the build as it stands (the same
        calculator the fast trials use, so the two agree), the selected part
        is restored, and every numeric stat is the mean over the parts
        (strings and booleans come from the first).
        """

        raw = self._bridge.execute(self._read_stats_chunk(keys, parts, keep_flask_flags=keep_flask_flags), nret=1)
        return json.loads(raw[0] or "{}")

    def read_stats_uncapped(self, keys: list[str] | None, parts: list[int] | None = None) -> dict[str, Any]:
        """`read_stats` of the build without D78's ailment-stack surfaces, written in place and put back.

        {"changed": False} when the Baseline config set holds none of them (nothing was touched);
        otherwise {"changed": True, "stats": <read_stats result>}, read with the surfaces removed from the
        live Baseline set (`_UNCAPPED_PRELUDE_LUA`), the set restored and the build recalculated afterwards.
        """

        raw = self._bridge.execute(self._read_stats_chunk(keys, parts, uncapped=True), nret=1)
        return json.loads(raw[0] or "{}")

    def checkpoint_config(self) -> None:
        """Remember the live build's whole config state (`_CONFIG_CHECKPOINT_LUA`); one checkpoint at a time."""

        self._bridge.execute("\n".join(_CONFIG_CHECKPOINT_LUA), nret=1)

    def rollback_config(self) -> None:
        """Put the config state of the last `checkpoint_config` back and recalculate; errors without one."""

        self._bridge.execute("\n".join(_CONFIG_ROLLBACK_LUA), nret=1)

    def _read_stats_chunk(self, keys: list[str] | None, parts: list[int] | None, *, uncapped: bool = False, keep_flask_flags: bool = False) -> str:
        keys_json = json.dumps(keys or [], allow_nan=False)
        parts_json = json.dumps([int(p) for p in parts] if parts else [], allow_nan=False)
        head = (
            "local json = require('dkjson')",
            *_FLASK_UPTIME_LUA,
            f"local wanted = json.decode({_lua_long_string(keys_json)}, 1, nil)",
            f"local parts = json.decode({_lua_long_string(parts_json)}, 1, nil)",
        )
        core = (
                    "if build.buildFlag then runCallback('OnFrame') end",
                    *(() if keep_flask_flags else ("derive_flask_flags()",)),
                    *_MEAN_PARTS_LUA,
                    "local function collect(out)",
                    "  local result = setmetatable({}, { __jsontype = 'object' })",
                    "  local function lookup(key)",
                    "    if key == 'EnergyShieldProtectsMana' then",
                    "      local env = build.calcsTab.mainEnv",
                    "      return env and env.modDB:Flag(nil, 'EnergyShieldProtectsMana') and 1 or 0",
                    "    end",
                    # #1015: PoB's `skillFlags.permanentMinion` of the main skill (baseFlags or the `infinite_minion_duration` stat, SkillStatMap.lua:25)
                    "    if key == 'MainSkillPermanentMinion' then",
                    "      local env = build.calcsTab.mainEnv",
                    "      local main = env and env.player and env.player.mainSkill",
                    "      return (main and main.skillFlags and main.skillFlags.permanentMinion) and 1 or 0",
                    "    end",
                    # #702: the boss ailment threshold exactly as CalcOffence.lua:5209-5218 builds it, and each
                    # non-damaging ailment's minimum effect (data.nonDamagingAilment), read from PoB's own tables
                    "    if key == 'EnemyAilmentThreshold' then",
                    "      local env = build.calcsTab.mainEnv",
                    "      if not env or not env.enemyDB then return nil end",
                    "      local isBoss = env.configInput['enemyIsBoss'] ~= 'None'",
                    "      local level = env.enemyLevel",
                    "      local lifeMult, ailmentMult = 1, 1",
                    "      if level >= 66 then",
                    "        lifeMult = isBoss and data.mapLevelBossLifeMult[level] or data.mapLevelLifeMult[level]",
                    "        ailmentMult = isBoss and data.mapLevelBossAilmentMult[level] or ailmentMult",
                    "      end",
                    "      return data.monsterAilmentThresholdTable[level] * (isBoss and 7.68 or 1) * lifeMult * env.enemyDB:More(nil, 'Life') * ailmentMult * env.enemyDB:More(nil, 'AilmentThreshold')",
                    "    end",
                    "    local minimum_of = string.match(key, '^AilmentMinimum(%a+)$')",
                    "    if minimum_of then return data.nonDamagingAilment[minimum_of] and data.nonDamagingAilment[minimum_of].min or nil end",
                    "    local elem = key == 'FireResistMax' and 'Fire' or (key == 'ColdResistMax' and 'Cold' or (key == 'LightningResistMax' and 'Lightning' or nil))",
                    "    if elem and out[elem .. 'Resist'] ~= nil and out['Missing' .. elem .. 'Resist'] ~= nil then",
                    "      return out[elem .. 'Resist'] + out['Missing' .. elem .. 'Resist']",
                    "    end",
                    "    local node = out",
                    "    for part in string.gmatch(key, '[^%.]+') do",
                    "      if type(node) ~= 'table' then return nil end",
                    "      node = node[part]",
                    "    end",
                    "    return node",
                    "  end",
                    "  if #wanted > 0 then",
                    "    for _, key in ipairs(wanted) do local v = scalar(lookup(key)) if v ~= nil then result[key] = v end end",
                    "  else",
                    "    for key, v in pairs(out) do if type(key) == 'string' then local sv = scalar(v) if sv ~= nil then result[key] = sv end end end",
                    "  end",
                    "  return result",
                    "end",
                    "local result",
                    "if #parts > 0 then",
                    "  local calcFunc = build.calcsTab:GetMiscCalculator()",
                    "  if not calcFunc then error('PoB misc calculator is not available (build not calculated yet)') end",
                    "  local use_full_dps = false",
                    "  for _, k in ipairs(wanted) do if k == 'FullDPS' then use_full_dps = true end end",
                    "  result = mean_over_parts(parts, function() return collect(calcFunc({}, use_full_dps)) end)",
                    "else",
                    "  result = collect(build.calcsTab.mainOutput or {})",
                    "end",
                    "return json.encode(result)",
        )
        if not uncapped:
            return "\n".join((*head, *core))
        # the flags derived under the lifted config are not kept: the build the next call sees is the one this call started from
        return "\n".join(
            (
                *head,
                *_UNCAPPED_PRELUDE_LUA,
                "local function read_body()",
                "  local flask_before = flask_flags_snapshot()",
                "  local read_ok, read_res = pcall(function()",
                *core,
                "  end)",
                "  flask_flags_restore(flask_before)",
                "  if not read_ok then error(read_res, 0) end",
                "  return read_res",
                "end",
                *_UNCAPPED_EPILOGUE_LUA,
            )
        )

    def read_active_skill_stats(self, skill_ids: list[str], keys: list[str]) -> dict[str, dict[str, Any]]:
        """Read selected active skills' output and restore every main-skill selection.

        The Flask flags are derived for each skill read (#575: a flask's uptime depends on the main skill's modDB,
        so the flags a skill is read under are that skill's own) and once more for the build's own main skill after
        the selection is put back: the flags this call leaves are the ones a stats read of the build would leave.
        """

        skill_ids_json = json.dumps(skill_ids, allow_nan=False)
        keys_json = json.dumps(keys, allow_nan=False)
        raw = self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    *_FLASK_UPTIME_LUA,
                    f"local wanted = json.decode({_lua_long_string(skill_ids_json)}, 1, nil)",
                    f"local keys = json.decode({_lua_long_string(keys_json)}, 1, nil)",
                    "local wanted_set = {}",
                    "for _, id in ipairs(wanted) do wanted_set[id] = true end",
                    "local function scalar(v)",
                    "  local t = type(v)",
                    "  if t == 'number' then if v ~= v or v == math.huge or v == -math.huge then return nil end return v end",
                    "  if t == 'string' or t == 'boolean' then return v end",
                    "  return nil",
                    "end",
                    "local skills_tab = build.skillsTab",
                    "local old_set = skills_tab.activeSkillSetId",
                    "local old_group = build.mainSocketGroup",
                    "local old_active = {}",
                    "for _, set_index in ipairs(skills_tab.skillSetOrderList or {}) do",
                    "  for group_index, group in ipairs((skills_tab.skillSets[set_index] or {}).socketGroupList or {}) do",
                    "    old_active[tostring(set_index) .. ':' .. tostring(group_index)] = { group.mainActiveSkill, group.mainActiveSkillCalcs }",
                    "  end",
                    "end",
                    "local result = setmetatable({}, { __jsontype = 'object' })",
                    # #908: PoB's trigger handler takes as the source of a mana-spent trigger (Manaforged Arrows) the bow
                    # attack with the highest rate, the first listed on a tie (CalcTriggers.lua:74-86), and `isTriggered`
                    # is the filter it asks (:405). A Vaal gem lists its Vaal skill (souls, no mana cost) ahead of its own
                    # plain twin at the same rate, so a Frenzy triggered by it read Speed 0 ("Source skill has no mana
                    # cost", :551-553) where the plain gem reads 0.725. A Vaal skill is not a sustained source: while a skill is
                    # read, every Vaal skill but the one being read counts as triggered, i.e. is not a candidate source.
                    "local reading_effect = nil",
                    "local original_is_triggered = isTriggered",
                    "if original_is_triggered and SkillType and SkillType.Vaal then",
                    "  isTriggered = function(skill)",
                    "    local types = skill and skill.skillTypes",
                    "    if types and types[SkillType.Vaal] and not (skill.activeEffect and skill.activeEffect.grantedEffect == reading_effect) then return true end",
                    "    return original_is_triggered(skill)",
                    "  end",
                    "end",
                    "local ok, err = xpcall(function()",
                    "  for _, set_index in ipairs(skills_tab.skillSetOrderList or {}) do",
                    "    skills_tab:SetActiveSkillSet(set_index)",
                    "    for group_index, group in ipairs(skills_tab.socketGroupList or {}) do",
                    "      for active_index, active in ipairs(group.displaySkillList or {}) do",
                    "        local effect = active.activeEffect and active.activeEffect.grantedEffect or nil",
                    "        local id = effect and effect.id or nil",
                    "        local source = active.activeEffect and active.activeEffect.srcInstance or nil",
                    "        local skill_set_id = set_index == 1 and 'skills.main' or ('skills.' .. tostring(set_index))",
                    "        local active_id = skill_set_id .. '.socket_group.' .. tostring(group_index) .. '.active_skill.' .. tostring(active_index)",
                    "        if group.enabled and (not source or source.enabled) and id and (wanted_set[id] or wanted_set[active_id]) then",
                    "          build.mainSocketGroup = group_index",
                    "          group.mainActiveSkill = active_index",
                    "          group.mainActiveSkillCalcs = active_index",
                    "          reading_effect = effect",
                    "          build.buildFlag = true",
                    "          runCallback('OnFrame')",
                    "          derive_flask_flags()",
                    "          local row = setmetatable({}, { __jsontype = 'object' })",
                    "          for _, key in ipairs(keys) do",
                    "            local value",
                    "            if key == 'ManaReservedPercent' or key == 'LifeReservedPercent' then value = active.skillData and active.skillData[key]",
                    "            else value = (build.calcsTab.mainOutput or {})[key] end",
                    "            value = scalar(value)",
                    "            if value ~= nil then row[key] = value end",
                    "          end",
                    "          if wanted_set[id] then result[id] = row end",
                    "          if wanted_set[active_id] then result[active_id] = row end",
                    "        end",
                    "      end",
                    "    end",
                    "  end",
                    "end, debug.traceback)",
                    "isTriggered = original_is_triggered",
                    "for _, set_index in ipairs(skills_tab.skillSetOrderList or {}) do",
                    "  for group_index, group in ipairs((skills_tab.skillSets[set_index] or {}).socketGroupList or {}) do",
                    "    local saved = old_active[tostring(set_index) .. ':' .. tostring(group_index)]",
                    "    if saved then group.mainActiveSkill = saved[1]; group.mainActiveSkillCalcs = saved[2] end",
                    "  end",
                    "end",
                    "skills_tab:SetActiveSkillSet(old_set)",
                    "build.mainSocketGroup = old_group",
                    "build.buildFlag = true",
                    "runCallback('OnFrame')",
                    "derive_flask_flags()",
                    "if not ok then error(err) end",
                    "return json.encode(result)",
                )
            ),
            nret=1,
        )
        payload = json.loads(raw[0] or "{}")
        return {str(skill_id): dict(values) for skill_id, values in payload.items() if isinstance(values, dict)}

    def flask_flags_fingerprint(self) -> str:
        """The five Flask slots' `active` flags as one string ("1" / "0", "-" for a slot PoB does not have): the
        worker compares it around a call that derives the flags (`_FLASK_DERIVING_ACTIONS`), in the Lua state,
        without a round trip to the host."""

        raw = self._bridge.execute(
            "local t = {} for i = 1, 5 do local s = build and build.itemsTab and build.itemsTab.slots['Flask ' .. i] "
            "t[i] = s and (s.active and '1' or '0') or '-' end return table.concat(t)",
            nret=1,
        )
        return raw[0] or ""

    def read_mana_cost_warnings(self) -> list[str]:
        """PoB MAIN mode's own mana-cost warning list for the current build."""

        raw = self._bridge.execute(
            "\n".join((
                "local json = require('dkjson')",
                "if build.buildFlag then runCallback('OnFrame') end",
                "local warnings = (build.calcsTab.mainOutput or {}).ManaCostWarningList or {}",
                "local result = {}",
                "for _, name in ipairs(warnings) do if type(name) == 'string' then table.insert(result, name) end end",
                "return json.encode(result)",
            )),
            nret=1,
        )
        value = json.loads(raw[0] or "[]")
        return [str(name) for name in value] if isinstance(value, list) else []

    def read_granted_passives(self) -> list[int]:
        """Node ids PoB's MAIN calculation allocated through a `GrantedPassive` mod (an amulet anoint),
        not through the tree: they are in the calc env, not in `spec.allocNodes`."""

        raw = self._bridge.execute(
            "\n".join((
                "local json = require('dkjson')",
                "if build.buildFlag then runCallback('OnFrame') end",
                "local ids = {}",
                "for node_id, _ in pairs((build.calcsTab.mainEnv or {}).grantedPassives or {}) do table.insert(ids, node_id) end",
                "table.sort(ids)",
                "return json.encode({ node_ids = ids })",
            )),
            nret=1,
        )
        value = json.loads(raw[0] or "{}")
        return [int(n) for n in value.get("node_ids") or []]

    def parse_mods(self, request: dict[str, Any]) -> dict[str, Any]:
        """Run mod lines through PoB's own parser (modLib.parseMod); structured mods with tags."""

        payload = _require_mapping(request, "parse_mods_request")
        lines = [str(x) for x in _require_array(payload.get("lines") or [], "parse_mods_request.lines")]
        chunk = "\n".join(_PARSE_MODS_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps({"lines": lines}, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def uniques(self, request: dict[str, Any]) -> dict[str, Any]:
        """One unique by name (raw item text from PoB's unique database) or the whole list."""

        payload = _require_mapping(request, "uniques_request")
        name = payload.get("name")
        if name is not None and not isinstance(name, str):
            raise WorkerContractError("runtime_protocol_failed", "uniques_request.name must be a string.")
        chunk = "\n".join(_UNIQUES_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps({"name": name}, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def read_config_options(self, request: dict[str, Any]) -> dict[str, Any]:
        """Which config inputs PoB shows for the current build (its predicate logic), their
        current values, and which mods reference the underlying conditions/multipliers."""

        payload = _require_mapping(request, "config_options_request")
        predicates = payload.get("predicates") or {}
        if not isinstance(predicates, dict):
            raise WorkerContractError("runtime_protocol_failed", "config_options_request.predicates must be an object.")
        condition_flag_vars = [str(var) for var in _require_array(payload.get("condition_flag_vars") or [], "config_options_request.condition_flag_vars")]
        chunk = "\n".join(_CONFIG_OPTIONS_LUA).replace(
            "REQUEST_JSON",
            _lua_long_string(json.dumps({"predicates": predicates, "condition_flag_vars": condition_flag_vars}, allow_nan=False)),
        )
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def list_bench_mods(self, request: dict[str, Any]) -> dict[str, Any]:
        """Crafting bench mods PoB allows on a base's item type (data.masterMods)."""

        payload = _require_mapping(request, "bench_mods_request")
        base = payload.get("base")
        if not isinstance(base, str) or not base:
            raise WorkerContractError("runtime_protocol_failed", "bench_mods_request.base must be a base item name.")
        ilvl = payload.get("ilvl")
        req = {"base": base, "ilvl": _require_int(ilvl, "bench_mods_request.ilvl") if ilvl is not None else None, "range": float(payload.get("range", 0.5))}
        chunk = "\n".join(_LIST_BENCH_MODS_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(req, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def read_tree_light(self, request: dict[str, Any]) -> dict[str, Any]:
        """The three tree fields the optimizer asks for on every step (class, allocated nodes without
        the engine's start nodes, mastery selections), straight from `build.spec`: the same values
        `read_state` reports in `tree_state`, without exporting and parsing the whole build."""

        _require_mapping(request, "tree_light_request")
        raw = self._bridge.execute("\n".join(_TREE_LIGHT_LUA), nret=1)
        return json.loads(raw[0] or "{}")

    def convert_tree(self, request: dict[str, Any]) -> dict[str, Any]:
        """Convert the active passive spec to another tree version through PoB's own
        `TreeTab:ConvertToVersion`, and recalc.

        Request: {"version": "3_29" | null}; null means PoB's `latestTreeVersion`.
        Returns {"from", "to", "converted", "nodes_before", "nodes_after", "lost_node_ids"}.
        """

        payload = _require_mapping(request, "convert_tree_request")
        extra = sorted(set(payload) - {"version"})
        if extra:
            raise WorkerContractError("runtime_protocol_failed", "Unsupported convert_tree_request field(s): " + ", ".join(extra))
        version = payload.get("version")
        if version is not None and (not isinstance(version, str) or not version):
            raise WorkerContractError("runtime_protocol_failed", "convert_tree_request.version must be a non-empty string or null.")
        chunk = "\n".join(_CONVERT_TREE_LUA).replace("PAYLOAD_JSON", _lua_long_string(json.dumps({"version": version}, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def read_config_inputs(self, request: dict[str, Any]) -> dict[str, Any]:
        """{"inputs": {var: bool | number | str}} of the active config set: the same rows
        `ConfigTab:Save` writes into <Config>, without the export and the XML parse."""

        _require_mapping(request, "config_inputs_request")
        raw = self._bridge.execute("\n".join(_CONFIG_INPUTS_LUA), nret=1)
        return json.loads(raw[0] or "{}")

    def unsupported_gems(self, request: dict[str, Any]) -> dict[str, Any]:
        """PoB's own verdict on every enabled support gem of the current build: the ones its
        MAIN calc applied to no active skill of their group (the skills tab's "Cannot apply
        to any of the active skills") or superseded by a stronger copy."""

        _require_mapping(request, "unsupported_gems_request")
        chunk = "\n".join(_UNSUPPORTED_GEMS_LUA)
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def random_rares(self, request: dict[str, Any]) -> dict[str, Any]:
        """Roll N random rares on a base using PoB's spawn weights (loot simulation)."""

        payload = _require_mapping(request, "random_rares_request")
        base = payload.get("base")
        if not isinstance(base, str) or not base:
            raise WorkerContractError("runtime_protocol_failed", "random_rares_request.base must be a base item name.")
        req = {
            "base": base,
            "n": _require_int(payload.get("n", 100), "random_rares_request.n"),
            "ilvl": _require_int(payload.get("ilvl", 70), "random_rares_request.ilvl"),
            "quality": _require_int(payload.get("quality", 20), "random_rares_request.quality"),
            "sockets": payload.get("sockets"),
            "seed": _require_int(payload.get("seed", 1), "random_rares_request.seed"),
            "mod_counts": [_require_int(v, "random_rares_request.mod_counts[]") for v in _require_array(payload.get("mod_counts") or [4, 4, 4, 5, 5, 6], "random_rares_request.mod_counts")],
            "pool": str(payload.get("pool") or "explicit"),
            "families": _require_families(payload.get("families"), "random_rares_request.families"),
            "forced": [
                [str(mod_id) for mod_id in _require_array(ids, f"random_rares_request.forced[{index}]")]
                for index, ids in enumerate(_require_array(payload.get("forced") or [], "random_rares_request.forced"))
            ],
        }
        chunk = "\n".join(_RANDOM_RARES_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(req, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def equip_items(self, request: dict[str, Any]) -> dict[str, Any]:
        """Equip raw item text into named slots of the active item set; other slots untouched.
        raw None/empty unequips the slot."""

        payload = _require_mapping(request, "equip_request")
        items = []
        for index, entry in enumerate(_require_array(payload.get("items") or [], "equip_request.items"), start=1):
            entry = _require_mapping(entry, f"equip_request.items[{index}]")
            slot = entry.get("slot")
            if not isinstance(slot, str) or not slot:
                raise WorkerContractError("runtime_protocol_failed", f"equip_request.items[{index}].slot must be a slot name.")
            raw = entry.get("raw")
            if raw is not None and not isinstance(raw, str):
                raise WorkerContractError("runtime_protocol_failed", f"equip_request.items[{index}].raw must be a string or null.")
            items.append({"slot": slot, "raw": raw})
        request_json = {"items": items, **({"drop_replaced": True} if payload.get("drop_replaced") is True else {})}
        chunk = "\n".join(_EQUIP_ITEMS_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(request_json, allow_nan=False)))
        raw_result = self._bridge.execute(chunk, nret=1)
        return json.loads(raw_result[0] or "{}")

    def socket_jewels(self, request: dict[str, Any]) -> dict[str, Any]:
        """Put jewels into / take jewels out of allocated passive-tree sockets; the rest of the build is untouched.

        Request: {"remove": [node_id], "put": [{"node_id", "raw"}]} (remove runs first; both optional, so an
        empty request only reads). Putting into a socket that is not allocated raises. Returns
        {"jewels": [{node_id, allocated, name, raw}]}: every jewel PoB holds in a tree socket, cluster jewels included.
        """

        payload = _require_mapping(request, "socket_jewels_request")
        remove = [_require_int(v, "socket_jewels_request.remove[]") for v in _require_array(payload.get("remove") or [], "socket_jewels_request.remove")]
        put = []
        for index, entry in enumerate(_require_array(payload.get("put") or [], "socket_jewels_request.put"), start=1):
            entry = _require_mapping(entry, f"socket_jewels_request.put[{index}]")
            raw = entry.get("raw")
            if not isinstance(raw, str) or not raw.strip():
                raise WorkerContractError("runtime_protocol_failed", f"socket_jewels_request.put[{index}].raw must be a non-empty string.")
            put.append({"node_id": _require_int(entry.get("node_id"), f"socket_jewels_request.put[{index}].node_id"), "raw": raw})
        chunk = "\n".join(_SOCKET_JEWELS_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps({"remove": remove, "put": put}, allow_nan=False)))
        raw_result = self._bridge.execute(chunk, nret=1)
        return json.loads(raw_result[0] or "{}")

    def cluster_graph(self, request: dict[str, Any]) -> dict[str, Any]:
        """The subgraph PoB built for the cluster jewel in tree socket ``socket_id`` (empty when it holds none).

        Returns {"nodes": [{id, kind, name, linked, allocated}]}, read from the spec's subGraphs: `kind` is
        entry (the node linked to the socket) | small | notable | socket | keystone; the mastery placeholder
        node is left out; `linked` holds the ids PoB links the node to (the entry also links the socket).
        """

        payload = _require_mapping(request, "cluster_graph_request")
        req = {"socket_id": _require_int(payload.get("socket_id"), "cluster_graph_request.socket_id")}
        chunk = "\n".join(_CLUSTER_GRAPH_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(req, allow_nan=False)))
        raw_result = self._bridge.execute(chunk, nret=1)
        return json.loads(raw_result[0] or "{}")

    def list_item_mods(self, request: dict[str, Any]) -> dict[str, Any]:
        """All explicit prefix/suffix mods PoB allows on a base (optionally at an item level)."""

        payload = _require_mapping(request, "item_mods_request")
        base = payload.get("base")
        if not isinstance(base, str) or not base:
            raise WorkerContractError("runtime_protocol_failed", "item_mods_request.base must be a base item name.")
        ilvl = payload.get("ilvl")
        pool = str(payload.get("pool") or "explicit")
        if pool not in {"explicit", "all"}:
            raise WorkerContractError("runtime_protocol_failed", "item_mods_request.pool must be 'explicit' or 'all'.")
        req = {"base": base, "ilvl": _require_int(ilvl, "item_mods_request.ilvl") if ilvl is not None else None, "pool": pool}
        chunk = "\n".join(_LIST_ITEM_MODS_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(req, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def craft_rare(self, request: dict[str, Any]) -> dict[str, Any]:
        """Craft a rare through PoB's own Item:Craft() from mod ids; returns validated raw item text."""

        payload = _require_mapping(request, "craft_request")
        base = payload.get("base")
        if not isinstance(base, str) or not base:
            raise WorkerContractError("runtime_protocol_failed", "craft_request.base must be a base item name.")

        def affix_list(key: str) -> list[dict[str, Any]]:
            out = []
            for index, entry in enumerate(_require_array(payload.get(key) or [], f"craft_request.{key}"), start=1):
                if isinstance(entry, str):
                    entry = {"mod_id": entry}
                entry = _require_mapping(entry, f"craft_request.{key}[{index}]")
                mod_id = entry.get("mod_id")
                if not isinstance(mod_id, str) or not mod_id:
                    raise WorkerContractError("runtime_protocol_failed", f"craft_request.{key}[{index}].mod_id must be a string.")
                rng = entry.get("range", 0.5)
                if not isinstance(rng, (int, float)) or isinstance(rng, bool) or not 0.0 <= float(rng) <= 1.0:
                    raise WorkerContractError("runtime_protocol_failed", f"craft_request.{key}[{index}].range must be within [0, 1].")
                out.append({"mod_id": mod_id, "range": float(rng)})
            return out

        req = {
            "base": base,
            "name": payload.get("name"),
            "ilvl": _require_int(payload["ilvl"], "craft_request.ilvl") if payload.get("ilvl") is not None else None,
            "quality": _require_int(payload["quality"], "craft_request.quality") if payload.get("quality") is not None else None,
            "sockets": payload.get("sockets"),
            "prefixes": affix_list("prefixes"),
            "suffixes": affix_list("suffixes"),
            "implicit_range": float(payload.get("implicit_range", 0.5)),
            "extra_lines": [str(x) for x in _require_array(payload.get("extra_lines") or [], "craft_request.extra_lines")],
            "families": _require_families(payload.get("families"), "craft_request.families"),
        }
        chunk = "\n".join(_CRAFT_RARE_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps(req, allow_nan=False)))
        raw = self._bridge.execute(chunk, nret=1)
        return json.loads(raw[0] or "{}")

    def recraft(self, request: dict[str, Any]) -> dict[str, Any]:
        """Re-render a rare's affix text from its `Prefix:`/`Suffix:` headers through PoB's own `Item:Craft()`
        (it keeps `{crafted}` and `{custom}` lines); returns {"raw": the re-rendered item text}."""

        payload = _require_mapping(request, "recraft_request")
        raw = payload.get("raw")
        if not isinstance(raw, str) or not raw:
            raise WorkerContractError("runtime_protocol_failed", "recraft_request.raw must be item text.")
        chunk = "\n".join(_RECRAFT_LUA).replace("REQUEST_JSON", _lua_long_string(json.dumps({"raw": raw}, allow_nan=False)))
        out = self._bridge.execute(chunk, nret=1)
        return json.loads(out[0] or "{}")

    def trial_stats(self, trial_payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate several candidate allocations without keeping any of them.

        Payload: {"trials": [{"add": [node_ids], "remove": [node_ids], "mastery": {node_id: effect_id}}],
                  "keys": [stat names], "mode": "full" | "fast", "parts": [skill part indices]}.
        "parts" (fast mode only): every trial is evaluated once per listed part of the main
        skill and its numeric stats are the mean over them (a random-element skill).

        mode "full": allocate for real, recalc everything (OnFrame), read, restore.
        mode "fast": PoB's own what-if calculator (calcs.getMiscCalculator with
        addNodes/removeNodes overrides): one calc pass, no mutation, FullDPS
        roll-up only when "FullDPS" is among keys. Node removal in fast mode
        does not cascade (only the listed nodes are excluded), so use it for
        leaf removals; additions include the node's current shortest path.
        For each trial: allocate (PoB paths automatically), recalc, read the
        requested stats, then restore the exact prior allocation and mastery
        selections. One IPC round trip for the whole batch. This is the
        optimizer's inner loop primitive.
        """

        payload = _require_mapping(trial_payload, "trial_payload")
        keys = [str(k) for k in _require_array(payload.get("keys") or [], "trial_payload.keys")]
        if not keys:
            raise WorkerContractError("runtime_protocol_failed", "trial_payload.keys must list at least one stat.")
        trials: list[dict[str, Any]] = []
        for index, entry in enumerate(_require_array(payload.get("trials") or [], "trial_payload.trials"), start=1):
            trial = _require_mapping(entry, f"trial_payload.trials[{index}]")
            add = [_require_int(v, f"trial_payload.trials[{index}].add[]") for v in _require_array(trial.get("add") or [], f"trial_payload.trials[{index}].add")]
            remove = [_require_int(v, f"trial_payload.trials[{index}].remove[]") for v in _require_array(trial.get("remove") or [], f"trial_payload.trials[{index}].remove")]
            mastery: dict[str, int] = {}
            for key, value in _require_mapping(trial.get("mastery") or {}, f"trial_payload.trials[{index}].mastery").items():
                mastery[str(int(str(key)))] = _require_int(value, f"trial_payload.trials[{index}].mastery[{key}]")
            item = trial.get("item")
            if item is not None:
                item = _require_mapping(item, f"trial_payload.trials[{index}].item")
                if not isinstance(item.get("slot"), str) or not isinstance(item.get("raw"), str):
                    raise WorkerContractError("runtime_protocol_failed", f"trial_payload.trials[{index}].item needs slot and raw strings.")
                item = {"slot": item["slot"], "raw": item["raw"], "recraft": item.get("recraft") is True}
            entry_out: dict[str, Any] = {"add": add, "remove": remove, "mastery": mastery, "item": item}
            marks = trial.get("marks")
            if marks:  # #1124 unit 4: the red-line mark lines this what-if calculation takes; no key when a trial has none
                marks = _require_mapping(marks, f"trial_payload.trials[{index}].marks")
                lines = {
                    side: [str(v) for v in _require_array(marks.get(side) or [], f"trial_payload.trials[{index}].marks.{side}")]
                    for side in ("add", "remove")
                }
                if lines["add"] or lines["remove"]:
                    entry_out["marks"] = lines
            trials.append(entry_out)
        parts = [_require_int(v, "trial_payload.parts[]") for v in _require_array(payload.get("parts") or [], "trial_payload.parts")]
        payload_json = json.dumps({"trials": trials, "keys": keys, "parts": parts}, allow_nan=False)
        mode = str(payload.get("mode") or "full")
        if mode not in {"full", "fast"}:
            raise WorkerContractError("runtime_protocol_failed", "trial_payload.mode must be 'full' or 'fast'.")
        lua_lines = _TRIAL_STATS_FAST_LUA if mode == "fast" else _TRIAL_STATS_LUA
        chunk = "\n".join(lua_lines).replace("PAYLOAD_JSON", _lua_long_string(payload_json))
        raw = self._bridge.execute(chunk, nret=1)
        decoded = json.loads(raw[0] or "[]")
        return decoded if isinstance(decoded, list) else []

    def mutate_tree_nodes(self, mutation_payload: dict[str, Any], *, always_rebuild_paths: bool = False) -> dict[str, Any]:
        """Incrementally allocate / deallocate passive nodes on the active spec.

        Payload: {"add_node_ids": [...], "remove_node_ids": [...],
                  "mastery_effects": {node_id: effect_id}}  (required for Mastery adds).
        Removal happens first. Allocation uses PoB AllocNode, which also
        allocates the shortest connecting path, so the caller does not need to
        list connector nodes. Returns the resulting allocated user-node set,
        the exact added/removed diff (removal cascades to nodes that depended
        on the removed one for connectivity), and point counts.
        """

        payload = _require_mapping(mutation_payload, "mutation_payload")
        extra = sorted(set(payload) - {"add_node_ids", "remove_node_ids", "mastery_effects"})
        if extra:
            raise WorkerContractError("runtime_protocol_failed", "Unsupported mutation_payload field(s): " + ", ".join(extra))
        add_ids = [
            _require_int(v, "mutation_payload.add_node_ids[]")
            for v in _require_array(payload.get("add_node_ids") or [], "mutation_payload.add_node_ids")
        ]
        remove_ids = [
            _require_int(v, "mutation_payload.remove_node_ids[]")
            for v in _require_array(payload.get("remove_node_ids") or [], "mutation_payload.remove_node_ids")
        ]
        mastery: dict[str, int] = {}
        for key, value in _require_mapping(payload.get("mastery_effects") or {}, "mutation_payload.mastery_effects").items():
            try:
                node_key = str(int(str(key)))
            except ValueError as exc:
                raise WorkerContractError("runtime_protocol_failed", "mutation_payload.mastery_effects keys must be node ids.") from exc
            mastery[node_key] = _require_int(
                value, f"mutation_payload.mastery_effects[{key}]"
            )
        payload_json = json.dumps({"add": add_ids, "remove": remove_ids, "mastery": mastery}, allow_nan=False)
        lua_lines = _MUTATE_TREE_LUA_ALWAYS_REBUILD if always_rebuild_paths else _MUTATE_TREE_LUA
        chunk = "\n".join(lua_lines).replace("PAYLOAD_JSON", _lua_long_string(payload_json))
        raw = self._bridge.execute(chunk, nret=1)
        result = json.loads(raw[0] or "{}")
        if result.get("missing"):
            raise WorkerContractError("runtime_protocol_failed", f"mutate_tree_nodes: unknown node id(s): {result['missing']}")
        if result.get("unreachable"):
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"mutate_tree_nodes: node id(s) have no path from the allocated tree: {result['unreachable']}",
            )
        if result.get("missing_mastery_effect"):
            raise WorkerContractError(
                "runtime_protocol_failed",
                "mutate_tree_nodes: mastery node(s) need mastery_effects[node_id] = effect_id: "
                f"{result['missing_mastery_effect']}",
            )
        return result

    def load_reopen_source(self, xml_text: str) -> None:
        self._bridge.execute(
            "\n".join(
                (
                    f"loadBuildFromXML({_lua_long_string(xml_text)}, 'Reopened Headless Proof Build')",
                    "runCallback('OnFrame')",
                )
            )
        )

    def equip_boots_item(self) -> None:
        self.apply_item_state(
            {
                "active_item_set_id": _CANONICAL_ITEM_SET_ID,
                "item_sets": [
                    {
                        "item_set_id": _CANONICAL_ITEM_SET_ID,
                        "use_second_weapon_set": False,
                        "slots": [
                            {
                                "slot": EXPECTED_BOOTS_SLOT,
                                "raw_item_text": _PROOF_RUNTIME_ITEM_RAW,
                            }
                        ],
                    }
                ],
            }
        )

    def apply_item_state(self, item_payload: dict[str, Any]) -> None:
        try:
            payload_json = json.dumps(item_payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise WorkerContractError("runtime_protocol_failed", "item_payload must be JSON-serializable.") from exc

        self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    f"local payload_json = {_lua_long_string(payload_json)}",
                    "local payload, _, decode_err = json.decode(payload_json, 1, nil)",
                    "if type(payload) ~= 'table' then",
                    "  error('item_payload must decode to a Lua table: ' .. tostring(decode_err or 'unknown error'))",
                    "end",
                    "local allowed_keys = {",
                    "  active_item_set_id = true,",
                    "  item_sets = true,",
                    "}",
                    "for key, _ in pairs(payload) do",
                    "  if not allowed_keys[key] then",
                    "    error('Unsupported item_payload field: ' .. tostring(key))",
                    "  end",
                    "end",
                    "local function require_array(value, field_name)",
                    "  if type(value) ~= 'table' then",
                    "    error(field_name .. ' must be an array.')",
                    "  end",
                    "  return value",
                    "end",
                    "local function require_object(value, field_name)",
                    "  if type(value) ~= 'table' then",
                    "    error(field_name .. ' must be an object.')",
                    "  end",
                    "  return value",
                    "end",
                    "local function require_string(value, field_name)",
                    "  if type(value) ~= 'string' or value == '' then",
                    "    error(field_name .. ' must be a non-empty string.')",
                    "  end",
                    "  return value",
                    "end",
                    "local function require_bool(value, field_name)",
                    "  if type(value) ~= 'boolean' then",
                    "    error(field_name .. ' must be a boolean.')",
                    "  end",
                    "  return value",
                    "end",
                    "local function normalize_item_set_index(value, field_name)",
                    "  if type(value) == 'number' then",
                    "    local index = math.floor(value)",
                    "    if index >= 1 then",
                    "      return index",
                    "    end",
                    "  elseif type(value) == 'string' then",
                    "    if value == 'itemset.main' then",
                    "      return 1",
                    "    end",
                    "    local raw_index = value:match('^itemset%.(%d+)$')",
                    "    if raw_index then",
                    "      local index = tonumber(raw_index)",
                    "      if index and index >= 1 then",
                    "        return index",
                    "      end",
                    "    end",
                    "  end",
                    "  error(field_name .. ' must reference itemset.main or itemset.<positive-index>.')",
                    "end",
                    "local function build_item_from_raw(raw_item_text, field_name)",
                    "  local raw_text = require_string(raw_item_text, field_name .. '.raw_item_text')",
                    "  build.itemsTab:CreateDisplayItemFromRaw(raw_text, true)",
                    "  if not build.itemsTab.displayItem then",
                    "    error('Pinned runtime could not parse ' .. field_name .. '.raw_item_text into an item.')",
                    "  end",
                    "  local item = build.itemsTab.displayItem",
                    "  build.itemsTab:AddItem(item, true)",
                    "  build.itemsTab:SetDisplayItem()",
                    "  return item",
                    "end",
                    "local function is_abyss_slot(slot_name)",
                    "  return type(slot_name) == 'string' and slot_name:find('Abyssal Socket', 1, true) ~= nil",
                    "end",
                    "local function is_swap_slot(slot_name)",
                    "  return slot_name == 'Weapon 1 Swap' or slot_name == 'Weapon 2 Swap'",
                    "end",
                    "local function slot_has_active_carrier(item_set, slot)",
                    "  if slot.weaponSet == 2 and not item_set.useSecondWeaponSet then",
                    "    return false",
                    "  end",
                    "  if slot.parentSlot and slot.slotNum then",
                    "    local parent_slot_name = slot.parentSlot.slotName",
                    "    local parent_state = item_set[parent_slot_name]",
                    "    local parent_item_id = parent_state and parent_state.selItemId or 0",
                    "    local parent_item = build.itemsTab.items[parent_item_id]",
                    "    local abyssal_socket_count = parent_item and tonumber(parent_item.abyssalSocketCount or 0) or 0",
                    "    return abyssal_socket_count >= tonumber(slot.slotNum)",
                    "  end",
                    "  return true",
                    "end",
                    "local function reset_item_sets_preserving_tree_jewels()",
                    "  local protected_items = {}",
                    "  for _, item_id in pairs(build.spec.jewels or {}) do",
                    "    if type(item_id) == 'number' and item_id > 0 and build.itemsTab.items[item_id] then",
                    "      protected_items[item_id] = build.itemsTab.items[item_id]",
                    "    end",
                    "  end",
                    "  wipeTable(build.itemsTab.items)",
                    "  wipeTable(build.itemsTab.itemOrderList)",
                    "  for item_id, item in pairs(protected_items) do",
                    "    build.itemsTab.items[item_id] = item",
                    "    table.insert(build.itemsTab.itemOrderList, item_id)",
                    "  end",
                    "  table.sort(build.itemsTab.itemOrderList)",
                    "  wipeTable(build.itemsTab.itemSets)",
                    "  wipeTable(build.itemsTab.itemSetOrderList)",
                    "  build.itemsTab.activeItemSetId = 0",
                    "  build.itemsTab.activeItemSet = nil",
                    "  for slot_name, slot in pairs(build.itemsTab.slots) do",
                    "    if not slot.nodeId then",
                    "      slot.selItemId = 0",
                    "      slot.active = false",
                    "      if slot.controls and slot.controls.activate then",
                    "        slot.controls.activate.state = false",
                    "      end",
                    "    end",
                    "  end",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local requested_item_sets = {}",
                    "local requested_item_set_lookup = {}",
                    "for index, entry in ipairs(require_array(payload.item_sets, 'item_sets')) do",
                    "  local item_set = require_object(entry, 'item_sets[' .. tostring(index) .. ']')",
                    "  local item_set_index = normalize_item_set_index(item_set.item_set_id, 'item_sets[' .. tostring(index) .. '].item_set_id')",
                    "  if requested_item_set_lookup[item_set_index] then",
                    "    error('item_sets contains duplicate item_set_id ' .. tostring(item_set.item_set_id) .. '.')",
                    "  end",
                    "  local use_second_weapon_set = require_bool(",
                    "    item_set.use_second_weapon_set,",
                    "    'item_sets[' .. tostring(index) .. '].use_second_weapon_set'",
                    "  )",
                    "  local slot_requests = {}",
                    "  local seen_slots = {}",
                    "  for slot_index, slot_entry in ipairs(require_array(item_set.slots, 'item_sets[' .. tostring(index) .. '].slots')) do",
                    "    local slot_payload = require_object(",
                    "      slot_entry,",
                    "      'item_sets[' .. tostring(index) .. '].slots[' .. tostring(slot_index) .. ']'",
                    "    )",
                    "    local slot_name = require_string(",
                    "      slot_payload.slot,",
                    "      'item_sets[' .. tostring(index) .. '].slots[' .. tostring(slot_index) .. '].slot'",
                    "    )",
                    "    if seen_slots[slot_name] then",
                    "      error('item_sets[' .. tostring(index) .. '] contains duplicate slot ' .. slot_name .. '.')",
                    "    end",
                    "    seen_slots[slot_name] = true",
                    "    table.insert(slot_requests, {",
                    "      slot = slot_name,",
                    "      raw_item_text = require_string(",
                    "        slot_payload.raw_item_text,",
                    "        'item_sets[' .. tostring(index) .. '].slots[' .. tostring(slot_index) .. '].raw_item_text'",
                    "      ),",
                    "    })",
                    "  end",
                    "  requested_item_set_lookup[item_set_index] = true",
                    "  table.insert(requested_item_sets, {",
                    "    index = item_set_index,",
                    "    use_second_weapon_set = use_second_weapon_set,",
                    "    slots = slot_requests,",
                    "  })",
                    "end",
                    "if #requested_item_sets == 0 then",
                    "  error('item_sets must contain at least one item set definition.')",
                    "end",
                    "local active_item_set_index = normalize_item_set_index(payload.active_item_set_id, 'active_item_set_id')",
                    "if not requested_item_set_lookup[active_item_set_index] then",
                    "  error('active_item_set_id must reference one of item_sets[].item_set_id.')",
                    "end",
                    "table.sort(requested_item_sets, function(left, right)",
                    "  return left.index < right.index",
                    "end)",
                    "reset_item_sets_preserving_tree_jewels()",
                    "for _, requested in ipairs(requested_item_sets) do",
                    "  local item_set = build.itemsTab:NewItemSet(requested.index)",
                    "  table.insert(build.itemsTab.itemSetOrderList, requested.index)",
                    "  item_set.useSecondWeaponSet = requested.use_second_weapon_set",
                    "  requested.item_set = item_set",
                    "end",
                    "build.itemsTab:SetActiveItemSet(active_item_set_index)",
                    "local function assign_requested_slot(requested, slot_request, field_name)",
                    "  local slot_name = slot_request.slot",
                    "  local slot = build.itemsTab.slots[slot_name]",
                    "  if not slot or slot.nodeId then",
                    "    error(field_name .. ' references an unsupported item slot ' .. tostring(slot_name) .. '.')",
                    "  end",
                    "  if is_swap_slot(slot_name) and not requested.item_set.useSecondWeaponSet then",
                    "    error(field_name .. ' requires use_second_weapon_set=true for slot ' .. slot_name .. '.')",
                    "  end",
                    "  if is_abyss_slot(slot_name) and not slot_has_active_carrier(requested.item_set, slot) then",
                    "    error(field_name .. ' does not have an active abyssal carrier for slot ' .. slot_name .. '.')",
                    "  end",
                    "  local item = build_item_from_raw(slot_request.raw_item_text, field_name)",
                    "  if not build.itemsTab:IsItemValidForSlot(item, slot_name, requested.item_set) then",
                    "    error(field_name .. ' could not equip the parsed item in slot ' .. slot_name .. '.')",
                    "  end",
                    "  if requested.item_set == build.itemsTab.activeItemSet then",
                    "    build.itemsTab.slots[slot_name]:SetSelItemId(item.id)",
                    "  else",
                    "    requested.item_set[slot_name].selItemId = item.id",
                    "  end",
                    "end",
                    "for _, requested in ipairs(requested_item_sets) do",
                    "  for slot_index, slot_request in ipairs(requested.slots) do",
                    "    if not is_abyss_slot(slot_request.slot) then",
                    "      assign_requested_slot(",
                    "        requested,",
                    "        slot_request,",
                    "        'item_sets[' .. tostring(requested.index) .. '].slots[' .. tostring(slot_index) .. ']'",
                    "      )",
                    "    end",
                    "  end",
                    "end",
                    "for _, requested in ipairs(requested_item_sets) do",
                    "  for slot_index, slot_request in ipairs(requested.slots) do",
                    "    if is_abyss_slot(slot_request.slot) then",
                    "      assign_requested_slot(",
                    "        requested,",
                    "        slot_request,",
                    "        'item_sets[' .. tostring(requested.index) .. '].slots[' .. tostring(slot_index) .. ']'",
                    "      )",
                    "    end",
                    "  end",
                    "end",
                    "build.itemsTab:SetActiveItemSet(active_item_set_index)",
                    "build.itemsTab:UpdateSockets()",
                    "runCallback('OnFrame')",
                )
            )
        )

    def flask_uptimes(self) -> dict[str, dict[str, Any]]:
        """Per Flask slot holding a flask: {"line": PoB's uptime line or None, "full": bool, "active": bool}.

        The flags are derived first (`derive_flask_flags`: active iff "Flask uptime: 100%", recalculated once
        when a flag changed), then the lines are read off the calculation as it stands; `active` is the slot's
        flag after that. Lines: "Flask uptime: 100%", "Flask uptime: X% average, Y% minimum", None (PoB prints
        none: a Life / Mana flask whose effect is removed, or a flask that cannot be used). A tincture in a
        Flask slot is left out.
        """

        raw = self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    *_FLASK_UPTIME_LUA,
                    "derive_flask_flags()",
                    "local result = setmetatable({}, { __jsontype = 'object' })",
                    "local env = build.calcsTab.mainEnv",
                    "if env then",
                    "  for name, r in pairs(flask_uptimes_for(env.modDB, build.calcsTab.mainOutput or env.player.output, flask_live_item)) do",
                    "    result[name] = { line = r.line or json.null, full = r.full, active = flask_slot_active(name) }",
                    "  end",
                    "end",
                    "return json.encode(result)",
                )
            ),
            nret=1,
        )
        decoded = json.loads(raw[0] or "{}")
        return {str(k): dict(v) for k, v in decoded.items()} if isinstance(decoded, dict) else {}

    def set_flasks_active(self, active_by_slot: dict[str, Any]) -> None:
        """Set PoB's per-slot `active` flag (the checkbox left of a flask slot) for the named Flask slots.

        A flask or tincture's mods reach the calc only while its slot is active (CalcSetup.lua:
        `env.flasks` / `env.tinctures`). The flag lives on the slot control and on the active item
        set's slot row (`ItemSlotControl.lua:33-38`); both are written, as the checkbox does.
        """

        flasks = {name for name in EXPECTED_GEAR_SLOT_ORDER if name.startswith("Flask ")}
        for name, value in active_by_slot.items():
            if name not in flasks:
                raise WorkerContractError("runtime_protocol_failed", f"set_flasks_active: {name!r} is not a Flask slot.")
            if not isinstance(value, bool):
                raise WorkerContractError("runtime_protocol_failed", f"set_flasks_active[{name!r}] must be a boolean.")
        payload_json = json.dumps(active_by_slot, allow_nan=False, sort_keys=True)
        self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    f"local requested = json.decode({_lua_long_string(payload_json)}, 1, nil)",
                    "for slot_name, state in pairs(requested) do",
                    "  local slot = build.itemsTab.slots[slot_name]",
                    "  if not slot or not slot.controls or not slot.controls.activate then",
                    "    error('set_flasks_active: ' .. tostring(slot_name) .. ' has no activate control.')",
                    "  end",
                    "  slot.active = state",
                    "  slot.controls.activate.state = state",
                    "  build.itemsTab.activeItemSet[slot_name].active = state",
                    "end",
                    "build.buildFlag = true",
                    "runCallback('OnFrame')",
                )
            )
        )

    def apply_skill_state(self, skill_payload: dict[str, Any]) -> None:
        """Write the whole skills surface into the live build.

        Every field of the normalized payload maps onto a `build.skillsTab` field, so there is
        no payload this cannot express and no fallback to `_apply_skill_state_xml` (kept as the
        equivalence reference). ~63 ms instead of ~470 ms; the exported build is identical.

        The gem names PoB has already resolved once are remembered (`_GEM_ID_MEMO_SETUP`), so
        `ProcessSocketGroup` reaches the same gem data by id instead of scanning the whole gem
        database per gem: 74.1 -> 69.2 ms on stormbrand's six-group surface. What is left is the
        recalc, which is why a narrower "one gem in one group" write has nothing to take.
        """

        self._apply_skill_state_inplace(self._normalize_skill_payload(skill_payload))

    def _apply_skill_state_inplace(self, normalized: dict[str, Any]) -> None:
        settings = normalized["settings"]
        payload = {
            "settings": {
                "activeSkillSet": int(settings["activeSkillSet"]),
                "defaultGemLevel": settings["defaultGemLevel"],
                "defaultGemQuality": int(settings["defaultGemQuality"]),
                "sortGemsByDPS": settings["sortGemsByDPS"] == "true",
                "sortGemsByDPSField": settings["sortGemsByDPSField"],
                "showLegacyGems": settings["showLegacyGems"] == "true",
                "showSupportGemTypes": settings["showSupportGemTypes"],
            },
            "main_socket_group": int(normalized["main_socket_group_index"]),
            "skill_sets": [
                {
                    "id": skill_set["skill_set_index"],
                    "title": skill_set["title"],
                    "socket_groups": [
                        {
                            "enabled": group["enabled"],
                            "include_in_full_dps": group["include_in_full_dps"],
                            # PoB leaves groupCount nil for a single group (D49); the XML path
                            # omits the attribute and tonumber(nil) is nil on reload
                            "group_count": None if int(group["group_count"]) == 1 else int(group["group_count"]),
                            "label": group["label"],
                            "slot": group["slot"],
                            "main_active_skill": int(group["main_active_skill_index"]),
                            "gems": [
                                {
                                    "nameSpec": gem["gem_name"],
                                    "level": gem["level"],
                                    "quality": gem["quality"],
                                    "enabled": gem["enabled"],
                                    "enableGlobal1": gem["enable_global_1"],
                                    "enableGlobal2": gem["enable_global_2"],
                                    "count": gem["count"],
                                    "skillPart": gem["skill_part"],
                                    "skillStageCount": gem["skill_stage_count"],
                                    "skillMineCount": gem["skill_mine_count"],
                                    "skillMinion": gem["skill_minion"],
                                    "skillMinionItemSet": gem["skill_minion_item_set_index"],
                                    "skillMinionSkill": gem["skill_minion_skill_index"],
                                }
                                for gem in group["gems"]
                            ],
                        }
                        for group in skill_set["socket_groups"]
                    ],
                }
                for skill_set in normalized["skill_sets"]
            ],
        }
        lua = _APPLY_SKILLS_LUA if os.environ.get("JUNKROAN_GEM_ID_MEMO", "1") != "0" else _APPLY_SKILLS_LUA_NO_GEM_ID_MEMO
        if normalized.get("keep_main_active_skill"):
            payload["keep_main_active_skill"] = True
        if "spectre_list" in normalized:
            payload["spectre_list"] = list(normalized["spectre_list"])
            at = lua.index("local s = p.settings")
            lua = (*lua[:at], *_SET_SPECTRE_LIST_LUA, *lua[at:])
        chunk = "\n".join(lua).replace("PAYLOAD_JSON", _lua_json_literal(payload))
        self._bridge.execute(chunk, nret=1)

    def _apply_skill_state_xml(self, skill_payload: dict[str, Any]) -> None:
        """The pre-2026-09-18 path: export the build, rewrite <Skills>, reload the whole build.
        Kept as the reference the in-place writer is proven against (tests/test_pob_inplace_writes.py)."""

        normalized = self._normalize_skill_payload(skill_payload)
        xml_text = self.export_build_xml()
        root = self._parse_build_xml(xml_text)
        build_node = root.find("Build")
        skills_node = root.find("Skills")
        if build_node is None or skills_node is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export is missing Build or Skills nodes required for skill authoring.",
            )

        build_node.attrib.pop("mainSkillIndex", None)
        _set_optional_attr(build_node, "mainSocketGroup", normalized["main_socket_group_index"])
        if "spectre_list" in normalized:
            for old in build_node.findall("Spectre"):
                build_node.remove(old)
            for spectre_id in normalized["spectre_list"]:
                ElementTree.SubElement(build_node, "Spectre", {"id": spectre_id})

        skills_node.attrib.clear()
        skills_node.attrib.update(normalized["settings"])
        for child in list(skills_node):
            skills_node.remove(child)

        for skill_set in normalized["skill_sets"]:
            skill_set_node = ElementTree.SubElement(
                skills_node,
                "SkillSet",
                {"id": str(skill_set["skill_set_index"])},
            )
            _set_optional_attr(skill_set_node, "title", skill_set["title"])
            for socket_group in skill_set["socket_groups"]:
                skill_node = ElementTree.SubElement(
                    skill_set_node,
                    "Skill",
                    {
                        "enabled": _bool_xml(socket_group["enabled"]),
                        "includeInFullDPS": _bool_xml(socket_group["include_in_full_dps"]),
                        # PoB's getActiveSkillCount takes groupCount over the gems' own counts when it is set;
                        # the app leaves it nil, so a group count of 1 (the default) is not written (D49)
                        **({"groupCount": str(socket_group["group_count"])} if int(socket_group["group_count"]) != 1 else {}),
                        "mainActiveSkill": str(socket_group["main_active_skill_index"]),
                        "mainActiveSkillCalcs": str(socket_group["main_active_skill_index"]),
                    },
                )
                _set_optional_attr(skill_node, "label", socket_group["label"])
                _set_optional_attr(skill_node, "slot", socket_group["slot"])
                for gem in socket_group["gems"]:
                    gem_node = ElementTree.SubElement(
                        skill_node,
                        "Gem",
                        {
                            "nameSpec": gem["gem_name"],
                            "level": str(gem["level"]),
                            "quality": str(gem["quality"]),
                            "enabled": _bool_xml(gem["enabled"]),
                            "enableGlobal1": _bool_xml(gem["enable_global_1"]),
                            "enableGlobal2": _bool_xml(gem["enable_global_2"]),
                            "count": str(gem["count"]),
                        },
                    )
                    _set_optional_attr(gem_node, "skillPart", gem["skill_part"])
                    _set_optional_attr(gem_node, "skillPartCalcs", gem["skill_part"])
                    _set_optional_attr(gem_node, "skillStageCount", gem["skill_stage_count"])
                    _set_optional_attr(gem_node, "skillStageCountCalcs", gem["skill_stage_count"])
                    _set_optional_attr(gem_node, "skillMineCount", gem["skill_mine_count"])
                    _set_optional_attr(gem_node, "skillMineCountCalcs", gem["skill_mine_count"])
                    _set_optional_attr(gem_node, "skillMinion", gem["skill_minion"])
                    _set_optional_attr(gem_node, "skillMinionCalcs", gem["skill_minion"])
                    _set_optional_attr(gem_node, "skillMinionItemSet", gem["skill_minion_item_set_index"])
                    _set_optional_attr(gem_node, "skillMinionItemSetCalcs", gem["skill_minion_item_set_index"])
                    _set_optional_attr(gem_node, "skillMinionSkill", gem["skill_minion_skill_index"])
                    _set_optional_attr(gem_node, "skillMinionSkillCalcs", gem["skill_minion_skill_index"])

        self.load_reopen_source(_serialize_xml(root))

    def _parse_build_xml(self, xml_text: str) -> ElementTree.Element:
        try:
            return ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export did not return parseable XML for skill mutation.",
            ) from exc

    def _normalize_skill_payload(self, skill_payload: dict[str, Any]) -> dict[str, Any]:
        payload = _require_mapping(skill_payload, "skill_payload")
        allowed_keys = {
            "active_skill_set_id",
            "main_socket_group_id",
            "default_gem_level",
            "default_gem_quality",
            "show_legacy_gems",
            "show_support_gem_types",
            "sort_gems_by_dps",
            "sort_gems_by_dps_field",
            "skill_sets",
            "spectre_list",
            "keep_main_active_skill",
        }
        extra_keys = sorted(set(payload) - allowed_keys)
        if extra_keys:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Unsupported skill_payload field(s): " + ", ".join(extra_keys),
            )

        skill_sets: list[dict[str, Any]] = []
        skill_set_index_lookup: dict[int, dict[str, Any]] = {}
        for index, entry in enumerate(_require_array(payload.get("skill_sets"), "skill_payload.skill_sets"), start=1):
            skill_set = _require_mapping(entry, f"skill_payload.skill_sets[{index}]")
            allowed_skill_set_keys = {"skill_set_id", "title", "socket_groups"}
            extra_skill_set_keys = sorted(set(skill_set) - allowed_skill_set_keys)
            if extra_skill_set_keys:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"Unsupported skill set field(s) in skill_payload.skill_sets[{index}]: "
                    + ", ".join(extra_skill_set_keys),
                )
            skill_set_index = _normalize_skill_set_index(
                skill_set.get("skill_set_id"),
                f"skill_payload.skill_sets[{index}].skill_set_id",
            )
            if skill_set_index in skill_set_index_lookup:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"skill_payload.skill_sets[{index}] duplicates skill_set_id {skill_set.get('skill_set_id')!r}.",
                )

            socket_groups: list[dict[str, Any]] = []
            for group_index, group_entry in enumerate(
                _require_array(skill_set.get("socket_groups"), f"skill_payload.skill_sets[{index}].socket_groups"),
                start=1,
            ):
                group_payload = _require_mapping(
                    group_entry,
                    f"skill_payload.skill_sets[{index}].socket_groups[{group_index}]",
                )
                allowed_group_keys = {
                    "label",
                    "slot",
                    "enabled",
                    "include_in_full_dps",
                    "group_count",
                    "main_active_skill_index",
                    "gems",
                }
                extra_group_keys = sorted(set(group_payload) - allowed_group_keys)
                if extra_group_keys:
                    raise WorkerContractError(
                        "runtime_protocol_failed",
                        f"Unsupported socket group field(s) in skill_payload.skill_sets[{index}].socket_groups[{group_index}]: "
                        + ", ".join(extra_group_keys),
                    )
                gems: list[dict[str, Any]] = []
                for gem_index, gem_entry in enumerate(
                    _require_array(
                        group_payload.get("gems"),
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems",
                    ),
                    start=1,
                ):
                    gem_payload = _require_mapping(
                        gem_entry,
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}]",
                    )
                    allowed_gem_keys = {
                        "gem_name",
                        "level",
                        "quality",
                        "enabled",
                        "count",
                        "enable_global_1",
                        "enable_global_2",
                        "skill_part",
                        "skill_stage_count",
                        "skill_mine_count",
                        "skill_minion",
                        "skill_minion_item_set_id",
                        "skill_minion_skill_index",
                    }
                    extra_gem_keys = sorted(set(gem_payload) - allowed_gem_keys)
                    if extra_gem_keys:
                        raise WorkerContractError(
                            "runtime_protocol_failed",
                            f"Unsupported gem field(s) in skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}]: "
                            + ", ".join(extra_gem_keys),
                        )
                    gem_name = _require_non_empty_string(
                        gem_payload.get("gem_name"),
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].gem_name",
                    )
                    level = _require_int(
                        gem_payload.get("level", 1),
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].level",
                    )
                    quality = _require_int(
                        gem_payload.get("quality", 0),
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].quality",
                    )
                    count = _require_int(
                        gem_payload.get("count", 1),
                        f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].count",
                    )
                    if level < 1 or quality < 0 or count < 1:
                        raise WorkerContractError(
                            "runtime_protocol_failed",
                            f"Gem numeric fields must be positive in skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].",
                        )
                    skill_part = gem_payload.get("skill_part")
                    skill_stage_count = gem_payload.get("skill_stage_count")
                    skill_mine_count = gem_payload.get("skill_mine_count")
                    skill_minion_skill_index = gem_payload.get("skill_minion_skill_index")
                    normalized_gem = {
                        "gem_name": gem_name,
                        "level": level,
                        "quality": quality,
                        "enabled": _require_bool(
                            gem_payload.get("enabled", True),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].enabled",
                        ),
                        "count": count,
                        "enable_global_1": _require_bool(
                            gem_payload.get("enable_global_1", True),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].enable_global_1",
                        ),
                        "enable_global_2": _require_bool(
                            gem_payload.get("enable_global_2", False),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].enable_global_2",
                        ),
                        "skill_part": None
                        if skill_part is None
                        else _require_int(
                            skill_part,
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_part",
                        ),
                        "skill_stage_count": None
                        if skill_stage_count is None
                        else _require_int(
                            skill_stage_count,
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_stage_count",
                        ),
                        "skill_mine_count": None
                        if skill_mine_count is None
                        else _require_int(
                            skill_mine_count,
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_mine_count",
                        ),
                        "skill_minion": _require_optional_string(
                            gem_payload.get("skill_minion"),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_minion",
                        ),
                        "skill_minion_item_set_index": None
                        if gem_payload.get("skill_minion_item_set_id") is None
                        else _normalize_item_set_index(
                            gem_payload.get("skill_minion_item_set_id"),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_minion_item_set_id",
                        ),
                        "skill_minion_skill_index": None
                        if skill_minion_skill_index is None
                        else _require_int(
                            skill_minion_skill_index,
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].skill_minion_skill_index",
                        ),
                    }
                    for numeric_field in ("skill_part", "skill_stage_count", "skill_mine_count", "skill_minion_skill_index"):
                        numeric_value = normalized_gem[numeric_field]
                        if numeric_value is not None and numeric_value < 1:
                            raise WorkerContractError(
                                "runtime_protocol_failed",
                                f"{numeric_field} must be >= 1 in skill_payload.skill_sets[{index}].socket_groups[{group_index}].gems[{gem_index}].",
                            )
                    gems.append(normalized_gem)

                group_count = _require_int(
                    group_payload.get("group_count", 1),
                    f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].group_count",
                )
                main_active_skill_index = _require_int(
                    group_payload.get("main_active_skill_index", 1),
                    f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].main_active_skill_index",
                )
                if group_count < 1 or main_active_skill_index < 1:
                    raise WorkerContractError(
                        "runtime_protocol_failed",
                        f"Socket group numeric selectors must be >= 1 in skill_payload.skill_sets[{index}].socket_groups[{group_index}].",
                    )
                socket_groups.append(
                    {
                        "label": _require_optional_string(
                            group_payload.get("label"),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].label",
                        ),
                        "slot": _require_optional_string(
                            group_payload.get("slot"),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].slot",
                        ),
                        "enabled": _require_bool(
                            group_payload.get("enabled", True),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].enabled",
                        ),
                        "include_in_full_dps": _require_bool(
                            group_payload.get("include_in_full_dps", False),
                            f"skill_payload.skill_sets[{index}].socket_groups[{group_index}].include_in_full_dps",
                        ),
                        "group_count": group_count,
                        "main_active_skill_index": main_active_skill_index,
                        "gems": gems,
                    }
                )

            normalized_skill_set = {
                "skill_set_index": skill_set_index,
                "skill_set_id": _normalize_skill_set_id(skill_set_index),
                "title": _require_optional_string(
                    skill_set.get("title"),
                    f"skill_payload.skill_sets[{index}].title",
                ),
                "socket_groups": socket_groups,
            }
            skill_sets.append(normalized_skill_set)
            skill_set_index_lookup[skill_set_index] = normalized_skill_set

        if not skill_sets:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.skill_sets must contain at least one skill set definition.",
            )

        active_skill_set_index = _normalize_skill_set_index(
            payload.get("active_skill_set_id"),
            "skill_payload.active_skill_set_id",
        )
        active_skill_set = skill_set_index_lookup.get(active_skill_set_index)
        if active_skill_set is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.active_skill_set_id must reference one of skill_payload.skill_sets[].skill_set_id.",
            )

        main_socket_group_index = _normalize_socket_group_index(
            payload.get("main_socket_group_id", 1),
            field_name="skill_payload.main_socket_group_id",
            expected_skill_set_id=active_skill_set["skill_set_id"],
        )
        if active_skill_set["socket_groups"] and main_socket_group_index > len(active_skill_set["socket_groups"]):
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.main_socket_group_id must reference one of the active skill set socket groups.",
            )

        default_gem_quality = _require_int(payload.get("default_gem_quality", 0), "skill_payload.default_gem_quality")
        if default_gem_quality < 0:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.default_gem_quality must be >= 0.",
            )
        settings = {
            "sortGemsByDPS": _bool_xml(_require_bool(payload.get("sort_gems_by_dps", True), "skill_payload.sort_gems_by_dps")),
            "sortGemsByDPSField": self._normalize_sort_gems_by_dps_field(payload.get("sort_gems_by_dps_field", "CombinedDPS")),
            "activeSkillSet": str(active_skill_set_index),
            "defaultGemQuality": str(default_gem_quality),
            "defaultGemLevel": self._normalize_default_gem_level(payload.get("default_gem_level", "normalMaximum")),
            "showLegacyGems": _bool_xml(_require_bool(payload.get("show_legacy_gems", False), "skill_payload.show_legacy_gems")),
            "showSupportGemTypes": self._normalize_show_support_gem_types(payload.get("show_support_gem_types", "ALL")),
        }
        normalized_payload: dict[str, Any] = {
            "active_skill_set_index": active_skill_set_index,
            "main_socket_group_index": main_socket_group_index,
            "settings": settings,
            "skill_sets": skill_sets,
        }
        if payload.get("keep_main_active_skill") is not None:
            normalized_payload["keep_main_active_skill"] = _require_bool(
                payload["keep_main_active_skill"], "skill_payload.keep_main_active_skill"
            )
        if payload.get("spectre_list") is not None:
            # the build's spectreList (Build.lua:969-974): written only when the payload names it, so a
            # payload without the field leaves the list the build already holds and the Lua chunk unchanged
            normalized_payload["spectre_list"] = [
                _require_non_empty_string(spectre_id, f"skill_payload.spectre_list[{i}]")
                for i, spectre_id in enumerate(_require_array(payload["spectre_list"], "skill_payload.spectre_list"))
            ]
        return normalized_payload

    def _normalize_default_gem_level(self, value: Any) -> str:
        normalized = _require_non_empty_string(value, "skill_payload.default_gem_level")
        if normalized not in _SUPPORTED_GEM_LEVEL_MODES:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.default_gem_level must be one of "
                + ", ".join(sorted(_SUPPORTED_GEM_LEVEL_MODES))
                + ".",
            )
        return normalized

    def _normalize_show_support_gem_types(self, value: Any) -> str:
        normalized = _require_non_empty_string(value, "skill_payload.show_support_gem_types")
        if normalized not in _SUPPORTED_SUPPORT_GEM_TYPES:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.show_support_gem_types must be one of "
                + ", ".join(sorted(_SUPPORTED_SUPPORT_GEM_TYPES))
                + ".",
            )
        return normalized

    def _normalize_sort_gems_by_dps_field(self, value: Any) -> str:
        normalized = _require_non_empty_string(value, "skill_payload.sort_gems_by_dps_field")
        if normalized not in _SUPPORTED_SORT_GEM_FIELDS:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "skill_payload.sort_gems_by_dps_field must be one of "
                + ", ".join(sorted(_SUPPORTED_SORT_GEM_FIELDS))
                + ".",
            )
        return normalized

    def apply_config_state(self, config_payload: dict[str, Any]) -> None:
        """Write both config sets into the live build (no XML round trip, no reload).

        Every field of the normalized payload maps onto `build.configTab` / `build`, so there is
        no fallback to `_apply_config_state_xml` (kept as the equivalence reference).
        ~165 ms instead of ~590 ms; the exported build is identical.
        """

        self._apply_config_state_inplace(self._normalize_config_payload(config_payload))

    def _apply_config_state_inplace(self, normalized: dict[str, Any]) -> None:
        active_index = normalized["active_config_set_index"]
        payload = {
            "active_config_set": active_index,
            "build_attrs": normalized["config_sets_by_index"][active_index]["build_attrs"],
            "config_sets": [
                {
                    "id": config_set["config_set_index"],
                    "title": config_set["title"],
                    # the same order the XML path writes the <Input> elements in
                    "inputs": [[name, config_set["xml_inputs"][name]] for name in config_set["xml_input_order"]],
                }
                for config_set in normalized["config_sets"]
            ],
        }
        chunk = "\n".join(_APPLY_CONFIG_LUA).replace("PAYLOAD_JSON", _lua_json_literal(payload))
        self._bridge.execute(chunk, nret=1)

    def _apply_config_state_xml(self, config_payload: dict[str, Any]) -> None:
        """The pre-2026-09-18 path: export the build, rewrite <Config>, reload the whole build.
        Kept as the reference the in-place writer is proven against (tests/test_pob_inplace_writes.py)."""

        normalized = self._normalize_config_payload(config_payload)
        xml_text = self.export_build_xml()
        root = self._parse_build_xml(xml_text)
        build_node = root.find("Build")
        config_node = root.find("Config")
        if build_node is None or config_node is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export is missing Build or Config nodes required for config authoring.",
            )

        active_config_set = normalized["config_sets_by_index"][normalized["active_config_set_index"]]
        build_node.set("bandit", active_config_set["build_attrs"]["bandit"])
        build_node.set("pantheonMajorGod", active_config_set["build_attrs"]["pantheonMajorGod"])
        build_node.set("pantheonMinorGod", active_config_set["build_attrs"]["pantheonMinorGod"])

        config_node.attrib.clear()
        config_node.set("activeConfigSet", str(normalized["active_config_set_index"]))
        for child in list(config_node):
            config_node.remove(child)

        for config_set in normalized["config_sets"]:
            config_set_node = ElementTree.SubElement(
                config_node,
                "ConfigSet",
                {
                    "id": str(config_set["config_set_index"]),
                    "title": config_set["title"],
                },
            )
            for field_name in config_set["xml_input_order"]:
                field_value = config_set["xml_inputs"][field_name]
                input_node = ElementTree.SubElement(config_set_node, "Input", {"name": field_name})
                if isinstance(field_value, bool):
                    input_node.set("boolean", _bool_xml(field_value))
                elif isinstance(field_value, (int, float)):
                    input_node.set("number", _number_xml(field_value))
                else:
                    input_node.set("string", str(field_value))

        self.load_reopen_source(_serialize_xml(root))

    def _normalize_config_payload(self, config_payload: dict[str, Any]) -> dict[str, Any]:
        payload = _require_mapping(config_payload, "config_payload")
        allowed_keys = {"active_config_set_id", "config_sets"}
        extra_keys = sorted(set(payload) - allowed_keys)
        if extra_keys:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Unsupported config_payload field(s): " + ", ".join(extra_keys),
            )

        config_sets: list[dict[str, Any]] = []
        config_sets_by_index: dict[int, dict[str, Any]] = {}
        for index, entry in enumerate(_require_array(payload.get("config_sets"), "config_payload.config_sets"), start=1):
            config_set = _require_mapping(entry, f"config_payload.config_sets[{index}]")
            allowed_set_keys = {
                "config_set_id",
                "title",
                "bandit",
                "pantheon_major",
                "pantheon_minor",
                "buffs",
                "combat_conditions",
                "enemy_state",
                "inputs",
            }
            extra_set_keys = sorted(set(config_set) - allowed_set_keys)
            if extra_set_keys:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"Unsupported config set field(s) in config_payload.config_sets[{index}]: "
                    + ", ".join(extra_set_keys),
                )

            config_set_index = _normalize_config_set_index(
                config_set.get("config_set_id"),
                f"config_payload.config_sets[{index}].config_set_id",
            )
            if config_set_index in config_sets_by_index:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"config_payload.config_sets[{index}] duplicates config_set_id {config_set.get('config_set_id')!r}.",
                )

            buffs_payload = _require_mapping(
                config_set.get("buffs", {}),
                f"config_payload.config_sets[{index}].buffs",
            )
            extra_buff_keys = sorted(set(buffs_payload) - {"onslaught", "fortification"})
            if extra_buff_keys:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"Unsupported buffs field(s) in config_payload.config_sets[{index}].buffs: "
                    + ", ".join(extra_buff_keys),
                )

            combat_payload = _require_mapping(
                config_set.get("combat_conditions", {}),
                f"config_payload.config_sets[{index}].combat_conditions",
            )
            extra_combat_keys = sorted(set(combat_payload) - {"using_flask"})
            if extra_combat_keys:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"Unsupported combat_conditions field(s) in config_payload.config_sets[{index}].combat_conditions: "
                    + ", ".join(extra_combat_keys),
                )

            enemy_payload = _require_mapping(
                config_set.get("enemy_state", {}),
                f"config_payload.config_sets[{index}].enemy_state",
            )
            extra_enemy_keys = sorted(set(enemy_payload) - {"is_boss", "is_shocked", "is_ignited", "shock_effect"})
            if extra_enemy_keys:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"Unsupported enemy_state field(s) in config_payload.config_sets[{index}].enemy_state: "
                    + ", ".join(extra_enemy_keys),
                )

            bandit = self._normalize_config_choice(
                config_set.get("bandit"),
                field_name=f"config_payload.config_sets[{index}].bandit",
                allowed_values=_SUPPORTED_BANDIT_CHOICES,
                default_value="None",
            )
            pantheon_major = self._normalize_config_choice(
                config_set.get("pantheon_major"),
                field_name=f"config_payload.config_sets[{index}].pantheon_major",
                allowed_values=_SUPPORTED_MAJOR_PANTHEONS,
                default_value="None",
            )
            pantheon_minor = self._normalize_config_choice(
                config_set.get("pantheon_minor"),
                field_name=f"config_payload.config_sets[{index}].pantheon_minor",
                allowed_values=_SUPPORTED_MINOR_PANTHEONS,
                default_value="None",
            )
            enemy_is_boss = self._normalize_config_choice(
                enemy_payload.get("is_boss"),
                field_name=f"config_payload.config_sets[{index}].enemy_state.is_boss",
                allowed_values=_SUPPORTED_ENEMY_BOSS_STATES,
                default_value="Pinnacle",
            )
            enemy_is_shocked = _require_bool(
                enemy_payload.get("is_shocked", False),
                f"config_payload.config_sets[{index}].enemy_state.is_shocked",
            )
            enemy_is_ignited = _require_bool(
                enemy_payload.get("is_ignited", False),
                f"config_payload.config_sets[{index}].enemy_state.is_ignited",
            )
            shock_effect_raw = enemy_payload.get("shock_effect")
            if shock_effect_raw is None:
                shock_effect = None
            else:
                shock_effect = _require_int(
                    shock_effect_raw,
                    f"config_payload.config_sets[{index}].enemy_state.shock_effect",
                )
                if shock_effect < 0:
                    raise WorkerContractError(
                        "runtime_protocol_failed",
                        f"config_payload.config_sets[{index}].enemy_state.shock_effect must be >= 0.",
                    )
                if not enemy_is_shocked:
                    raise WorkerContractError(
                        "runtime_protocol_failed",
                        f"config_payload.config_sets[{index}].enemy_state.shock_effect requires is_shocked=true.",
                    )

            xml_inputs: dict[str, str | bool | int] = {}
            if bandit != _CONFIG_DEFAULT_INPUTS["bandit"]:
                xml_inputs["bandit"] = bandit
            if pantheon_major != _CONFIG_DEFAULT_INPUTS["pantheonMajorGod"]:
                xml_inputs["pantheonMajorGod"] = pantheon_major
            if pantheon_minor != _CONFIG_DEFAULT_INPUTS["pantheonMinorGod"]:
                xml_inputs["pantheonMinorGod"] = pantheon_minor
            if enemy_is_boss != _CONFIG_DEFAULT_INPUTS["enemyIsBoss"]:
                xml_inputs["enemyIsBoss"] = enemy_is_boss
            if _require_bool(
                buffs_payload.get("onslaught", False),
                f"config_payload.config_sets[{index}].buffs.onslaught",
            ):
                xml_inputs["buffOnslaught"] = True
            if _require_bool(
                buffs_payload.get("fortification", False),
                f"config_payload.config_sets[{index}].buffs.fortification",
            ):
                xml_inputs["buffFortification"] = True
            if _require_bool(
                combat_payload.get("using_flask", False),
                f"config_payload.config_sets[{index}].combat_conditions.using_flask",
            ):
                xml_inputs["conditionUsingFlask"] = True
            if enemy_is_shocked:
                xml_inputs["conditionEnemyShocked"] = True
            if enemy_is_ignited:
                xml_inputs["conditionEnemyIgnited"] = True
            if shock_effect is not None:
                xml_inputs["conditionShockEffect"] = shock_effect
            for var_name, var_value in _normalize_config_inputs(
                config_set.get("inputs"),
                field_name=f"config_payload.config_sets[{index}].inputs",
            ).items():
                xml_inputs[var_name] = var_value

            normalized_config_set = {
                "config_set_index": config_set_index,
                "config_set_id": _normalize_config_set_id(config_set_index),
                "title": _require_optional_string(
                    config_set.get("title"),
                    f"config_payload.config_sets[{index}].title",
                )
                or ("Default" if config_set_index == 1 else f"Config {config_set_index}"),
                "build_attrs": {
                    "bandit": bandit,
                    "pantheonMajorGod": pantheon_major,
                    "pantheonMinorGod": pantheon_minor,
                },
                "xml_inputs": xml_inputs,
                "xml_input_order": sorted(xml_inputs),
            }
            config_sets.append(normalized_config_set)
            config_sets_by_index[config_set_index] = normalized_config_set

        if not config_sets:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "config_payload.config_sets must contain at least one config set definition.",
            )

        active_config_set_index = _normalize_config_set_index(
            payload.get("active_config_set_id"),
            "config_payload.active_config_set_id",
        )
        if active_config_set_index not in config_sets_by_index:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "config_payload.active_config_set_id must reference one of config_payload.config_sets[].config_set_id.",
            )

        return {
            "active_config_set_index": active_config_set_index,
            "active_config_set_id": _normalize_config_set_id(active_config_set_index),
            "config_sets": config_sets,
            "config_sets_by_index": config_sets_by_index,
        }

    def _normalize_config_choice(
        self,
        value: Any,
        *,
        field_name: str,
        allowed_values: frozenset[str],
        default_value: str,
    ) -> str:
        if value is None:
            return default_value
        normalized = _require_non_empty_string(value, field_name)
        if normalized not in allowed_values:
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"{field_name} must be one of {', '.join(sorted(allowed_values))}.",
            )
        return normalized

    def apply_tree_state(self, tree_payload: dict[str, Any]) -> None:
        try:
            payload_json = json.dumps(tree_payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise WorkerContractError("runtime_protocol_failed", "tree_payload must be JSON-serializable.") from exc

        self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    f"local payload_json = {_lua_long_string(payload_json)}",
                    "local payload, _, decode_err = json.decode(payload_json, 1, nil)",
                    "if type(payload) ~= 'table' then",
                    "  error('tree_payload must decode to a Lua table: ' .. tostring(decode_err or 'unknown error'))",
                    "end",
                    "local allowed_keys = {",
                    "  active_spec_id = true,",
                    "  class_id = true,",
                    "  ascendancy_id = true,",
                    "  secondary_ascendancy_id = true,",
                    "  ascendancy_node_ids = true,",
                    "  ascendancy_notable_node_ids = true,",
                    "  user_allocated_node_ids = true,",
                    "  keystone_node_ids = true,",
                    "  mastery_effect_ids = true,",
                    "  cluster_jewel_socket_ids = true,",
                    "  socketed_jewel_node_ids = true,",
                    "  anoint_allocations = true,",
                    "  override_carrier_node_ids = true,",
                    "  override_carriers = true,",
                    "  cluster_jewel_items = true,",
                    "  socketed_jewel_items = true,",
                    "}",
                    "for key, _ in pairs(payload) do",
                    "  if not allowed_keys[key] then",
                    "    error('Unsupported tree_payload field: ' .. tostring(key))",
                    "  end",
                    "end",
                    "local function is_null(value)",
                    "  return value == nil or value == json.null",
                    "end",
                    "local function require_array(value, field_name)",
                    "  if is_null(value) then",
                    "    return {}",
                    "  end",
                    "  if type(value) ~= 'table' then",
                    "    error(field_name .. ' must be an array.')",
                    "  end",
                    "  return value",
                    "end",
                    "local function require_int(value, field_name)",
                    "  if type(value) ~= 'number' then",
                    "    error(field_name .. ' must be an integer.')",
                    "  end",
                    "  return math.floor(value)",
                    "end",
                    "local function normalize_spec_index(value)",
                    "  if is_null(value) then",
                    "    return 1",
                    "  end",
                    "  if type(value) == 'number' then",
                    "    local index = math.floor(value)",
                    "    if index < 1 then",
                    "      error('active_spec_id must reference spec.main or spec.<positive-index>.')",
                    "    end",
                    "    return index",
                    "  end",
                    "  if type(value) == 'string' then",
                    "    if value == 'spec.main' then",
                    "      return 1",
                    "    end",
                    "    local raw_index = value:match('^spec%.(%d+)$')",
                    "    if raw_index then",
                    "      local index = tonumber(raw_index)",
                    "      if index and index >= 1 then",
                    "        return index",
                    "      end",
                    "    end",
                    "  end",
                    "  error('active_spec_id must reference spec.main or spec.<positive-index>.')",
                    "end",
                    "local function normalize_optional_node_ids(value, field_name)",
                    "  local normalized = {}",
                    "  for index, raw_value in ipairs(require_array(value, field_name)) do",
                    "    normalized[index] = require_int(raw_value, field_name .. '[' .. tostring(index) .. ']')",
                    "  end",
                    "  return normalized",
                    "end",
                    "local function resolve_class_id(value)",
                    "  if is_null(value) then",
                    "    return build.spec.curClassId or " + str(_CANONICAL_BLANK_CLASS_ID),
                    "  end",
                    "  if type(value) == 'number' then",
                    "    local class_id = math.floor(value)",
                    "    if build.spec.tree.classes[class_id] then",
                    "      return class_id",
                    "    end",
                    "  elseif type(value) == 'string' then",
                    "    for class_id, class in pairs(build.spec.tree.classes) do",
                    "      if class.name == value or tostring(class_id) == value then",
                    "        return tonumber(class_id)",
                    "      end",
                    "    end",
                    "  end",
                    "  error('Unknown passive-tree class reference: ' .. tostring(value))",
                    "end",
                    "local function resolve_ascendancy_id(value, class_id)",
                    "  if is_null(value) then",
                    "    return 0",
                    "  end",
                    "  local class = build.spec.tree.classes[class_id]",
                    "  if not class or type(class.classes) ~= 'table' then",
                    "    error('Could not resolve ascendancy because class ' .. tostring(class_id) .. ' is unavailable.')",
                    "  end",
                    "  if type(value) == 'number' then",
                    "    local ascendancy_id = math.floor(value)",
                    "    if class.classes[ascendancy_id] then",
                    "      return ascendancy_id",
                    "    end",
                    "  elseif type(value) == 'string' then",
                    "    if value == '' or value == 'None' then",
                    "      return 0",
                    "    end",
                    "    for ascendancy_id, ascendancy in pairs(class.classes) do",
                    "      if ascendancy.name == value or ascendancy.id == value or tostring(ascendancy_id) == value then",
                    "        return tonumber(ascendancy_id)",
                    "      end",
                    "    end",
                    "  end",
                    "  error('Unknown ascendancy reference for class ' .. tostring(class_id) .. ': ' .. tostring(value))",
                    "end",
                    "local function resolve_secondary_ascendancy_id(value)",
                    "  if is_null(value) then",
                    "    return 0",
                    "  end",
                    "  if type(value) == 'number' then",
                    "    local ascendancy_id = math.floor(value)",
                    "    if ascendancy_id == 0 then",
                    "      return 0",
                    "    end",
                    "    if build.spec.tree.alternate_ascendancies and build.spec.tree.alternate_ascendancies[ascendancy_id] then",
                    "      return ascendancy_id",
                    "    end",
                    "  elseif type(value) == 'string' then",
                    "    if value == '' or value == 'None' then",
                    "      return 0",
                    "    end",
                    "    if build.spec.tree.alternate_ascendancies then",
                    "      for ascendancy_id, ascendancy in pairs(build.spec.tree.alternate_ascendancies) do",
                    "        if ascendancy.name == value or tostring(ascendancy_id) == value then",
                    "          return tonumber(ascendancy_id)",
                    "        end",
                    "      end",
                    "    end",
                    "  end",
                    "  error('Unknown secondary ascendancy reference: ' .. tostring(value))",
                    "end",
                    "local function ensure_spec(index)",
                    "  while #build.treeTab.specList < index do",
                    "    local source_spec = build.treeTab.specList[#build.treeTab.specList]",
                    "    local new_spec = new('PassiveSpec', build, source_spec.treeVersion)",
                    "    new_spec:RestoreUndoState(source_spec:CreateUndoState(), source_spec.treeVersion)",
                    "    table.insert(build.treeTab.specList, new_spec)",
                    "  end",
                    "  build.treeTab:SetActiveSpec(index)",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function clear_tree_socket_items()",
                    "  if type(build.itemsTab.sockets) ~= 'table' then",
                    "    build.spec.jewels = {}",
                    "    build.spec:BuildClusterJewelGraphs()",
                    "    return",
                    "  end",
                    "  for _, socket in pairs(build.itemsTab.sockets) do",
                    "    if socket and socket.selItemId and socket.selItemId ~= 0 then",
                    "      socket:SetSelItemId(0)",
                    "    end",
                    "  end",
                    "  build.spec.jewels = {}",
                    "  build.spec:BuildClusterJewelGraphs()",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function rebuild_blank_tree(class_id, ascendancy_id, secondary_ascendancy_id)",
                    "  build.spec:ResetNodes()",
                    "  build.spec.hashOverrides = {}",
                    "  wipeTable(build.spec.masterySelections)",
                    "  build.spec:SelectClass(class_id)",
                    "  build.spec:SelectAscendClass(ascendancy_id)",
                    "  build.spec:SelectSecondaryAscendClass(secondary_ascendancy_id)",
                    "  build.spec:BuildAllDependsAndPaths()",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function node_display_name(node)",
                    "  return tostring(node.dn or node.name or node.label or 'unknown node')",
                    "end",
                    *_ASCENDANCY_MATCH_LUA,
                    "local function node_is_ascendancy_start(node)",
                    "  return node.isAscendancyStart == true or node.ascendancyStart == true",
                    "end",
                    "local function node_is_notable(node)",
                    "  return node.isNotable == true or node.notable == true or node.type == 'Notable'",
                    "end",
                    "local function validate_ascendancy_nodes(node_ids, field_name, expected_ascendancy_name, require_notable)",
                    "  if #node_ids == 0 then",
                    "    return",
                    "  end",
                    "  if type(expected_ascendancy_name) ~= 'string' or expected_ascendancy_name == '' or expected_ascendancy_name == 'None' then",
                    "    error(field_name .. ' requires a selected ascendancy_id.')",
                    "  end",
                    "  local ascendancy_names = current_ascendancy_names()",
                    "  for index, node_id in ipairs(node_ids) do",
                    "    local node = build.spec.nodes[node_id]",
                    "    if not node then",
                    "      error(field_name .. '[' .. tostring(index) .. '] references node ' .. tostring(node_id) .. ' which is unavailable in the selected class/ascendancy tree.')",
                    "    end",
                    "    if not node_in_current_ascendancy(node, ascendancy_names) or node_is_ascendancy_start(node) then",
                    "      error(field_name .. '[' .. tostring(index) .. '] references node ' .. tostring(node_id) .. ' outside selected ascendancy ' .. tostring(expected_ascendancy_name) .. '.')",
                    "    end",
                    "    if require_notable and not node_is_notable(node) then",
                    "      error(field_name .. '[' .. tostring(index) .. '] references non-notable ascendancy node ' .. tostring(node_id) .. ' (' .. node_display_name(node) .. ').')",
                    "    end",
                    "  end",
                    "end",
                    "local function apply_override_carriers(entries)",
                    "  for index, entry in ipairs(require_array(entries, 'override_carriers')) do",
                    "    if type(entry) ~= 'table' then",
                    "      error('override_carriers[' .. tostring(index) .. '] must be an object.')",
                    "    end",
                    "    local node_id = require_int(entry.node_id or entry.id, 'override_carriers[' .. tostring(index) .. '].node_id')",
                    "    local tattoo_name = entry.tattoo_name or entry.display_name or entry.name or entry.dn",
                    "    if type(tattoo_name) ~= 'string' or tattoo_name == '' then",
                    "      error('override_carriers[' .. tostring(index) .. '] must include a non-empty tattoo_name.')",
                    "    end",
                    "    local source = build.spec.tree.tattoo and build.spec.tree.tattoo.nodes and build.spec.tree.tattoo.nodes[tattoo_name]",
                    "    if not source then",
                    "      error('Pinned runtime could not resolve tattoo override ' .. tattoo_name .. '.')",
                    "    end",
                    "    local override = copyTable(source, true)",
                    "    override.id = node_id",
                    "    build.spec.hashOverrides[node_id] = override",
                    "    local live_node = build.spec.nodes[node_id]",
                    "    if live_node then",
                    "      build.spec:ReplaceNode(live_node, override)",
                    "    end",
                    "  end",
                    "  build.spec:BuildAllDependsAndPaths()",
                    "end",
                    "local function apply_masteries(entries)",
                    "  for index, entry in ipairs(require_array(entries, 'mastery_effect_ids')) do",
                    "    local node_id = nil",
                    "    local effect_id = nil",
                    "    if type(entry) == 'string' then",
                    "      local raw_node_id, raw_effect_id = entry:match('^(%d+):(%d+)$')",
                    "      if not raw_node_id or not raw_effect_id then",
                    "        error('mastery_effect_ids[' .. tostring(index) .. '] must encode node_id:effect_id.')",
                    "      end",
                    "      node_id = tonumber(raw_node_id)",
                    "      effect_id = tonumber(raw_effect_id)",
                    "    elseif type(entry) == 'table' then",
                    "      node_id = require_int(entry.node_id or entry.id, 'mastery_effect_ids[' .. tostring(index) .. '].node_id')",
                    "      effect_id = require_int(entry.effect_id or entry.effect, 'mastery_effect_ids[' .. tostring(index) .. '].effect_id')",
                    "    else",
                    "      error('mastery_effect_ids[' .. tostring(index) .. '] must be a node_id:effect_id string or object.')",
                    "    end",
                    "    local node = build.spec.nodes[node_id]",
                    "    if not node or node.type ~= 'Mastery' then",
                    "      error('Mastery node ' .. tostring(node_id) .. ' is unavailable in the active passive tree.')",
                    "    end",
                    "    local effect = build.spec.tree.masteryEffects[effect_id]",
                    "    if not effect then",
                    "      error('Mastery effect ' .. tostring(effect_id) .. ' is unavailable in the active passive tree.')",
                    "    end",
                    "    build.spec.masterySelections[node_id] = effect_id",
                    "    node.sd = effect.sd",
                    "    node.allMasteryOptions = false",
                    "    node.reminderText = { 'Tip: Right click to select a different effect' }",
                    "    build.spec.tree:ProcessStats(node)",
                    "  end",
                    "end",
                    "local function finalize_masteries(entries)",
                    "  for index, entry in ipairs(require_array(entries, 'mastery_effect_ids')) do",
                    "    local node_id = nil",
                    "    local effect_id = nil",
                    "    if type(entry) == 'string' then",
                    "      local raw_node_id, raw_effect_id = entry:match('^(%d+):(%d+)$')",
                    "      if not raw_node_id or not raw_effect_id then",
                    "        error('mastery_effect_ids[' .. tostring(index) .. '] must encode node_id:effect_id.')",
                    "      end",
                    "      node_id = tonumber(raw_node_id)",
                    "      effect_id = tonumber(raw_effect_id)",
                    "    elseif type(entry) == 'table' then",
                    "      node_id = require_int(entry.node_id or entry.id, 'mastery_effect_ids[' .. tostring(index) .. '].node_id')",
                    "      effect_id = require_int(entry.effect_id or entry.effect, 'mastery_effect_ids[' .. tostring(index) .. '].effect_id')",
                    "    else",
                    "      error('mastery_effect_ids[' .. tostring(index) .. '] must be a node_id:effect_id string or object.')",
                    "    end",
                    "    local node = build.spec.nodes[node_id]",
                    "    local effect = build.spec.tree.masteryEffects[effect_id]",
                    "    if not node or node.type ~= 'Mastery' then",
                    "      error('Mastery node ' .. tostring(node_id) .. ' is unavailable in the active passive tree.')",
                    "    end",
                    "    if not effect then",
                    "      error('Mastery effect ' .. tostring(effect_id) .. ' is unavailable in the active passive tree.')",
                    "    end",
                    "    build.spec.masterySelections[node_id] = effect_id",
                    "    node.sd = effect.sd",
                    "    node.allMasteryOptions = false",
                    "    node.reminderText = { 'Tip: Right click to select a different effect' }",
                    "    build.spec.tree:ProcessStats(node)",
                    "    if not node.alloc then",
                    "      build.spec:AllocNode(node)",
                    "    end",
                    "  end",
                    "  build.spec:BuildAllDependsAndPaths()",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function allocate_nodes(node_ids, field_name, allow_missing)",
                    "  for index, node_id in ipairs(node_ids) do",
                    "    local node = build.spec.nodes[node_id]",
                    "    if node then",
                    "      build.spec:AllocNode(node)",
                    "    elseif not allow_missing then",
                    "      error(field_name .. '[' .. tostring(index) .. '] references node ' .. tostring(node_id) .. ' which is unavailable in the active passive tree.')",
                    "    end",
                    "  end",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function build_item_from_raw(raw_item_text, field_name)",
                    "  if type(raw_item_text) ~= 'string' or raw_item_text == '' then",
                    "    error(field_name .. '.raw_item_text must be a non-empty string.')",
                    "  end",
                    "  build.itemsTab:CreateDisplayItemFromRaw(raw_item_text, true)",
                    "  if not build.itemsTab.displayItem then",
                    "    error('Pinned runtime could not parse ' .. field_name .. '.raw_item_text into an item.')",
                    "  end",
                    "  local item = build.itemsTab.displayItem",
                    "  build.itemsTab:AddItem(item, true)",
                    "  build.itemsTab:SetDisplayItem()",
                    "  return item",
                    "end",
                    "local function assign_socket_item(node_id, raw_item_text, field_name)",
                    "  build.itemsTab:UpdateSockets()",
                    "  local socket = build.itemsTab.sockets[node_id]",
                    "  if not socket then",
                    "    error(field_name .. ' references node ' .. tostring(node_id) .. ' which is not an active jewel socket.')",
                    "  end",
                    "  local item = build_item_from_raw(raw_item_text, field_name)",
                    "  socket:SetSelItemId(item.id)",
                    "  build.itemsTab:UpdateSockets()",
                    "  return item",
                    "end",
                    "local function apply_cluster_jewels(entries)",
                    "  for index, entry in ipairs(require_array(entries, 'cluster_jewel_items')) do",
                    "    if type(entry) ~= 'table' then",
                    "      error('cluster_jewel_items[' .. tostring(index) .. '] must be an object.')",
                    "    end",
                    "    local node_id = require_int(entry.node_id or entry.socket_node_id, 'cluster_jewel_items[' .. tostring(index) .. '].node_id')",
                    "    local node = build.spec.nodes[node_id]",
                    "    if not node then",
                    "      error('cluster_jewel_items[' .. tostring(index) .. '] references unavailable node ' .. tostring(node_id) .. '.')",
                    "    end",
                    "    build.spec:AllocNode(node)",
                    "    local item = assign_socket_item(node_id, entry.raw_item_text, 'cluster_jewel_items[' .. tostring(index) .. ']')",
                    "    if not (item.clusterJewel or (item.jewelData and item.jewelData.clusterJewelValid)) then",
                    "      error('cluster_jewel_items[' .. tostring(index) .. '] did not materialize a valid cluster jewel.')",
                    "    end",
                    "  end",
                    "  build.spec:BuildClusterJewelGraphs()",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local function apply_socketed_jewels(entries)",
                    "  for index, entry in ipairs(require_array(entries, 'socketed_jewel_items')) do",
                    "    if type(entry) ~= 'table' then",
                    "      error('socketed_jewel_items[' .. tostring(index) .. '] must be an object.')",
                    "    end",
                    "    local node_id = require_int(entry.node_id or entry.socket_node_id, 'socketed_jewel_items[' .. tostring(index) .. '].node_id')",
                    "    local node = build.spec.nodes[node_id]",
                    "    if not node then",
                    "      error('socketed_jewel_items[' .. tostring(index) .. '] references unavailable node ' .. tostring(node_id) .. '.')",
                    "    end",
                    "    build.spec:AllocNode(node)",
                    "    assign_socket_item(node_id, entry.raw_item_text, 'socketed_jewel_items[' .. tostring(index) .. ']')",
                    "  end",
                    "end",
                    "local function validate_exact_ids(field_name, expected_ids, observed_ids)",
                    "  table.sort(expected_ids)",
                    "  table.sort(observed_ids)",
                    "  if #expected_ids ~= #observed_ids then",
                    "    error(field_name .. ' did not materialize the requested node set.')",
                    "  end",
                    "  for index, node_id in ipairs(expected_ids) do",
                    "    if observed_ids[index] ~= node_id then",
                    "      error(field_name .. ' did not materialize the requested node set.')",
                    "    end",
                    "  end",
                    "end",
                    "local function validate_present_ids(field_name, expected_ids, observed_ids)",
                    "  local observed_lookup = {}",
                    "  for _, node_id in ipairs(observed_ids) do",
                    "    observed_lookup[node_id] = true",
                    "  end",
                    "  local missing_ids = {}",
                    "  for _, node_id in ipairs(expected_ids) do",
                    "    if not observed_lookup[node_id] then",
                    "      table.insert(missing_ids, node_id)",
                    "    end",
                    "  end",
                    "  if #missing_ids > 0 then",
                    "    table.sort(missing_ids)",
                    "    error(field_name .. ' did not materialize requested node(s): ' .. table.concat(missing_ids, ', '))",
                    "  end",
                    "end",
                    "local function import_available_nodes(node_ids, class_id, ascendancy_id, secondary_ascendancy_id)",
                    "  local import_node_ids = {}",
                    "  for _, node_id in ipairs(node_ids) do",
                    "    if build.spec.nodes[node_id] then",
                    "      table.insert(import_node_ids, node_id)",
                    "    end",
                    "  end",
                    "  local mastery_effects = {}",
                    "  for mastery_node_id, effect_id in pairs(build.spec.masterySelections) do",
                    "    mastery_effects[mastery_node_id] = effect_id",
                    "  end",
                    "  local hash_overrides = {}",
                    "  for node_id, override in pairs(build.spec.hashOverrides) do",
                    "    hash_overrides[node_id] = override",
                    "  end",
                    "  build.spec:ImportFromNodeList(",
                    "    nil,  -- className (added in PoB 2.67: resolved from class_id when nil)",
                    "    class_id,",
                    "    ascendancy_id,",
                    "    secondary_ascendancy_id,",
                    "    import_node_ids,",
                    "    hash_overrides,",
                    "    mastery_effects",
                    "  )",
                    "  build.itemsTab:UpdateSockets()",
                    "end",
                    "local target_spec_index = normalize_spec_index(payload.active_spec_id)",
                    "ensure_spec(target_spec_index)",
                    "clear_tree_socket_items()",
                    "local class_id = resolve_class_id(payload.class_id)",
                    "local ascendancy_id = resolve_ascendancy_id(payload.ascendancy_id, class_id)",
                    "local secondary_ascendancy_id = resolve_secondary_ascendancy_id(payload.secondary_ascendancy_id)",
                    "rebuild_blank_tree(class_id, ascendancy_id, secondary_ascendancy_id)",
                    "if #require_array(payload.anoint_allocations, 'anoint_allocations') > 0 then",
                    "  error('anoint_allocations are not repo-owned in this tree-local proof slice.')",
                    "end",
                    "apply_override_carriers(payload.override_carriers)",
                    "apply_masteries(payload.mastery_effect_ids)",
                    "local requested_user_nodes = normalize_optional_node_ids(payload.user_allocated_node_ids, 'user_allocated_node_ids')",
                    "local requested_ascendancy_nodes = normalize_optional_node_ids(payload.ascendancy_node_ids, 'ascendancy_node_ids')",
                    "local requested_ascendancy_notables = normalize_optional_node_ids(payload.ascendancy_notable_node_ids, 'ascendancy_notable_node_ids')",
                    "validate_ascendancy_nodes(requested_ascendancy_nodes, 'ascendancy_node_ids', build.spec.curAscendClassName, false)",
                    "validate_ascendancy_nodes(requested_ascendancy_notables, 'ascendancy_notable_node_ids', build.spec.curAscendClassName, true)",
                    "local requested_keystones = normalize_optional_node_ids(payload.keystone_node_ids, 'keystone_node_ids')",
                    "local requested_cluster_sockets = normalize_optional_node_ids(payload.cluster_jewel_socket_ids, 'cluster_jewel_socket_ids')",
                    "local requested_socketed_nodes = normalize_optional_node_ids(payload.socketed_jewel_node_ids, 'socketed_jewel_node_ids')",
                    "local requested_override_nodes = normalize_optional_node_ids(payload.override_carrier_node_ids, 'override_carrier_node_ids')",
                    "local merged_node_ids = {}",
                    "local seen_node_ids = {}",
                    "local function merge_nodes(node_ids)",
                    "  for _, node_id in ipairs(node_ids) do",
                    "    if not seen_node_ids[node_id] then",
                    "      seen_node_ids[node_id] = true",
                    "      table.insert(merged_node_ids, node_id)",
                    "    end",
                    "  end",
                    "end",
                    "merge_nodes(requested_user_nodes)",
                    "merge_nodes(requested_ascendancy_nodes)",
                    "merge_nodes(requested_ascendancy_notables)",
                    "merge_nodes(requested_keystones)",
                    "merge_nodes(requested_cluster_sockets)",
                    "merge_nodes(requested_socketed_nodes)",
                    "merge_nodes(requested_override_nodes)",
                    "for _, entry in ipairs(require_array(payload.mastery_effect_ids, 'mastery_effect_ids')) do",
                    "  if type(entry) == 'string' then",
                    "    local raw_node_id = entry:match('^(%d+):%d+$')",
                    "    if raw_node_id then",
                    "      merge_nodes({ tonumber(raw_node_id) })",
                    "    end",
                    "  elseif type(entry) == 'table' then",
                    "    merge_nodes({ require_int(entry.node_id or entry.id, 'mastery_effect_ids.node_id') })",
                    "  end",
                    "end",
                    "for _, entry in ipairs(require_array(payload.override_carriers, 'override_carriers')) do",
                    "  if type(entry) == 'table' then",
                    "    merge_nodes({ require_int(entry.node_id or entry.id, 'override_carriers.node_id') })",
                    "  end",
                    "end",
                    "import_available_nodes(merged_node_ids, class_id, ascendancy_id, secondary_ascendancy_id)",
                    "apply_cluster_jewels(payload.cluster_jewel_items)",
                    "allocate_nodes(merged_node_ids, 'user_allocated_node_ids', false)",
                    "finalize_masteries(payload.mastery_effect_ids)",
                    "apply_socketed_jewels(payload.socketed_jewel_items)",
                    "local observed_cluster_sockets = {}",
                    "local observed_socketed_nodes = {}",
                    "for node_id, item_id in pairs(build.spec.jewels) do",
                    "  if type(item_id) == 'number' and item_id > 0 then",
                    "    table.insert(observed_socketed_nodes, node_id)",
                    "    local item = build.itemsTab.items[item_id]",
                    "    if item and (item.clusterJewel or (item.jewelData and item.jewelData.clusterJewelValid)) then",
                    "      table.insert(observed_cluster_sockets, node_id)",
                    "    end",
                    "  end",
                    "end",
                    "if #requested_cluster_sockets > 0 then",
                    "  validate_exact_ids('cluster_jewel_socket_ids', requested_cluster_sockets, observed_cluster_sockets)",
                    "end",
                    "if #requested_socketed_nodes > 0 then",
                    "  validate_exact_ids('socketed_jewel_node_ids', requested_socketed_nodes, observed_socketed_nodes)",
                    "end",
                    "if #requested_override_nodes > 0 then",
                    "  local observed_override_nodes = {}",
                    "  for node_id, _ in pairs(build.spec.hashOverrides) do",
                    "    table.insert(observed_override_nodes, node_id)",
                    "  end",
                    "  validate_exact_ids('override_carrier_node_ids', requested_override_nodes, observed_override_nodes)",
                    "end",
                    "if #requested_ascendancy_nodes > 0 or #requested_ascendancy_notables > 0 then",
                    "  local observed_ascendancy_nodes = {}",
                    "  local observed_ascendancy_notables = {}",
                    "  local observed_ascendancy_names = current_ascendancy_names()",
                    "  for node_id, node in pairs(build.spec.allocNodes) do",
                    "    if node_in_current_ascendancy(node, observed_ascendancy_names) and not node_is_ascendancy_start(node) then",
                    "      table.insert(observed_ascendancy_nodes, node_id)",
                    "      if node_is_notable(node) then",
                    "        table.insert(observed_ascendancy_notables, node_id)",
                    "      end",
                    "    end",
                    "  end",
                    "  validate_present_ids('ascendancy_node_ids', requested_ascendancy_nodes, observed_ascendancy_nodes)",
                    "  validate_present_ids('ascendancy_notable_node_ids', requested_ascendancy_notables, observed_ascendancy_notables)",
                    "end",
                    "runCallback('OnFrame')",
                )
            )
        )

    def export_build_xml(self, *, derive_flask_flags: bool = False) -> str:
        """The build's XML. `derive_flask_flags` (the delivered export, #575) derives the Flask slots' flags first,
        so the XML carries exactly PoB's uptime-derived flags; the internal readers (state, config, calc snapshot)
        leave the flags as the slots hold them."""

        lines = (*_FLASK_UPTIME_LUA, "derive_flask_flags()") if derive_flask_flags else ()
        xml_text = self._bridge.execute("\n".join((*lines, "return build:SaveDB('code')")), nret=1)[0]
        if not xml_text or not xml_text.strip():
            raise WorkerContractError("missing_export_payload", "PoB did not return a non-empty XML export payload.")
        return xml_text

    def verify_pob_import_code_string(self, import_code: str) -> dict[str, Any]:
        if not isinstance(import_code, str):
            raise WorkerContractError("runtime_protocol_failed", "import_code must be a string.")
        payload = self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    f"local result = verifyImportCodeString({_lua_long_string(import_code)})",
                    "return json.encode(result)",
                )
            ),
            nret=1,
        )[0]
        if payload is None:
            raise WorkerContractError("runtime_protocol_failed", "Native import-code verifier returned no payload.")
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise WorkerContractError("runtime_protocol_failed", "Native import-code verifier returned a non-object payload.")
        missing_input = result.pop("missing_input", "")
        invalid_reason = result.pop("invalid_reason", "")
        result["missing_inputs"] = (
            [missing_input] if isinstance(missing_input, str) and missing_input.strip() else []
        )
        result["invalid_reasons"] = (
            [invalid_reason] if isinstance(invalid_reason, str) and invalid_reason.strip() else []
        )
        return result

    def read_node_power_report(self, node_power_request: dict[str, Any] | None = None) -> dict[str, Any]:
        request = _normalize_node_power_report_request(node_power_request)
        config_set_id = request["config_set_id"]
        if config_set_id is not None:
            self._set_active_config_set(config_set_id)

        config_set_literal = "json.null" if config_set_id is None else _lua_long_string(config_set_id)
        max_depth_literal = "nil" if request["max_depth"] is None else str(request["max_depth"])
        max_rows_literal = "nil" if request["max_rows"] is None else str(request["max_rows"])
        family_by_stat = {stat: "defense" for stat in _NODE_POWER_DEFENSE_STATS}
        payload = self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    f"local report_id = {_lua_long_string(request['report_id'])}",
                    f"local metric_stat = {_lua_long_string(request['metric_stat'])}",
                    f"local metric_lane = {_lua_long_string(request['metric_lane'])}",
                    f"local requested_config_set_id = {config_set_literal}",
                    f"local max_depth = {max_depth_literal}",
                    f"local max_rows = {max_rows_literal}",
                    f"local family_by_stat_json = {_lua_json_literal(family_by_stat)}",
                    "local family_by_stat, _, family_decode_err = json.decode(family_by_stat_json, 1, nil)",
                    "if type(family_by_stat) ~= 'table' then",
                    "  error('node-power metric family mapping must decode to a table: ' .. tostring(family_decode_err or 'unknown error'))",
                    "end",
                    "local function encode_null(value)",
                    "  if value == nil then return json.null end",
                    "  return value",
                    "end",
                    "local function empty_object()",
                    "  return setmetatable({}, { __jsontype = 'object' })",
                    "end",
                    "local function scalar_number(value)",
                    "  if type(value) == 'number' and value == value and value ~= math.huge and value ~= -math.huge then",
                    "    return value",
                    "  end",
                    "  return json.null",
                    "end",
                    "local function string_array(value)",
                    "  local result = {}",
                    "  if type(value) ~= 'table' then",
                    "    return result",
                    "  end",
                    "  for _, item in ipairs(value) do",
                    "    if type(item) == 'string' and item ~= '' then",
                    "      table.insert(result, item)",
                    "    end",
                    "  end",
                    "  return result",
                    "end",
                    "local source_refs = {",
                    "  {",
                    "    ref_id = 'pob.source.CalcsTab.PowerBuilder',",
                    "    ref_kind = 'pinned_pob_source',",
                    "    locator = 'vendor/pob/source/src/Classes/CalcsTab.lua:474-612',",
                    "    json_pointer = '/CalcsTabClass/PowerBuilder',",
                    "    summary = 'Pinned PoB PowerBuilder computes node.power for passive nodes.',",
                    "  },",
                    "  {",
                    "    ref_id = 'pob.source.TreeTab.BuildPowerReportList',",
                    "    ref_kind = 'pinned_pob_source',",
                    "    locator = 'vendor/pob/source/src/Classes/TreeTab.lua:1052-1165',",
                    "    json_pointer = '/TreeTabClass/BuildPowerReportList',",
                    "    summary = 'Pinned PoB BuildPowerReportList emits node-power report rows.',",
                    "  },",
                    "  {",
                    "    ref_id = 'pob.source.Data.powerStatList',",
                    "    ref_kind = 'pinned_pob_source',",
                    "    locator = 'vendor/pob/source/src/Modules/Data.lua:111-161',",
                    "    json_pointer = '/data/powerStatList',",
                    "    summary = 'Pinned PoB powerStatList defines node-power metric selectors.',",
                    "  },",
                    "}",
                    "local function active_config_set_id()",
                    "  local index = build and build.configTab and tonumber(build.configTab.activeConfigSetId) or 1",
                    "  if index == 1 then return 'config.main' end",
                    "  return 'config.' .. tostring(index)",
                    "end",
                    "local function selected_metric_payload(stat_data)",
                    "  if type(stat_data) ~= 'table' then",
                    "    return {",
                    "      stat = metric_stat,",
                    "      label = metric_stat,",
                    "      metric_family = 'unavailable',",
                    "      display_format = json.null,",
                    "      lower_is_better = false,",
                    "      percent_scaling = false,",
                    "    }",
                    "  end",
                    "  local stat = tostring(stat_data.stat or metric_stat)",
                    "  return {",
                    "    stat = stat,",
                    "    label = tostring(stat_data.label or stat),",
                    "    metric_family = family_by_stat[stat] or 'offense',",
                    "    display_format = stat_data.fmt or json.null,",
                    "    lower_is_better = stat_data.lowerIsBetter == true,",
                    "    percent_scaling = (stat_data.pc == true or stat_data.mod == true),",
                    "  }",
                    "end",
                    "local function unavailable(failure_state, summary)",
                    "  return {",
                    f"    schema_version = {_lua_long_string(_POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION)},",
                    f"    record_kind = {_lua_long_string(_POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND)},",
                    "    status = 'unavailable',",
                    "    failure_state = failure_state,",
                    "    report_id = report_id,",
                    f"    source_kind = {_lua_long_string(_POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND)},",
                    f"    supported_path = {_lua_long_string(_POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH)},",
                    "    active_config_set_id = active_config_set_id(),",
                    "    metric_lane = metric_lane,",
                    "    selected_metric = selected_metric_payload(nil),",
                    "    max_depth = encode_null(max_depth),",
                    "    max_rows = encode_null(max_rows),",
                    "    row_count = 0,",
                    "    raw_report_row_count = 0,",
                    "    truncated = false,",
                    "    rows = {},",
                    "    source_refs = source_refs,",
                    "    limitations = { summary },",
                    "    unavailable_metrics = { metric_stat },",
                    "    boundary = {",
                    "      final_build_authority = false,",
                    "      final_tree_authority = false,",
                    "      passive_budget_authority = false,",
                    "      node_power_calculator_authority = false,",
                    "      publication_artifact_emitted = false,",
                    "    },",
                    "  }",
                    "end",
                    "if not (build and build.treeTab and build.calcsTab and data and data.powerStatList) then",
                    "  return json.encode(unavailable(",
                    "    'pob_native_node_power_report_unavailable_in_headless_runtime',",
                    "    'Pinned runtime is missing build.treeTab, build.calcsTab, or data.powerStatList.'",
                    "  ))",
                    "end",
                    "local selected_metric = nil",
                    "for _, stat_data in ipairs(data.powerStatList or {}) do",
                    "  if not stat_data.ignoreForNodes and tostring(stat_data.stat or '') == metric_stat then",
                    "    selected_metric = stat_data",
                    "    break",
                    "  end",
                    "end",
                    "if not selected_metric then",
                    "  local failure = metric_stat == 'HitChance'",
                    "    and 'pob_native_hit_chance_node_power_metric_unavailable'",
                    "    or 'pob_native_node_power_metric_unavailable'",
                    "  return json.encode(unavailable(failure, 'Pinned PoB powerStatList exposes no node-power metric named ' .. metric_stat .. '.'))",
                    "end",
                    "build.calcsTab.nodePowerMaxDepth = max_depth",
                    "build.treeTab:SetPowerCalc(selected_metric)",
                    "runCallback('OnFrame')",
                    "local guard = 0",
                    "while build.calcsTab.powerBuildFlag or build.calcsTab.powerBuilder do",
                    "  build.calcsTab:BuildPower()",
                    "  guard = guard + 1",
                    "  if guard > 100000 then",
                    "    error('Pinned PoB node-power builder did not finish within the bounded headless guard.')",
                    "  end",
                    "end",
                    "local native_rows = build.treeTab:BuildPowerReportList(selected_metric)",
                    "if type(native_rows) ~= 'table' then",
                    "  error('Pinned PoB BuildPowerReportList did not return a table.')",
                    "end",
                    "local selected_payload = selected_metric_payload(selected_metric)",
                    "local function node_for_row(row)",
                    "  if type(row) ~= 'table' or row.id == nil then",
                    "    return nil",
                    "  end",
                    "  local direct = build.spec and build.spec.nodes and build.spec.nodes[row.id] or nil",
                    "  if direct then return direct end",
                    "  if build.spec and build.spec.tree and build.spec.tree.clusterNodeMap then",
                    "    for _, node in pairs(build.spec.tree.clusterNodeMap) do",
                    "      if node.id == row.id then return node end",
                    "    end",
                    "  end",
                    "  return nil",
                    "end",
                    "local function target_kind(row, node)",
                    "  local row_type = tostring(row.type or (node and node.type) or 'passive')",
                    "  if row_type == 'Keystone' then return 'keystone' end",
                    "  if row_type == 'Notable' then",
                    "    if node and node.clusterJewel then return 'cluster_notable' end",
                    "    return 'notable'",
                    "  end",
                    "  if row_type == 'Normal' then return 'small_passive' end",
                    "  return row_type",
                    "end",
                    "local rows = {}",
                    "local total_rows = 0",
                    "for index, row in ipairs(native_rows) do",
                    "  total_rows = total_rows + 1",
                    "  if not max_rows or #rows < max_rows then",
                    "    local node = node_for_row(row)",
                    "    local path_dist = row.pathDist",
                    "    local point_cost = type(path_dist) == 'number' and path_dist > 0 and path_dist or json.null",
                    "    local path_power = scalar_number(row.pathPower)",
                    "    local value_per_point = path_power",
                    "    local node_power = scalar_number(row.power)",
                    "    local node_id = tonumber(row.id)",
                    "    local row_id = 'pob.node-power.' .. tostring(node_id or index) .. '.' .. metric_stat",
                    "    table.insert(rows, {",
                    "      row_id = row_id,",
                    "      source_id = node_id and ('passives:' .. tostring(node_id)) or ('passives:unknown.' .. tostring(index)),",
                    "      node_id = node_id or 0,",
                    "      node_name = tostring(row.name or (node and node.dn) or 'unknown node'),",
                    "      name = tostring(row.name or (node and node.dn) or 'unknown node'),",
                    "      target_kind = target_kind(row, node),",
                    "      metric_lane = metric_lane,",
                    "      metric_name = selected_payload.stat,",
                    "      metric_label = selected_payload.label,",
                    "      metric_family = selected_payload.metric_family,",
                    "      node_power_score = node_power,",
                    "      power = node_power,",
                    "      powerStr = row.powerStr or json.null,",
                    "      path_power_score = path_power,",
                    "      pathPower = path_power,",
                    "      pathPowerStr = row.pathPowerStr or json.null,",
                    "      path_dist = encode_null(path_dist),",
                    "      pathDist = encode_null(path_dist),",
                    "      point_cost = point_cost,",
                    "      value_per_point = value_per_point,",
                    "      allocated = row.allocated == true,",
                    "      source_locator = 'vendor/pob/source/src/Classes/TreeTab.lua:1052-1165#/BuildPowerReportList/rows/' .. tostring(index),",
                    "      source_context = {",
                    "        is_mastery = false,",
                    "        is_notable = row.type == 'Notable',",
                    "        is_keystone = row.type == 'Keystone',",
                    "        pob_row_type = tostring(row.type or ''),",
                    "        x = row.x or json.null,",
                    "        y = row.y or json.null,",
                    "      },",
                    "      display_stat = {",
                    "        stat = selected_payload.stat,",
                    "        label = selected_payload.label,",
                    "        lower_is_better = selected_payload.lower_is_better,",
                    "        percent_scaling = selected_payload.percent_scaling,",
                    "      },",
                    "      stats_or_supporting_text = node and string_array(node.sd) or {},",
                    "      metric_tags = {},",
                    "      facets = {},",
                    "      matched_branch_axes = {},",
                    "    })",
                    "  end",
                    "end",
                    "local limitations = {",
                    "  'The action reads one active PoB config/set lane at a time and reports metric_lane without mixing baseline and conditional states.',",
                    "}",
                    "if max_depth then",
                    "  table.insert(limitations, 'Pinned PoB nodePowerMaxDepth was bounded to ' .. tostring(max_depth) .. ' for this headless read.')",
                    "end",
                    "if max_rows and total_rows > max_rows then",
                    "  table.insert(limitations, 'Report rows were truncated from ' .. tostring(total_rows) .. ' to ' .. tostring(max_rows) .. ' after PoB-native sorting.')",
                    "end",
                    "local result = {",
                    f"  schema_version = {_lua_long_string(_POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION)},",
                    f"  record_kind = {_lua_long_string(_POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND)},",
                    "  status = 'accepted',",
                    "  report_id = report_id,",
                    f"  source_kind = {_lua_long_string(_POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND)},",
                    f"  supported_path = {_lua_long_string(_POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH)},",
                    "  active_config_set_id = requested_config_set_id ~= json.null and requested_config_set_id or active_config_set_id(),",
                    "  metric_lane = metric_lane,",
                    "  selected_metric = selected_payload,",
                    "  max_depth = encode_null(max_depth),",
                    "  max_rows = encode_null(max_rows),",
                    "  row_count = #rows,",
                    "  raw_report_row_count = total_rows,",
                    "  truncated = max_rows ~= nil and total_rows > max_rows,",
                    "  rows = rows,",
                    "  source_refs = source_refs,",
                    "  limitations = limitations,",
                    "  unavailable_metrics = metric_stat == 'HitChance' and { 'HitChance' } or {},",
                    "  boundary = {",
                    "    final_build_authority = false,",
                    "    final_tree_authority = false,",
                    "    passive_budget_authority = false,",
                    "    node_power_calculator_authority = false,",
                    "    publication_artifact_emitted = false,",
                    "  },",
                    "}",
                    "return json.encode(result)",
                )
            ),
            nret=1,
        )[0]
        if payload is None:
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime returned no node-power report payload.")
        try:
            result = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime returned invalid node-power report JSON.") from exc
        if not isinstance(result, dict):
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime node-power report payload must decode to an object.")
        return result

    def read_ascendancy_node_report(self) -> dict[str, Any]:
        payload = self._bridge.execute(
            "\n".join(
                (
                    "local json = require('dkjson')",
                    "local function encode_null(value)",
                    "  if value == nil or value == '' or value == 'None' then return json.null end",
                    "  return value",
                    "end",
                    "local function string_array(values)",
                    "  local result = {}",
                    "  if type(values) ~= 'table' then return result end",
                    "  for _, value in ipairs(values) do",
                    "    if type(value) == 'string' and value ~= '' then table.insert(result, value) end",
                    "  end",
                    "  return result",
                    "end",
                    "local function node_display_name(node)",
                    "  return tostring(node.dn or node.name or node.label or 'unknown node')",
                    "end",
                    *_ASCENDANCY_MATCH_LUA,
                    "local function node_is_ascendancy_start(node)",
                    "  return node.isAscendancyStart == true or node.ascendancyStart == true",
                    "end",
                    "local function node_is_notable(node)",
                    "  return node.isNotable == true or node.notable == true or node.type == 'Notable'",
                    "end",
                    "local function node_id_value(node_id, node)",
                    "  return tonumber(node.id or node.nodeId or node_id)",
                    "end",
                    "local function collect_link_ids(node)",
                    "  local result = {}",
                    "  local seen = {}",
                    "  local function add(value)",
                    "    local numeric = tonumber(value)",
                    "    if numeric and not seen[numeric] then",
                    "      seen[numeric] = true",
                    "      table.insert(result, numeric)",
                    "    end",
                    "  end",
                    "  local fields = { 'out', 'outNodes', 'outs', 'links', 'connections' }",
                    "  for _, field_name in ipairs(fields) do",
                    "    local values = node[field_name]",
                    "    if type(values) == 'table' then",
                    "      for key, entry in pairs(values) do",
                    "        if type(entry) == 'table' then",
                    "          add(entry.id or entry.nodeId or entry[1])",
                    "        elseif type(entry) == 'number' or type(entry) == 'string' then",
                    "          add(entry)",
                    "        else",
                    "          add(key)",
                    "        end",
                    "      end",
                    "    end",
                    "  end",
                    "  table.sort(result)",
                    "  return result",
                    "end",
                    "local active_ascendancy = build.spec.curAscendClassName",
                    "local active_ascendancy_names = current_ascendancy_names()",
                    "local rows = {}",
                    "for node_id, node in pairs(build.spec.tree.nodes or {}) do",
                    "  if node_in_current_ascendancy(node, active_ascendancy_names) and not node_is_ascendancy_start(node) then",
                    "    local numeric_id = node_id_value(node_id, node)",
                    "    table.insert(rows, {",
                    "      row_id = 'pob.ascendancy-node.' .. tostring(numeric_id),",
                    "      node_id = numeric_id,",
                    "      node_name = node_display_name(node),",
                    "      ascendancy_name = active_ascendancy,",
                    "      target_kind = node_is_notable(node) and 'ascendancy_notable' or 'ascendancy_small_passive',",
                    "      is_notable = node_is_notable(node),",
                    "      is_ascendancy_start = node_is_ascendancy_start(node),",
                    "      allocated = build.spec.allocNodes[numeric_id] ~= nil,",
                    "      stats_or_supporting_text = string_array(node.sd),",
                    "      connected_node_ids = collect_link_ids(node),",
                    "      source_locator = 'pinned_pob_runtime.build.spec.tree.nodes/' .. tostring(numeric_id),",
                    "    })",
                    "  end",
                    "end",
                    "table.sort(rows, function(left, right)",
                    "  if left.is_notable ~= right.is_notable then return left.is_notable end",
                    "  return tostring(left.node_name) < tostring(right.node_name)",
                    "end)",
                    "local result = {",
                    "  schema_version = '0.1.0',",
                    "  record_kind = 'pob_ascendancy_node_report',",
                    "  status = 'accepted',",
                    "  source_kind = 'pinned_pob_runtime_ascendancy_tree_readback',",
                    "  active_class_id = encode_null(build.spec.curClassName),",
                    "  active_ascendancy_id = encode_null(active_ascendancy),",
                    "  row_count = #rows,",
                    "  rows = rows,",
                    "  boundary = {",
                    "    final_build_authority = false,",
                    "    final_tree_authority = false,",
                    "    ascendancy_selection_authority = false,",
                    "    publication_artifact_emitted = false,",
                    "  },",
                    "  warnings = {},",
                    "}",
                    "return json.encode(result)",
                )
            ),
            nret=1,
        )[0]
        if payload is None:
            raise WorkerContractError("runtime_protocol_failed", "Ascendancy node report returned no payload.")
        try:
            result = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise WorkerContractError("runtime_protocol_failed", "Ascendancy node report returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise WorkerContractError("runtime_protocol_failed", "Ascendancy node report payload must decode to an object.")
        return result

    def _extract_skill_set_indices(self, xml_text: str) -> tuple[int, list[int]]:
        root = self._parse_build_xml(xml_text)
        skills_node = root.find("Skills")
        if skills_node is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export is missing the Skills node required for skill read-back.",
            )
        try:
            active_skill_set_index = int(skills_node.attrib.get("activeSkillSet", "1"))
        except ValueError as exc:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export recorded a non-integer activeSkillSet value.",
            ) from exc
        skill_set_indices: list[int] = []
        for index, skill_set_node in enumerate(skills_node.findall("SkillSet"), start=1):
            raw_id = skill_set_node.attrib.get("id", str(index))
            try:
                skill_set_index = int(raw_id)
            except ValueError as exc:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    "Pinned PoB export recorded a non-integer SkillSet id.",
                ) from exc
            if skill_set_index < 1:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    "Pinned PoB export recorded a SkillSet id below 1.",
                )
            skill_set_indices.append(skill_set_index)
        if not skill_set_indices:
            skill_set_indices = [1]
        if active_skill_set_index not in skill_set_indices:
            skill_set_indices.insert(0, active_skill_set_index)
        return active_skill_set_index, skill_set_indices

    def _xml_with_active_skill_set(self, xml_text: str, skill_set_index: int) -> str:
        root = self._parse_build_xml(xml_text)
        skills_node = root.find("Skills")
        if skills_node is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export is missing the Skills node required for skill read-back.",
            )
        skills_node.set("activeSkillSet", str(skill_set_index))
        return _serialize_xml(root)

    def _snapshot_rich_skill_state(self) -> dict[str, Any]:
        export_xml = self.export_build_xml()
        active_skill_set_index, skill_set_indices = self._extract_skill_set_indices(export_xml)
        # The active skill set is read from the live build. Only another set needs the build reopened with
        # that set active, and only then is the original restored: reopening the build for the active set
        # too (and once more to "restore" it) was two full XML loads, ~1.5 s, on every read_state, which
        # the pipeline asks for a thousand times per build (34% of a build's wall time, 7.1h profile).
        self._bridge.execute("if build.buildFlag then runCallback('OnFrame') end", nret=0)
        by_index: dict[int, dict[str, Any]] = {}
        active_skill_set_state: dict[str, Any] | None = None
        if active_skill_set_index in skill_set_indices:
            active_skill_set_state = self._snapshot_active_skill_set_state()
            by_index[active_skill_set_index] = active_skill_set_state
        reopened = False
        try:
            for skill_set_index in skill_set_indices:
                if skill_set_index in by_index:
                    continue
                reopened = True
                self.load_reopen_source(self._xml_with_active_skill_set(export_xml, skill_set_index))
                by_index[skill_set_index] = self._snapshot_active_skill_set_state()
        finally:
            if reopened:
                self.load_reopen_source(export_xml)
        skill_sets: list[dict[str, Any]] = [by_index[i] for i in skill_set_indices if i in by_index]

        if active_skill_set_state is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Could not observe the active skill set during skill read-back.",
            )

        nondefault_state = len(skill_sets) > 1 or any(
            int(skill_set["socket_group_count"]) > 0 for skill_set in skill_sets
        )
        payload = {
            "state_kind": "nondefault" if nondefault_state else "empty",
            "active_skill_set_id": active_skill_set_state["skill_set_id"],
            "socket_group_count": active_skill_set_state["socket_group_count"],
            "socket_groups": active_skill_set_state["socket_groups"],
            "main_socket_group_id": active_skill_set_state["main_socket_group_id"],
            "main_active_skill_id": active_skill_set_state["main_active_skill_id"],
        }
        if nondefault_state:
            payload["skill_set_count"] = len(skill_sets)
            payload["skill_set_ids"] = [skill_set["skill_set_id"] for skill_set in skill_sets]
            payload["skill_sets"] = skill_sets
        return payload

    def _snapshot_active_skill_set_state(self) -> dict[str, Any]:
        chunk = "\n".join(
            (
                "local json = require('dkjson')",
                "local function encode_null(value)",
                "  if value == nil or value == '' or value == 'None' then",
                "    return json.null",
                "  end",
                "  return tostring(value)",
                "end",
                "local function normalize_skill_set_id(index)",
                f"  if tonumber(index) == 1 then return {_lua_long_string(_CANONICAL_SKILLS_ID)} end",
                "  return 'skills.' .. tostring(index)",
                "end",
                "local function normalize_item_set_id(index)",
                "  if type(index) ~= 'number' then",
                "    return json.null",
                "  end",
                "  index = math.floor(index)",
                "  if index < 1 then",
                "    return json.null",
                "  end",
                f"  if index == 1 then return {_lua_long_string(_CANONICAL_ITEM_SET_ID)} end",
                "  return 'itemset.' .. tostring(index)",
                "end",
                "local function normalize_socket_group_id(skill_set_id, index)",
                "  return tostring(skill_set_id) .. '.socket_group.' .. tostring(index)",
                "end",
                "local function normalize_gem_entry_id(socket_group_id, index)",
                "  return tostring(socket_group_id) .. '.gem.' .. tostring(index)",
                "end",
                "local function normalize_active_skill_id(socket_group_id, index)",
                "  return tostring(socket_group_id) .. '.active_skill.' .. tostring(index)",
                "end",
                "local function source_kind(socket_group)",
                "  if socket_group.sourceItem then return 'item' end",
                "  if socket_group.sourceNode then return 'node' end",
                "  if socket_group.source == 'Explode' then return 'explode' end",
                "  if socket_group.source ~= nil then return 'other' end",
                "  return 'manual'",
                "end",
                "local function source_label(socket_group)",
                "  if socket_group.sourceItem and socket_group.sourceItem.name then",
                "    return socket_group.sourceItem.name",
                "  end",
                "  if socket_group.sourceNode and socket_group.sourceNode.name then",
                "    return socket_group.sourceNode.name",
                "  end",
                "  if socket_group.source ~= nil then",
                "    return tostring(socket_group.source)",
                "  end",
                "  return json.null",
                "end",
                "local function collect_support_links(active_skill, gem_entry_lookup)",
                "  local result = {}",
                "  if type(active_skill.effectList) ~= 'table' then",
                "    return result",
                "  end",
                "  for _, effect in ipairs(active_skill.effectList) do",
                "    local granted_effect = effect and effect.grantedEffect or nil",
                "    if granted_effect and granted_effect.support then",
                "      table.insert(result, {",
                "        name = encode_null(granted_effect.name),",
                "        skill_id = encode_null(granted_effect.id),",
                "        from_item = (granted_effect.fromItem == true)",
                "          or (effect.srcInstance and effect.srcInstance.fromItem == true)",
                "          or false,",
                "        source_gem_entry_id = (effect.srcInstance and gem_entry_lookup[effect.srcInstance]) or json.null,",
                "      })",
                "    end",
                "  end",
                "  return result",
                "end",
                "local function serialize_active_skill(socket_group_id, index, active_skill, gem_entry_lookup)",
                "  local active_effect = active_skill and active_skill.activeEffect or nil",
                "  local src_instance = active_effect and active_effect.srcInstance or nil",
                "  local granted_effect = active_effect and active_effect.grantedEffect or nil",
                "  local support_links = collect_support_links(active_skill, gem_entry_lookup)",
                "  local minion_skill_name = json.null",
                "  local minion_skill_index = src_instance and src_instance.skillMinionSkill or nil",
                "  if active_skill and active_skill.minion and type(active_skill.minion.activeSkillList) == 'table' then",
                "    local selected_skill = active_skill.minion.activeSkillList[minion_skill_index or 1]",
                "    local minion_effect = selected_skill and selected_skill.activeEffect or nil",
                "    if minion_effect and minion_effect.grantedEffect and minion_effect.grantedEffect.name then",
                "      minion_skill_name = minion_effect.grantedEffect.name",
                "    end",
                "  end",
                "  local part_name = json.null",
                "  if granted_effect and type(granted_effect.parts) == 'table' and src_instance and src_instance.skillPart and granted_effect.parts[src_instance.skillPart] then",
                "    part_name = encode_null(granted_effect.parts[src_instance.skillPart].name)",
                "  end",
                "  return {",
                "    active_skill_id = normalize_active_skill_id(socket_group_id, index),",
                "    name = granted_effect and encode_null(granted_effect.name) or json.null,",
                "    granted_effect_id = granted_effect and encode_null(granted_effect.id) or json.null,",
                "    source_gem_entry_id = (src_instance and gem_entry_lookup[src_instance]) or json.null,",
                "    enabled = not src_instance or src_instance.enabled ~= false,",
                "    triggered = ((src_instance and src_instance.triggered == true)",
                "      or (active_skill.skillData and active_skill.skillData.triggered)",
                "      or (active_skill.skillFlags and active_skill.skillFlags.triggered)) and true or false,",
                "    trigger_chance = src_instance and src_instance.triggerChance or json.null,",
                "    trigger_label = active_skill.infoTrigger or active_skill.trigger or json.null,",
                "    part_index = src_instance and src_instance.skillPart or json.null,",
                "    part_name = part_name,",
                "    stage_count = src_instance and src_instance.skillStageCount or json.null,",
                "    mine_count = src_instance and src_instance.skillMineCount or json.null,",
                "    minion_id = src_instance and src_instance.skillMinion or json.null,",
                "    minion_item_set_id = src_instance and normalize_item_set_id(src_instance.skillMinionItemSet) or json.null,",
                "    minion_skill_index = minion_skill_index or json.null,",
                "    minion_skill_name = minion_skill_name,",
                "    support_link_count = #support_links,",
                "    support_links = support_links,",
                "  }",
                "end",
                "local function serialize_gem(socket_group_id, index, gem_instance)",
                "  local granted_effect = (gem_instance.gemData and gem_instance.gemData.grantedEffect) or gem_instance.grantedEffect",
                "  return {",
                "    gem_entry_id = normalize_gem_entry_id(socket_group_id, index),",
                "    socket_index = index,",
                "    gem_name = encode_null(gem_instance.nameSpec),",
                "    skill_id = encode_null(gem_instance.skillId),",
                "    gem_id = (gem_instance.gemData and encode_null(gem_instance.gemData.gameId)) or json.null,",
                "    is_support = (granted_effect and granted_effect.support == true) or false,",
                "    level = tonumber(gem_instance.level) or 0,",
                "    quality = tonumber(gem_instance.quality) or 0,",
                "    matches_socket = gem_instance.matchesSocket and true or false,",
                "    socket_quality = gem_instance.matchesSocket and (data.misc.MatchingSocketQualityBonus or 0) or 0,",
                "    enabled = gem_instance.enabled == true,",
                "    count = tonumber(gem_instance.count) or 1,",
                "    enable_global_1 = gem_instance.enableGlobal1 ~= false,",
                "    enable_global_2 = gem_instance.enableGlobal2 == true,",
                "    skill_part = gem_instance.skillPart or json.null,",
                "    skill_stage_count = gem_instance.skillStageCount or json.null,",
                "    skill_mine_count = gem_instance.skillMineCount or json.null,",
                "    skill_minion = gem_instance.skillMinion or json.null,",
                "    skill_minion_item_set_id = normalize_item_set_id(gem_instance.skillMinionItemSet),",
                "    skill_minion_skill_index = gem_instance.skillMinionSkill or json.null,",
                "    triggered = gem_instance.triggered == true,",
                "    trigger_chance = gem_instance.triggerChance or json.null,",
                "  }",
                "end",
                "local function serialize_socket_group(skill_set_id, index, socket_group)",
                "  local socket_group_id = normalize_socket_group_id(skill_set_id, index)",
                "  local gems = {}",
                "  local gem_entry_lookup = {}",
                "  for gem_index, gem_instance in ipairs(socket_group.gemList or {}) do",
                "    local gem_payload = serialize_gem(socket_group_id, gem_index, gem_instance)",
                "    gems[gem_index] = gem_payload",
                "    gem_entry_lookup[gem_instance] = gem_payload.gem_entry_id",
                "  end",
                "  local active_skill_entries = {}",
                "  for active_skill_index, active_skill in ipairs(socket_group.displaySkillList or {}) do",
                "    active_skill_entries[active_skill_index] = serialize_active_skill(",
                "      socket_group_id,",
                "      active_skill_index,",
                "      active_skill,",
                "      gem_entry_lookup",
                "    )",
                "  end",
                "  local main_active_skill_index = tonumber(socket_group.mainActiveSkill) or 1",
                "  return {",
                "    socket_group_id = socket_group_id,",
                "    label = encode_null(socket_group.label),",
                "    slot = encode_null(socket_group.slot),",
                "    slot_enabled = socket_group.slotEnabled ~= false,",
                "    source = encode_null(socket_group.source),",
                "    source_kind = source_kind(socket_group),",
                "    source_label = source_label(socket_group),",
                "    enabled = socket_group.enabled == true,",
                "    include_in_full_dps = socket_group.includeInFullDPS == true,",
                "    group_count = tonumber(socket_group.groupCount) or 1,",
                "    gem_count = #gems,",
                "    gems = gems,",
                "    active_skill_entry_count = #active_skill_entries,",
                "    active_skill_entries = active_skill_entries,",
                "    main_active_skill_index = main_active_skill_index,",
                "    main_active_skill_id = active_skill_entries[main_active_skill_index]",
                "      and active_skill_entries[main_active_skill_index].active_skill_id",
                "      or json.null,",
                "  }",
                "end",
                "local active_skill_set_index = tonumber(build.skillsTab.activeSkillSetId) or 1",
                "local active_skill_set = build.skillsTab.skillSets[active_skill_set_index] or {}",
                "local skill_set_id = normalize_skill_set_id(active_skill_set_index)",
                "local socket_groups = {}",
                "local socket_group_ids = {}",
                "for socket_group_index, socket_group in ipairs(build.skillsTab.socketGroupList or {}) do",
                "  local socket_group_payload = serialize_socket_group(skill_set_id, socket_group_index, socket_group)",
                "  socket_groups[socket_group_index] = socket_group_payload",
                "  socket_group_ids[socket_group_index] = socket_group_payload.socket_group_id",
                "end",
                "local main_socket_group_index = tonumber(build.mainSocketGroup) or 1",
                "local main_socket_group = socket_groups[main_socket_group_index]",
                "return json.encode({",
                "  skill_set_id = skill_set_id,",
                "  title = encode_null(active_skill_set.title),",
                "  socket_group_count = #socket_groups,",
                "  socket_group_ids = socket_group_ids,",
                "  socket_groups = socket_groups,",
                "  main_socket_group_id = main_socket_group and main_socket_group.socket_group_id or json.null,",
                "  main_active_skill_id = main_socket_group and main_socket_group.main_active_skill_id or json.null,",
                "})",
            )
        )
        payload = self._bridge.execute(chunk, nret=1)[0]
        if payload is None:
            raise WorkerContractError("runtime_protocol_failed", "PoB skill snapshot returned no payload.")
        return json.loads(payload)

    def _snapshot_config_state(self) -> dict[str, Any]:
        return self._config_state_from_xml(self.export_build_xml())

    def _config_state_from_xml(self, xml_text: str) -> dict[str, Any]:
        root = self._parse_build_xml(xml_text)
        build_node = root.find("Build")
        config_node = root.find("Config")
        if build_node is None or config_node is None:
            raise WorkerContractError(
                "runtime_protocol_failed",
                "Pinned PoB export is missing Build or Config nodes required for config read-back.",
            )

        raw_config_sets = self._collect_raw_config_sets(config_node)
        raw_config_sets_by_index = {
            config_set["config_set_index"]: config_set for config_set in raw_config_sets
        }
        active_config_set_index = _parse_positive_int_attr(
            config_node.attrib.get("activeConfigSet"),
            field_name="Config.activeConfigSet",
            default=1,
        )
        if active_config_set_index not in raw_config_sets_by_index:
            active_config_set_index = raw_config_sets[0]["config_set_index"]

        is_nondefault = len(raw_config_sets) > 1 or any(
            self._config_set_has_nondefault_state(
                config_set,
                build_node=build_node,
                is_active=config_set["config_set_index"] == active_config_set_index,
            )
            for config_set in raw_config_sets
        )
        if not is_nondefault:
            return {
                "state_kind": "default",
                "active_config_set_id": _CANONICAL_CONFIG_ID,
                "enabled_conditions": [],
                "custom_values": {},
                "notes": None,
                "bandit": None,
                "pantheon_major": None,
                "pantheon_minor": None,
                "engine_default_fields": {},
            }

        config_set_summaries: dict[str, dict[str, Any]] = {}
        config_set_ids: list[str] = []
        baseline_config_set_id: str | None = None
        conditional_config_set_id: str | None = None
        for config_set in raw_config_sets:
            summary = self._build_config_state_summary(
                config_set,
                build_node=build_node,
                is_active=config_set["config_set_index"] == active_config_set_index,
                include_default_enemy_state=True,
                config_set_count=len(raw_config_sets),
            )
            config_set_ids.append(summary["config_set_id"])
            config_set_summaries[summary["config_set_id"]] = summary
            if summary["state_role"] == "baseline" and baseline_config_set_id is None:
                baseline_config_set_id = summary["config_set_id"]
            if summary["state_role"] == "conditional" and conditional_config_set_id is None:
                conditional_config_set_id = summary["config_set_id"]

        active_config_set_id = _normalize_config_set_id(active_config_set_index)
        active_summary = config_set_summaries[active_config_set_id]
        state = {
            "state_kind": "nondefault",
            "active_config_set_id": active_config_set_id,
            "enabled_conditions": list(active_summary["enabled_conditions"]),
            "custom_values": dict(active_summary["custom_values"]),
            "notes": active_summary["notes"],
            "bandit": active_summary["bandit"],
            "pantheon_major": active_summary["pantheon_major"],
            "pantheon_minor": active_summary["pantheon_minor"],
            "engine_default_fields": dict(active_summary["engine_default_fields"]),
            "config_set_ids": config_set_ids,
            "config_sets": config_set_summaries,
        }
        if baseline_config_set_id is not None:
            state["baseline_config_set_id"] = baseline_config_set_id
        if conditional_config_set_id is not None:
            state["conditional_config_set_id"] = conditional_config_set_id
        return state

    def _collect_raw_config_sets(self, config_node: ElementTree.Element) -> list[dict[str, Any]]:
        config_set_nodes = [child for child in list(config_node) if child.tag == "ConfigSet"]
        if not config_set_nodes:
            return [
                {
                    "config_set_index": 1,
                    "config_set_id": _CANONICAL_CONFIG_ID,
                    "title": "Default",
                    "inputs": self._collect_supported_config_inputs(config_node, field_prefix="Config"),
                }
            ]

        raw_config_sets: list[dict[str, Any]] = []
        for ordinal, config_set_node in enumerate(config_set_nodes, start=1):
            config_set_index = _parse_positive_int_attr(
                config_set_node.attrib.get("id"),
                field_name=f"ConfigSet[{ordinal}].id",
                default=ordinal,
            )
            raw_config_sets.append(
                {
                    "config_set_index": config_set_index,
                    "config_set_id": _normalize_config_set_id(config_set_index),
                    "title": (config_set_node.attrib.get("title") or "Default").strip() or "Default",
                    "inputs": self._collect_supported_config_inputs(
                        config_set_node,
                        field_prefix=f"ConfigSet[{config_set_index}]",
                    ),
                }
            )
        raw_config_sets.sort(key=lambda entry: int(entry["config_set_index"]))
        return raw_config_sets

    def _collect_supported_config_inputs(
        self,
        parent_node: ElementTree.Element,
        *,
        field_prefix: str,
    ) -> dict[str, str | bool | int]:
        supported_inputs: dict[str, str | bool | int] = {}
        for child_index, child in enumerate(list(parent_node), start=1):
            if child.tag != "Input":
                continue
            input_name = child.attrib.get("name")
            if input_name not in _CONFIG_DEFAULT_INPUTS:
                continue
            supported_inputs[input_name] = self._decode_supported_config_input(
                child,
                field_name=f"{field_prefix}.Input[{child_index}]",
            )
        return supported_inputs

    def _decode_supported_config_input(
        self,
        input_node: ElementTree.Element,
        *,
        field_name: str,
    ) -> str | bool | int:
        input_name = input_node.attrib.get("name")
        if not input_name:
            raise WorkerContractError("runtime_protocol_failed", f"{field_name} is missing a name attribute.")
        if "boolean" in input_node.attrib:
            raw_value = input_node.attrib["boolean"]
            if raw_value not in {"true", "false"}:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"{field_name}.{input_name} must encode a true/false boolean value.",
                )
            return raw_value == "true"
        if "number" in input_node.attrib:
            try:
                return int(input_node.attrib["number"])
            except ValueError as exc:
                raise WorkerContractError(
                    "runtime_protocol_failed",
                    f"{field_name}.{input_name} must encode an integer number.",
                ) from exc
        if "string" in input_node.attrib:
            return input_node.attrib["string"]
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name}.{input_name} must encode a string, number, or boolean value.",
        )

    def _config_set_has_nondefault_state(
        self,
        config_set: dict[str, Any],
        *,
        build_node: ElementTree.Element,
        is_active: bool,
    ) -> bool:
        if config_set["title"] != "Default":
            return True
        for input_name in _CONFIG_DEFAULT_INPUTS:
            resolved_value, _ = self._resolve_config_input_value(
                config_set["inputs"],
                input_name,
                build_node=build_node,
                is_active=is_active,
            )
            if resolved_value != _CONFIG_DEFAULT_INPUTS[input_name]:
                return True
        return False

    def _resolve_config_input_value(
        self,
        input_values: dict[str, Any],
        input_name: str,
        *,
        build_node: ElementTree.Element,
        is_active: bool,
    ) -> tuple[str | bool | int | None, bool]:
        if input_name in input_values:
            return input_values[input_name], False
        if is_active and input_name in {"bandit", "pantheonMajorGod", "pantheonMinorGod"}:
            build_value = build_node.attrib.get(input_name)
            if build_value is not None:
                return build_value, build_value == _CONFIG_DEFAULT_INPUTS[input_name]
        return _CONFIG_DEFAULT_INPUTS[input_name], True

    def _build_config_state_summary(
        self,
        config_set: dict[str, Any],
        *,
        build_node: ElementTree.Element,
        is_active: bool,
        include_default_enemy_state: bool,
        config_set_count: int,
    ) -> dict[str, Any]:
        bandit_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "bandit",
            build_node=build_node,
            is_active=is_active,
        )
        pantheon_major_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "pantheonMajorGod",
            build_node=build_node,
            is_active=is_active,
        )
        pantheon_minor_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "pantheonMinorGod",
            build_node=build_node,
            is_active=is_active,
        )
        enemy_is_boss_raw, enemy_is_boss_defaulted = self._resolve_config_input_value(
            config_set["inputs"],
            "enemyIsBoss",
            build_node=build_node,
            is_active=is_active,
        )
        buff_onslaught_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "buffOnslaught",
            build_node=build_node,
            is_active=is_active,
        )
        buff_fortification_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "buffFortification",
            build_node=build_node,
            is_active=is_active,
        )
        using_flask_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "conditionUsingFlask",
            build_node=build_node,
            is_active=is_active,
        )
        enemy_shocked_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "conditionEnemyShocked",
            build_node=build_node,
            is_active=is_active,
        )
        enemy_ignited_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "conditionEnemyIgnited",
            build_node=build_node,
            is_active=is_active,
        )
        shock_effect_raw, _ = self._resolve_config_input_value(
            config_set["inputs"],
            "conditionShockEffect",
            build_node=build_node,
            is_active=is_active,
        )

        bandit = None if bandit_raw in (None, "None") else str(bandit_raw)
        pantheon_major = None if pantheon_major_raw in (None, "None") else str(pantheon_major_raw)
        pantheon_minor = None if pantheon_minor_raw in (None, "None") else str(pantheon_minor_raw)
        enemy_is_boss = str(enemy_is_boss_raw or _CONFIG_DEFAULT_INPUTS["enemyIsBoss"])
        buffs = {
            "onslaught": bool(buff_onslaught_raw),
            "fortification": bool(buff_fortification_raw),
        }
        combat_conditions = {
            "using_flask": bool(using_flask_raw),
        }
        enemy_state = {
            "is_boss": enemy_is_boss,
            "is_shocked": bool(enemy_shocked_raw),
            "is_ignited": bool(enemy_ignited_raw),
            "shock_effect": None if shock_effect_raw is None else int(shock_effect_raw),
        }

        enabled_conditions = sorted(
            condition_id
            for input_name, condition_id in _CONFIG_ENABLED_CONDITION_IDS.items()
            if (
                (input_name == "buffOnslaught" and buffs["onslaught"])
                or (input_name == "buffFortification" and buffs["fortification"])
                or (input_name == "conditionUsingFlask" and combat_conditions["using_flask"])
                or (input_name == "conditionEnemyShocked" and enemy_state["is_shocked"])
                or (input_name == "conditionEnemyIgnited" and enemy_state["is_ignited"])
            )
        )
        custom_values: dict[str, Any] = {}
        engine_default_fields: dict[str, Any] = {}
        if include_default_enemy_state or enemy_state["is_boss"] != _CONFIG_DEFAULT_INPUTS["enemyIsBoss"]:
            custom_values[_CONFIG_CUSTOM_VALUE_KEYS["enemyIsBoss"]] = enemy_state["is_boss"]
            if enemy_is_boss_defaulted:
                engine_default_fields[_CONFIG_CUSTOM_VALUE_KEYS["enemyIsBoss"]] = enemy_state["is_boss"]
        if enemy_state["shock_effect"] is not None:
            custom_values[_CONFIG_CUSTOM_VALUE_KEYS["conditionShockEffect"]] = enemy_state["shock_effect"]
        if enemy_state["is_ignited"]:
            custom_values[_CONFIG_CUSTOM_VALUE_KEYS["conditionEnemyIgnited"]] = True

        return {
            "config_set_id": config_set["config_set_id"],
            "title": config_set["title"],
            "state_role": self._config_state_role(
                config_set_id=config_set["config_set_id"],
                title=config_set["title"],
                config_set_count=config_set_count,
            ),
            "enabled_conditions": enabled_conditions,
            "custom_values": custom_values,
            "notes": None,
            "bandit": bandit,
            "pantheon_major": pantheon_major,
            "pantheon_minor": pantheon_minor,
            "engine_default_fields": engine_default_fields,
            "buffs": buffs,
            "combat_conditions": combat_conditions,
            "enemy_state": enemy_state,
        }

    def _config_state_role(
        self,
        *,
        config_set_id: str,
        title: str,
        config_set_count: int,
    ) -> str | None:
        normalized_title = title.strip().lower()
        if normalized_title == "baseline":
            return "baseline"
        if normalized_title == "conditional":
            return "conditional"
        if config_set_count == 2 and config_set_id == _CANONICAL_CONFIG_ID:
            return "baseline"
        if config_set_count == 2 and config_set_id == "config.2":
            return "conditional"
        return None

    def _set_active_config_set(self, config_set_id: str) -> None:
        config_set_index = _normalize_config_set_index(config_set_id, "config_set_id")
        self._bridge.execute(
            "\n".join(
                (
                    f"local config_set_index = {config_set_index}",
                    "if not build or not build.configTab then",
                    "  error('Pinned runtime is missing build.configTab during calc snapshot read-back.')",
                    "end",
                    "if not build.configTab.configSets or not build.configTab.configSets[config_set_index] then",
                    "  error('Pinned runtime is missing config set ' .. tostring(config_set_index) .. ' during calc snapshot read-back.')",
                    "end",
                    "build.configTab:SetActiveConfigSet(config_set_index)",
                    "runCallback('OnFrame')",
                )
            )
        )

    def _snapshot_calc_section(
        self,
        *,
        config_set_id: str,
        state_role: str,
        config_summary: dict[str, Any],
    ) -> dict[str, Any]:
        self._set_active_config_set(config_set_id)
        chunk = "\n".join(
            (
                "local json = require('dkjson')",
                f"local family_by_stat_json = {_lua_json_literal(_CALC_DISPLAY_FAMILY_BY_STAT)}",
                f"local family_order_json = {_lua_json_literal(list(_CALC_DISPLAY_FAMILY_ORDER))}",
                "local family_by_stat, _, family_decode_err = json.decode(family_by_stat_json, 1, nil)",
                "if type(family_by_stat) ~= 'table' then",
                "  error('family_by_stat mapping must decode to a table: ' .. tostring(family_decode_err or 'unknown error'))",
                "end",
                "local family_order, _, order_decode_err = json.decode(family_order_json, 1, nil)",
                "if type(family_order) ~= 'table' then",
                "  error('family_order mapping must decode to a table: ' .. tostring(order_decode_err or 'unknown error'))",
                "end",
                "local function empty_object()",
                "  return setmetatable({}, { __jsontype = 'object' })",
                "end",
                "local function scalar_value(value)",
                "  local value_type = type(value)",
                "  if value_type == 'number' then",
                "    if value == value and value ~= math.huge and value ~= -math.huge then",
                "      return value",
                "    end",
                "    return nil",
                "  end",
                "  if value_type == 'string' or value_type == 'boolean' then",
                "    return value",
                "  end",
                "  return nil",
                "end",
                "local function collect_scalar_output(output)",
                "  local result = empty_object()",
                "  if type(output) ~= 'table' then",
                "    return result",
                "  end",
                "  local keys = {}",
                "  for key, value in pairs(output) do",
                "    if type(key) == 'string' and scalar_value(value) ~= nil then",
                "      table.insert(keys, key)",
                "    end",
                "  end",
                "  table.sort(keys)",
                "  for _, key in ipairs(keys) do",
                "    result[key] = output[key]",
                "  end",
                "  return result",
                "end",
                "local function family_id_for_stat(stat_name)",
                "  return family_by_stat[stat_name] or 'offense'",
                "end",
                "local function one_flag_matches(flag, skill_flags)",
                "  if flag == nil then",
                "    return true",
                "  end",
                "  if type(flag) == 'table' then",
                "    for _, item in ipairs(flag) do",
                "      if not one_flag_matches(item, skill_flags) then",
                "        return false",
                "      end",
                "    end",
                "    return true",
                "  end",
                "  return skill_flags and skill_flags[flag] == true",
                "end",
                "local function matches_flags(flag, not_flag, skill_flags)",
                "  if not one_flag_matches(flag, skill_flags) then",
                "    return false",
                "  end",
                "  if not_flag == nil then",
                "    return true",
                "  end",
                "  if type(not_flag) == 'table' then",
                "    for _, item in ipairs(not_flag) do",
                "      if one_flag_matches(item, skill_flags) then",
                "        return false",
                "      end",
                "    end",
                "    return true",
                "  end",
                "  return not one_flag_matches(not_flag, skill_flags)",
                "end",
                "local function collect_display_rows(stat_list, actor, output, source_output)",
                "  local family_rows = {}",
                "  for _, family_id in ipairs(family_order) do",
                "    family_rows[family_id] = { family_id = family_id, rows = {} }",
                "  end",
                "  if type(stat_list) ~= 'table' or type(actor) ~= 'table' or type(output) ~= 'table' then",
                "    return {}",
                "  end",
                "  local main_skill = actor.mainSkill or {}",
                "  local skill_flags = main_skill.skillFlags or {}",
                "  for _, statData in ipairs(stat_list) do",
                "    if matches_flags(statData.flag, statData.notFlag, skill_flags) then",
                "      if statData.stat and statData.stat ~= 'SkillDPS' then",
                "        local stat_val = output[statData.stat]",
                "        if stat_val ~= nil and statData.childStat and type(stat_val) == 'table' then",
                "          stat_val = stat_val[statData.childStat]",
                "        end",
                "        local visible = false",
                "        if stat_val ~= nil then",
                "          if statData.condFunc then",
                "            visible = statData.condFunc(stat_val, output) and true or false",
                "          else",
                "            visible = stat_val ~= 0",
                "          end",
                "        end",
                "        if visible and not statData.hideStat then",
                "          local scalar_stat = scalar_value(stat_val)",
                "          if scalar_stat ~= nil then",
                "            local overcap_value = json.null",
                "            if statData.overCapStat then",
                "              local scalar_overcap = scalar_value(output[statData.overCapStat])",
                "              if scalar_overcap ~= nil then",
                "                overcap_value = scalar_overcap",
                "              end",
                "            end",
                "            local warning_value = json.null",
                "            if statData.warnFunc then",
                "              local warning_text = statData.warnFunc(stat_val, output)",
                "              if type(warning_text) == 'string' and warning_text ~= '' then",
                "                warning_value = warning_text",
                "              end",
                "            end",
                "            table.insert(family_rows[family_id_for_stat(statData.stat)].rows, {",
                "              stat_key = statData.childStat and (tostring(statData.stat) .. '.' .. tostring(statData.childStat)) or tostring(statData.stat),",
                "              label = tostring(statData.label or statData.stat),",
                "              value = scalar_stat,",
                "              overcap_value = overcap_value,",
                "              warning = warning_value,",
                "              lower_is_better = statData.lowerIsBetter == true,",
                "              source_output = source_output,",
                "            })",
                "          end",
                "        end",
                "      end",
                "    end",
                "  end",
                "  local families = {}",
                "  for _, family_id in ipairs(family_order) do",
                "    if #family_rows[family_id].rows > 0 then",
                "      table.insert(families, family_rows[family_id])",
                "    end",
                "  end",
                "  return families",
                "end",
                "local function collect_warning_lines(lines)",
                "  local result = {}",
                "  local seen = {}",
                "  if type(lines) ~= 'table' then",
                "    return result",
                "  end",
                "  for _, entry in pairs(lines) do",
                "    local line = entry",
                "    if type(entry) == 'table' then",
                "      line = entry.line",
                "    end",
                "    if type(line) == 'string' and line ~= '' and not seen[line] then",
                "      seen[line] = true",
                "      table.insert(result, line)",
                "    end",
                "  end",
                "  table.sort(result)",
                "  return result",
                "end",
                "if not build or not build.calcsTab or not build.controls then",
                "  error('Pinned runtime is missing build.calcsTab or build.controls during calc snapshot read-back.')",
                "end",
                "build:RefreshStatList()",
                "local player_actor = build.calcsTab.mainEnv and build.calcsTab.mainEnv.player or nil",
                "if type(player_actor) ~= 'table' then",
                "  error('Pinned runtime is missing player actor during calc snapshot read-back.')",
                "end",
                "local player_output = build.calcsTab.mainOutput",
                "local calcs_output = build.calcsTab.calcsOutput",
                "if type(player_output) ~= 'table' or type(calcs_output) ~= 'table' then",
                "  error('Pinned runtime is missing mainOutput or calcsOutput during calc snapshot read-back.')",
                "end",
                "local payload = {",
                "  main_output = collect_scalar_output(player_output),",
                "  calcs_output = collect_scalar_output(calcs_output),",
                "  display_families = {",
                "    player = collect_display_rows(build.displayStats or {}, player_actor, player_output, 'main_output'),",
                "    minion = {},",
                "  },",
                "  warnings = collect_warning_lines(build.controls.warnings and build.controls.warnings.lines or nil),",
                "}",
                "if build.calcsTab.mainEnv and type(build.calcsTab.mainEnv.minion) == 'table' and type(player_output.Minion) == 'table' then",
                "  payload.display_families.minion = collect_display_rows(",
                "    build.minionDisplayStats or {},",
                "    build.calcsTab.mainEnv.minion,",
                "    player_output.Minion,",
                "    'main_output.minion'",
                "  )",
                "end",
                "return json.encode(payload)",
            )
        )
        payload_raw = self._bridge.execute(chunk, nret=1)[0]
        if payload_raw is None:
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime returned no calc snapshot payload.")
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError as exc:
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime returned invalid calc snapshot JSON.") from exc
        if not isinstance(payload, dict):
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime calc snapshot payload must decode to an object.")
        main_output = payload.get("main_output")
        calcs_output = payload.get("calcs_output")
        display_families = payload.get("display_families")
        warnings = payload.get("warnings")
        if not isinstance(main_output, dict) or not isinstance(calcs_output, dict):
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime calc snapshot must expose main_output and calcs_output objects.")
        if not isinstance(display_families, dict):
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime calc snapshot must expose display_families.")
        if not isinstance(warnings, list) or any(not isinstance(line, str) or not line.strip() for line in warnings):
            raise WorkerContractError("runtime_protocol_failed", "Pinned runtime calc snapshot warnings must stay a string array.")

        return {
            "config_set_id": config_set_id,
            "state_role": state_role,
            "config_summary": _json_clone(config_summary, field_name=f"{state_role}.config_summary"),
            "main_output": _json_clone(main_output, field_name=f"{state_role}.main_output"),
            "calcs_output": _json_clone(calcs_output, field_name=f"{state_role}.calcs_output"),
            "display_families": _json_clone(display_families, field_name=f"{state_role}.display_families"),
            "warnings": [line.strip() for line in warnings],
            "warning_codes": _warning_codes_from_lines([line.strip() for line in warnings]),
        }

    def snapshot_calc_packet(self) -> dict[str, Any]:
        """Calc snapshot over config lanes.

        Lanes: "baseline" and "conditional". When the build declares config sets
        titled Baseline/Conditional (or exactly two sets), both are evaluated.
        Otherwise the active config set is used for both lanes and evaluated
        once (single-lane fast path, e.g. imported builds with one config set).
        """

        config_state = self._snapshot_config_state()
        active_config_set_id = str(config_state.get("active_config_set_id") or _CANONICAL_CONFIG_ID)
        config_sets = config_state.get("config_sets")
        if not isinstance(config_sets, dict):
            config_sets = {}
        baseline_config_set_id = str(config_state.get("baseline_config_set_id") or active_config_set_id)
        conditional_config_set_id = str(config_state.get("conditional_config_set_id") or baseline_config_set_id)

        def summary_for(config_set_id: str, state_role: str) -> dict[str, Any]:
            summary = config_sets.get(config_set_id)
            if isinstance(summary, dict):
                return summary
            return {
                "config_set_id": config_set_id,
                "state_role": state_role,
                "state_kind": config_state.get("state_kind"),
                "note": "single-lane: no explicit baseline/conditional config sets declared",
            }

        primary_error: Exception | None = None
        try:
            baseline = self._snapshot_calc_section(
                config_set_id=baseline_config_set_id,
                state_role="baseline",
                config_summary=summary_for(baseline_config_set_id, "baseline"),
            )
            if conditional_config_set_id == baseline_config_set_id:
                conditional = dict(baseline)
                conditional["state_role"] = "conditional"
            else:
                conditional = self._snapshot_calc_section(
                    config_set_id=conditional_config_set_id,
                    state_role="conditional",
                    config_summary=summary_for(conditional_config_set_id, "conditional"),
                )
            return {
                "active_config_set_id": active_config_set_id,
                "single_lane": conditional_config_set_id == baseline_config_set_id,
                "baseline": baseline,
                "conditional": conditional,
            }
        except Exception as exc:
            primary_error = exc
        finally:
            try:
                self._set_active_config_set(active_config_set_id)
            except Exception:
                if primary_error is None:
                    raise
        if primary_error is not None:
            raise primary_error

    def time_state_parts(self) -> dict[str, float]:
        """Seconds spent in each part of `snapshot_state` (a profiling aid for 7.1h)."""

        import time as _time

        out: dict[str, float] = {}
        t = _time.perf_counter(); self._snapshot_rich_skill_state(); out["skills_state"] = _time.perf_counter() - t
        t = _time.perf_counter(); self._snapshot_config_state(); out["config_state"] = _time.perf_counter() - t
        t = _time.perf_counter(); self.export_build_xml(); out["export_build_xml"] = _time.perf_counter() - t
        t = _time.perf_counter(); self.snapshot_state(); out["snapshot_state_total"] = _time.perf_counter() - t
        return out

    def snapshot_state(self) -> dict[str, Any]:
        chunk = "\n".join(
            (
                "local json = require('dkjson')",
                f"local slot_order = {_slot_order_literal()}",
                "local function encode_null(value)",
                "  if value == nil or value == '' or value == 'None' then",
                "    return json.null",
                "  end",
                "  return tostring(value)",
                "end",
                "local function normalize_rarity(value)",
                "  if value == nil then",
                "    return 'Rare'",
                "  end",
                "  local lowered = tostring(value):lower()",
                "  return lowered:sub(1, 1):upper() .. lowered:sub(2)",
                "end",
                "local function collect_line_list(lines, item)",
                "  -- the lines as PoB uses them: variant lines the item does not select are skipped,",
                "  -- ranges are resolved at the item's roll (Item:BuildModList does the same before parsing)",
                "  local result = {}",
                "  if type(lines) ~= 'table' then",
                "    return result",
                "  end",
                "  for _, entry in ipairs(lines) do",
                "    local line = entry",
                "    local keep = true",
                "    if type(entry) == 'table' then",
                "      line = entry.line",
                "      if item and entry.variantList then",
                "        if item.usesVariantGroups then",
                "          keep = item:CheckModLineVariant(entry) and true or false",
                "        elseif item.variant then",
                "          keep = entry.variantList[item.variant] and true or false",
                "        end",
                "      end",
                "      if keep and type(line) == 'string' and line:find('%(%-?%d+%.?%d*%-%-?%d+%.?%d*%)') then",
                "        local ok, resolved = pcall(itemLib.applyRange, line, entry.range or 1, entry.valueScalar or 1, entry.corruptedRange or 1)",
                "        if ok and type(resolved) == 'string' then line = resolved end",
                "      end",
                "    end",
                "    if keep and type(line) == 'string' and line ~= '' then",
                "      table.insert(result, line)",
                "    end",
                "  end",
                "  return result",
                "end",
                "local function collect_sorted_node_ids(mapping)",
                "  local result = {}",
                "  if type(mapping) ~= 'table' then",
                "    return result",
                "  end",
                "  for node_id, _ in pairs(mapping) do",
                "    table.insert(result, node_id)",
                "  end",
                "  table.sort(result)",
                "  return result",
                "end",
                "local function node_display_name(node)",
                "  return tostring(node.dn or node.name or node.label or 'unknown node')",
                "end",
                *_ASCENDANCY_MATCH_LUA,
                "local function node_is_ascendancy_start(node)",
                "  return node.isAscendancyStart == true or node.ascendancyStart == true",
                "end",
                "local function node_is_notable(node)",
                "  return node.isNotable == true or node.notable == true or node.type == 'Notable'",
                "end",
                "local function list_has_entries(values)",
                "  return type(values) == 'table' and #values > 0",
                "end",
                "local function empty_object()",
                "  return setmetatable({}, { __jsontype = 'object' })",
                "end",
                "local function count_links(sockets)",
                "  if type(sockets) ~= 'table' then",
                "    return 0",
                "  end",
                "  local group_counts = {}",
                "  local max_links = 0",
                "  for _, socket in ipairs(sockets) do",
                "    local group = tonumber(socket.group) or 0",
                "    group_counts[group] = (group_counts[group] or 0) + 1",
                "    if group_counts[group] > max_links then",
                "      max_links = group_counts[group]",
                "    end",
                "  end",
                "  return max_links",
                "end",
                "local function collect_socket_list(item)",
                "  local result = {}",
                "  if type(item.sockets) ~= 'table' then",
                "    return result",
                "  end",
                "  for _, socket in ipairs(item.sockets) do",
                "    table.insert(result, {",
                "      color = tostring(socket.color or ''),",
                "      group = tonumber(socket.group) or 0,",
                "    })",
                "  end",
                "  return result",
                "end",
                "local function collect_influences(item)",
                "  local result = {}",
                "  if item.shaper then",
                "    table.insert(result, 'Shaper')",
                "  end",
                "  if item.elder then",
                "    table.insert(result, 'Elder')",
                "  end",
                "  if item.crusader then",
                "    table.insert(result, 'Crusader')",
                "  end",
                "  if item.hunter then",
                "    table.insert(result, 'Hunter')",
                "  end",
                "  if item.redeemer then",
                "    table.insert(result, 'Redeemer')",
                "  end",
                "  if item.warlord then",
                "    table.insert(result, 'Warlord')",
                "  end",
                "  if item.exarch then",
                "    table.insert(result, 'Exarch')",
                "  end",
                "  if item.eater then",
                "    table.insert(result, 'Eater')",
                "  end",
                "  if item.synthesis then",
                "    table.insert(result, 'Synthesised')",
                "  end",
                "  table.sort(result)",
                "  return result",
                "end",
                "local function serialize_item(slot_name, item)",
                "  return {",
                "    rarity = normalize_rarity(item.rarity),",
                "    slot = tostring(slot_name),",
                "    type_label = tostring(item.type or slot_name),",
                "    base_type = tostring(item.baseName or (item.base and item.base.name) or item.type or slot_name),",
                "    explicit_affixes = collect_line_list(item.explicitModLines, item),",
                "    implicit_affixes = collect_line_list(item.implicitModLines, item),",
                "    crafted = item.crafted == true,",
                "    enchanted = type(item.enchantModLines) == 'table' and #item.enchantModLines > 0 or false,",
                "    fractured = item.fractured == true,",
                "    veiled = item.veiled == true,",
                "    influences = collect_influences(item),",
                "    corrupted = item.corrupted == true or item.scourge == true,",
                "    sockets = collect_socket_list(item),",
                "    links = count_links(item.sockets),",
                "  }",
                "end",
                "local function strip_minimal_proof_item(item_payload)",
                "  if type(item_payload) ~= 'table' then",
                "    return item_payload",
                "  end",
                "  item_payload.base_type = nil",
                "  item_payload.sockets = {}",
                "  item_payload.links = 0",
                "  return item_payload",
                "end",
                "local function normalize_item_set_id(item_set_id)",
                "  local numeric_id = tonumber(item_set_id) or 1",
                "  if numeric_id == 1 then",
                "    return " + _lua_long_string(_CANONICAL_ITEM_SET_ID),
                "  end",
                "  return 'itemset.' .. tostring(numeric_id)",
                "end",
                "local function serialize_slot_payload(item_set, slot_name)",
                "  local slot_state = item_set[slot_name]",
                "  local sel_item_id = slot_state and slot_state.selItemId or 0",
                "  if type(sel_item_id) ~= 'number' or sel_item_id == 0 then",
                "    return { occupied = false, item = json.null }",
                "  end",
                "  local item = build.itemsTab.items[sel_item_id]",
                "  if not item then",
                "    error('Item slot ' .. tostring(slot_name) .. ' references missing item id ' .. tostring(sel_item_id) .. '.')",
                "  end",
                "  return { occupied = true, item = serialize_item(slot_name, item) }",
                "end",
                "local base_slot_lookup = {}",
                "for _, slot_name in ipairs(slot_order) do",
                "  base_slot_lookup[slot_name] = true",
                "end",
                "local function slot_has_visible_carrier(item_set, slot)",
                "  if slot.weaponSet == 2 and not item_set.useSecondWeaponSet then",
                "    return false",
                "  end",
                "  if slot.parentSlot and slot.slotNum then",
                "    local parent_slot_name = slot.parentSlot.slotName",
                "    local parent_state = item_set[parent_slot_name]",
                "    local parent_item_id = parent_state and parent_state.selItemId or 0",
                "    local parent_item = build.itemsTab.items[parent_item_id]",
                "    local abyssal_socket_count = parent_item and tonumber(parent_item.abyssalSocketCount or 0) or 0",
                "    return abyssal_socket_count >= tonumber(slot.slotNum)",
                "  end",
                "  return true",
                "end",
                "local function collect_extra_slot_names(item_set)",
                "  local result = {}",
                "  for slot_name, slot in pairs(build.itemsTab.slots) do",
                "    if not slot.nodeId and not base_slot_lookup[slot_name] then",
                "      local slot_state = item_set[slot_name]",
                "      local sel_item_id = slot_state and slot_state.selItemId or 0",
                "      if slot_has_visible_carrier(item_set, slot) or (type(sel_item_id) == 'number' and sel_item_id > 0) then",
                "        table.insert(result, slot_name)",
                "      end",
                "    end",
                "  end",
                "  table.sort(result)",
                "  return result",
                "end",
                "local function serialize_item_set(item_set_id)",
                "  local item_set = build.itemsTab.itemSets[item_set_id]",
                "  if not item_set then",
                "    error('Missing item set ' .. tostring(item_set_id) .. ' while snapshotting state.')",
                "  end",
                "  local extra_slot_names = collect_extra_slot_names(item_set)",
                "  local slots = {}",
                "  local nonempty_slot_count = 0",
                "  local function record_slot(slot_name)",
                "    local slot_payload = serialize_slot_payload(item_set, slot_name)",
                "    if slot_payload.occupied then",
                "      nonempty_slot_count = nonempty_slot_count + 1",
                "    end",
                "    slots[slot_name] = slot_payload",
                "  end",
                "  local flasks_active = {}",
                "  for _, slot_name in ipairs(slot_order) do",
                "    record_slot(slot_name)",
                "    if slot_name:find('^Flask %d') then",
                "      flasks_active[slot_name] = item_set[slot_name] ~= nil and item_set[slot_name].active == true",
                "    end",
                "  end",
                "  for _, slot_name in ipairs(extra_slot_names) do",
                "    record_slot(slot_name)",
                "  end",
                "  return {",
                "    item_set_id = normalize_item_set_id(item_set_id),",
                "    use_second_weapon_set = item_set.useSecondWeaponSet == true,",
                "    extra_slots = extra_slot_names,",
                "    slots = slots,",
                "    nonempty_slot_count = nonempty_slot_count,",
                "    flasks_active = flasks_active,",
                "  }",
                "end",
                "local socket_groups = {}",
                "for _, socket_group in ipairs(build.skillsTab.socketGroupList) do",
                "  table.insert(socket_groups, {",
                "    label = socket_group.label or json.null,",
                "    slot = socket_group.slot or json.null,",
                "    source = socket_group.source or json.null,",
                "    gem_count = #socket_group.gemList,",
                "  })",
                "end",
                "local engine_default_lookup = {}",
                "local function mark_engine_default(node_id)",
                "  if node_id and build.spec.allocNodes[node_id] then",
                "    engine_default_lookup[node_id] = true",
                "  end",
                "end",
                "mark_engine_default(build.spec.curClass and build.spec.curClass.startNodeId or nil)",
                "mark_engine_default(build.spec.curAscendClass and build.spec.curAscendClass.startNodeId or nil)",
                "mark_engine_default(build.spec.curSecondaryAscendClass and build.spec.curSecondaryAscendClass.startNodeId or nil)",
                "local engine_default_node_ids = {}",
                "for node_id, _ in pairs(engine_default_lookup) do",
                "  table.insert(engine_default_node_ids, node_id)",
                "end",
                "table.sort(engine_default_node_ids)",
                "local user_allocated_node_ids = {}",
                "local keystone_node_ids = {}",
                "local allocated_ascendancy_node_ids = {}",
                "local allocated_ascendancy_notable_node_ids = {}",
                "local allocated_ascendancy_notable_entries = {}",
                "local allocated_ascendancy_names = current_ascendancy_names()",
                "for node_id, node in pairs(build.spec.allocNodes) do",
                "  if not engine_default_lookup[node_id] then",
                "    table.insert(user_allocated_node_ids, node_id)",
                "    if node.isKeystone or node.type == 'Keystone' then",
                "      table.insert(keystone_node_ids, node_id)",
                "    end",
                "    if node_in_current_ascendancy(node, allocated_ascendancy_names) and not node_is_ascendancy_start(node) then",
                "      table.insert(allocated_ascendancy_node_ids, node_id)",
                "      if node_is_notable(node) then",
                "        table.insert(allocated_ascendancy_notable_node_ids, node_id)",
                "        table.insert(allocated_ascendancy_notable_entries, { node_id = node_id, name = node_display_name(node) })",
                "      end",
                "    end",
                "  end",
                "end",
                "table.sort(user_allocated_node_ids)",
                "table.sort(keystone_node_ids)",
                "table.sort(allocated_ascendancy_node_ids)",
                "table.sort(allocated_ascendancy_notable_node_ids)",
                "table.sort(allocated_ascendancy_notable_entries, function(left, right)",
                "  return left.node_id < right.node_id",
                "end)",
                "local allocated_ascendancy_notables = {}",
                "for _, entry in ipairs(allocated_ascendancy_notable_entries) do",
                "  table.insert(allocated_ascendancy_notables, entry.name)",
                "end",
                "local ascendancy_readback = {",
                "  source_kind = 'pinned_pob_alloc_nodes_readback',",
                "  class_id = encode_null(build.spec.curClassName),",
                "  ascendancy_id = encode_null(build.spec.curAscendClassName),",
                "  allocated_ascendancy_points = #allocated_ascendancy_node_ids,",
                "  allocated_ascendancy_node_ids = allocated_ascendancy_node_ids,",
                "  allocated_ascendancy_notable_count = #allocated_ascendancy_notable_node_ids,",
                "  allocated_ascendancy_notable_node_ids = allocated_ascendancy_notable_node_ids,",
                "  allocated_ascendancy_notables = allocated_ascendancy_notables,",
                "}",
                "local mastery_effect_ids = {}",
                "for mastery_node_id, effect_id in pairs(build.spec.masterySelections or {}) do",
                "  table.insert(mastery_effect_ids, tostring(mastery_node_id) .. ':' .. tostring(effect_id))",
                "end",
                "table.sort(mastery_effect_ids)",
                "local cluster_jewel_socket_ids = {}",
                "local socketed_jewel_node_ids = {}",
                "for node_id, item_id in pairs(build.spec.jewels or {}) do",
                "  if type(item_id) == 'number' and item_id > 0 then",
                "    table.insert(socketed_jewel_node_ids, node_id)",
                "    local item = build.itemsTab.items[item_id]",
                "    if item and (item.clusterJewel or (item.jewelData and item.jewelData.clusterJewelValid)) then",
                "      table.insert(cluster_jewel_socket_ids, node_id)",
                "    end",
                "  end",
                "end",
                "table.sort(cluster_jewel_socket_ids)",
                "table.sort(socketed_jewel_node_ids)",
                "local cluster_jewel_items = {}",
                "local socketed_jewel_items = {}",
                "for node_id, item_id in pairs(build.spec.jewels or {}) do",
                "  if type(item_id) == 'number' and item_id > 0 then",
                "    local item = build.itemsTab.items[item_id]",
                "    if not item then",
                "      error('Tree jewel socket ' .. tostring(node_id) .. ' references missing item id ' .. tostring(item_id) .. '.')",
                "    end",
                "    local entry = {",
                "      node_id = node_id,",
                "      item = serialize_item('Jewel', item),",
                "    }",
                "    if item.clusterJewel or (item.jewelData and item.jewelData.clusterJewelValid) then",
                "      table.insert(cluster_jewel_items, entry)",
                "    else",
                "      table.insert(socketed_jewel_items, entry)",
                "    end",
                "  end",
                "end",
                "table.sort(cluster_jewel_items, function(left, right)",
                "  return left.node_id < right.node_id",
                "end)",
                "table.sort(socketed_jewel_items, function(left, right)",
                "  return left.node_id < right.node_id",
                "end)",
                "local override_carrier_node_ids = collect_sorted_node_ids(build.spec.hashOverrides)",
                "local active_spec_index = tonumber(build.treeTab.activeSpec) or 1",
                "local active_spec_id = active_spec_index == 1 and " + _lua_long_string(_CANONICAL_SPEC_ID) + " or ('spec.' .. tostring(active_spec_index))",
                "local active_item_set_index = tonumber(build.itemsTab.activeItemSetId) or 1",
                "local active_item_set = serialize_item_set(active_item_set_index)",
                "local include_item_sets = (#build.itemsTab.itemSetOrderList > 1)",
                "  or active_item_set.use_second_weapon_set",
                "  or #active_item_set.extra_slots > 0",
                "local item_set_ids = {}",
                "local item_sets = empty_object()",
                "local total_nonempty_slot_count = active_item_set.nonempty_slot_count",
                "if include_item_sets then",
                "  total_nonempty_slot_count = 0",
                "  for _, item_set_id in ipairs(build.itemsTab.itemSetOrderList) do",
                "    local serialized_item_set = serialize_item_set(tonumber(item_set_id) or item_set_id)",
                "    table.insert(item_set_ids, serialized_item_set.item_set_id)",
                "    item_sets[serialized_item_set.item_set_id] = serialized_item_set",
                "    total_nonempty_slot_count = total_nonempty_slot_count + serialized_item_set.nonempty_slot_count",
                "  end",
                "end",
                "local gear_state_kind = 'nondefault'",
                "if total_nonempty_slot_count == 0 then",
                "  gear_state_kind = 'empty'",
                "elseif not include_item_sets",
                "  and active_item_set.nonempty_slot_count == 1",
                "  and active_item_set.slots['Boots']",
                "  and active_item_set.slots['Boots'].occupied then",
                "  local boots_only = true",
                "  for _, slot_name in ipairs(slot_order) do",
                "    if slot_name ~= 'Boots' and active_item_set.slots[slot_name] and active_item_set.slots[slot_name].occupied then",
                "      boots_only = false",
                "      break",
                "    end",
                "  end",
                "  if boots_only and #active_item_set.extra_slots == 0 then",
                "    gear_state_kind = 'boots_only'",
                "  end",
                "end",
                "local skills_state_kind = (#socket_groups == 0) and 'empty' or 'nondefault'",
                "local config_state_kind = 'default'",
                "local active_class_id = tonumber(build.spec.curClassId) or 0",
                "local active_ascendancy_id = tonumber(build.spec.curAscendClassId) or 0",
                "local active_secondary_ascendancy_id = tonumber(build.spec.curSecondaryAscendClassId) or 0",
                "local tree_state_kind = 'nondefault'",
                "if active_spec_id == " + _lua_long_string(_CANONICAL_SPEC_ID),
                "  and active_class_id == " + str(_CANONICAL_BLANK_CLASS_ID),
                "  and active_ascendancy_id == " + str(_CANONICAL_BLANK_ASCENDANCY_ID),
                "  and active_secondary_ascendancy_id == " + str(_CANONICAL_BLANK_SECONDARY_ASCENDANCY_ID),
                "  and #user_allocated_node_ids == 0",
                "  and #mastery_effect_ids == 0",
                "  and #cluster_jewel_socket_ids == 0",
                "  and #socketed_jewel_node_ids == 0",
                "  and #override_carrier_node_ids == 0 then",
                "  tree_state_kind = 'default'",
                "end",
                "local payload = {",
                "  identity_state = {",
                "    level = tonumber(build.characterLevel) or json.null,",
                "    character_level_auto_mode = build.characterLevelAutoMode == true,",
                "    active_spec_id = active_spec_id,",
                "    class_id = encode_null(build.spec.curClassName),",
                "    ascendancy_id = encode_null(build.spec.curAscendClassName),",
                "    secondary_ascendancy_id = encode_null(build.spec.curSecondaryAscendClassName),",
                "  },",
                "  gear_slots = {",
                "    state_kind = gear_state_kind,",
                "    active_item_set_id = active_item_set.item_set_id,",
                "    use_second_weapon_set = active_item_set.use_second_weapon_set,",
                "    slot_order = slot_order,",
                "    extra_slots = active_item_set.extra_slots,",
                "    slots = active_item_set.slots,",
                "    nonempty_slot_count = active_item_set.nonempty_slot_count,",
                "    flasks_active = active_item_set.flasks_active,",
                "  },",
                "  tree_state = {",
                "    state_kind = tree_state_kind,",
                "    active_spec_id = active_spec_id,",
                "    class_id = encode_null(build.spec.curClassName),",
                "    ascendancy_id = encode_null(build.spec.curAscendClassName),",
                "    secondary_ascendancy_id = encode_null(build.spec.curSecondaryAscendClassName),",
                "    default_root_state_present = #engine_default_node_ids > 0,",
                "    engine_default_node_ids = engine_default_node_ids,",
                "    user_allocated_node_ids = user_allocated_node_ids,",
                # which passive tree the allocated ids are read against: PoB keeps the version the
                # XML declared (TreeTab.lua:511) and never converts on its own, so a loaded build
                # can sit on an older tree than the one we optimize on (`PobSession.convert_tree`)
                "    tree_version = tostring(build.spec.treeVersion),",
                "    latest_tree_version = tostring(latestTreeVersion),",
                "    keystone_node_ids = keystone_node_ids,",
                "    ascendancy_readback = ascendancy_readback,",
                "    allocated_ascendancy_points = ascendancy_readback.allocated_ascendancy_points,",
                "    allocated_ascendancy_node_ids = allocated_ascendancy_node_ids,",
                "    allocated_ascendancy_notable_count = ascendancy_readback.allocated_ascendancy_notable_count,",
                "    allocated_ascendancy_notable_node_ids = allocated_ascendancy_notable_node_ids,",
                "    allocated_ascendancy_notables = allocated_ascendancy_notables,",
                "    mastery_effect_ids = mastery_effect_ids,",
                "    cluster_jewel_socket_ids = cluster_jewel_socket_ids,",
                "    socketed_jewel_node_ids = socketed_jewel_node_ids,",
                "    anoint_allocations = {},",
                "  },",
                "  skills_state = {",
                "    state_kind = skills_state_kind,",
                f"    active_skill_set_id = {_lua_long_string(_CANONICAL_SKILLS_ID)},",
                "    socket_group_count = #socket_groups,",
                "    socket_groups = socket_groups,",
                "    main_socket_group_id = (#socket_groups == 0) and json.null or tostring(build.mainSocketGroup),",
                "    main_active_skill_id = json.null,",
                "  },",
                "  config_state = {",
                "    state_kind = config_state_kind,",
                f"    active_config_set_id = {_lua_long_string(_CANONICAL_CONFIG_ID)},",
                "    enabled_conditions = {},",
                "    custom_values = empty_object(),",
                "    notes = json.null,",
                "    bandit = json.null,",
                "    pantheon_major = json.null,",
                "    pantheon_minor = json.null,",
                "    engine_default_fields = empty_object(),",
                "  },",
                "}",
                "payload.ascendancy_readback = ascendancy_readback",
                "if gear_state_kind == 'boots_only'",
                "  and payload.gear_slots.slots['Boots']",
                "  and payload.gear_slots.slots['Boots'].occupied",
                "  and payload.gear_slots.slots['Boots'].item then",
                "  payload.gear_slots.slots['Boots'].item = strip_minimal_proof_item(payload.gear_slots.slots['Boots'].item)",
                "end",
                "if include_item_sets then",
                "  payload.gear_slots.item_set_ids = item_set_ids",
                "  payload.gear_slots.item_sets = item_sets",
                "end",
                "if list_has_entries(override_carrier_node_ids) then",
                "  payload.tree_state.override_carrier_node_ids = override_carrier_node_ids",
                "end",
                "if list_has_entries(cluster_jewel_items) then",
                "  payload.tree_state.cluster_jewel_items = cluster_jewel_items",
                "end",
                "if list_has_entries(socketed_jewel_items) then",
                "  payload.tree_state.socketed_jewel_items = socketed_jewel_items",
                "end",
                "return json.encode(payload)",
            )
        )
        payload = self._bridge.execute(chunk, nret=1)[0]
        if payload is None:
            raise WorkerContractError("runtime_protocol_failed", "PoB state snapshot returned no payload.")
        state = json.loads(payload)
        if not isinstance(state, dict):
            raise WorkerContractError("runtime_protocol_failed", "PoB state snapshot did not decode to an object.")
        gear_slots = state.get("gear_slots")
        if not isinstance(gear_slots, dict):
            raise WorkerContractError("runtime_protocol_failed", "PoB state snapshot is missing the repo-owned gear_slots object.")
        state["items_state"] = json.loads(json.dumps(gear_slots, ensure_ascii=False, allow_nan=False, sort_keys=True))
        state["state_contract_version"] = "pob_unified_state_snapshot.v1"
        state["skills_state"] = self._snapshot_rich_skill_state()
        state["config_state"] = self._snapshot_config_state()
        return state

    def close(self) -> None:
        try:
            self._bridge.close()
        finally:
            os.chdir(self._previous_cwd)


def _read_json_line() -> dict[str, Any] | None:
    line = sys.stdin.readline()
    if not line:
        return None
    stripped = line.strip()
    if not stripped:
        return {}
    return json.loads(stripped)


# Actions that derive the Flask flags from PoB's uptime (#575) while the host treats them as reads. Their reply says
# whether the flags changed over the call (`flask_flags_changed`), so the host drops its cached state exactly then.
_FLASK_DERIVING_ACTIONS = frozenset({"read_stats", "read_stats_uncapped", "read_active_skill_stats", "trial_stats", "export_build_xml"})
# (fingerprint reader, fingerprint before the call) while such an action runs; None otherwise
_flask_flags_tracker: tuple[Any, str] | None = None


def _write_message(payload: dict[str, Any]) -> None:
    if _flask_flags_tracker is not None:
        read_fingerprint, before = _flask_flags_tracker
        payload["flask_flags_changed"] = read_fingerprint() != before
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _success(**payload: Any) -> None:
    message = {"ok": True}
    message.update(payload)
    _write_message(message)


def _failure(exc: Exception) -> None:
    if isinstance(exc, WorkerContractError):
        payload = {"ok": False, "failure_state": exc.failure_state, "message": str(exc)}
    else:
        payload = {"ok": False, "failure_state": "runtime_protocol_failed", "message": str(exc)}
    _write_message(payload)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--wrapper-path", required=True)
    parser.add_argument("--session-role", required=True, choices=("normal", "reopen"))
    parser.add_argument("--reopen-source", default=None)
    return parser


_CONFIG_SURFACES_PATH = Path(__file__).with_name("corpus_data") / "config_surfaces.json"
_KNOWN_CONFIG_VARS: dict[str, dict[str, Any]] | None = None


def _known_config_vars() -> dict[str, dict[str, Any]]:
    """PoB config input names (ConfigOptions.lua) as extracted into corpus_data/config_surfaces.json."""

    global _KNOWN_CONFIG_VARS
    if _KNOWN_CONFIG_VARS is None:
        try:
            payload = json.loads(_CONFIG_SURFACES_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        records = payload.get("records") if isinstance(payload, dict) else payload
        vars_by_name: dict[str, dict[str, Any]] = {}
        for record in records or []:
            if isinstance(record, dict) and isinstance(record.get("var"), str):
                vars_by_name[record["var"]] = record
        _KNOWN_CONFIG_VARS = vars_by_name
    return _KNOWN_CONFIG_VARS


def _normalize_config_inputs(value: Any, *, field_name: str) -> dict[str, bool | int | float | str]:
    """Validate raw PoB config inputs: {var_name: bool | number | string}.

    Names are checked against the config surfaces corpus so typos fail loudly
    instead of silently doing nothing inside PoB.
    """

    if value is None:
        return {}
    payload = _require_mapping(value, field_name)
    known = _known_config_vars()
    unknown = sorted(name for name in payload if known and name not in known)
    if unknown:
        raise WorkerContractError(
            "runtime_protocol_failed",
            f"{field_name} references unknown PoB config var(s): " + ", ".join(unknown),
        )
    normalized: dict[str, bool | int | float | str] = {}
    for name, raw in payload.items():
        if isinstance(raw, (bool, int, float, str)):
            normalized[name] = raw
        else:
            raise WorkerContractError(
                "runtime_protocol_failed",
                f"{field_name}.{name} must be a boolean, number, or string.",
            )
    return normalized


def _number_xml(value: int | float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _run_worker(args: argparse.Namespace) -> int:
    runtime_root = Path(args.runtime_root).resolve(strict=False)
    session_root = Path(args.session_root).resolve(strict=False)
    wrapper_path = Path(args.wrapper_path).resolve(strict=False)
    reopen_source = None if args.reopen_source is None else Path(args.reopen_source).resolve(strict=False)

    os.environ["POB_RUNTIME_ROOT"] = runtime_root.as_posix()
    os.environ["POB_HEADLESS_USER_PATH"] = session_root.as_posix()
    os.environ["POB_HEADLESS_WORKDIR"] = session_root.as_posix()
    os.environ.setdefault("CI", "1")

    runtime = HeadlessLuaRuntime(runtime_root=runtime_root, session_root=session_root, wrapper_path=wrapper_path)
    try:
        if args.session_role == "reopen":
            if reopen_source is None or not reopen_source.is_file():
                raise WorkerContractError("reopen_source_missing", f"Missing reopen source XML: {reopen_source}")
            runtime.load_reopen_source(reopen_source.read_text(encoding="utf-8"))

        _write_message({"status": "ready"})

        while True:
            command = _read_json_line()
            if command is None:
                return 0
            if not command:
                continue

            action = command.get("action")
            global _flask_flags_tracker
            _flask_flags_tracker = (runtime.flask_flags_fingerprint, runtime.flask_flags_fingerprint()) if action in _FLASK_DERIVING_ACTIONS else None
            try:
                if action == "create_blank_build":
                    runtime.create_blank_build()
                    _success()
                    continue
                if action == "parse_mods":
                    _success(result=runtime.parse_mods(command.get("request") or {}))
                    continue
                if action == "uniques":
                    _success(result=runtime.uniques(command.get("request") or {}))
                    continue
                if action == "read_config_options":
                    _success(result=runtime.read_config_options(command.get("request") or {}))
                    continue
                if action == "list_bench_mods":
                    _success(result=runtime.list_bench_mods(command.get("request") or {}))
                    continue
                if action == "read_tree_light":
                    _success(result=runtime.read_tree_light(command.get("request") or {}))
                    continue
                if action == "convert_tree":
                    _success(result=runtime.convert_tree(command.get("request") or {}))
                    continue
                if action == "read_config_inputs":
                    _success(result=runtime.read_config_inputs(command.get("request") or {}))
                    continue
                if action == "unsupported_gems":
                    _success(result=runtime.unsupported_gems(command.get("request") or {}))
                    continue
                if action == "random_rares":
                    _success(result=runtime.random_rares(command.get("request") or {}))
                    continue
                if action == "equip_items":
                    _success(result=runtime.equip_items(command.get("request") or {}))
                    continue
                if action == "socket_jewels":
                    _success(result=runtime.socket_jewels(command.get("request") or {}))
                    continue
                if action == "cluster_graph":
                    _success(result=runtime.cluster_graph(command.get("request") or {}))
                    continue
                if action == "list_item_mods":
                    _success(result=runtime.list_item_mods(command.get("request") or {}))
                    continue
                if action == "craft_rare":
                    _success(result=runtime.craft_rare(command.get("request") or {}))
                    continue
                if action == "recraft":
                    _success(result=runtime.recraft(command.get("request") or {}))
                    continue
                if action == "trial_stats":
                    trial_payload = command.get("trial_payload")
                    if not isinstance(trial_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "trial_stats requires trial_payload to be an object.")
                    _success(result={"results": runtime.trial_stats(trial_payload)})
                    continue
                if action == "read_stats":
                    keys = command.get("keys")
                    if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
                        raise WorkerContractError("runtime_protocol_failed", "read_stats keys must be a list of strings or null.")
                    parts = command.get("parts")
                    if parts is not None and not (isinstance(parts, list) and all(isinstance(p, int) for p in parts)):
                        raise WorkerContractError("runtime_protocol_failed", "read_stats parts must be a list of integers or null.")
                    _success(result=runtime.read_stats(keys, parts, keep_flask_flags=command.get("keep_flask_flags") is True))
                    continue
                if action == "read_stats_uncapped":
                    keys = command.get("keys")
                    if keys is not None and not (isinstance(keys, list) and all(isinstance(k, str) for k in keys)):
                        raise WorkerContractError("runtime_protocol_failed", "read_stats_uncapped keys must be a list of strings or null.")
                    parts = command.get("parts")
                    if parts is not None and not (isinstance(parts, list) and all(isinstance(p, int) for p in parts)):
                        raise WorkerContractError("runtime_protocol_failed", "read_stats_uncapped parts must be a list of integers or null.")
                    _success(result=runtime.read_stats_uncapped(keys, parts))
                    continue
                if action == "read_active_skill_stats":
                    skill_ids = command.get("skill_ids")
                    keys = command.get("keys")
                    if not isinstance(skill_ids, list) or not all(isinstance(skill_id, str) and skill_id for skill_id in skill_ids):
                        raise WorkerContractError("runtime_protocol_failed", "read_active_skill_stats skill_ids must be a list of non-empty strings.")
                    if not isinstance(keys, list) or not all(isinstance(key, str) and key for key in keys):
                        raise WorkerContractError("runtime_protocol_failed", "read_active_skill_stats keys must be a list of non-empty strings.")
                    _success(result=runtime.read_active_skill_stats(skill_ids, keys))
                    continue
                if action == "read_mana_cost_warnings":
                    _success(result={"warnings": runtime.read_mana_cost_warnings()})
                    continue
                if action == "read_granted_passives":
                    _success(result={"node_ids": runtime.read_granted_passives()})
                    continue
                if action == "mutate_tree_nodes":
                    mutation_payload = command.get("mutation_payload")
                    if not isinstance(mutation_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "mutate_tree_nodes requires mutation_payload to be an object.")
                    _success(result=runtime.mutate_tree_nodes(mutation_payload))
                    continue
                if action == "load_build_xml":
                    xml_text = command.get("xml_text")
                    if not isinstance(xml_text, str) or not xml_text.strip():
                        raise WorkerContractError("runtime_protocol_failed", "load_build_xml requires non-empty xml_text.")
                    runtime.load_reopen_source(xml_text)
                    _success()
                    continue
                if action == "apply_identity_state":
                    identity_payload = command.get("identity_payload")
                    if not isinstance(identity_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "apply_identity_state requires identity_payload to be an object.")
                    runtime.apply_identity_state(identity_payload)
                    _success()
                    continue
                if action == "read_state":
                    _success(result=runtime.snapshot_state())
                    continue
                if action == "time_state_parts":
                    _success(result=runtime.time_state_parts())
                    continue
                if action == "read_calc_snapshot":
                    _success(result=runtime.snapshot_calc_packet())
                    continue
                if action == "read_node_power_report":
                    node_power_request = command.get("node_power_request")
                    if node_power_request is not None and not isinstance(node_power_request, dict):
                        raise WorkerContractError(
                            "runtime_protocol_failed",
                            "read_node_power_report requires node_power_request to be an object when provided.",
                        )
                    _success(result=runtime.read_node_power_report(node_power_request))
                    continue
                if action == "read_ascendancy_node_report":
                    _success(result=runtime.read_ascendancy_node_report())
                    continue
                if action == "equip_boots_item":
                    runtime.equip_boots_item()
                    _success()
                    continue
                if action == "apply_tree_state":
                    tree_payload = command.get("tree_payload")
                    if not isinstance(tree_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "apply_tree_state requires tree_payload to be an object.")
                    runtime.apply_tree_state(tree_payload)
                    _success()
                    continue
                if action == "apply_item_state":
                    item_payload = command.get("item_payload")
                    if not isinstance(item_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "apply_item_state requires item_payload to be an object.")
                    runtime.apply_item_state(item_payload)
                    _success()
                    continue
                if action == "flask_uptimes":
                    _success(result=runtime.flask_uptimes())
                    continue
                if action == "set_flasks_active":
                    flasks_payload = command.get("flasks_active")
                    if not isinstance(flasks_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "set_flasks_active requires flasks_active to be an object.")
                    runtime.set_flasks_active(flasks_payload)
                    _success()
                    continue
                if action == "apply_skill_state":
                    skill_payload = command.get("skill_payload")
                    if not isinstance(skill_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "apply_skill_state requires skill_payload to be an object.")
                    runtime.apply_skill_state(skill_payload)
                    _success()
                    continue
                if action == "checkpoint_config":
                    runtime.checkpoint_config()
                    _success()
                    continue
                if action == "rollback_config":
                    runtime.rollback_config()
                    _success()
                    continue
                if action == "apply_config_state":
                    config_payload = command.get("config_payload")
                    if not isinstance(config_payload, dict):
                        raise WorkerContractError("runtime_protocol_failed", "apply_config_state requires config_payload to be an object.")
                    runtime.apply_config_state(config_payload)
                    _success()
                    continue
                if action == "export_build_xml":
                    _success(result=runtime.export_build_xml(derive_flask_flags=True))
                    continue
                if action == "verify_pob_import_code_string":
                    import_code = command.get("import_code")
                    if not isinstance(import_code, str):
                        raise WorkerContractError(
                            "runtime_protocol_failed",
                            "verify_pob_import_code_string requires import_code to be a string.",
                        )
                    _success(result=runtime.verify_pob_import_code_string(import_code))
                    continue
                if action == "shutdown":
                    _success(termination="process_exit_observed", exit_code=0)
                    return 0
                raise WorkerContractError("runtime_protocol_failed", f"Unsupported worker action: {action}")
            except Exception as exc:  # pragma: no cover - fail-closed protocol surface
                _failure(exc)
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return _run_worker(args)
    except Exception as exc:  # pragma: no cover - startup failures stay explicit
        _failure(exc)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
