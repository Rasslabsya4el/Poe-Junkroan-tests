"""Normalized calculation snapshot publication from real headless PoB outputs."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .artifacts import sha256_bytes, validate_token, write_json
from .host_runtime import PoBHeadlessProofRun, PoBHeadlessSessionHandle
from .release_manager import utc_now_iso

NORMALIZED_CALC_SNAPSHOT_SUPPORTED_PATH = "pob_headless_normalized_calc_snapshot_v1"
NORMALIZED_CALC_SNAPSHOT_VERSION = "pob_headless_normalized_calc_snapshot.v1"
_DISPLAY_FAMILY_IDS = frozenset(
    {
        "offense",
        "requirements",
        "defense",
        "resources",
        "resistances",
        "movement",
        "utility",
        "other",
    }
)
_DISPLAY_SOURCE_OUTPUTS = frozenset({"main_output", "main_output.minion"})
_ELEMENTS = (
    ("fire", "Fire"),
    ("cold", "Cold"),
    ("lightning", "Lightning"),
)


class PoBHeadlessCalcSnapshotContractError(RuntimeError):
    """Raised when the normalized calc snapshot contract fails closed."""

    def __init__(self, failure_state: str, message: str) -> None:
        super().__init__(message)
        self.failure_state = failure_state


@dataclass(frozen=True, slots=True)
class PoBNormalizedCalcSnapshotPublication:
    """Published normalized calc snapshot for one headless PoB build state."""

    artifact_path: Path
    payload: dict[str, Any]
    raw_metrics_fingerprint: str
    input_fingerprint: str


def _fail(failure_state: str, message: str) -> None:
    raise PoBHeadlessCalcSnapshotContractError(failure_state, message)


def _path_string(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _stable_json_bytes(payload: Any, *, field_name: str) -> bytes:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail("invalid_calc_snapshot", f"{field_name} must be JSON-serializable and finite.")
        raise AssertionError from exc


def _json_clone(payload: Any, *, field_name: str) -> Any:
    return json.loads(_stable_json_bytes(payload, field_name=field_name).decode("utf-8"))


def _load_json_object(path: Path, *, failure_state: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        _fail(failure_state, f"JSON surface is missing: {path}")
        raise AssertionError from exc
    except json.JSONDecodeError as exc:
        _fail(failure_state, f"JSON surface is not valid JSON: {path}")
        raise AssertionError from exc
    if not isinstance(payload, dict):
        _fail(failure_state, f"JSON surface must decode to an object: {path}")
    return payload


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("invalid_calc_snapshot", f"{field_name} must be an object.")
    return dict(value)


def _require_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_calc_snapshot", f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_string_array(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_calc_snapshot", f"{field_name} must be an array.")
    normalized: list[str] = []
    for index, entry in enumerate(value):
        normalized.append(_require_string(entry, f"{field_name}[{index}]"))
    return normalized


def _normalize_scalar(value: Any, field_name: str) -> str | float | bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            _fail("unsupported_calc_field", f"{field_name} must be finite.")
        return numeric
    if isinstance(value, str):
        return value
    _fail("unsupported_calc_field", f"{field_name} must stay scalar, not {type(value).__name__}.")
    raise AssertionError("unreachable")


def _normalize_output_map(value: Any, field_name: str) -> dict[str, str | float | bool | None]:
    payload = _require_mapping(value, field_name)
    normalized: dict[str, str | float | bool | None] = {}
    for raw_key, raw_value in sorted(payload.items()):
        key = _require_string(raw_key, f"{field_name}.<key>")
        normalized[key] = _normalize_scalar(raw_value, f"{field_name}.{key}")
    return normalized


def _normalize_config_summary(value: Any, *, lane: str, config_set_id: str) -> dict[str, Any]:
    payload = _require_mapping(value, f"{lane}.config_summary")
    if _require_string(payload.get("config_set_id"), f"{lane}.config_summary.config_set_id") != config_set_id:
        _fail("invalid_calc_snapshot", f"{lane}.config_summary.config_set_id must match {lane}.config_set_id.")
    state_role = payload.get("state_role")
    if state_role is not None and _require_string(state_role, f"{lane}.config_summary.state_role") != lane:
        _fail("invalid_calc_snapshot", f"{lane}.config_summary.state_role must stay {lane!r}.")
    return _json_clone(payload, field_name=f"{lane}.config_summary")


def _normalize_display_families(value: Any, *, lane: str) -> dict[str, list[dict[str, Any]]]:
    payload = _require_mapping(value, f"{lane}.display_families")
    normalized: dict[str, list[dict[str, Any]]] = {}
    for actor_name in ("player", "minion"):
        raw_families = payload.get(actor_name, [])
        if not isinstance(raw_families, list):
            _fail("invalid_calc_snapshot", f"{lane}.display_families.{actor_name} must be an array.")
        families: list[dict[str, Any]] = []
        for family_index, raw_family in enumerate(raw_families):
            family = _require_mapping(raw_family, f"{lane}.display_families.{actor_name}[{family_index}]")
            family_id = _require_string(
                family.get("family_id"),
                f"{lane}.display_families.{actor_name}[{family_index}].family_id",
            )
            if family_id not in _DISPLAY_FAMILY_IDS:
                _fail(
                    "invalid_calc_snapshot",
                    f"{lane}.display_families.{actor_name}[{family_index}].family_id must be one of "
                    + ", ".join(sorted(_DISPLAY_FAMILY_IDS))
                    + ".",
                )
            raw_rows = family.get("rows", [])
            if not isinstance(raw_rows, list):
                _fail("invalid_calc_snapshot", f"{lane}.display_families.{actor_name}[{family_index}].rows must be an array.")
            rows: list[dict[str, Any]] = []
            for row_index, raw_row in enumerate(raw_rows):
                row = _require_mapping(
                    raw_row,
                    f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}]",
                )
                source_output = _require_string(
                    row.get("source_output"),
                    f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].source_output",
                )
                if source_output not in _DISPLAY_SOURCE_OUTPUTS:
                    _fail(
                        "invalid_calc_snapshot",
                        f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].source_output "
                        "must stay within the accepted display-output sources.",
                    )
                lower_is_better = row.get("lower_is_better", False)
                if not isinstance(lower_is_better, bool):
                    _fail(
                        "invalid_calc_snapshot",
                        f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].lower_is_better must be boolean.",
                    )
                rows.append(
                    {
                        "stat_key": _require_string(
                            row.get("stat_key"),
                            f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].stat_key",
                        ),
                        "label": _require_string(
                            row.get("label"),
                            f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].label",
                        ),
                        "value": _normalize_scalar(
                            row.get("value"),
                            f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].value",
                        ),
                        "overcap_value": _normalize_scalar(
                            row.get("overcap_value"),
                            f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].overcap_value",
                        ),
                        "warning": _normalize_scalar(
                            row.get("warning"),
                            f"{lane}.display_families.{actor_name}[{family_index}].rows[{row_index}].warning",
                        ),
                        "lower_is_better": lower_is_better,
                        "source_output": source_output,
                    }
                )
            families.append({"family_id": family_id, "rows": rows})
        normalized[actor_name] = families
    return normalized


def _require_numeric_output(output: Mapping[str, Any], key: str, *, lane: str, section_name: str) -> float:
    value = output.get(key)
    if value is None:
        _fail("missing_calc_field", f"{lane}.{section_name}.{key} is required for the normalized calc snapshot.")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be numeric.")
    numeric = float(value)
    if not math.isfinite(numeric):
        _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be finite.")
    return numeric


def _optional_numeric_output(output: Mapping[str, Any], key: str, *, lane: str, section_name: str) -> float | None:
    value = output.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be numeric when present.")
    numeric = float(value)
    if not math.isfinite(numeric):
        _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be finite when present.")
    return numeric


def _first_numeric_source(
    output: Mapping[str, Any],
    candidates: tuple[str, ...],
    *,
    lane: str,
    section_name: str,
    metric_name: str,
) -> tuple[float, str]:
    for key in candidates:
        value = output.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be numeric for {metric_name}.")
        numeric = float(value)
        if not math.isfinite(numeric):
            _fail("unsupported_calc_field", f"{lane}.{section_name}.{key} must be finite for {metric_name}.")
        return numeric, f"{section_name}.{key}"
    _fail(
        "missing_calc_field",
        f"{lane} requires one of {', '.join(candidates)} to derive metric {metric_name!r}.",
    )
    raise AssertionError("unreachable")


def _add_optional_metric(
    metrics: dict[str, float],
    metric_sources: dict[str, str],
    *,
    metric_name: str,
    output: Mapping[str, Any],
    key: str,
    lane: str,
    section_name: str,
    transform: Any = None,
) -> None:
    numeric = _optional_numeric_output(output, key, lane=lane, section_name=section_name)
    if numeric is None:
        return
    if transform is not None:
        numeric = float(transform(numeric))
    metrics[metric_name] = float(numeric)
    metric_sources[metric_name] = f"{section_name}.{key}"


def _cap_entry(*, current: float, cap: float, overcap: float, total: float | None = None) -> dict[str, Any]:
    return {
        "current": float(current),
        "cap": float(cap),
        "missing_to_cap": float(max(0.0, cap - current)),
        "overcap": float(max(0.0, overcap)),
        "uncapped_total": None if total is None else float(total),
        "is_capped": bool(current >= cap),
        "near_cap": bool(max(0.0, cap - current) <= 5.0),
    }


def _requirement_entry(*, available: float, required: float) -> dict[str, Any]:
    shortfall = max(0.0, required - available)
    return {
        "available": float(available),
        "required": float(required),
        "shortfall": float(shortfall),
        "satisfied": bool(shortfall <= 0.0),
    }


def _build_metrics_and_sources(main_output: Mapping[str, Any], *, lane: str) -> tuple[dict[str, float], dict[str, str]]:
    metrics: dict[str, float] = {}
    metric_sources: dict[str, str] = {}

    damage_per_second, damage_source = _first_numeric_source(
        main_output,
        ("FullDPS", "CombinedDPS", "TotalDPS", "TotalDotDPS"),
        lane=lane,
        section_name="main_output",
        metric_name="damage_per_second",
    )
    effective_hit_pool = _require_numeric_output(main_output, "TotalEHP", lane=lane, section_name="main_output")
    fire_max_hit = _require_numeric_output(main_output, "FireMaximumHitTaken", lane=lane, section_name="main_output")
    cold_max_hit = _require_numeric_output(main_output, "ColdMaximumHitTaken", lane=lane, section_name="main_output")
    lightning_max_hit = _require_numeric_output(
        main_output,
        "LightningMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    movement_speed_percent = _require_numeric_output(
        main_output,
        "EffectiveMovementSpeedMod",
        lane=lane,
        section_name="main_output",
    )
    unreserved_mana = _require_numeric_output(main_output, "ManaUnreserved", lane=lane, section_name="main_output")

    metrics["damage_per_second"] = float(damage_per_second)
    metric_sources["damage_per_second"] = damage_source
    metrics["effective_hit_pool"] = float(effective_hit_pool)
    metric_sources["effective_hit_pool"] = "main_output.TotalEHP"
    metrics["max_hit_elemental"] = float(min(fire_max_hit, cold_max_hit, lightning_max_hit))
    metric_sources["max_hit_elemental"] = (
        "derived:min(main_output.FireMaximumHitTaken, main_output.ColdMaximumHitTaken, "
        "main_output.LightningMaximumHitTaken)"
    )
    metrics["movement_speed"] = float(1.0 + movement_speed_percent / 100.0)
    metric_sources["movement_speed"] = "derived:1 + main_output.EffectiveMovementSpeedMod / 100"
    metrics["unreserved_mana"] = float(unreserved_mana)
    metric_sources["unreserved_mana"] = "main_output.ManaUnreserved"

    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="full_dps",
        output=main_output,
        key="FullDPS",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="combined_dps",
        output=main_output,
        key="CombinedDPS",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="hit_dps",
        output=main_output,
        key="TotalDPS",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="dot_dps",
        output=main_output,
        key="TotalDotDPS",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="total_net_recovery",
        output=main_output,
        key="TotalNetRegen",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="physical_max_hit",
        output=main_output,
        key="PhysicalMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="fire_max_hit",
        output=main_output,
        key="FireMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="cold_max_hit",
        output=main_output,
        key="ColdMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="lightning_max_hit",
        output=main_output,
        key="LightningMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="chaos_max_hit",
        output=main_output,
        key="ChaosMaximumHitTaken",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="spell_suppression_chance",
        output=main_output,
        key="EffectiveSpellSuppressionChance",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="block_chance",
        output=main_output,
        key="EffectiveBlockChance",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="spell_block_chance",
        output=main_output,
        key="EffectiveSpellBlockChance",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="movement_speed_percent",
        output=main_output,
        key="EffectiveMovementSpeedMod",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="life_total",
        output=main_output,
        key="Life",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="mana_total",
        output=main_output,
        key="Mana",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="energy_shield",
        output=main_output,
        key="EnergyShield",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="ward",
        output=main_output,
        key="Ward",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="armour",
        output=main_output,
        key="Armour",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="evasion",
        output=main_output,
        key="Evasion",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="life_unreserved",
        output=main_output,
        key="LifeUnreserved",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="life_unreserved_percent",
        output=main_output,
        key="LifeUnreservedPercent",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="mana_unreserved_percent",
        output=main_output,
        key="ManaUnreservedPercent",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="life_regen_recovery",
        output=main_output,
        key="LifeRegenRecovery",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="mana_regen_recovery",
        output=main_output,
        key="ManaRegenRecovery",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="energy_shield_regen_recovery",
        output=main_output,
        key="EnergyShieldRegenRecovery",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="fire_resistance",
        output=main_output,
        key="FireResist",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="cold_resistance",
        output=main_output,
        key="ColdResist",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="lightning_resistance",
        output=main_output,
        key="LightningResist",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="chaos_resistance",
        output=main_output,
        key="ChaosResist",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="fire_resistance_overcap",
        output=main_output,
        key="FireResistOverCap",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="cold_resistance_overcap",
        output=main_output,
        key="ColdResistOverCap",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="lightning_resistance_overcap",
        output=main_output,
        key="LightningResistOverCap",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="chaos_resistance_overcap",
        output=main_output,
        key="ChaosResistOverCap",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="hit_chance",
        output=main_output,
        key="HitChance",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="crit_chance",
        output=main_output,
        key="CritChance",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="crit_multiplier",
        output=main_output,
        key="CritMultiplier",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="action_speed",
        output=main_output,
        key="Speed",
        lane=lane,
        section_name="main_output",
    )
    _add_optional_metric(
        metrics,
        metric_sources,
        metric_name="cooldown",
        output=main_output,
        key="Cooldown",
        lane=lane,
        section_name="main_output",
    )
    return dict(sorted(metrics.items())), dict(sorted(metric_sources.items()))


def _build_triage(
    main_output: Mapping[str, Any],
    warning_codes: list[str],
    *,
    lane: str,
) -> dict[str, Any]:
    cap_pressure: dict[str, Any] = {
        "elemental_resistances": {},
    }
    elemental_constraint_failures: list[str] = []
    elemental_overcaps: list[float] = []
    for element_name, prefix in _ELEMENTS:
        current = _optional_numeric_output(main_output, f"{prefix}Resist", lane=lane, section_name="main_output")
        total = _optional_numeric_output(main_output, f"{prefix}ResistTotal", lane=lane, section_name="main_output")
        overcap = _optional_numeric_output(main_output, f"{prefix}ResistOverCap", lane=lane, section_name="main_output") or 0.0
        missing = _optional_numeric_output(main_output, f"Missing{prefix}Resist", lane=lane, section_name="main_output") or 0.0
        if current is None:
            continue
        cap_pressure["elemental_resistances"][element_name] = _cap_entry(
            current=current,
            cap=current + missing,
            overcap=overcap,
            total=total if total is not None else current + overcap,
        )
        elemental_overcaps.append(overcap)
        if missing > 0:
            elemental_constraint_failures.append(f"uncapped_{element_name}_resistance")
    if elemental_overcaps:
        cap_pressure["elemental_resistance_min_overcap"] = float(min(elemental_overcaps))
        cap_pressure["elemental_resistances_solved"] = bool(not elemental_constraint_failures)

    chaos_current = _optional_numeric_output(main_output, "ChaosResist", lane=lane, section_name="main_output")
    if chaos_current is not None:
        chaos_overcap = _optional_numeric_output(main_output, "ChaosResistOverCap", lane=lane, section_name="main_output") or 0.0
        chaos_missing = _optional_numeric_output(main_output, "MissingChaosResist", lane=lane, section_name="main_output") or 0.0
        chaos_total = _optional_numeric_output(main_output, "ChaosResistTotal", lane=lane, section_name="main_output")
        cap_pressure["chaos_resistance"] = _cap_entry(
            current=chaos_current,
            cap=chaos_current + chaos_missing,
            overcap=chaos_overcap,
            total=chaos_total if chaos_total is not None else chaos_current + chaos_overcap,
        )

    suppression_current = _optional_numeric_output(
        main_output,
        "EffectiveSpellSuppressionChance",
        lane=lane,
        section_name="main_output",
    )
    if suppression_current is not None:
        cap_pressure["spell_suppression"] = _cap_entry(
            current=suppression_current,
            cap=100.0,
            overcap=_optional_numeric_output(
                main_output,
                "SpellSuppressionChanceOverCap",
                lane=lane,
                section_name="main_output",
            )
            or 0.0,
        )

    block_current = _optional_numeric_output(main_output, "EffectiveBlockChance", lane=lane, section_name="main_output")
    if block_current is not None:
        block_cap = _optional_numeric_output(main_output, "BlockChanceMax", lane=lane, section_name="main_output")
        block_overcap = _optional_numeric_output(main_output, "BlockChanceOverCap", lane=lane, section_name="main_output") or 0.0
        cap_pressure["block"] = _cap_entry(
            current=block_current,
            cap=block_cap if block_cap is not None else block_current + block_overcap,
            overcap=block_overcap,
        )

    spell_block_current = _optional_numeric_output(
        main_output,
        "EffectiveSpellBlockChance",
        lane=lane,
        section_name="main_output",
    )
    if spell_block_current is not None:
        spell_block_cap = _optional_numeric_output(
            main_output,
            "SpellBlockChanceMax",
            lane=lane,
            section_name="main_output",
        )
        spell_block_overcap = _optional_numeric_output(
            main_output,
            "SpellBlockChanceOverCap",
            lane=lane,
            section_name="main_output",
        ) or 0.0
        cap_pressure["spell_block"] = _cap_entry(
            current=spell_block_current,
            cap=spell_block_cap if spell_block_cap is not None else spell_block_current + spell_block_overcap,
            overcap=spell_block_overcap,
        )

    requirement_pressure = {
        "strength": _requirement_entry(
            available=_optional_numeric_output(main_output, "Str", lane=lane, section_name="main_output") or 0.0,
            required=_optional_numeric_output(main_output, "ReqStr", lane=lane, section_name="main_output") or 0.0,
        ),
        "dexterity": _requirement_entry(
            available=_optional_numeric_output(main_output, "Dex", lane=lane, section_name="main_output") or 0.0,
            required=_optional_numeric_output(main_output, "ReqDex", lane=lane, section_name="main_output") or 0.0,
        ),
        "intelligence": _requirement_entry(
            available=_optional_numeric_output(main_output, "Int", lane=lane, section_name="main_output") or 0.0,
            required=_optional_numeric_output(main_output, "ReqInt", lane=lane, section_name="main_output") or 0.0,
        ),
        "omniscience": _requirement_entry(
            available=_optional_numeric_output(main_output, "Omni", lane=lane, section_name="main_output") or 0.0,
            required=_optional_numeric_output(main_output, "ReqOmni", lane=lane, section_name="main_output") or 0.0,
        ),
    }

    saturation = {
        "movement_speed": {
            "ratio": float(
                1.0
                + (_optional_numeric_output(main_output, "EffectiveMovementSpeedMod", lane=lane, section_name="main_output") or 0.0)
                / 100.0
            ),
            "modifier_percent": float(
                _optional_numeric_output(main_output, "EffectiveMovementSpeedMod", lane=lane, section_name="main_output")
                or 0.0
            ),
        },
        "resources": {
            "life": {
                "current": float(
                    _optional_numeric_output(main_output, "LifeUnreserved", lane=lane, section_name="main_output") or 0.0
                ),
                "percent": float(
                    _optional_numeric_output(
                        main_output,
                        "LifeUnreservedPercent",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
                "empty_or_negative": bool(
                    (_optional_numeric_output(main_output, "LifeUnreserved", lane=lane, section_name="main_output") or 0.0)
                    <= 0.0
                ),
            },
            "mana": {
                "current": float(
                    _optional_numeric_output(main_output, "ManaUnreserved", lane=lane, section_name="main_output") or 0.0
                ),
                "percent": float(
                    _optional_numeric_output(
                        main_output,
                        "ManaUnreservedPercent",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
                "empty_or_negative": bool(
                    (_optional_numeric_output(main_output, "ManaUnreserved", lane=lane, section_name="main_output") or 0.0)
                    < 0.0
                ),
            },
            "energy_shield": {
                "current": float(
                    _optional_numeric_output(main_output, "EnergyShield", lane=lane, section_name="main_output") or 0.0
                ),
                "recovery_cap": float(
                    _optional_numeric_output(
                        main_output,
                        "EnergyShieldRecoveryCap",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
            },
        },
        "cost_pressure": {
            "mana": {
                "cost": float(
                    _optional_numeric_output(main_output, "ManaCost", lane=lane, section_name="main_output") or 0.0
                ),
                "cost_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "ManaPerSecondCost",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
                "recovery_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "ManaRegenRecovery",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
            },
            "life": {
                "cost": float(
                    _optional_numeric_output(main_output, "LifeCost", lane=lane, section_name="main_output") or 0.0
                ),
                "cost_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "LifePerSecondCost",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
                "recovery_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "LifeRegenRecovery",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
            },
            "energy_shield": {
                "cost": float(
                    _optional_numeric_output(main_output, "ESCost", lane=lane, section_name="main_output") or 0.0
                ),
                "cost_per_second": float(
                    _optional_numeric_output(main_output, "ESPerSecondCost", lane=lane, section_name="main_output")
                    or 0.0
                ),
                "recovery_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "EnergyShieldRegenRecovery",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
            },
            "rage": {
                "cost": float(
                    _optional_numeric_output(main_output, "RageCost", lane=lane, section_name="main_output") or 0.0
                ),
                "cost_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "RagePerSecondCost",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
                "recovery_per_second": float(
                    _optional_numeric_output(
                        main_output,
                        "RageRegenRecovery",
                        lane=lane,
                        section_name="main_output",
                    )
                    or 0.0
                ),
            },
        },
        "avoidance_overcaps": {
            "block": float(
                _optional_numeric_output(main_output, "BlockChanceOverCap", lane=lane, section_name="main_output") or 0.0
            ),
            "spell_block": float(
                _optional_numeric_output(
                    main_output,
                    "SpellBlockChanceOverCap",
                    lane=lane,
                    section_name="main_output",
                )
                or 0.0
            ),
            "spell_suppression": float(
                _optional_numeric_output(
                    main_output,
                    "SpellSuppressionChanceOverCap",
                    lane=lane,
                    section_name="main_output",
                )
                or 0.0
            ),
        },
        "damage_profile": {
            "hit_chance": float(
                _optional_numeric_output(main_output, "HitChance", lane=lane, section_name="main_output") or 0.0
            ),
            "missing_to_hit_cap": float(
                max(
                    0.0,
                    100.0
                    - (_optional_numeric_output(main_output, "HitChance", lane=lane, section_name="main_output") or 0.0),
                )
            ),
            "crit_chance": float(
                _optional_numeric_output(main_output, "CritChance", lane=lane, section_name="main_output") or 0.0
            ),
            "crit_multiplier": float(
                _optional_numeric_output(main_output, "CritMultiplier", lane=lane, section_name="main_output")
                or 0.0
            ),
        },
    }

    constraint_failures: list[str] = list(elemental_constraint_failures)
    if cap_pressure.get("chaos_resistance", {}).get("missing_to_cap", 0.0) > 0.0:
        constraint_failures.append("uncapped_chaos_resistance")
    for attribute_name, entry in requirement_pressure.items():
        if not entry["satisfied"]:
            constraint_failures.append(f"unmet_{attribute_name}_requirement")
    if saturation["resources"]["life"]["empty_or_negative"]:
        constraint_failures.append("life_unreserved_below_one")
    if saturation["resources"]["mana"]["empty_or_negative"]:
        constraint_failures.append("mana_unreserved_negative")
    for warning_code in warning_codes:
        if warning_code in {
            "life_cost_pool_exhausted",
            "mana_cost_pool_exhausted",
            "rage_cost_pool_exhausted",
            "energy_shield_cost_pool_exhausted",
            "life_percent_cost_pool_exhausted",
            "mana_percent_cost_pool_exhausted",
            "jewel_limit_exceeded",
            "socket_limit_exceeded",
        }:
            constraint_failures.append(warning_code)

    return {
        "cap_pressure": cap_pressure,
        "requirement_pressure": requirement_pressure,
        "saturation": saturation,
        "constraint_failures": sorted(set(constraint_failures)),
    }


def _normalize_section(raw_section: Any, *, lane: str) -> dict[str, Any]:
    section = _require_mapping(raw_section, lane)
    config_set_id = _require_string(section.get("config_set_id"), f"{lane}.config_set_id")
    if _require_string(section.get("state_role"), f"{lane}.state_role") != lane:
        _fail("invalid_calc_snapshot", f"{lane}.state_role must stay {lane!r}.")
    config_summary = _normalize_config_summary(section.get("config_summary"), lane=lane, config_set_id=config_set_id)
    main_output = _normalize_output_map(section.get("main_output"), f"{lane}.main_output")
    calcs_output = _normalize_output_map(section.get("calcs_output"), f"{lane}.calcs_output")
    display_families = _normalize_display_families(section.get("display_families", {}), lane=lane)
    warnings = _normalize_string_array(section.get("warnings"), f"{lane}.warnings")
    warning_codes = sorted(set(_normalize_string_array(section.get("warning_codes"), f"{lane}.warning_codes")))
    metrics, metric_sources = _build_metrics_and_sources(main_output, lane=lane)
    triage = _build_triage(main_output, warning_codes, lane=lane)

    return {
        "metrics": metrics,
        "calc_snapshot": {
            "config_set_id": config_set_id,
            "state_role": lane,
            "config_summary": config_summary,
            "metric_sources": metric_sources,
            "main_output": main_output,
            "calcs_output": calcs_output,
            "display_families": display_families,
            "warnings": warnings,
            "warning_codes": warning_codes,
            "triage": triage,
        },
    }


def build_normalized_calc_snapshot(
    raw_packet: Mapping[str, Any],
    *,
    run_id: str,
    build_id: str,
    build_source: str,
    evaluated_at: str,
    input_fingerprint: str,
    raw_metrics_fingerprint: str,
    artifact_root: str,
    pob_release: Mapping[str, Any],
) -> dict[str, Any]:
    """Normalize one raw calc packet into compare-compatible metrics plus calc snapshot."""

    payload = _require_mapping(raw_packet, "raw_packet")
    baseline = _normalize_section(payload.get("baseline"), lane="baseline")
    conditional = _normalize_section(payload.get("conditional"), lane="conditional")
    if baseline["calc_snapshot"]["config_set_id"] == conditional["calc_snapshot"]["config_set_id"]:
        _fail("invalid_calc_snapshot", "baseline and conditional calc snapshots must reference distinct config sets.")

    warnings = sorted(
        {
            *(
                f"baseline:{code}"
                for code in (
                    baseline["calc_snapshot"]["warning_codes"] + baseline["calc_snapshot"]["triage"]["constraint_failures"]
                )
            ),
            *(
                f"conditional:{code}"
                for code in (
                    conditional["calc_snapshot"]["warning_codes"]
                    + conditional["calc_snapshot"]["triage"]["constraint_failures"]
                )
            ),
        }
    )
    release = _require_mapping(pob_release, "pob_release")

    return {
        "baseline": baseline,
        "conditional": conditional,
        "metadata": {
            "run_id": validate_token(run_id, "run_id"),
            "build_id": validate_token(build_id, "build_id"),
            "build_source": _require_string(build_source, "build_source"),
            "evaluated_at": _require_string(evaluated_at, "evaluated_at"),
            "supported_path": NORMALIZED_CALC_SNAPSHOT_SUPPORTED_PATH,
            "input_fingerprint": _require_string(input_fingerprint, "input_fingerprint"),
            "raw_metrics_fingerprint": _require_string(raw_metrics_fingerprint, "raw_metrics_fingerprint"),
            "runtime_metadata": {
                "calc_snapshot_contract_version": NORMALIZED_CALC_SNAPSHOT_VERSION,
                "active_config_set_id": _require_string(
                    payload.get("active_config_set_id"),
                    "raw_packet.active_config_set_id",
                ),
                "baseline_config_set_id": baseline["calc_snapshot"]["config_set_id"],
                "conditional_config_set_id": conditional["calc_snapshot"]["config_set_id"],
            },
            "pob_release": {
                "repo": _require_string(release.get("repo"), "pob_release.repo"),
                "tag": _require_string(release.get("tag"), "pob_release.tag"),
                "asset_name": _require_string(release.get("asset_name"), "pob_release.asset_name"),
                "asset_sha256": _require_string(release.get("asset_sha256"), "pob_release.asset_sha256"),
                "lock_fingerprint": _require_string(release.get("lock_fingerprint"), "pob_release.lock_fingerprint"),
            },
            "artifact_root": _require_string(artifact_root, "artifact_root"),
        },
        "warnings": warnings,
    }


def _snapshot_summary(publication: PoBNormalizedCalcSnapshotPublication, *, build_id: str) -> dict[str, Any]:
    return {
        "supported_path": NORMALIZED_CALC_SNAPSHOT_SUPPORTED_PATH,
        "locator": _path_string(publication.artifact_path),
        "build_id": build_id,
        "raw_metrics_fingerprint": publication.raw_metrics_fingerprint,
        "input_fingerprint": publication.input_fingerprint,
        "baseline_config_set_id": publication.payload["baseline"]["calc_snapshot"]["config_set_id"],
        "conditional_config_set_id": publication.payload["conditional"]["calc_snapshot"]["config_set_id"],
        "warnings": list(publication.payload["warnings"]),
    }


def publish_normalized_calc_snapshot(
    run: PoBHeadlessProofRun,
    handle: PoBHeadlessSessionHandle,
    runtime_adapter: Any | None = None,
    *,
    build_id: str | None = None,
    build_source: str = "pob_headless_runtime",
    artifact_path: Path | None = None,
    evaluated_at: str | None = None,
    raw_packet: Mapping[str, Any] | None = None,
    export_xml: str | None = None,
) -> PoBNormalizedCalcSnapshotPublication:
    """Read, normalize, publish, and route one calc snapshot from the live headless runtime.

    Safe live-run order is: read the raw calc packet, export XML, seal the
    session, then publish from those captured inputs.
    """

    snapshot_build_id = build_id or run.request.pob_run_id
    if raw_packet is None:
        if runtime_adapter is None:
            _fail(
                "invalid_calc_snapshot",
                "publish_normalized_calc_snapshot(...) requires runtime_adapter or explicit raw_packet.",
            )
        raw_packet = _require_mapping(runtime_adapter.read_calc_snapshot(handle), "runtime_adapter.read_calc_snapshot(...)")
    else:
        raw_packet = _require_mapping(raw_packet, "raw_packet")
    if export_xml is None:
        if runtime_adapter is None:
            _fail(
                "invalid_calc_snapshot",
                "publish_normalized_calc_snapshot(...) requires runtime_adapter or explicit export_xml.",
            )
        export_xml = runtime_adapter.export_build_artifact(handle)
    if not isinstance(export_xml, str) or not export_xml.strip():
        _fail("invalid_calc_snapshot", "runtime_adapter.export_build_artifact(...) must return non-empty XML text.")

    raw_metrics_fingerprint = sha256_bytes(_stable_json_bytes(raw_packet, field_name="raw_packet"))
    input_fingerprint = sha256_bytes(export_xml.encode("utf-8"))
    payload = build_normalized_calc_snapshot(
        raw_packet,
        run_id=run.request.pob_run_id,
        build_id=snapshot_build_id,
        build_source=build_source,
        evaluated_at=evaluated_at or utc_now_iso(),
        input_fingerprint=input_fingerprint,
        raw_metrics_fingerprint=raw_metrics_fingerprint,
        artifact_root=_path_string(run.layout.run_root),
        pob_release=run.release_ref.to_dict(),
    )

    target_path = (
        run.layout.manifest_paths.live_control_result_path.parent / "normalized-calc-snapshot.json"
        if artifact_path is None
        else Path(artifact_path)
    )
    write_json(target_path, payload)
    publication = PoBNormalizedCalcSnapshotPublication(
        artifact_path=target_path.resolve(strict=False),
        payload=payload,
        raw_metrics_fingerprint=raw_metrics_fingerprint,
        input_fingerprint=input_fingerprint,
    )
    summary = _snapshot_summary(publication, build_id=snapshot_build_id)

    run_manifest = _load_json_object(run.layout.manifest_paths.run_manifest_path, failure_state="missing_durable_surface")
    run_manifest["normalized_calc_snapshot_locator"] = summary["locator"]
    run_manifest["normalized_calc_snapshot_supported_path"] = summary["supported_path"]
    run_manifest["normalized_calc_snapshot_raw_metrics_fingerprint"] = raw_metrics_fingerprint
    write_json(run.layout.manifest_paths.run_manifest_path, run_manifest)

    primary_proof = _load_json_object(run.layout.manifest_paths.primary_proof_path, failure_state="missing_durable_surface")
    primary_proof["calc_snapshot_assertion"] = {
        "status": "recorded",
        **summary,
    }
    write_json(run.layout.manifest_paths.primary_proof_path, primary_proof)

    live_control = _load_json_object(
        run.layout.manifest_paths.live_control_result_path,
        failure_state="missing_durable_surface",
    )
    normal_readback_summary = live_control.get("normal_readback_summary")
    if not isinstance(normal_readback_summary, dict):
        _fail("missing_durable_surface", "live-control-result.json normal_readback_summary must stay an object.")
    normal_readback_summary["normalized_calc_snapshot"] = dict(summary)
    live_control["normalized_calc_snapshot_locator"] = summary["locator"]
    write_json(run.layout.manifest_paths.live_control_result_path, live_control)

    handoff = _load_json_object(run.layout.manifest_paths.next_run_handoff_path, failure_state="missing_durable_surface")
    handoff["normalized_calc_snapshot"] = dict(summary)
    write_json(run.layout.manifest_paths.next_run_handoff_path, handoff)

    return publication


__all__ = [
    "NORMALIZED_CALC_SNAPSHOT_SUPPORTED_PATH",
    "NORMALIZED_CALC_SNAPSHOT_VERSION",
    "PoBHeadlessCalcSnapshotContractError",
    "PoBNormalizedCalcSnapshotPublication",
    "build_normalized_calc_snapshot",
    "publish_normalized_calc_snapshot",
]
