"""Measure generated rare gear on each author's prepared reference build.

The benchmark owns author preparation. This script restores that prepared author
state, clears only its equipped non-jewel/non-flask rares, and fills those slots
again. It therefore measures gear value without changing the author's tree, gems,
config, uniques, flasks, or jewels.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any, Callable, Iterable, Mapping
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from benchmark import KEYS, SETS, prepare_author  # noqa: E402
from fixture_gear_tiers import META_PREFIXES  # noqa: E402
from junkroan.optimizer.loot_gear import LootGear, ordered_slots  # noqa: E402
from junkroan.optimizer.rails import Rails  # noqa: E402
from junkroan.optimizer.wishlist_gear import WishlistGear, is_pure_es  # noqa: E402
from junkroan.pob.session import PobSession  # noqa: E402
from junkroan.report_format import human_duration  # noqa: E402

MAX_HIT_KEYS = (
    "PhysicalMaximumHitTaken",
    "FireMaximumHitTaken",
    "ColdMaximumHitTaken",
    "LightningMaximumHitTaken",
)
RESIST_KEYS = ("FireResist", "ColdResist", "LightningResist")
RESIST_OVERCAP_KEYS = ("FireResistOverCap", "ColdResistOverCap", "LightningResistOverCap")
DEFAULT_RESULTS = ROOT / "artifacts" / "runs" / "gear-transplant" / "results.json"
DEFAULT_REPORT = ROOT / "docs" / "research" / "2026-09-19-gear-transplant.md"


@dataclass(frozen=True, slots=True)
class RareSlot:
    """The original active rare's base and socket colours for a filler call."""

    base: str
    sockets: str | None = None


def active_items(xml: str) -> dict[str, str]:
    """The active item set's equipped slot -> raw item text, including uniques."""

    root = ET.fromstring(xml)
    items = root.find("Items")
    if items is None:
        return {}
    by_id = {item.get("id"): item.text or "" for item in items.findall("Item")}
    active = items.get("activeItemSet") or "1"
    item_set = next((entry for entry in items.findall("ItemSet") if entry.get("id") == active), None)
    slots = item_set.findall("Slot") if item_set is not None else items.findall("Slot")
    return {
        str(slot.get("name")): by_id[str(slot.get("itemId"))]
        for slot in slots
        if slot.get("name") and slot.get("itemId") not in (None, "0") and slot.get("itemId") in by_id
    }


def _item_lines(raw: str) -> list[str]:
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _rarity(raw: str) -> str:
    return next((line.split(":", 1)[1].strip().upper() for line in _item_lines(raw) if line.startswith("Rarity:")), "")


def _base(raw: str) -> str | None:
    lines = _item_lines(raw)
    return lines[2] if len(lines) >= 3 else None


def _sockets(raw: str) -> str | None:
    return next((line.split(":", 1)[1].strip() for line in _item_lines(raw) if line.startswith("Sockets:")), None)


def _mod_text(line: str) -> str:
    """PoB writes {tags:...}{prefix} in front of an explicit line; a person does not read that."""

    return re.sub(r"^(\{[^}]*\})+", "", line).strip()


def item_view(raw: str) -> dict[str, object]:
    """One finished item as a person compares it: base, implicit, every explicit line.

    The loot arm and the author have no structured mod list of their own, so both
    are read back out of the raw item text into the shape the template arm
    already reports (`wishlist_gear.items`).
    """

    lines = _item_lines(raw)
    start = next((index for index, line in enumerate(lines) if line.startswith("Implicits:")), None)
    count = int(lines[start].split(":", 1)[1]) if start is not None else 0
    implicits = lines[start + 1: start + 1 + count] if start is not None else []
    mods: list[dict[str, object]] = []
    for line in (lines[start + 1 + count:] if start is not None else []):
        if line.startswith(META_PREFIXES):
            continue
        mods.append({"line": _mod_text(line), "tier": None, "crafted": line.startswith("{crafted}")})
    return {
        "base": _base(raw) or "",
        "implicit": " / ".join(_mod_text(line) for line in implicits),
        "mods": mods,
        "raw": raw,
    }


def active_rare_slots(xml: str) -> dict[str, RareSlot]:
    """Only active equipment rares that can be replaced without touching protected gear.

    Flasks and jewels are deliberately excluded even if a fixture ever has a rare
    one: the measurement swaps the author's wearable rare equipment, not their
    flask or jewel surfaces. Weapon-swap items are not active gear.
    """

    out: dict[str, RareSlot] = {}
    for slot, raw in active_items(xml).items():
        if "Swap" in slot or slot.startswith("Flask") or "Jewel" in slot or "Abyssal" in slot:
            continue
        base = _base(raw)
        if _rarity(raw) == "RARE" and base:
            out[slot] = RareSlot(base=base, sockets=_sockets(raw))
    return out


def clear_rare_slots(pob: Any, slots: Mapping[str, RareSlot]) -> None:
    """Unequip exactly the rare equipment selected from the active item set."""

    pob.equip({slot: None for slot in slots})


def _finite(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(float(value)) else None


def safe_ratio(numerator: object, denominator: object) -> float | None:
    """A JSON-safe ratio; a missing, zero, or non-finite denominator has no ratio."""

    top, bottom = _finite(numerator), _finite(denominator)
    if top is None or bottom is None or bottom == 0:
        return None
    return top / bottom


CANDIDATE_ROWS_PER_LINE = 12
BASE_ROWS_PER_SLOT = 8


def _top_base_rows(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """The base the slot wears plus the best few it beat, in the screen's own order.

    D79 rows have no explicit rank and retain their violation/value ordering.
    Weapon rows include their payable effective-value rank, so this table shows
    the exact order the requirement-cost screen used.
    """

    rows = list(rows)
    def key(row: Mapping[str, object]) -> tuple[float, float, float]:
        rank = row.get("rank")
        if isinstance(rank, int):
            return (0.0, float(rank), 0.0)
        violation = _finite(row.get("violation"))
        value = _finite(row.get("value"))
        return (1.0, violation if violation is not None else float("inf"), -(value if value is not None else float("-inf")))

    keep = [row for row in rows if row.get("verdict") == "TAKEN" or row.get("requested")]
    for row in sorted(rows, key=key):
        if len(keep) >= BASE_ROWS_PER_SLOT:
            break
        if row not in keep:
            keep.append(row)
    return [{**row, "of_bases": len(rows)} for row in sorted(keep, key=key)]


def _top_candidate_rows(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """The taken candidate plus the best few refused ones, so a table stays readable."""

    rows = list(rows)
    scored = sorted((row for row in rows if _finite(row.get("after")) is not None),
                    key=lambda row: float(row["after"]), reverse=True)
    keep = [row for row in rows if row.get("taken")]
    for row in scored:
        if len(keep) >= CANDIDATE_ROWS_PER_LINE:
            break
        if row not in keep:
            keep.append(row)
    return [{**row, "of_candidates": len(rows)} for row in keep]


def stats_snapshot(stats: Mapping[str, object], objective) -> dict[str, object]:
    """The fixed metric surface reported for the author and each replacement set."""

    score = objective.score(stats)
    return {
        "value": _finite(stats.get(objective.maximize)),
        "feasible": score.feasible,
        "violation": _finite(score.violation),
        "life": _finite(stats.get("Life")),
        "total_ehp": _finite(stats.get("TotalEHP")),
        "max_hits": {key: _finite(stats.get(key)) for key in MAX_HIT_KEYS},
        "resists": {key: _finite(stats.get(key)) for key in RESIST_KEYS},
    }


def metric_row(slug: str, damage_mode: str, objective, author_stats: Mapping[str, object],
               loot_stats: Mapping[str, object], wishlist_stats: Mapping[str, object], *,
               seconds: Mapping[str, float]) -> dict[str, object]:
    """One JSON/report row for A (author), B (loot), and C (wishlist)."""

    author = stats_snapshot(author_stats, objective)
    loot = stats_snapshot(loot_stats, objective)
    wishlist = stats_snapshot(wishlist_stats, objective)
    return {
        "ok": True,
        "slug": slug,
        "damage_mode": damage_mode,
        "stat": objective.maximize,
        "a": author,
        "b_loot": loot,
        "c_wishlist": wishlist,
        "loot_ratio": safe_ratio(loot["value"], author["value"]),
        "wishlist_ratio": safe_ratio(wishlist["value"], author["value"]),
        "loot_life_ratio": safe_ratio(loot["life"], author["life"]),
        "wishlist_life_ratio": safe_ratio(wishlist["life"], author["life"]),
        "loot_ehp_ratio": safe_ratio(loot["total_ehp"], author["total_ehp"]),
        "wishlist_ehp_ratio": safe_ratio(wishlist["total_ehp"], author["total_ehp"]),
        "seconds": {key: float(value) for key, value in seconds.items()},
    }


def damage_mode(main_skill: str, stats: Mapping[str, object]) -> str:
    """A report grouping derived from the skill corpus, with PoB's DoT output as fallback."""

    from junkroan.optimizer.objective_select import is_minion_skill
    from junkroan.search.hypothesis import active_gems

    if is_minion_skill(main_skill):
        return "minion"
    tags = set((active_gems().get(main_skill.lower()) or {}).get("tag_keys") or ())
    total, dot = _finite(stats.get("TotalDPS")), _finite(stats.get("TotalDotDPS"))
    if dot is not None and dot > max(0.0, total or 0.0):
        return "DoT"
    if "attack" in tags:
        return "attack"
    return "spell"


def restore_prepared_author(pob: Any, state_xml: str) -> None:
    """Restore the byte-identical prepared author checkpoint before a gear model."""

    pob.load_xml(state_xml)
    # mean_parts is session-side state rather than XML, so restore it alongside XML.
    from junkroan.optimizer.random_parts import apply_mean_parts

    apply_mean_parts(pob)


def fill_model(pob: Any, prepared: Any, slots: Mapping[str, RareSlot], *, model: str, seed: int,
                loot_n: int | None, wishlist_item_level: int | None = None,
                weapon_open_lines: int | None = None, weapon_open_tier_positions: tuple[float, ...] | None = None,
                flexible: Mapping[str, bool] | None = None,
                log: Callable[[str], None]) -> tuple[dict, float, dict[str, str], Rails, dict[str, object]]:
    """Restore the author checkpoint, fill one model, and return its full stats."""

    restore_prepared_author(pob, prepared.state_xml)
    pure_es = bool(prepared.skeleton.pure_es) or is_pure_es(pob.stats(("Life", "EnergyShield", "ChaosInoculation")))
    unique_gear = {slot: pob.unique_item(name)["raw"] for slot, name in prepared.skeleton.uniques.items()}
    clear_rare_slots(pob, slots)
    started = time.perf_counter()
    bases = {slot: rare.base for slot, rare in slots.items()}
    sockets = {slot: rare.sockets for slot, rare in slots.items() if rare.sockets}
    if model == "loot":
        rails = prepared.rails
        LootGear(pob, prepared.objective, rails, log=log, uniques=unique_gear).fill(
            bases,
            sockets_by_slot=sockets,
            passes=2,
            n=loot_n if loot_n is not None else rails.gear.construction_best_of_n,
            seed=seed,
            bench=True,
        )
        detail: dict[str, object] = {}
    elif model == "wishlist":
        rails = prepared.rails
        if wishlist_item_level is not None or weapon_open_lines is not None or weapon_open_tier_positions is not None or flexible:
            rails = replace(
                rails,
                gear=replace(
                    rails.gear,
                    wishlist=replace(
                        rails.gear.wishlist,
                        **({"item_level": {"default": wishlist_item_level, "Weapon 1": wishlist_item_level, "Weapon 2": wishlist_item_level}} if wishlist_item_level is not None else {}),
                        **({"weapon_open_lines": weapon_open_lines} if weapon_open_lines is not None else {}),
                        **({"weapon_open_tier_positions": weapon_open_tier_positions} if weapon_open_tier_positions is not None else {}),
                        **(dict(flexible) if flexible else {}),
                    ),
                ),
            )
        gear = WishlistGear(pob, prepared.objective, rails, log=log, pure_es=pure_es, uniques=unique_gear)
        results = gear.fill(
            bases,
            sockets_by_slot=sockets,
            passes=2,
            seed=seed,
            bench=True,
        )
        results = gear.shopping_results()
        plan = gear.resistance_plan
        detail = {
            "resistance_shortfall": dict(plan.shortfall) if plan is not None else {},
            "resistance_overcap": dict(plan.overcap) if plan is not None else {},
            "open_or_craft_resistance_lines": sum(
                line.get("kind") == "resistance_craft"
                for result in results
                for line in result.shopping
            ),
            "extra_resistance_lines": sum(result.extra_resistance is not None for result in results),
            "items": {
                result.slot: {
                    "base": result.base,
                    "implicit": result.implicit,
                    # Every line of a hybrid mod, never just its first (D79 rule 7).
                    "mods": [{"line": mod.text, "tier": mod.tier, "attribute": mod.attribute, "gem_level": mod.gem_level}
                             for mod in result.affixes],
                    "bench": result.bench_line,
                }
                for result in results
            },
            "line_counts": {
                kind: sum(line.get("kind") == kind for result in results for line in result.shopping)
                for kind in ("life", "resistance_fixed", "extra_resistance", "resistance_craft", "attribute", "objective_line", "free_line")
            },
            "attribute_items": sum(
                any(mod.attribute for mod in result.affixes) or result.bench_attribute for result in results
            ),
            "gem_level_trials": [trial for result in results for trial in result.gem_level_trials],
            # The weapon's own per-line table: which candidate PoB took and why (D79 rules 2 and 5).
            "weapon_candidates": {
                result.slot: [
                    {**entry, "rows": _top_candidate_rows(entry.get("rows") or [])}
                    for entry in result.candidate_log
                    if entry.get("base") == result.base
                ]
                for result in results
                if result.slot.startswith("Weapon") and result.candidate_log
            },
            # The base screen behind each weapon: which bases PoB was offered (D73).
            "weapon_bases": {
                result.slot: _top_base_rows(result.base_log)
                for result in results
                if result.slot.startswith("Weapon") and result.base_log
            },
            "weapon_requirement_refills": list(gear.weapon_requirement_refills),
            # Template v4 (docs/specs/2026-09-22-template-v4-flexible-lines.md, requirement 4c):
            # moves tried/kept per kind and the loop's own seconds; {} when both switches are off.
            "flexible_report": dict(gear.flexible_report),
        }
    else:
        raise ValueError(f"unknown gear model {model!r}")
    final_xml = pob.export_xml()
    generated = {slot: raw for slot, raw in active_items(final_xml).items() if slot in slots}
    if model == "loot":
        # The loot arm keeps no structured mod list, so its finished items are read
        # back out of their raw text into the same shape the template arm reports.
        detail["items"] = {slot: item_view(generated[slot]) for slot in ordered_slots(generated)}
    for slot, item in (detail.get("items") or {}).items():
        item["raw"] = generated.get(slot)
    pob.equip({slot: None for slot in slots})
    empty_gear = pob.stats((*RESIST_KEYS, *RESIST_OVERCAP_KEYS))
    # Weapons first: PoB refuses a quiver in Weapon 2 while Weapon 1 is empty, and the
    # XML's own slot order is not weapon-first on every build (bleed_bow raised
    # "item is not valid for slot Weapon 2" here).
    pob.equip({slot: generated[slot] for slot in ordered_slots(generated)})
    equipped_gear = pob.stats((*RESIST_KEYS, *RESIST_OVERCAP_KEYS))
    pob.load_xml(final_xml)
    gear_only = {
        element: (float(equipped_gear.get(key) or 0.0) + float(equipped_gear.get(overcap) or 0.0)
                  - float(empty_gear.get(key) or 0.0) - float(empty_gear.get(overcap) or 0.0))
        for element, key, overcap in zip(("fire", "cold", "lightning"), RESIST_KEYS, RESIST_OVERCAP_KEYS)
    }
    detail["gear_only_resists"] = {
        element: value for element, value in gear_only.items()
    }
    detail["resistance_shortfall"] = {
        element: max(0.0, 75.0 - value) for element, value in gear_only.items()
    }
    detail["resistance_overcap"] = {
        element: max(0.0, value - 75.0) for element, value in gear_only.items()
    }
    detail["resists_capped_on_gear_alone"] = not any(detail["resistance_shortfall"].values())
    # The user reads PoBs: keep both finished builds as import codes.
    from junkroan.pob.session import encode_import_code

    detail["import_code"] = encode_import_code(final_xml)
    keys = tuple(dict.fromkeys((*KEYS, *prepared.objective.stat_keys)))
    return pob.stats(keys), time.perf_counter() - started, active_items(pob.export_xml()), rails, detail


def measure_reference(slug: str, *, seed: int = 1, loot_n: int | None = None,
                       wishlist_item_level: int | None = None,
                       weapon_open_lines: int | None = None, weapon_open_tier_positions: tuple[float, ...] | None = None,
                       flexible: Mapping[str, bool] | None = None,
                        log: Callable[[str], None] | None = None) -> dict[str, object]:
    """Prepare one author once, then transplant both gear models onto it."""

    emit = log or (lambda _line: None)
    started = time.perf_counter()
    try:
        with PobSession(run_id=f"gear-transplant-{slug}") as pob:
            prep_started = time.perf_counter()
            prepared = prepare_author(pob, slug, log=emit)
            prep_seconds = time.perf_counter() - prep_started
            author_stats = dict(prepared.author_lane) | pob.stats(("TotalDPS", "TotalDotDPS"))
            slots = active_rare_slots(prepared.state_xml)
            protected = {slot: raw for slot, raw in active_items(prepared.state_xml).items() if slot not in slots}
            uniques = {slot: raw for slot, raw in protected.items() if _rarity(raw) == "UNIQUE"}
            author_items = {
                slot: item_view(raw)
                for slot, raw in active_items(prepared.state_xml).items()
                if slot in slots
            }
            loot_stats, loot_seconds, loot_items, loot_rails, loot_detail = fill_model(
                pob, prepared, slots, model="loot", seed=seed, loot_n=loot_n,
                log=emit)
            wishlist_stats, wishlist_seconds, wishlist_items, wishlist_rails, wishlist_detail = fill_model(
                pob, prepared, slots, model="wishlist", seed=seed, loot_n=loot_n,
                wishlist_item_level=wishlist_item_level,
                weapon_open_lines=weapon_open_lines,
                weapon_open_tier_positions=weapon_open_tier_positions,
                flexible=flexible,
                log=emit)

        row = metric_row(
            slug,
            damage_mode(prepared.skeleton.main_link[0], author_stats),
            prepared.objective,
            author_stats,
            loot_stats,
            wishlist_stats,
            seconds={
                "prepare": prep_seconds,
                "loot": loot_seconds,
                "wishlist": wishlist_seconds,
                "total": time.perf_counter() - started,
            },
        )
        row.update({
            "seed": seed,
            "loot_n": loot_n if loot_n is not None else loot_rails.gear.construction_best_of_n,
            "wishlist_item_level": wishlist_item_level,
            "weapon_open_lines": weapon_open_lines,
            "weapon_open_tier_positions": weapon_open_tier_positions,
            "flexible": dict(flexible) if flexible else {},
            "rare_slots": {slot: {"base": rare.base, "sockets": rare.sockets} for slot, rare in slots.items()},
            "protected_items_unchanged": {
                "loot": {slot: loot_items.get(slot) == raw for slot, raw in protected.items()},
                "wishlist": {slot: wishlist_items.get(slot) == raw for slot, raw in protected.items()},
            },
            "unique_items_unchanged": {
                "loot": {slot: loot_items.get(slot) == raw for slot, raw in uniques.items()},
                "wishlist": {slot: wishlist_items.get(slot) == raw for slot, raw in uniques.items()},
            },
            "wishlist_gear": wishlist_detail,
            "loot_gear": loot_detail,
            # The rare slots the transplant replaced, as the author wore them.
            "author_items": author_items,
        })
        return row
    except Exception as exc:
        return {
            "ok": False,
            "slug": slug,
            "seed": seed,
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(),
            "seconds": {"total": time.perf_counter() - started},
        }


def run_references(slugs: Iterable[str], runner: Callable[[str], dict[str, object]]) -> list[dict[str, object]]:
    """Run every reference even if a caller unexpectedly raises for one of them."""

    rows = []
    for slug in slugs:
        try:
            rows.append(runner(slug))
        except Exception as exc:
            rows.append({"ok": False, "slug": slug, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()})
    return rows


def _median(values: Iterable[object]) -> float | None:
    valid = sorted(value for value in (_finite(v) for v in values) if value is not None)
    return float(median(valid)) if valid else None


def median_rows(rows: Iterable[Mapping[str, object]], *, label: str, predicate: Callable[[Mapping[str, object]], bool] | None = None) -> dict[str, object]:
    """The requested B/A and C/A medians for a set of successful measurements."""

    kept = [row for row in rows if row.get("ok") and (predicate is None or predicate(row))]
    # When a caller asks for several seeds, each reference remains one reference
    # in the all/smoke/mode medians instead of gaining extra weight.
    by_slug: dict[str, list[Mapping[str, object]]] = {}
    for row in kept:
        by_slug.setdefault(str(row.get("slug")), []).append(row)
    loot = [_median(row.get("loot_ratio") for row in same_slug) for same_slug in by_slug.values()]
    wishlist = [_median(row.get("wishlist_ratio") for row in same_slug) for same_slug in by_slug.values()]
    return {
        "group": label,
        "references": len(by_slug),
        "loot_ratio_median": _median(loot),
        "wishlist_ratio_median": _median(wishlist),
    }


def aggregate_medians(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    rows = list(rows)
    groups = [median_rows(rows, label="all")]
    smoke = set(SETS["smoke"])
    groups.append(median_rows(rows, label="smoke", predicate=lambda row: str(row.get("slug")) in smoke))
    for mode in ("attack", "spell", "minion", "DoT"):
        groups.append(median_rows(rows, label=mode, predicate=lambda row, mode=mode: row.get("damage_mode") == mode))
    return groups


def _percent(value: object) -> str:
    return "-" if _finite(value) is None else f"{float(value):.1%}"


def _number(value: object) -> str:
    return "-" if _finite(value) is None else f"{float(value):,.0f}"


def _violation(value: object) -> str:
    """Violations are fractions of a floor; 0.375 must not print as 0."""

    return "-" if _finite(value) is None else f"{float(value):.4g}"


def tier_positions(value: str) -> tuple[float, ...]:
    """Parse the repeatable per-rank weapon rail from one comma-separated value."""

    try:
        positions = tuple(float(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("weapon tier positions must be a comma-separated 0..1 list") from exc
    if not positions or any(position < 0.0 or position > 1.0 for position in positions):
        raise argparse.ArgumentTypeError("weapon tier positions must be a non-empty comma-separated 0..1 list")
    return positions


def render_items(title: str, items: Mapping[str, Mapping[str, object]]) -> list[str]:
    """One item set as a person reads it. The author, the loot and the template
    arms all render through here, in the same slot order, so the three sections
    line up slot for slot."""

    out = ["", f"## {title}"]
    if not items:
        return [*out, "- (none)"]
    for slot in ordered_slots(items):
        item = items[slot]
        out.append(f"- {slot}: {item.get('base') or '?'}" + (f"; implicit {item['implicit']}" if item.get("implicit") else ""))
        for mod in item.get("mods") or []:
            marks = "".join(mark for mark, flag in ((" [attribute]", mod.get("attribute")), (" [gem level]", mod.get("gem_level"))) if flag)
            tier = f"T{mod['tier']} " if mod.get("tier") else ""
            crafted = "{crafted} " if mod.get("crafted") else ""
            out.append(f"  - {crafted}{tier}{mod.get('line', '?')}{marks}")
        if item.get("bench"):
            out.append("  - {crafted} " + str(item["bench"]))
    return out


def markdown_report(rows: Iterable[Mapping[str, object]], medians: Iterable[Mapping[str, object]]) -> str:
    """Tables only: raw rows and the requested medians."""

    lines = [
        "| reference | seed | mode | stat | A | B loot | C wishlist | B/A | C/A | A feasible | B feasible | C feasible | B life/A | C life/A | B EHP/A | C EHP/A | time |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        if not row.get("ok"):
            lines.append(f"| {row.get('slug', '-')} | {row.get('seed', '-')} | | | FAILED: {row.get('error', 'unknown error')} | | | | | | | | | | | | | {human_duration(float((row.get('seconds') or {}).get('total') or 0.0))} |")
            continue
        a, b, c = row["a"], row["b_loot"], row["c_wishlist"]
        lines.append(
            f"| {row['slug']} | {row.get('seed', '-')} | {row['damage_mode']} | {row['stat']} | {_number(a['value'])} | {_number(b['value'])} | {_number(c['value'])} | "
            f"{_percent(row['loot_ratio'])} | {_percent(row['wishlist_ratio'])} | {a['feasible']} | {b['feasible']} | {c['feasible']} | "
            f"{_percent(row['loot_life_ratio'])} | {_percent(row['wishlist_life_ratio'])} | {_percent(row['loot_ehp_ratio'])} | {_percent(row['wishlist_ehp_ratio'])} | {human_duration(float(row['seconds']['total']))} |"
        )
    lines += ["", "| group | references | median B/A | median C/A |", "|---|---:|---:|---:|"]
    for summary in medians:
        lines.append(f"| {summary['group']} | {summary['references']} | {_percent(summary['loot_ratio_median'])} | {_percent(summary['wishlist_ratio_median'])} |")

    lines += ["", "| reference | A max hits phys/fire/cold/light | B max hits phys/fire/cold/light | C max hits phys/fire/cold/light | A resists fire/cold/light | B resists fire/cold/light | C resists fire/cold/light |", "|---|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        if not row.get("ok"):
            continue
        def joined(snapshot: Mapping[str, object], key: str) -> str:
            values = snapshot[key]
            return "/".join(_number(values[name]) for name in (MAX_HIT_KEYS if key == "max_hits" else RESIST_KEYS))

        lines.append(
            f"| {row['slug']} | {joined(row['a'], 'max_hits')} | {joined(row['b_loot'], 'max_hits')} | {joined(row['c_wishlist'], 'max_hits')} | "
            f"{joined(row['a'], 'resists')} | {joined(row['b_loot'], 'resists')} | {joined(row['c_wishlist'], 'resists')} |"
        )

    lines += ["", "| reference | wishlist gear shortfall fire/cold/light | wishlist final overcap fire/cold/light | capped on gear alone | extra resistance lines | open-or-craft resistance lines |", "|---|---:|---:|---|---:|---:|"]
    for row in rows:
        if not row.get("ok"):
            continue
        gear = row.get("wishlist_gear") or {}
        shortfall = gear.get("resistance_shortfall") or {}
        overcap = gear.get("resistance_overcap") or {}
        lines.append(
            f"| {row['slug']} | {'/'.join(_number(shortfall.get(element)) for element in ('fire', 'cold', 'lightning'))} | "
            f"{'/'.join(_number(overcap.get(element)) for element in ('fire', 'cold', 'lightning'))} | {gear.get('resists_capped_on_gear_alone', False)} | "
            f"{gear.get('extra_resistance_lines', 0)} | {gear.get('open_or_craft_resistance_lines', 0)} |"
        )

    kinds = ("life", "resistance_fixed", "extra_resistance", "resistance_craft", "attribute", "objective_line", "free_line")
    lines += ["", "| reference | C time | " + " | ".join(kinds) + " | items paying an attribute | gem-level lines kept / tried |",
              "|---|---:|" + "---:|" * (len(kinds) + 2)]
    for row in rows:
        if not row.get("ok"):
            continue
        gear = row.get("wishlist_gear") or {}
        counts = gear.get("line_counts") or {}
        trials = gear.get("gem_level_trials") or []
        lines.append(
            f"| {row['slug']} | {human_duration(float((row.get('seconds') or {}).get('wishlist') or 0.0))} | "
            + " | ".join(str(counts.get(kind, 0)) for kind in kinds)
            + f" | {gear.get('attribute_items', 0)} | {sum(1 for trial in trials if trial.get('kept'))} / {len(trials)} |"
        )

    for row in rows:
        if not row.get("ok"):
            continue
        # Three views of the same slots, in the same order, so a person can compare.
        lines += render_items(f"{row['slug']} author items", row.get("author_items") or {})
        lines += render_items(f"{row['slug']} loot items", (row.get("loot_gear") or {}).get("items") or {})
        lines += render_items(f"{row['slug']} wishlist items", (row.get("wishlist_gear") or {}).get("items") or {})

    for row in rows:
        if not row.get("ok"):
            continue
        bases = (row.get("wishlist_gear") or {}).get("weapon_bases") or {}
        for slot, entries in bases.items():
            lines += ["", f"## {row['slug']} {slot}: bases PoB was offered",
                       "| base | implicit | requirements | drop level | value | effective value | violation | shortfall / capacity | payable | lines | verdict |",
                       "|---|---|---:|---:|---:|---:|---:|---|---|---:|---|"]
            for entry in entries:
                shortfall = entry.get("shortfall") or {}
                payable = entry.get("payable")
                details = "; ".join(
                    f"{stat}: {value.get('needs', 0):g}/{value.get('capacity', 0):g}"
                    for stat, value in shortfall.items() if isinstance(value, Mapping)
                ) or "-"
                lines.append(
                    f"| {entry.get('base', '-')} | {entry.get('implicit') or '-'} | {entry.get('requirements') or '-'} | "
                    f"{_number(entry.get('drop_level'))} | {_number(entry.get('value'))} | {_number(entry.get('effective_value'))} | {_violation(entry.get('violation'))} | "
                    f"{details} | {'yes' if payable is True else ('no' if payable is False else '-')} | "
                    f"{entry.get('lines_needed') if entry.get('lines_needed') is not None else '-'} | "
                    f"{entry.get('verdict', '-')} |"
                )
            if entries:
                lines.append(f"| *of {entries[0].get('of_bases', len(entries))} bases* | | | | | | | | | | |")

        refills = (row.get("wishlist_gear") or {}).get("weapon_requirement_refills") or []
        if refills:
            lines += ["", f"## {row['slug']}: weapon requirement refills", "",
                      "| slot | from | unmet | to | refilled | reason |", "|---|---|---|---|---|---|"]
            for refill in refills:
                lines.append(
                    f"| {refill.get('slot', '-')} | {refill.get('from', '-')} | {refill.get('unmet', '-')} | "
                    f"{refill.get('to', '-')} | {refill.get('refilled', False)} | {refill.get('reason', '-')} |"
                )

    for row in rows:
        if not row.get("ok"):
            continue
        candidates = (row.get("wishlist_gear") or {}).get("weapon_candidates") or {}
        for slot, entries in candidates.items():
            lines += ["", f"## {row['slug']} {slot}: what PoB was offered per line",
                      "| line | candidate | value before | value after | violation before | violation after | verdict |",
                      "|---|---|---:|---:|---:|---:|---|"]
            for entry in entries:
                head = f"{entry['line']} {entry['kind']}"
                for candidate in entry.get("rows") or []:
                    lines.append(
                        f"| {head} | {candidate.get('candidate', '-')} | {_number(candidate.get('before'))} | {_number(candidate.get('after'))} | "
                        f"{_violation(candidate.get('before_violation'))} | {_violation(candidate.get('after_violation'))} | {candidate.get('reason', '-')} |"
                    )
                    head = ""
                if entry.get("rows"):
                    lines.append(f"| | *of {entry['rows'][0].get('of_candidates', len(entry['rows']))} candidates* | | | | | |")

    return "\n".join(lines) + "\n"


def json_safe(value: object) -> object:
    """Replace every non-finite float with None, at any depth.

    The results file is written with ``allow_nan=False`` so a reader never has
    to cope with ``Infinity``. A build with no weapon really does have infinite
    violation, and one such number used to kill the whole run AFTER every
    reference had been measured -- hours of PoB work thrown away by the encoder.
    """

    if isinstance(value, float):
        return _finite(value)
    if isinstance(value, Mapping):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


ARMS = (("wishlist_gear", ""), ("loot_gear", "-loot"))


def _row_without_import_code(row: Mapping[str, object]) -> dict[str, object]:
    """The import codes live in their own .pob.txt files; keep them out of the JSON."""

    out = dict(row)
    for key, _suffix in ARMS:
        gear = out.get(key)
        if isinstance(gear, Mapping) and "import_code" in gear:
            out[key] = {name: value for name, value in gear.items() if name != "import_code"}
    return out


def write_pob_files(rows: Iterable[Mapping[str, object]], directory: Path, prefix: str) -> list[Path]:
    """`<prefix>-<reference>.pob.txt` for the template build, `-loot` for the loot one."""

    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for row in rows:
        if not row.get("ok"):
            continue
        for key, suffix in ARMS:
            gear = row.get(key)
            code = gear.get("import_code") if isinstance(gear, Mapping) else None
            if not code:
                continue
            path = directory / f"{prefix}-{row['slug']}{suffix}.pob.txt"
            path.write_text(str(code), encoding="utf-8")
            written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="Tuadh reference slugs; none = new18 + core14")
    parser.add_argument("--set", dest="sets", choices=sorted(SETS), action="append", help="add a named reference set")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=1, help="repeat every selected reference for seed, seed+1, ...")
    parser.add_argument("--loot-n", type=int, help="override loot construction best-of-N")
    parser.add_argument("--wishlist-ilvl", type=int, help="use one item level for every template slot (measurement only)")
    parser.add_argument("--weapon-open-lines", type=int, help="override the number of natural weapon template lines")
    parser.add_argument("--weapon-open-tier-position", "--weapon-open-tier-positions", dest="weapon_open_tier_positions", type=tier_positions,
                        help="override per-rank weapon positions as a comma-separated 0..1 list")
    # Template v4 (docs/specs/2026-09-22-template-v4-flexible-lines.md): three independent rails
    # switches, all ON in rails_default.json; each flag overrides the file (--no-... turns one off to
    # measure the pinned fixed template), --flexible-all / --no-flexible-all set all three at once.
    parser.add_argument("--quiver-weapon-shape", action=argparse.BooleanOptionalAction, default=None, help="requirement 1: a quiver takes the weapon's open+craft shape")
    parser.add_argument("--flexible-lines", action=argparse.BooleanOptionalAction, default=None, help="requirements 2-4: every armour/jewellery line is a PoB decision, then the move loop")
    parser.add_argument("--boots-movement-floor", action=argparse.BooleanOptionalAction, default=None, help="requirement 5: boots' movement line picks its own tier by PoB")
    parser.add_argument("--flexible-all", action=argparse.BooleanOptionalAction, default=None, help="all three switches above on (or, with --no-flexible-all, off) at once")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    slugs = list(args.slugs)
    for set_name in args.sets or []:
        slugs.extend(slug for slug in SETS[set_name] if slug not in slugs)
    slugs = slugs or [*SETS["new18"], *SETS["core14"]]
    env_positions = os.environ.get("JUNKROAN_WEAPON_OPEN_TIER_POSITIONS") or os.environ.get("JUNKROAN_WEAPON_OPEN_TIER_POSITION")
    weapon_open_tier_positions = args.weapon_open_tier_positions or (tier_positions(env_positions) if env_positions else None)
    flexible = {
        key: value
        for key, value in (
            ("quiver_weapon_shape", args.flexible_all if args.quiver_weapon_shape is None else args.quiver_weapon_shape),
            ("flexible_lines", args.flexible_all if args.flexible_lines is None else args.flexible_lines),
            ("boots_movement_floor", args.flexible_all if args.boots_movement_floor is None else args.boots_movement_floor),
        )
        if value is not None
    } or None  # only what a flag named: the rest stays as rails_default.json has it
    rows = []
    for seed in range(args.seed, args.seed + args.seeds):
        rows.extend(run_references(slugs, lambda slug, seed=seed: measure_reference(
            slug,
            seed=seed,
            loot_n=args.loot_n,
            wishlist_item_level=args.wishlist_ilvl,
            weapon_open_lines=args.weapon_open_lines,
            weapon_open_tier_positions=weapon_open_tier_positions,
            flexible=flexible,
            log=print,
        )))
    medians = aggregate_medians(rows)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    prefix = args.results.stem[: -len("-results")] if args.results.stem.endswith("-results") else args.results.stem
    for path in write_pob_files(rows, args.results.parent, prefix):
        print(f"pob: {path}")
    # The report first: a run that measured every reference must not lose its
    # tables to a serialization problem in the results file.
    args.report.write_text(markdown_report(rows, medians), encoding="utf-8")
    payload = json_safe({"rows": [_row_without_import_code(row) for row in rows], "medians": medians})
    args.results.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print(f"results: {args.results}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
