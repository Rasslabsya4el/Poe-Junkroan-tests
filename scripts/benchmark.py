"""Benchmark (ROADMAP Phase 6): rebuild every reference build from its own
skeleton (class, ascendancy nodes, keystones, main link, utility groups,
uniques, rare bases) through the full pipeline, and compare with the author.

Like with like: the author's build is re-scored under our conservative config
lane (the author's own config is dropped), floors are the author's own
life / EHP / maximum hits (so DPS cannot be bought by shedding defence), the tree
budget is the author's allocated count, gems and gear follow the rails.

Run:  python scripts/benchmark.py [slug ...] [--workers 5] [--seeds 3] [--gear template|loot]
(gear defaults to template; `wishlist` is its alias, both run the pipeline's wishlist mode)
References live in tests/fixtures/tuadh_329 (day-1 runs) and tests/fixtures/zizaran_<league>/early
(the early-game loadout of each hand-optimised Zizaran / Maxroll league starter of 3.25-3.29,
`--set ziz`, named z<league>_<slug> because a slug repeats across leagues); a bare slug is looked
up in that order, newest league first.
Seeds: the loot is the pipeline's randomness (best of N random rares per slot),
and one seed moves a reference by up to 20%; `--seeds 3` rebuilds every
reference with seeds 1..3 and the report gives the median and the spread.
Output: artifacts/benchmark/<stamp>/{report.md, results.json, rows/, <slug>.pob.txt}
        and PoB Builds/Junkroan/benchmark <slug>.xml
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import statistics
import sys
import threading
import time
import traceback
from datetime import datetime
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# scripts first, then src in front of it: scripts/junkroan.py (the CLI entry point) would otherwise
# shadow the `junkroan` package for anything that imports this module before importing junkroan
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from junkroan.optimizer.benchmark_rows import LOAD_SAMPLE_PERIOD_SECONDS, audit_errors, counted_row, last_stage_violation, non_fixed_point_audit_errors, not_at_fixed_point, time_under_load
from junkroan import pobbin
from junkroan.optimizer.trace import TRACE
import junkroan.optimizer.trace_600  # noqa: F401  (#600 classes: boots-with/without-30-movement)
from junkroan.optimizer.trace_output import trace_output_from_xml
from junkroan.optimizer.move_ledger import aggregate_move_tables, reentry_line, render_move_rows
from junkroan.pob import slot_budget
from junkroan.report_format import human_duration
from junkroan.optimizer import yield_probe
from junkroan.optimizer.yield_probe import BuildDeferred
from junkroan.runs.build_estimate import estimate_build
from junkroan.runs.yield_plan import read_yield_from_env
from junkroan.runs import hosts as runs_hosts

FIXTURES = ROOT / "tests" / "fixtures" / "tuadh_329"
# where a reference slug is looked up, in order: the Tuadh day-1 runs, then the early-game loadout of
# each Zizaran / Maxroll league starter, newest league first (tests/fixtures/zizaran_<league>/early,
# cut out of the authors' multi-loadout guide PoBs by scripts/extract_loadout.py).
FIXTURE_DIRS = (FIXTURES, *sorted((ROOT / "tests" / "fixtures").glob("zizaran_*/early"), reverse=True))
# the same slug exists in several leagues (champion_explosive_arrow in four of them), so a Zizaran
# reference is named z<league>_<slug>: "z327_champion_explosive_arrow". A bare slug still works and
# takes the newest league that has it.
_LEAGUE_SLUG = re.compile(r"^z(\d{3})_(.+)$")
KEYS = ("CombinedDPS", "FullDPS", "Life", "TotalEHP", "FireResist", "ColdResist", "LightningResist", "FireResistMax", "ColdResistMax", "LightningResistMax", "ChaosResist", "EffectiveMovementSpeedMod", "ManaUnreserved",
        "PhysicalMaximumHitTaken", "FireMaximumHitTaken", "ColdMaximumHitTaken", "LightningMaximumHitTaken")

# --set shortcuts (ROADMAP 7.1e): the 7.1 smoke set, the 14 references of runs C-E, the 18 of the D56 intake
SETS = {
    "smoke": ["cold_dot", "bleed_bow", "summon_raging_spirits", "impale_ballista", "stormbrand", "burning_arrow_snipe"],
    "core14": ["absolution_minions", "bleed_bow", "cold_dot", "hit_penance_brand", "ignite_penance_brand", "physical_dot", "poison_spectral_throw",
               "regular_viper_strike", "smite", "spark", "stormbrand", "summon_raging_spirits", "toxic_rain", "winter_orb"],
    "new18": ["arc_archmage", "archmage_volatile_dead", "bleed_perforate", "burning_arrow_snipe", "elemental_hit", "exsanguinate_mines", "impale_ballista",
              "impale_cyclone", "kinetic_bolt_wander", "kinetic_fusillade", "lightning_trap", "poison_spark", "pyroclast_mine", "shockwave_cyclone",
              "soulrend_chaos_dot", "spectral_shield_throw", "static_strike", "vd_spellslinger"],
    # the second reference set: hand-written, heavily optimised Zizaran / Maxroll league starters of
    # 3.25-3.29, each at the early-game loadout its manifest names (tests/fixtures/zizaran_*/early;
    # two builds of the intake carry no staged loadouts and are not here, see those folders' README).
    #
    # 31 loadouts were extracted, 26 are references: an author re-publishes a guide unchanged, and
    # the same build then appears under several leagues. Five such re-publications are trimmed, each
    # one the older copy of a pair PoB reads identically (level, allocated nodes, Life, TotalEHP,
    # CombinedDPS and FullDPS equal to the digit in the folders' stats.json, same allocated node set,
    # same items, same gems; what does differ is the declared tree version, PoB's own empty slots
    # -- "Graft 1/2", "Ring 3" -- and a gem rename, "Lesser Multiple Projectiles" -> "Multiple
    # Projectiles"). Only the newest league's copy is a reference; the files all stay in place:
    #   champion_explosive_arrow       327 = 328 = 329  -> z329 (z325 differs and stays)
    #   elementalist_lightning_conduit 326 = 327        -> z327
    #   gladiator_earthquake           326 = 327        -> z327 (z329 differs and stays)
    #   juggernaut_boneshatter         328 = 329        -> z329 (z327 differs and stays)
    # Counting them would have weighted those four builds 2-3x in the medians for nothing.
    "ziz": ["z325_berserker_ground_slam_autocry", "z325_champion_explosive_arrow", "z325_gladiator_eviscerate_retaliate", "z325_gladiator_lacerate",
            "z325_gladiator_spectral_shield_throw", "z325_hierophant_ice_nova_archmage", "z325_slayer_ground_slam", "z326_berserker_volcanic_fissure",
            "z326_chieftain_righteous_fire", "z326_elementalist_wave_of_conviction", "z326_necromancer_zombie_army_early",
            "z326_trickster_blight_of_contagion", "z327_assassin_poison_spark", "z327_elementalist_lightning_conduit", "z327_gladiator_earthquake",
            "z327_hierophant_storm_burst", "z327_juggernaut_boneshatter", "z327_necromancer_raise_spectre", "z327_slayer_earthshatter",
            "z328_hierophant_kinetic_fusillade", "z328_hierophant_shock_nova_archmage", "z329_champion_explosive_arrow", "z329_elementalist_winter_orb",
            "z329_gladiator_earthquake", "z329_juggernaut_boneshatter", "z329_occultist_essence_drain"],
}

# the re-publications trimmed out of SETS["ziz"] -> the reference that keeps the build (see the
# comment above). Kept as data so a test can hold the claim to the fixtures' own stats.json.
ZIZ_REPUBLISHED = {
    "z327_champion_explosive_arrow": "z329_champion_explosive_arrow",
    "z328_champion_explosive_arrow": "z329_champion_explosive_arrow",
    "z326_elementalist_lightning_conduit": "z327_elementalist_lightning_conduit",
    "z326_gladiator_earthquake": "z327_gladiator_earthquake",
    "z328_juggernaut_boneshatter": "z329_juggernaut_boneshatter",
}


def fixture_path(slug: str) -> Path:
    """The .pob.txt of a reference: "z327_juggernaut_boneshatter" names one league's file outright,
    a bare slug is searched through FIXTURE_DIRS in order (Tuadh first, newest league next)."""

    if match := _LEAGUE_SLUG.match(slug):
        path = ROOT / "tests" / "fixtures" / f"zizaran_{match[1]}" / "early" / f"{match[2]}.pob.txt"
        if path.is_file():
            return path
    for folder in FIXTURE_DIRS:
        if (path := folder / f"{slug}.pob.txt").is_file():
            return path
    raise FileNotFoundError(f"no fixture {slug}.pob.txt in {[str(d) for d in FIXTURE_DIRS]}")


def fixture_alias(path: Path) -> str:
    """The reference name of a fixture file: the bare slug, or z<league>_<slug> for a Zizaran one."""

    slug = path.name[: -len(".pob.txt")]
    folder = path.parent
    return f"z{folder.parent.name.split('_')[-1]}_{slug}" if folder.name == "early" and folder.parent.name.startswith("zizaran_") else slug


def fixture_slugs(*folders: Path) -> list[str]:
    """Every reference name of those fixture folders (default: all of them), sorted, no repeats."""

    return sorted({fixture_alias(p) for folder in (folders or FIXTURE_DIRS) for p in folder.glob("*.pob.txt")})


def lost_stages(stages: list[dict], *, threshold: float = 0.10) -> list[str]:
    """Stages that lost more than `threshold` of the value without lowering the violation (ROADMAP 7.1e):
    a stage may trade DPS for a floor, never for nothing. One line per such stage, for the report."""

    out = []
    for prev, cur in zip(stages, stages[1:]):
        if prev["value"] > 0 and cur["value"] < prev["value"] * (1.0 - threshold) and cur["violation"] >= prev["violation"] - 1e-9:
            out.append(f"{cur['name']} {prev['value']:,.0f} -> {cur['value']:,.0f} ({cur['value'] / prev['value'] - 1:+.0%})")
    return out


def author_floors(objective, author_raw: dict, author_lane: dict, rails, *, forced_keystones=()) -> dict[str, float]:
    """The floors a reference is rebuilt under: the rails' own, with the defence the author
    actually has put in their place, so DPS cannot be bought by shedding defence.

    #1044: with Chaos Inoculation among `forced_keystones` the author's Life is the budget the
    build must match in its own pool, so it is the EnergyShield floor and there is no Life floor;
    every other floor is the same.

    Life at 100% of the author's, no slack (D59): a 3% slack left 1-point life notables
    untaken. TotalEHP the same (D61, the user: B), measured on the author's build under OUR
    lane -- the same lane our build is judged under -- because the avoidance layers the
    author sold for damage (block, evasion, suppression) are in TotalEHP and in no other
    floor, and the frozen campaigns ran at 21-75% of theirs. Maximum hit taken keeps D53's
    factor and movement its 3% (the loot's best-of-200 boots reach 1.19x against an author
    at exactly 1.20x). Movement is read under OUR lane too (2026-09-26): impale_cyclone's author
    reaches 1.35 with his own config but 1.0665 under ours, so the old floor (1.164) was one the
    author himself failed; it was the only one of 58 references where raw and lane differ."""

    from junkroan.optimizer.objective import max_hit_floors
    from junkroan.optimizer.rails import pool_floor_for

    floors = {k: v for k, v in objective.floors.items() if not k.endswith("MaximumHitTaken")}
    floors["Life"] = author_raw["Life"]
    floors["TotalEHP"] = float(author_lane["TotalEHP"])
    floors.update(max_hit_floors(author_raw))
    movement = author_lane.get("EffectiveMovementSpeedMod") or author_raw.get("EffectiveMovementSpeedMod") or 1.0
    floors["EffectiveMovementSpeedMod"] = min(float(movement), rails.movement_speed_floor or 1.0) * 0.97
    return pool_floor_for(floors, forced_keystones)


def flag_main_group_for_full_dps(xml: str, count: int | None = None, main: str | None = None) -> str:
    """The author's XML with PoB's main socket group flagged "include in full DPS" (the author's other
    flags kept), so FullDPS is never 0 for the author when the benchmark compares on FullDPS; with
    `count`, the main gem's instance count is set to it (the author's typed-in count replaced by the
    same derivation our build gets, D57). The count goes on the gem named `main` (the skeleton's main
    skill), else on the group's first active gem: an author may socket a support first (Zizaran's
    Raise Spectre link starts with Minion Damage), and writing the count onto `gems[0]` then left the
    author's typed-in count on the spectre (20 = "4 Frostbearers x 5 Greater Volley projectiles" in
    the label) while the log said it was replaced."""

    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml)
    build = root.find("Build")
    skills = root.find("Skills")
    active = skills.get("activeSkillSet") or "1"
    skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active), None)
    groups = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
    main_idx = int(build.get("mainSocketGroup") or 1)
    if 1 <= main_idx <= len(groups):
        groups[main_idx - 1].set("includeInFullDPS", "true")
        gems = groups[main_idx - 1].findall("Gem")
        if count and gems:
            named = [g for g in gems if main and (g.get("nameSpec") or "").lower() == main.lower()]
            active = [g for g in gems if "Support" not in (g.get("gemId") or g.get("skillId") or "")]
            (named or active or gems)[0].set("count", str(int(count)))
    return ET.tostring(root, encoding="unicode")


def main_gem_count(xml: str, main: str) -> int:
    """The `count` the author typed on the main skill's gem (PoB's "4x Spectral Throw"); 1 when none."""

    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml)
    for gem in root.iter("Gem"):
        if (gem.get("nameSpec") or "").lower() == main.lower():
            try:
                return max(1, int(gem.get("count") or 1))
            except ValueError:
                return 1
    return 1


def normalize_author_gems(xml: str, rails) -> tuple[str, dict]:
    """The author's build with every gem written at the rails' level and quality, and a report of
    what that changed.

    Like with like (D23, CLAUDE.md "Rails worth remembering": *never compare a generated build with
    an author's on unequal gem levels*). Our build is always socketed at the rails' gems (level 18,
    quality 0, the main skill at the rails' own `main_skill_quality`), while an author writes
    whatever they were running: Zizaran's early loadouts are 20/20 throughout, and 20/20 alone
    inflated Cold DoT by 73% against its author before the gem rail existed. The Tuadh snapshots are
    day-1 runs, so the rails were derived from them and the change there is small -- but it is the
    same rule, and it is applied to every reference set.

    The main skill is the gem PoB's `mainActiveSkill` names in the main socket group
    (`main_active_gem_index`), the same head the skeleton takes, so the quality the author's main
    skill gets is the quality ours gets. Written on the XML rather than through `set_skills`, which
    replaces whole socket groups and would lose the author's slots, labels and flags. A level above
    a gem's own range is PoB's to clamp (Modules/CalcTools.lua `validateGemLevel`), exactly as it
    clamps ours.

    Returns (the XML, {"gems", "changed", "before": {"level", "quality"}, "after": ..., "line"})."""

    from statistics import median
    from xml.etree import ElementTree as ET

    from build_from_skeleton import main_active_gem_index
    from junkroan.pob.skill_facts import flat_reservation_aura_effect_ids
    from junkroan.search.hypothesis import active_gems

    root = ET.fromstring(xml)
    gems = [g for g in root.iter("Gem") if (g.get("nameSpec") or g.get("skillId") or "").strip()]
    before = {"level": float(median([float(g.get("level") or 0) for g in gems] or [0])),
              "quality": float(median([float(g.get("quality") or 0) for g in gems] or [0]))}

    main_gem = None
    build, skills = root.find("Build"), root.find("Skills")
    if build is not None and skills is not None:
        active = skills.get("activeSkillSet") or "1"
        skill_set = next((s for s in skills.findall("SkillSet") if s.get("id") == active), None)
        groups = skill_set.findall("Skill") if skill_set is not None else skills.findall("Skill")
        main_idx = int(build.get("mainSocketGroup") or 1)
        if 1 <= main_idx <= len(groups):
            live = [g for g in groups[main_idx - 1].findall("Gem") if g.get("enabled", "true") == "true" and (g.get("nameSpec") or "").strip()]
            head = main_active_gem_index([g.get("nameSpec") for g in live], int(groups[main_idx - 1].get("mainActiveSkill") or 1))
            main_gem = live[head] if head is not None else None

    flat_effects = flat_reservation_aura_effect_ids()
    effects_by_name = {name: str(rec.get("granted_effect_id") or "") for name, rec in active_gems().items()}
    changed = 0
    kept_low = 0
    for gem in gems:
        quality = rails.gems.main_quality if gem is main_gem else rails.gems.quality
        name = str(gem.get("nameSpec") or "").strip().lower()
        level = min(int(float(gem.get("level") or rails.gems.level)), rails.gems.level) if effects_by_name.get(name) in flat_effects else rails.gems.level
        if level < rails.gems.level:
            kept_low += 1
        if (gem.get("level"), gem.get("quality")) != (str(level), str(quality)):
            changed += 1
        gem.set("level", str(level))
        gem.set("quality", str(quality))
    after = {"level": float(rails.gems.level), "quality": float(rails.gems.quality)}
    line = (f"author gems normalized to the rails: level {before['level']:g}/{before['quality']:g} -> "
             f"{rails.gems.level}/{rails.gems.quality} on {changed} gems"
             + (f" ({kept_low} flat-reservation auras kept below the rail)" if kept_low else "")
             + (f" (main skill {main_gem.get('nameSpec')} quality {rails.gems.main_quality})" if main_gem is not None and rails.gems.main_quality != rails.gems.quality else ""))
    return ET.tostring(root, encoding="unicode"), {"gems": changed, "of": len(gems), "kept_low": kept_low, "changed": changed > 0, "before": before, "after": after, "line": line}


def _log_to(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    f = path.open("w", encoding="utf-8")

    def log(msg: str) -> None:
        f.write(msg + "\n")
        f.flush()

    return log


ABLATIONS = {  # --ablate NAME: the pipeline without one stage (ROADMAP "Later": ablation of the stage sequence)
    "rebuild": {"rebuild_tree": False},  # the six chain stages and their ablations are gone with D58 (the loop is the pipeline)
}


AUTHOR_REGIME = "flasks-uptime-100"  # the author's saved flasks' flags are derived from PoB's uptime calc (#575), like ours


def author_flask_count(xml: str) -> int:
    """How many Flask slots of the author's saved XML hold an item (0 = the reference has no flasks)."""

    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml)
    return sum(1 for slot in root.iter("Slot")
               if str(slot.get("name", "")).startswith("Flask ") and str(slot.get("itemId", "0")) not in ("", "0"))


def author_memo_path(cache_dir: str | None, slug: str, stat_override: str | None, *, cap_ailment_stacks: bool = True) -> Path | None:
    """Where the author's row for one reference is kept, so the other seeds of the same reference
    reuse it instead of measuring the same author again (7.1h). The memo lives inside the run's own
    output folder, so it can never be stale: a new run recomputes it."""

    suffix = ("" if cap_ailment_stacks else "-no-ailment-stack-caps") + f"-{AUTHOR_REGIME}"
    return Path(cache_dir) / f"{slug}{'-' + stat_override if stat_override else ''}{suffix}.json" if cache_dir else None


def read_author_memo(path: Path | None, *, tree_version: str | None = None, gem_rails: str | None = None) -> dict | None:
    """The author's row another seed of this reference already measured, or None. A half-written memo
    (the seed that measures it is still writing) reads as None, and this seed measures it itself.

    ``tree_version``: the passive tree the author's row is measured on since the benchmark converts
    the author's build to PoB's latest tree (`PobSession.convert_tree`). A memo without the field was
    written before that and holds a row scored on the author's own older tree, and one with another
    version belongs to another tree entirely: both are ignored rather than silently replayed.

    ``gem_rails``: "<level>/<quality>/<main quality>", the gems the author's row is measured on since
    the benchmark writes the rails' gems onto the author's build (`normalize_author_gems`). Same
    rule: a memo without the field carries a row scored on the author's own 20/20 gems, and one
    stamped with other rails answers another question."""

    if path is None or not path.is_file():
        return None
    try:
        memo = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(memo, dict):
        return None
    if tree_version is not None and memo.get("tree_version") != tree_version:
        return None
    if gem_rails is not None and memo.get("gem_rails") != gem_rails:
        return None
    return memo


def write_author_memo(path: Path | None, memo: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(memo), encoding="utf-8")
    _replace_retrying(tmp, path)  # atomic: a reader never sees a half-written memo


def _replace_retrying(tmp: Path, path: Path, *, attempts: int = 100, pause: float = 0.02) -> None:
    """os.replace that survives a reader holding the target open for a moment.

    On Windows replacing a file another process (a monitor, a test, progress.py) has open raises
    PermissionError; without a retry that one read kills the whole benchmark run (#24).
    """

    for attempt in range(attempts):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(pause)


def _write_text_atomic(path: Path, text: str) -> None:
    """Replace a text artifact without exposing a half-written version to a reader."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    _replace_retrying(tmp, path)


def code_commit(root: Path | None = None) -> str | None:
    """#748: the full hash of the code this process runs, or None when the tree has uncommitted changes to tracked
    files (untracked files and the junction dirs var/ vendor/ artifacts/ do not count) or git cannot say. A run
    snapshot is a git worktree of its pin, so plain `git rev-parse HEAD` inside it is the job's pin."""

    import subprocess

    top = str(root if root is not None else Path(__file__).resolve().parents[1])

    def git(*a: str) -> str | None:
        try:
            r = subprocess.run(["git", "-C", top, *a], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout if r.returncode == 0 else None

    head = (git("rev-parse", "HEAD") or "").strip()
    dirty = git("status", "--porcelain", "--untracked-files=no", "--", ".", ":(exclude)var", ":(exclude)vendor", ":(exclude)artifacts")
    if not re.fullmatch(r"[0-9a-f]{40}", head) or dirty is None or dirty.strip():
        return None
    return head


def provenance() -> dict:
    """#748: `commit` and `host` of one row (and of a fresh run's args.json)."""

    return {"commit": code_commit(), "host": slot_budget.current_host()}


def result_stem(row: dict) -> str:
    """The durable filename for one benchmark row. #1029: a `with <NAME>` variant (--force-keystone) is `-with-<name>`."""

    variant = row.get("variant") or ""
    if variant.startswith("with "):
        return f"{row['slug']}-s{row['seed']}-with-{variant[5:].replace(' ', '_').lower()}"
    return f"{row['slug']}-s{row['seed']}" + (f"-no-{variant[3:].replace(' ', '_').lower()}" if variant else "")


def variant_label(forbid_keystones=(), force_keystones=()) -> str:
    """#1029: a row's `variant`: `with <NAME>` under --force-keystone, `no <NAME>` for a D40 keystone variant, else ''."""

    if force_keystones:
        return f"with {', '.join(force_keystones)}"
    if forbid_keystones:
        return f"no {', '.join(forbid_keystones)}"
    return ""


def resolve_keystone_name(graph, name: str) -> tuple[int, str]:
    """#1029 `--force-keystone NAME`: the keystone's node id and its own name, for an exact case-insensitive match
    among the tree's keystones. An unknown name raises ValueError naming up to 5 close keystones."""

    keystones: dict[str, Any] = {}
    for node in graph.nodes.values():
        if node.kind == "keystone":
            keystones.setdefault(node.name.lower(), node)
    key = name.strip().lower()
    node = keystones.get(key)
    if node is None:
        close = [keystones[match].name for match in difflib.get_close_matches(key, sorted(keystones), n=5)]
        raise ValueError(f"unknown keystone {name!r}" + (f"; close names: {', '.join(close)}" if close else ""))
    return int(node.node_id), node.name


def add_force_keystones(skeleton, graph, names: list[str]) -> None:
    """#1029: each forced keystone's node id joins `skeleton.forced_nodes` once (prepare_author, after forbid_keystones):
    the request's own way to fix a passive node (#510). It is applied with the skeleton, put back after every tree reset
    and protected from removal by the tree optimizers; `skeleton.keystones` is none of the last (measured: a keystone
    put there was removed by 162 evaluated trials and missing from the final tree)."""

    for name in names:
        node_id = resolve_keystone_name(graph, name)[0]
        if node_id not in skeleton.forced_nodes:
            skeleton.forced_nodes.append(node_id)


def write_variants_plan(out_dir: Path, base_rows: int, base_done: int, variant_jobs: list[tuple[str, int, str, str]]) -> None:
    """`variants.json` (#580): the keystone variant rows (D40) planned so far, in the order they run, each with the
    base row it follows (`after`); `base_done` of `base_rows` base rows have ended, so `planned` is final only when
    they are equal. Variants off = `planned: []` with `base_done` moving."""

    planned = [
        {"slug": slug, "seed": seed, "variant": f"no {keystone}", "stem": result_stem({"slug": slug, "seed": seed, "variant": f"no {keystone}"}), "after": after}
        for slug, seed, keystone, after in variant_jobs
    ]
    plan = {"written": datetime.now().astimezone().isoformat(timespec="seconds"), "base_rows": base_rows, "base_done": base_done, "planned": planned}
    _write_text_atomic(out_dir / "variants.json", json.dumps(plan, indent=1))


def persisted_row(row: dict) -> dict:
    """The result payload without the large, separately persisted build exports."""

    return {key: value for key, value in row.items() if key not in ("xml", "import_code")}


def _pob_build_dir(stamp: str) -> Path:
    return Path.home() / "Documents" / "Path of Building" / "Builds" / "Junkroan" / f"benchmark {stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[9:]}"


def upload_code(code: str) -> str:
    return pobbin.upload_code(code)


def new_pobbin_run() -> pobbin.PobbinRun:
    run = pobbin.PobbinRun(lambda code: upload_code(code), pobbin.DEFAULT_CACHE)
    run.authors = {}  # slug -> author_pobbin_* fields, one upload per reference per run
    return run


def _author_code(slug: str) -> str | None:
    try:
        return fixture_path(slug).read_text(encoding="utf-8").strip() or None
    except Exception:
        return None


def _author_fields(pobbin_run: pobbin.PobbinRun, slug: str) -> dict:
    if slug not in pobbin_run.authors:
        code = _author_code(slug)
        fields: dict = {}
        if code:
            got = pobbin_run.upload(code, f"{slug}-author")
            fields = {f"author_{key}": value for key, value in got.items()}
        pobbin_run.authors[slug] = fields
    return pobbin_run.authors[slug]


def pobbin_retry_pass(out_dir: Path, results: list[dict], pobbin_run: pobbin.PobbinRun) -> int:
    """One retry pass at the run's end over every upload that failed; returns how many were fixed."""

    items: list[tuple[str, str]] = []
    for r in results:
        if r.get("ok") and r.get("import_code") and r.get("pobbin_error"):
            items.append((result_stem(r), r["import_code"]))
    author_codes: dict[str, str] = {}
    for slug in sorted({r["slug"] for r in results if r.get("author_pobbin_error")}):
        code = _author_code(slug)
        if code:
            author_codes[slug] = code
            items.append((f"{slug}-author", code))
    # #574: nothing waits on the parent after the pool closes, so the end pass waits out pobb.in's 429
    # (a fast run bursts its uploads); the write-time path never sleeps.
    plain = pobbin_run._upload
    pobbin_run._upload = _waiting_on_429(plain)
    try:
        fixed = pobbin_run.retry_pass(items)
    finally:
        pobbin_run._upload = plain

    def rewrite(r: dict) -> None:
        _write_text_atomic(
            out_dir / "rows" / f"{result_stem(r)}.json",
            json.dumps(persisted_row(r), indent=1, ensure_ascii=False),
        )

    count = 0
    for r in results:
        if r.get("ok") and r.get("import_code") and r.get("pobbin_error") and result_stem(r) in fixed:
            r.pop("pobbin_error")
            r.update(fixed[result_stem(r)])
            rewrite(r)
            count += 1
    for slug in author_codes:
        got = fixed.get(f"{slug}-author")
        if got is None:
            continue
        count += 1
        for r in results:
            if r["slug"] == slug and r.get("author_pobbin_error"):
                r.pop("author_pobbin_error")
                r.update({f"author_{key}": value for key, value in got.items()})
                rewrite(r)
    return count


BACKFILL_429_TRIES = 5
BACKFILL_429_WAIT_S = 60.0


def _waiting_on_429(upload):
    """#573/#574: pobb.in answers HTTP 429 after about 15 uploads in a row; wait it out (60 s, up to 5 tries)."""

    def wrapped(code: str) -> str:
        for attempt in range(BACKFILL_429_TRIES):
            try:
                return upload(code)
            except pobbin.HttpStatusError as e:
                if e.status != 429 or attempt == BACKFILL_429_TRIES - 1:
                    raise
                time.sleep(BACKFILL_429_WAIT_S)
        raise AssertionError("unreachable")

    return wrapped


def _upload_waiting_on_429(code: str) -> str:
    """#573: a backfill uploads a burst through the module's `upload_code`, waiting out 429s."""

    return _waiting_on_429(upload_code)(code)


def pobbin_backfill(out_dir: Path, tag: str | None = None) -> str:
    """#573: give a run's link-less ok rows their pobb.in links from the `<stem>.pob.txt` on disk.

    Rewrites `rows/<stem>.json` of each fixed row, then `results.json` from the rows' files (the run's
    row order kept). No PoB, `report.md` untouched. Returns the one summary line.
    """

    if not out_dir.is_dir():
        raise FileNotFoundError(f"benchmark run not found: {out_dir}")
    pobbin_run = new_pobbin_run()
    pobbin_run._upload = _upload_waiting_on_429
    uploaded = linked = errors = missing = authors = 0
    changed = False
    rows_by_stem: dict[str, dict] = {}
    for path in sorted((out_dir / "rows").glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        stem = path.stem
        rows_by_stem[stem] = row
        if row.get("pobbin_id"):
            linked += 1
            continue
        txt = out_dir / f"{stem}.pob.txt"
        if not row.get("ok") or not txt.is_file():
            missing += 1
            continue
        got = pobbin_run.upload(txt.read_bytes().decode("utf-8"), stem)
        known = set(pobbin_run.authors)
        author = _author_fields(pobbin_run, row["slug"])
        authors += row["slug"] not in known and "author_pobbin_id" in author
        row.pop("pobbin_error", None)
        row.update(got)
        row.pop("author_pobbin_error", None)
        row.update(author)
        if got.get("pobbin_id"):
            uploaded += 1
        else:
            errors += 1
        _write_text_atomic(path, json.dumps(persisted_row(row), indent=1, ensure_ascii=False))
        changed = True
    # results.json follows the rows' files whenever it differs from them, not only when a row changed now:
    # an in-flight run rewrites it from memory without links, and the pass after the run's end must fix that.
    results_path = out_dir / "results.json"
    order: list[str] = []
    old = None
    try:
        old = json.loads(results_path.read_text(encoding="utf-8"))
        old = old["rows"] if isinstance(old, dict) and "rows" in old else old
        order = [result_stem(r) for r in old]
        kept = {result_stem(r): r for r in old}
    except Exception:
        kept = {}
    order += [s for s in rows_by_stem if s not in order]
    merged = [persisted_row(rows_by_stem[s]) if s in rows_by_stem else kept[s] for s in order]
    if changed or merged != old:
        _write_text_atomic(results_path, json.dumps(merged, indent=1, ensure_ascii=False))
    name = tag or out_dir.name
    return (f"pobbin backfill {name}: {uploaded} uploaded, {linked} already linked, {errors} errors, "
            f"{missing} without a .pob.txt, authors {authors} uploaded")


# #956: the improvement loop stops on its counts (max passes, min gain, every move's count); no wall clock by default.
# `--loop-seconds <n>` given by hand is a net that fires (`loop_stop` = time) and makes the result depend on the machine.
LOOP_SECONDS_DEFAULT: float | None = None


def persist_completed_row(out_dir: Path, *, stamp: str, results: list[dict], row: dict,
                          total_builds: int, workers: int, seconds: float, gear_mode: str,
                          pobbin_run: pobbin.PobbinRun | None = None, plan: Callable[[], None] | None = None,
                          loop_seconds: float | None = LOOP_SECONDS_DEFAULT) -> None:
    """Persist one completed parent-side result and a readable snapshot of the run so far.

    Workers return their XML and import code to the parent. Keeping every write here means a
    killed process loses, at most, the build that was still running when it died.
    """

    results.sort(key=lambda r: (r["slug"], r.get("seed") or 0, r.get("variant") or ""))
    stem = result_stem(row)
    if row.get("ok"):
        _write_text_atomic(out_dir / f"{stem}.pob.txt", row["import_code"])
    if pobbin_run is not None:
        if row.get("ok") and row.get("import_code"):
            row.update(pobbin_run.upload(row["import_code"], stem))
        row.update(_author_fields(pobbin_run, row["slug"]))

    _write_text_atomic(
        out_dir / "rows" / f"{stem}.json",
        json.dumps(persisted_row(row), indent=1, ensure_ascii=False),
    )
    if plan is not None:  # #580: variants.json moves with the base row that just ended
        plan()
    _write_text_atomic(
        out_dir / "results.json",
        json.dumps([persisted_row(result) for result in results], indent=1, ensure_ascii=False),
    )

    # PoB's Builds folder has one current winner per reference / seed, as the old end-of-run
    # writer did. A later keystone variant replaces the base XML only when it is the better row.
    best_of = _best_rows(results)
    pob_dir = _pob_build_dir(stamp)
    if row.get("ok") and pob_dir.parent.parent.is_dir() and best_of.get((row["slug"], row["seed"])) is row:
        pob_dir.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(pob_dir / f"{row['slug']} s{row['seed']}.xml", row["xml"])

    partial = (len(results), total_builds) if len(results) < total_builds else None
    report = render_report(
        results,
        stamp=stamp,
        workers=workers,
        seconds=seconds,
        gear_mode=gear_mode,
        partial=partial,
        loop_seconds=loop_seconds,
    )
    _write_text_atomic(out_dir / "report.md", report)


@dataclass(slots=True)
class PreparedAuthor:
    """The benchmark's author state after every like-for-like normalization.

    The exported state is the checkpoint other measurements restore before changing
    gear. Keeping it here makes a reference comparison reuse the benchmark's one
    preparation sequence instead of creating a second, subtly different one.
    """

    state_xml: str
    skeleton: object
    rails: object
    objective: object
    author_raw: dict
    author_lane: dict
    choices: dict
    points: int
    stat: str
    author_ramp: float | None
    author_gems: dict
    author_note: str = ""


def prepare_author(pob, slug: str, *, log, stat_override: str | None = None,
                   author_cache: str | None = None, forbid_keystones: list[str] | None = None,
                   cap_ailment_stacks: bool = True, force_keystones: list[str] | None = None) -> PreparedAuthor:
    """Prepare one reference exactly as ``run_one`` scores its author.

    This is deliberately the benchmark's sequence: it is also used by the gear
    transplant measurement, whose question is about gear only and must leave the
    author's prepared tree, gems, uniques, config, flasks, and jewels untouched.
    """

    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.buff_gems import disable_unreliable_buff_gems_xml
    from junkroan.optimizer.judging import read_lanes, tune_choices, write_lanes
    from junkroan.optimizer.objective_select import counts_instances, objective_for
    from junkroan.optimizer.rails import Rails
    from junkroan.optimizer.ramp import ramp_seconds
    from junkroan.optimizer.random_parts import apply_mean_parts
    from junkroan.optimizer.tree_graph import TreeGraph, parse_allocated_from_xml
    from junkroan.pob.session import decode_import_code
    from junkroan.search.skeleton import derived_counts

    xml = decode_import_code(fixture_path(slug).read_text(encoding="utf-8").strip())
    # Like with like: the generated build never keeps a cooldown-limited buff free.
    xml, buff_gems_off = disable_unreliable_buff_gems_xml(xml)
    for why in buff_gems_off:
        log(f"author gem disabled (buff PoB would hold up for free): {why}")
    if stat_override == "FullDPS":
        xml = flag_main_group_for_full_dps(xml)

    rails = Rails.load()
    graph = TreeGraph.load()
    points = len([n for n in parse_allocated_from_xml(xml) if n in graph.allocatable])
    memo_path = author_memo_path(author_cache, slug, stat_override, cap_ailment_stacks=cap_ailment_stacks)
    tree_target = pob.latest_tree_version()
    gem_rails = f"{rails.gems.level}/{rails.gems.quality}/{rails.gems.main_quality}/flat-reservation-v1"
    memo = read_author_memo(memo_path, tree_version=tree_target, gem_rails=gem_rails)
    flask_slots = author_flask_count(xml)
    converted_once = False
    pre_convert_ascendancy_names: dict[int, str] = {}

    def load_author(xml_text: str) -> None:
        nonlocal converted_once
        pob.load_xml(xml_text)
        if not converted_once:
            # the fixture's own (pre-conversion) node names: an ascendancy node id can survive
            # `convert_tree` as a real id of an unrelated ascendancy or Atlas tree, so the name is
            # the only way to find its current-tree equivalent (skeleton_from_xml requirement 2).
            pre_convert_ascendancy_names.update(pob.ascendancy_node_names())
        conv = pob.convert_tree()
        if not converted_once or conv["lost_node_ids"]:
            log(f"author tree {conv['from']} -> {conv['to']}: {conv['nodes_after']} nodes, {len(conv['lost_node_ids'])} lost"
                + (f" {conv['lost_node_ids']}" if conv["lost_node_ids"] else ""))
            converted_once = True

    if memo is not None:
        load_author(memo["state_xml"])
        log(f"author row replayed from the memo of this run ({memo_path.name})")
    else:
        load_author(xml)

    # Our skeleton's ascendancy nodes are the author's nodes STILL allocated after the conversion:
    # a node the converted tree dropped has no path to the class start, and carrying it made
    # `set_tree` path through the missing prerequisite and end over the ascendancy limit (the lead,
    # 2026-09-23, after z325_berserker_ground_slam_autocry: 8 pre-conversion nodes -> 9 allocated).
    allocated_after_convert = set(parse_allocated_from_xml(pob.export_xml()))

    # The XML rewrite keeps the author's socket groups and item slots intact.
    xml, author_gems = normalize_author_gems(xml, rails)
    if author_gems["changed"] or author_gems["kept_low"]:
        log(author_gems["line"])
        if memo is None:
            load_author(xml)

    # PoB judges unsupported groups while it holds the author state; the XML provides
    # the skeleton's original surfaces, exactly as the benchmark did before extraction.
    skeleton = skeleton_from_xml(xml, pob=pob, log=log, rails=rails, ascendancy_node_names=pre_convert_ascendancy_names,
                                 allocated_after_convert=allocated_after_convert)
    if forbid_keystones:
        skeleton.forbid_keystones = list(forbid_keystones)
    if force_keystones:  # #1029: --force-keystone names, by node id, join the skeleton's forced nodes
        add_force_keystones(skeleton, graph, force_keystones)
    if apply_mean_parts(pob):
        log(f"author's {skeleton.main_link[0]} scored as the mean over parts {pob.mean_parts} (random element)")

    if memo is None and counts_instances(skeleton.main_link[0]):
        links = [list(skeleton.main_link)] + [list(g.gems) for g in skeleton.extra_groups if g.enabled]
        n = derived_counts(pob, [skeleton.main_link[0]], links=links).get(skeleton.main_link[0])
        if n:
            xml = flag_main_group_for_full_dps(xml, count=n, main=skeleton.main_link[0])
            load_author(xml)
            log(f"author's main group flagged for full DPS with the derived count {n} (their own count replaced)")
    elif memo is None and (typed := main_gem_count(xml, skeleton.main_link[0])) > 1:
        # #609: our search reads a non-instance skill once (count 1); the author's typed-in "4x Spectral Throw"
        # multiplies FullDPS (Calcs.lua: activeSkillCount) and nothing else, so lower the author to ours.
        xml = flag_main_group_for_full_dps(xml, count=1, main=skeleton.main_link[0])
        load_author(xml)
        log(f"author's main gem count {typed} lowered to 1, the count our search reads a non-instance skill with (#609)")

    author_raw = dict(memo["author_raw"]) if memo is not None else pob.stats(KEYS)
    if memo is None:
        # Current PoB unique variants and the conservative lane apply to both sides.
        normalized = {}
        for slot, name in skeleton.uniques.items():
            try:
                normalized[slot] = pob.unique_item(name)["raw"]
            except Exception as exc:
                log(f"author unique {name} ({slot}) kept as is: {type(exc).__name__}: {exc}")
        if normalized:
            pob.equip(normalized)
            after = pob.stats(KEYS)
            log(f"author uniques from PoB's database (current variant, mid roll) {sorted(normalized)}: CombinedDPS {author_raw['CombinedDPS']:,.0f} -> {after['CombinedDPS']:,.0f}, FullDPS {author_raw['FullDPS']:,.0f} -> {after['FullDPS']:,.0f} (author's own config)")
        derived = read_lanes(pob, cap_ailment_stacks=cap_ailment_stacks)
        # `log`, not a no-op: the lane write is where a fixture's own unknown config var is
        # dropped before it can fail `set_config`'s contract check (spec 2026-09-22, requirement 1).
        write_lanes(pob, skeleton, derived, log=log)

    objective = objective_for(rails, skeleton.main_link[0])
    if stat_override:
        objective = objective.replace(maximize=stat_override)
    stat = objective.maximize
    if memo is not None:
        author_choices, author_lane = dict(memo["choices"]), dict(memo["author_lane"])
    else:
        quiet = lambda _m: None  # noqa: E731 - the author's tuning logged nothing before it moved out of BuildPipeline
        author_choices = tune_choices(pob, skeleton, derived, objective=objective,
                                      write=lambda sk, lanes: write_lanes(pob, sk, lanes, log=quiet), log=quiet)
        author_lane = pob.stats((*KEYS, stat, *objective.stat_keys))
        write_author_memo(memo_path, {
            "state_xml": pob.export_xml(),
            "author_raw": author_raw,
            "author_lane": author_lane,
            "choices": author_choices,
            "tree_version": tree_target,
            "gem_rails": gem_rails,
        })
    author_ramp = ramp_seconds(author_lane, stat)
    objective = objective.replace(floors=author_floors(objective, author_raw, author_lane, rails, forced_keystones=force_keystones or ()))
    log(f"author raw {author_raw[stat]:,.0f} {stat}; under our lane {author_lane[stat]:,.0f} (choices {author_choices}); objective {objective.describe()}")
    return PreparedAuthor(
        state_xml=pob.export_xml(),
        skeleton=skeleton,
        rails=rails,
        objective=objective,
        author_raw=author_raw,
        author_lane=author_lane,
        choices=author_choices,
        points=points,
        stat=stat,
        author_ramp=author_ramp,
        author_gems=author_gems,
        author_note="" if flask_slots else "author: no flasks",
    )


class _LoadSampler:
    """#77: samples the host's mode and `others`-slot occupancy on a timer while one build runs.

    Runs on its own daemon thread so it never sits inside a PoB call; each tick reads
    ``config/hosts.json``'s live mode file and probes the slot locks, both plain file reads, no
    PoB session involved. A sampling failure (a mid-write budget file, a missing hosts config)
    is swallowed and simply contributes nothing for that tick, never raises.
    """

    def __init__(self, period: float = LOAD_SAMPLE_PERIOD_SECONDS) -> None:
        self._period = period
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._modes_seen: set[str] = set()
        self._busy_ticks = 0
        self._total_ticks = 0

    def _sample_once(self) -> None:
        try:
            host = slot_budget.current_host()
            modes = runs_hosts.read_modes()
            mode = (modes.get(host) or {}).get("mode") or "normal"
            self._modes_seen.add(str(mode))
        except Exception:
            pass
        try:
            # #117: every busy slot another run holds counts, whatever its role (`queue`
            # included) -- a time-budgeted build computes LESS in the same wall clock under
            # contention, not only slower, so a `queue`-role neighbour is exactly as much load as
            # an `others`-role one. `owner_key` tells a foreign run's slots from this build's own
            # (its `job` id when it has one, else the parent pid its worker pool shares).
            mine = slot_budget.current_owner_key()
            foreign_busy = any(slot_budget.owner_key(row) != mine for row in slot_budget.busy_slots())
        except Exception:
            return
        self._total_ticks += 1
        if foreign_busy:
            self._busy_ticks += 1

    def _loop(self) -> None:
        while not self._stop.wait(self._period):
            self._sample_once()

    def start(self) -> "_LoadSampler":
        self._sample_once()  # one immediate sample: a build shorter than one period is not blind
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return {
            "load_modes_seen": sorted(self._modes_seen) if self._modes_seen else None,
            "load_others_busy_share": (self._busy_ticks / self._total_ticks) if self._total_ticks else None,
        }


def _session_for(session, record_calls: str | None, log_path: str):
    """#569: with `--record-calls DIR` the session is wrapped in a RecordingPob writing
    `DIR/<stem>.calls.jsonl` (the row's own name stem, taken from its log); without it, the session itself."""

    if not record_calls:
        return session
    from junkroan.recording_pob import RecordingPob

    return RecordingPob(session, Path(record_calls) / f"{Path(log_path).stem}.calls.jsonl")


YIELD_KEEP_SECONDS = 600.0  # #621: a build with this much or less left runs to its end rather than give up its slot


def time_scale() -> float:
    """#621: `JUNKROAN_BENCH_TIME_SCALE` (default 1) = fake seconds per real second; only tests set it."""

    try:
        return float(os.environ.get("JUNKROAN_BENCH_TIME_SCALE") or 1.0)
    except ValueError:
        return 1.0


def make_yield_callback(*, stem: str, slug: str, out_dir: Path, loop_seconds: float | None, t0: float, bench_root: Path,
                        scale: float = 1.0, clock: Callable[[], float] = time.perf_counter, estimate: Callable = estimate_build) -> Callable[[str], None]:
    """The probe callback of one build (#621): when its stop file `<out_dir>/yield/<stem>.stop` exists it decides ONCE
    whether to keep running (little left, or in the fixed point check) or to raise `BuildDeferred`."""

    stop = out_dir / "yield" / f"{stem}.stop"
    kept = out_dir / "yield" / f"{stem}.kept"
    decided = False

    def callback(stage: str) -> None:
        nonlocal decided
        if decided or not stop.exists():
            return
        decided = True
        elapsed = (clock() - t0) * scale
        est, source = estimate(slug, out_dir, loop_seconds, bench_root)
        remaining = max(0.0, est - elapsed)
        if remaining <= YIELD_KEEP_SECONDS or "fixed point" in stage:
            try:
                kept.write_text("kept", encoding="utf-8")
            except OSError:
                pass
            print(f"kept {stem} to its end (about {human_duration(remaining)} was left; estimate: {source})", flush=True)
            return
        print(f"deferred {stem} after {human_duration(elapsed)} (about {human_duration(remaining)} left; estimate: {source})", flush=True)
        raise BuildDeferred(stage)

    return callback


def armed_build(slug: str, *, log_path: str, seed: int, variant: str, loop_seconds: float | None, body: Callable[[], dict],
                bench_root: Path | None = None) -> dict:
    """Run `body` with the yield probe armed (#621). The run folder is derived from `log_path`
    (`<out_dir>/logs/<stem>.log`). A build dropped at a probe returns `{"deferred": True, ...}`, never a row."""

    out_dir = Path(log_path).parent.parent
    stem = result_stem({"slug": slug, "seed": seed, "variant": variant})
    t0 = time.perf_counter()
    callback = make_yield_callback(stem=stem, slug=slug, out_dir=out_dir, loop_seconds=loop_seconds, t0=t0,
                                   bench_root=bench_root or (ROOT / "artifacts" / "benchmark"), scale=time_scale())
    yield_probe.arm(callback)
    try:
        return body()
    except BuildDeferred as exc:
        return {"deferred": True, "slug": slug, "seed": seed, "variant": variant, "stage": exc.stage}
    finally:
        yield_probe.disarm()


def run_one(slug: str, *, log_path: str, seed: int, gear_mode: str, construction: str = "classic", construction_only: bool = False, forbid_keystones: list[str] | None = None, tree_max_depth: int = 6, tree_max_trials: int = 300, ablate: str | None = None, stat_override: str | None = None, loop_seconds: float | None = LOOP_SECONDS_DEFAULT, cluster_candidates: bool = False, skip_inert: bool = False, fulldps_shortcut: bool = False, fixed_point_check: bool = True, author_cache: str | None = None, record_calls: str | None = None, force_keystones: list[str] | None = None) -> dict:
    # #621: main's explicit parameters stay explicit (#569's test reads `record_calls` off this signature)
    variant = variant_label(forbid_keystones or [], force_keystones or [])
    from junkroan.search.generator import SAVED_LISTS, write_saved_lists  # #978: the saved lists this build starts with
    SAVED_LISTS.clear()
    try:
        row = armed_build(slug, log_path=log_path, seed=seed, variant=variant, loop_seconds=loop_seconds,
                       body=lambda: _run_one_inner(slug, log_path=log_path, seed=seed, gear_mode=gear_mode, construction=construction,
                                                   construction_only=construction_only, forbid_keystones=forbid_keystones,
                                                   tree_max_depth=tree_max_depth, tree_max_trials=tree_max_trials, ablate=ablate,
                                                   stat_override=stat_override, loop_seconds=loop_seconds,
                                                   cluster_candidates=cluster_candidates, skip_inert=skip_inert,
                                                   fulldps_shortcut=fulldps_shortcut, fixed_point_check=fixed_point_check,
                                                   author_cache=author_cache, record_calls=record_calls, force_keystones=force_keystones))
    finally:
        if record_calls:
            write_saved_lists(Path(record_calls) / f"{Path(log_path).stem}.lists.json")
    if not row.get("deferred"):  # a deferred build has no row (#621)
        row.update(provenance())
    return row


def _run_one_inner(slug: str, *, log_path: str, seed: int, gear_mode: str, construction: str = "classic", construction_only: bool = False, forbid_keystones: list[str] | None = None, tree_max_depth: int = 6, tree_max_trials: int = 300, ablate: str | None = None, stat_override: str | None = None, loop_seconds: float | None = LOOP_SECONDS_DEFAULT, cluster_candidates: bool = False, skip_inert: bool = False, fulldps_shortcut: bool = False, fixed_point_check: bool = True, author_cache: str | None = None, record_calls: str | None = None, force_keystones: list[str] | None = None) -> dict:
    from junkroan.optimizer.objective import bossing_defence
    from junkroan.optimizer.pipeline import BuildPipeline
    from junkroan.pob.session import PobSession

    t0 = time.perf_counter()
    log = _log_to(Path(log_path))
    TRACE.reset()  # #498: this process runs one build at a time; the counters are this build's alone
    try:
        with PobSession(run_id=f"bench-{slug}-{os.getpid()}") as session:
            pob = _session_for(session, record_calls, log_path)
            prepared = prepare_author(
                pob,
                slug,
                log=log,
                stat_override=stat_override,
                author_cache=author_cache,
                forbid_keystones=forbid_keystones,
                force_keystones=force_keystones,
            )
            pipeline = BuildPipeline(pob, prepared.rails, objective=prepared.objective, log=log, construction=construction)
            kwargs = {}
            for name in (ablate or "").split(","):  # one or several stages off ("rebuild")
                kwargs.update(ABLATIONS.get(name.strip(), {}))
            sampler = _LoadSampler().start()  # #77: host mode / others-busy share while this build runs
            try:
                res = pipeline.run(prepared.skeleton, tree_points=prepared.points, seed=seed, gear_mode=gear_mode, tree_max_depth=tree_max_depth, tree_max_trials=tree_max_trials, loop_max_seconds=loop_seconds, cluster_candidates=cluster_candidates, skip_inert=skip_inert, fulldps_shortcut=fulldps_shortcut, fixed_point_check=fixed_point_check, construction_only=construction_only, **kwargs)
            finally:
                load_fields = sampler.stop()
        ours = res.final_stats
        return {
            "ok": True, "slug": slug, "seed": seed, "gear_mode": gear_mode, "variant": variant_label(forbid_keystones or [], force_keystones or []), "seconds": time.perf_counter() - t0, "points": prepared.points,
            **load_fields,
            "stat": prepared.stat, "author_raw": prepared.author_raw[prepared.stat], "author_lane": prepared.author_lane[prepared.stat], "author_ramp": prepared.author_ramp,
            # what the author was running before the gems were put on the rails (medians over their gems)
            "author_gem_levels": prepared.author_gems["before"], "author_gems_normalized": prepared.author_gems["gems"], "author_flat_reservation_auras_kept_low": prepared.author_gems["kept_low"],
            # the EHP column compares like with like: both sides under our lane, which is also the floor (D61)
            "author_life": prepared.author_raw["Life"], "author_ehp": prepared.author_lane["TotalEHP"], "author_ehp_raw": prepared.author_raw["TotalEHP"], "author_maxhit": bossing_defence(prepared.author_raw), "ours_maxhit": bossing_defence(ours),
            "author_mana_unreserved": prepared.author_lane.get("ManaUnreserved"), "ours_mana_unreserved": ours.get("ManaUnreserved"), "aura_levels": res.skeleton.aura_levels,
            "ours": ours.get(prepared.stat), "ours_optimistic": res.optimistic_stats.get(prepared.stat), "ours_life": ours.get("Life"), "ours_ehp": ours.get("TotalEHP"),
            "ours_ramp": ours.get("RampSeconds"), "ratio_lane": (ours.get(prepared.stat) or 0) / max(1.0, prepared.author_lane[prepared.stat]), "ratio_raw": (ours.get(prepared.stat) or 0) / max(1.0, prepared.author_raw[prepared.stat]),
            "keystones": res.keystones, "audit": [str(f) for f in res.audit], "audit_errors": sum(1 for f in res.audit if f.severity == "error"),
            "loop_stop": res.loop_stop,  # #38: "converged" or "time" (BuildPipeline.run, pipeline.py)
            "fixed_point_gain": res.fixed_point_gain, "fixed_point_note": res.fixed_point_note,
            "castability_calls": res.castability_calls, "castability_seconds": res.castability_seconds,
            "dropped_moves": res.dropped_moves, "moves": res.moves, "move_rows": res.moves,
            "considered": TRACE.considered(), "output": trace_output_from_xml(res.xml),
            "pob_calls": res.pob_calls, "tree_churn": res.tree_churn,
            "ledger_construction_value": res.ledger_construction_value,
            "ledger_value_before_final_lanes": res.ledger_value_before_final_lanes,
            "ledger_identity_error": res.ledger_identity_error,
            "stages": [{"name": s.name, "seconds": s.seconds, "value": s.score_value, "violation": s.violation, "notes": s.notes} for s in res.stages],
            "author_regime": AUTHOR_REGIME, "author_note": prepared.author_note,
            "summary": res.summary(), "import_code": res.import_code, "xml": res.xml,
        }
    except Exception as exc:  # one broken reference must not kill the benchmark
        return {"ok": False, "slug": slug, "seed": seed, "gear_mode": gear_mode, "variant": variant_label(forbid_keystones or [], force_keystones or []), "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(), "seconds": time.perf_counter() - t0}


# What the per-build table cannot be rendered without. The ledger's fields ("moves", "pob_calls",
# "tree_churn") are deliberately NOT here: a run finished before the ledger existed must rereport
# exactly as it did before, with its ledger sections simply absent.
REPORT_FIELDS = (
    "author_raw", "author_lane", "ours", "ratio_lane", "ratio_raw", "ours_life", "author_life",
    "ours_maxhit", "author_maxhit", "ours_ehp", "author_ehp", "ours_ramp", "keystones",
)


def _best_rows(results: list[dict]) -> dict[tuple[str, object], dict]:
    """Best finished variant per reference and seed, favoring rows that count."""

    best_of: dict[tuple[str, object], tuple[tuple, dict]] = {}
    for row in results:
        if not row.get("ok"):
            continue
        key = (str(row.get("slug")), row.get("seed"))
        rank = (counted_row(row), not non_fixed_point_audit_errors(row), -max(0.0, last_stage_violation(row)), row.get("ours") or 0)
        if key not in best_of or rank > best_of[key][0]:
            best_of[key] = (rank, row)
    return {key: row for key, (_rank, row) in best_of.items()}


def _medians_table(results: list[dict], best_of: dict[tuple[str, object], dict]) -> tuple[list[str], bool]:
    """The re-readable summary tables; return whether every display field exists."""

    ratios: dict[str, list[float]] = {}
    times: dict[str, list[float]] = {}
    for row in results:
        if best_of.get((str(row.get("slug")), row.get("seed"))) is row and counted_row(row) and isinstance(row.get("ratio_lane"), (int, float)):
            ratios.setdefault(str(row["slug"]), []).append(float(row["ratio_lane"]))
            if isinstance(row.get("seconds"), (int, float)):
                times.setdefault(str(row["slug"]), []).append(float(row["seconds"]))
    if not ratios:
        return ["", "No counted benchmark rows."], False
    lines = ["", "| reference | seeds | median ours / author (our lane) | min | max | median time |", "|---|---|---|---|---|---|"]
    medians = {}
    for slug, values in sorted(ratios.items()):
        values = sorted(values)
        medians[slug] = statistics.median(values)
        median_time = human_duration(statistics.median(times[slug])) if times.get(slug) else "-"
        lines.append(f"| {slug} | {len(values)} | {medians[slug]:.0%} | {values[0]:.0%} | {values[-1]:.0%} | {median_time} |")
    values = sorted(medians.values())
    lines += ["", f"per-reference medians, ours / author (our lane): median {statistics.median(values):.0%}, min {values[0]:.0%}, max {values[-1]:.0%}, references at or above 100%: {sum(1 for value in values if value >= 1.0)}/{len(values)}"]
    completed = [row for row in results if row.get("ok")]
    not_fixed = sum(not_at_fixed_point(row) for row in completed)
    lines.append(f"not at a fixed point (> 1%): {not_fixed} of {len(completed)} builds")
    return lines, all(all(field in row for field in REPORT_FIELDS) for row in results if row.get("ok"))


def _missing_report_fields(results: list[dict]) -> list[str]:
    return [field for field in REPORT_FIELDS if any(row.get("ok") and field not in row for row in results)]


def loop_net_line(results: list[dict], loop_seconds: float | None) -> str:
    """#569: how many rows the loop's clock (the safety net) stopped instead of the loop's own counts; #956: no clock unless `--loop-seconds` was given."""

    rows = [row for row in results if row.get("ok")]
    hit = [row for row in rows if row.get("loop_stop") == "time"]
    names = "".join(f": {', '.join(_row_name(row) for row in hit)}" if hit else "")
    net = "none given" if loop_seconds is None else human_duration(loop_seconds)
    return f"Loop safety net ({net}) hit: {len(hit)} of {len(rows)} rows{names}"


def _row_name(row: dict) -> str:
    return f"{row.get('slug')} s{row.get('seed')}" + (f" ({row['variant']})" if row.get("variant") else "")


def render_report(results: list[dict], *, stamp: str, workers: int | None = None, seconds: float | None = None,
                  gear_mode: str | None = None, rereport: bool = False,
                  partial: tuple[int, int] | None = None, loop_seconds: float | None = LOOP_SECONDS_DEFAULT) -> str:
    """Render a benchmark report from persisted results, without a PoB session."""

    best_of = _best_rows(results)
    medians, full_rows = _medians_table(results, best_of)
    if rereport and not full_rows:
        missing = ", ".join(_missing_report_fields(results))
        return "\n".join([
            "# Benchmark: references rebuilt from their own skeletons", "",
            f"{stamp}; rereported from results.json only. The stored rows lack fields needed for the per-build table: {missing}; rewritten median tables only.",
            *medians,
            "",
        ])
    lines = ([f"partial: {partial[0]} of {partial[1]} builds", ""] if partial else []) + ["# Benchmark: references rebuilt from their own skeletons", "",
             f"{stamp}; {len(results)} builds" + (f"; {human_duration(seconds)} on {workers} workers" if seconds is not None and workers is not None else "") + (f"; gear mode {gear_mode}" if gear_mode else "") + ". Author under our lane = the author's build with our conservative config; floors = the author's own life / EHP / maximum hits.", "",
             "| build | author (own config) | author (our lane) | ours | ours / author (our lane) | ours / author (raw) | life ours/author | max hit ours/author | EHP ours/author | mana ours/author | flat aura levels | ramp | fixed point | keystones | audit | time | loop stop |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    lost_rows: list[str] = []
    for row in results:
        name = f"{row.get('slug')} s{row.get('seed')}" + (f" ({row['variant']})" if row.get("variant") else "")
        if not row.get("ok"):
            lines.append(f"| {name} | FAILED: {row.get('error', 'unknown error')} | | | | | | | | | | | | | | | |")
            continue
        if row.get("author_note"):
            name += f" ({row['author_note']})"
        chosen = best_of.get((str(row.get("slug")), row.get("seed"))) is row
        if chosen and not counted_row(row):
            name += " (infeasible, not counted)" if last_stage_violation(row) > 1e-9 else " (audit error, not counted)"
        audit_findings = row.get("audit") or []
        audit = f"{len(audit_errors(row))} errors / {max(0, len(audit_findings) - len(audit_errors(row)))} warnings" if audit_findings or row.get("audit_errors") else "clean"
        if lost := lost_stages(row.get("stages") or []):
            audit += "; LOST " + "; ".join(lost)
            lost_rows.append(f"- {name}: " + "; ".join(lost))
        ramp = "-" if row.get("ours_ramp") is None else human_duration(float(row["ours_ramp"]))
        mana = f"{row.get('ours_mana_unreserved')}/{row.get('author_mana_unreserved')}" if row.get("ours_mana_unreserved") is not None else "-"
        aura_levels = ", ".join(f"{name} {level}" for name, level in sorted((row.get("aura_levels") or {}).items())) or "rail"
        fixed = f"{row['fixed_point_gain']:+.1%}" if row.get("fixed_point_gain") else (row.get("fixed_point_note") or "-")
        same_seed = [other for other in results if other.get("slug") == row.get("slug") and other.get("seed") == row.get("seed")]
        display = f"**{name}**" if chosen and len(same_seed) > 1 else name
        loop_stop_cell = (row.get("loop_stop") or "-") + ("*" if time_under_load(row) else "")
        lines.append(f"| {display} | {row['author_raw']:,.0f} | {row['author_lane']:,.0f} | {row['ours']:,.0f} | {row['ratio_lane']:.0%} | {row['ratio_raw']:.0%} | {row['ours_life']}/{row['author_life']} | {row.get('ours_maxhit') or 0:,.0f}/{row.get('author_maxhit') or 0:,.0f} | {row['ours_ehp']:,.0f}/{row['author_ehp']:,.0f} | {mana} | {aura_levels} | {ramp} | {fixed} | {', '.join(row['keystones']) or '-'} | {audit} | {human_duration(row.get('seconds'))} | {loop_stop_cell} |")
    lines.extend(medians)
    flagged = [row for row in results if row.get("ok") and time_under_load(row)]
    if flagged:
        lines += ["", f"`time*`: loop stopped on time while the host was under load ({len(flagged)} of {sum(1 for row in results if row.get('ok'))} builds, #77)."]
    lines += ["", loop_net_line(results, loop_seconds)]
    median_moves, total_moves = aggregate_move_tables(results)
    if median_moves:
        all_moves = [move for row in results if row.get("ok") for move in (row.get("moves") or row.get("move_rows") or ())]
        lines += ["", "## Loop Moves", "", "Median per build:", *render_move_rows(median_moves), "", "Total:",
                  *render_move_rows(total_moves), *reentry_line(all_moves)]
    if lost_rows:
        lines += ["", "## Stages that lost more than 10% of the value without lowering the violation", *lost_rows]
    for row in results:
        if row.get("ok") and row.get("summary"):
            lines += ["", f"## {row['slug']} s{row.get('seed')}" + (f" ({row['variant']})" if row.get("variant") else ""), "```", row["summary"], "```"]
    return "\n".join(lines) + "\n"


def rereport(path: Path) -> Path:
    """Rewrite one finished run's report using only its persisted result rows."""

    if not path.is_dir():
        raise FileNotFoundError(f"benchmark run not found: {path}")
    data = json.loads((path / "results.json").read_text(encoding="utf-8"))
    results = data["rows"] if isinstance(data, dict) and "rows" in data else data
    if not isinstance(results, list) or not all(isinstance(row, dict) for row in results):
        raise ValueError(f"{path / 'results.json'} does not contain benchmark rows")
    report = render_report(results, stamp=path.name, rereport=True)
    report_path = path / "report.md"
    report_path.write_text(report, encoding="utf-8")
    return report_path


def _resolve_run(arg: str) -> Path:
    """A finished benchmark directory, or its newest tag-matching directory."""

    path = Path(arg)
    if path.is_dir():
        return path
    matches = sorted(path for path in (ROOT / "artifacts" / "benchmark").glob(f"*-{arg}") if path.is_dir())
    return matches[-1] if matches else path


# #38: what a run's own folder must remember of its arguments for `--resume` to reproduce the same
# builds. Read back by `_prepare_resume`; not the whole Namespace, only what changes which slug/seed/
# keystone jobs exist or how `run_one` scores them.
_RESUMABLE_ARG_FIELDS = ("slugs", "seeds", "seed", "loop_seconds", "no_variants", "gear", "construction",
                        "construction_only", "stat", "ablate", "tree_depth", "tree_trials",
                        "cluster_candidates", "skip_inert", "fulldps_shortcut", "fixed_point_check", "record_calls",
                        "force_keystone")


def resolve_gear(value: str) -> str:
    """The pipeline's gear mode for a `--gear` value: `template` and its alias `wishlist` are the
    pipeline's `wishlist` mode (results keep `gear_mode: "wishlist"`); `loot` stays `loot`."""

    return "wishlist" if value in ("template", "wishlist") else value


def _resumable_args(args: argparse.Namespace) -> dict:
    return {field: getattr(args, field) for field in _RESUMABLE_ARG_FIELDS}


def resolve_run_config(args: argparse.Namespace) -> dict:
    """The whole resolved run config (#9), PoB-free: every `_resumable_args` field with `gear`
    normalized, plus the template file in use. This is what `args.json` holds."""

    from junkroan.optimizer.wishlist_gear import TEMPLATE_PATH

    config = _resumable_args(args)
    config["gear"] = resolve_gear(config["gear"])
    config["commit"] = code_commit()  # #748
    config["template_path"] = str(TEMPLATE_PATH.relative_to(Path(__file__).resolve().parents[1])) if config["gear"] == "wishlist" else None
    return config


def _existing_row(out_dir: Path, stem: str) -> dict | None:
    """A previously persisted row (#38 `--resume`): written atomically by `persist_completed_row`,
    so its mere presence on disk means the build is complete, never half-written."""

    path = out_dir / "rows" / f"{stem}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None


def _prepare_resume(args: argparse.Namespace) -> tuple[Path, str]:
    """Resolve `--resume`'s run directory and fold its own arguments into `args` (#38, requirement 2).

    `args.json` (written by every run since this feature) is authoritative for slugs/seeds/gear/etc.;
    an explicit conflicting value on the command line for slugs, seeds or --loop-seconds is refused.
    A folder from before `args.json` existed has none: the same arguments are then required on the
    command line, exactly as a fresh run would take them, and used as given (nothing to compare)."""

    out_dir = _resolve_run(args.resume)
    if not out_dir.is_dir():
        raise FileNotFoundError(f"--resume: no benchmark run at {args.resume!r}")
    args_path = out_dir / "args.json"
    if not args_path.is_file():
        if not (args.slugs or args.set):
            raise SystemExit(f"--resume {out_dir}: no args.json recorded; pass the run's own slugs/--set, --seeds and --loop-seconds on the command line")
        if args.set:
            args.slugs = SETS[args.set] + [x for x in args.slugs if x not in SETS[args.set]]
        args.slugs = args.slugs or fixture_slugs(FIXTURES)
        return out_dir, out_dir.name
    recorded = json.loads(args_path.read_text(encoding="utf-8"))
    cli_slugs = (SETS[args.set] + [x for x in args.slugs if x not in SETS[args.set]]) if args.set else args.slugs
    for field, cli_value, default in (("slugs", cli_slugs, []), ("seeds", args.seeds, 1), ("loop_seconds", args.loop_seconds, LOOP_SECONDS_DEFAULT)):
        if cli_value != default and cli_value != recorded.get(field):
            raise SystemExit(f"--resume {out_dir}: --{field.replace('_', '-')} {cli_value!r} does not match the run's own {recorded.get(field)!r}")
    for field in _RESUMABLE_ARG_FIELDS:
        if field in recorded and not (field == "record_calls" and recorded[field] is None):  # a resume may add the flag
            setattr(args, field, recorded[field])
    args.gear = resolve_gear(args.gear)
    _refuse_other_commit(out_dir, recorded.get("commit"))
    return out_dir, out_dir.name


def _refuse_other_commit(out_dir: Path, recorded_commit: str | None) -> None:
    """#748: a folder whose args.json has a `commit` is resumed only at that commit, and only when every row file
    in it was made at it. A folder from before this check (no `commit`) resumes as before."""

    if not recorded_commit:
        return
    here = code_commit()
    if here != recorded_commit:
        raise SystemExit(f"--resume {out_dir}: the run was opened at commit {recorded_commit}, this tree is at {here or 'an uncommitted tree'}")
    odd = []
    for path in sorted((out_dir / "rows").glob("*.json")):
        try:
            row_commit = json.loads(path.read_text(encoding="utf-8")).get("commit")
        except ValueError:
            continue  # an unreadable row is remade, as today
        if row_commit != recorded_commit:
            odd.append(f"{path.stem} ({row_commit or 'no commit'})")
    if odd:
        raise SystemExit(f"--resume {out_dir}: rows made at another commit than {recorded_commit}: {', '.join(odd)}")


def exit_code_for(results: list[dict]) -> int:
    """2 when no row counts (every build failed, #456), else 0; "counts" is the report's own counted_row."""

    return 0 if any(counted_row(r) for r in results) else 2


@dataclass(frozen=True)
class Job:
    """One planned build (#621): a base build (`keystone` None) or its keystone variant."""

    slug: str
    seed: int
    keystone: str | None = None
    force: tuple[str, ...] = ()  # #1029: --force-keystone names: the base build is a `with <NAME>` row

    @property
    def stem(self) -> str:
        return result_stem({"slug": self.slug, "seed": self.seed, "variant": variant_label([self.keystone] if self.keystone else [], self.force)})


def run_pool(pool: Any, pending: list[Job], *, submit: Callable[[Job], Any], handle: Callable[[Job, dict], list[Job]], workers: int, out_dir: Path,
             estimate_seconds: Callable[[str], float] | None = None, clock: Callable[[], float] | None = None, poll: float = 5.0,
             read_yield: Callable[[], int] = read_yield_from_env, sleep: Callable[[float], None] = time.sleep) -> None:
    """The build pool of `main` (#621). At most `allowed = workers - yield` builds are in flight; builds past that are
    asked to give up through `<out_dir>/yield/<stem>.stop` (those with little left first, then the youngest); a build
    that returns `{"deferred": True}` goes back to the FRONT of `pending`, with no row. `handle(job, row)` takes a
    finished row and returns the jobs it adds (keystone variants), which go to the end. Ends when nothing is pending
    or running; with allowed 0 it idles alive until the yield file drops."""

    scale = time_scale()
    clock = clock or (lambda: time.perf_counter() * scale)
    stop_dir = out_dir / "yield"
    stop_dir.mkdir(parents=True, exist_ok=True)
    for stale in [*stop_dir.glob("*.stop"), *stop_dir.glob("*.kept")]:
        stale.unlink(missing_ok=True)
    pending = list(pending)
    running: dict = {}  # future -> Job
    started: dict[str, float] = {}

    def drop_files(stem: str) -> None:
        for suffix in ("stop", "kept"):
            (stop_dir / f"{stem}.{suffix}").unlink(missing_ok=True)

    def sync_stop_files(allowed: int) -> None:
        jobs = list(running.values())
        asked = [j for j in jobs if (stop_dir / f"{j.stem}.stop").exists()]  # decided kept (frees its slot at its end) or not yet decided
        undecided = [j for j in asked if not (stop_dir / f"{j.stem}.kept").exists()]
        desired = max(0, len(jobs) - allowed)
        if len(asked) > desired:
            for job in sorted(undecided, key=lambda j: -started[j.stem])[: len(asked) - desired]:
                (stop_dir / f"{job.stem}.stop").unlink(missing_ok=True)
            return
        if len(asked) == desired:
            return
        now = clock()
        candidates = [j for j in jobs if not (stop_dir / f"{j.stem}.stop").exists()]

        def rank(job: Job) -> tuple:
            elapsed = now - started[job.stem]
            remaining = max(0.0, estimate_seconds(job.slug) - elapsed) if estimate_seconds else float("inf")
            return (0, remaining, 0.0) if remaining <= YIELD_KEEP_SECONDS else (1, 0.0, elapsed)

        for job in sorted(candidates, key=rank)[: desired - len(asked)]:
            (stop_dir / f"{job.stem}.stop").write_text("give up", encoding="utf-8")

    while pending or running:
        allowed = max(0, workers - read_yield())
        while pending and len(running) < allowed:
            job = pending.pop(0)
            drop_files(job.stem)
            started[job.stem] = clock()
            running[submit(job)] = job
        sync_stop_files(allowed)
        if not running:
            sleep(poll)
            continue
        for fut in wait(list(running), timeout=poll, return_when=FIRST_COMPLETED).done:
            job = running.pop(fut)
            drop_files(job.stem)
            r = fut.result()
            if r.get("deferred"):
                pending.insert(0, job)
                continue
            pending.extend(handle(job, r))


_GRAPH = None


def _variant_keystones(row: dict) -> list[str]:
    """The keystones of a base row's build that its reference did not fix: each gets a keystone variant row (D40)."""

    global _GRAPH
    from build_from_skeleton import skeleton_from_xml
    from junkroan.optimizer.tree_graph import TreeGraph
    from junkroan.pob.session import decode_import_code

    if _GRAPH is None:
        _GRAPH = TreeGraph.load()
    fixed = {
        _GRAPH.nodes[int(node_id)].name.lower()
        for node_id in skeleton_from_xml(decode_import_code(fixture_path(row["slug"]).read_text(encoding="utf-8").strip())).keystones
        if int(node_id) in _GRAPH.nodes
    }
    return [keystone for keystone in row["keystones"] if keystone.lower() not in fixed]


def _submit_build(pool: Any, job: Job, args: argparse.Namespace, out_dir: Path, author_cache: str):
    if job.keystone is None:
        return pool.submit(run_one, job.slug, log_path=str(out_dir / "logs" / f"{job.stem}.log"), seed=job.seed, gear_mode=args.gear, construction=args.construction, construction_only=args.construction_only, tree_max_depth=args.tree_depth, tree_max_trials=args.tree_trials, ablate=args.ablate, stat_override=args.stat, loop_seconds=args.loop_seconds, cluster_candidates=args.cluster_candidates, skip_inert=args.skip_inert, fulldps_shortcut=args.fulldps_shortcut, fixed_point_check=args.fixed_point_check, author_cache=author_cache, record_calls=args.record_calls, force_keystones=list(job.force) or None)
    return pool.submit(run_one, job.slug, log_path=str(out_dir / "logs" / f"{job.slug}-s{job.seed}-no-{job.keystone.replace(' ', '_').lower()}.log"), seed=job.seed, gear_mode=args.gear, construction=args.construction, construction_only=False, forbid_keystones=[job.keystone], loop_seconds=args.loop_seconds, cluster_candidates=args.cluster_candidates, skip_inert=args.skip_inert, fulldps_shortcut=args.fulldps_shortcut, fixed_point_check=args.fixed_point_check, author_cache=author_cache, record_calls=args.record_calls)


def _single_rows(args: argparse.Namespace, out_dir: Path) -> int:
    """#748 `--resume <folder> --missing` / `--row <stem>`: neither touches results.json or the report."""

    seeds = list(range(args.seed, args.seed + args.seeds))
    forced = tuple(getattr(args, "force_keystone", None) or ())  # #1029: a forced run's base rows are `with <NAME>` rows
    base_stems = {Job(slug, sd, force=forced).stem: Job(slug, sd, force=forced) for sd in seeds for slug in args.slugs}
    variants: dict[str, Job] = {}  # variant stems whose base row is in the folder
    if not (args.no_variants or args.construction_only or forced):
        for stem, job in base_stems.items():
            base = _existing_row(out_dir, stem)
            if base is not None and base.get("ok"):
                for keystone in _variant_keystones(base):
                    variants[result_stem({"slug": job.slug, "seed": job.seed, "variant": f"no {keystone}"})] = Job(job.slug, job.seed, keystone)
    candidates = {**base_stems, **variants}
    todo = [stem for stem in candidates if _existing_row(out_dir, stem) is None]
    if args.missing:
        for stem in todo:
            print(stem)
        return 0
    stem = args.row
    if _existing_row(out_dir, stem) is not None:
        print(f"{stem}: already in {out_dir}; nothing to do")
        return 0
    if stem not in candidates:
        base_of = [b for b in base_stems if stem.startswith(b + "-no-")]
        if base_of:
            raise SystemExit(f"--row {stem}: its base row {base_of[0]} is not in {out_dir} (or the stem is not one of its variants)")
        raise SystemExit(f"--row {stem}: not a row of {out_dir} (rows: {', '.join(candidates)})")
    job = candidates[stem]
    author_cache = str(out_dir / "author")
    rows: list[dict] = []

    def handle(_job: Job, row: dict) -> list[Job]:
        rows.append(row)
        if row.get("ok"):
            _write_text_atomic(out_dir / f"{stem}.pob.txt", row["import_code"])
        _write_text_atomic(out_dir / "rows" / f"{stem}.json", json.dumps(persisted_row(row), indent=1, ensure_ascii=False))
        return []

    with ProcessPoolExecutor(max_workers=1) as pool:
        run_pool(pool, [job], submit=lambda j: _submit_build(pool, j, args, out_dir, author_cache), handle=handle, workers=1, out_dir=out_dir)
    return exit_code_for(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*", default=[], help="fixture slugs, from any fixture folder (tuadh_329, then zizaran_329/early); none = every Tuadh reference (or --set)")
    ap.add_argument("--set", choices=sorted(SETS), help="a named reference set (7.1e): " + ", ".join(f"{k} ({len(v)})" for k, v in SETS.items()) + "; explicit slugs are added")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--gear", choices=["template", "wishlist", "loot"], default="template", help="day-1 gear: 'template' (the default; 'wishlist' is its alias) = fixed day-1 templates with PoB-selected open lines (D79); 'loot' = best of N random rares per slot (D19)")
    ap.add_argument("--construction", choices=["classic", "rig-first"], default="classic", help="construction order: full gear against an empty tree, or a cheap rig before gear pass 1")
    ap.add_argument("--construction-only", action="store_true", help="stop after tree rebuilt on gear; write the construction row and build without the loop or variants")
    ap.add_argument("--reopt-rounds", type=int, default=3, help="no-op since D58: the loop is the pipeline")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=1, help="rebuild every reference with this many seeds (seed, seed+1, ...): median and spread in the report")
    ap.add_argument("--no-variants", action="store_true", help="skip the keystone variants (each reference rebuilt without each keystone the tree took, D40)")
    ap.add_argument("--force-keystone", action="append", metavar="NAME", help="#1029: add this keystone (exact name, repeatable) to each reference's skeleton; rows are named `with <NAME>` (`-with-<name>` in the file stem); the D40 variants are off for the run, as with --no-variants")
    ap.add_argument("--tree-depth", type=int, default=6, help="TreeOptimizer max_depth (payoff nodes reachable within this many steps are candidates)")
    ap.add_argument("--tree-trials", type=int, default=300, help="TreeOptimizer max_trials per greedy step (candidates beyond it, the farthest, are not tried)")
    ap.add_argument("--ablate", help="run the pipeline without these stages, comma-separated: " + ", ".join(sorted(ABLATIONS)))
    ap.add_argument("--tag", default="", help="suffix for the output folder name")
    ap.add_argument("--stat", choices=["FullDPS", "CombinedDPS"], help="7.1a: judge every reference on this stat instead of objective_for's choice (FullDPS flags the author's main group)")
    ap.add_argument("--loop", action="store_true", help="no-op since D58: the loop is the pipeline")
    ap.add_argument("--loop-seconds", type=float, default=LOOP_SECONDS_DEFAULT, help="a wall-clock net for the loop (BuildPipeline.run loop_max_seconds); absent = no clock, the loop stops on its counts (max passes, min gain). Given, the result depends on the machine: a slower host is cut earlier (#956)")
    ap.add_argument("--cluster-candidates", action="store_true", help="7.2 rule 5: the greedy also tries small clusters of notables sharing a mechanic tag as one step")
    ap.add_argument("--skip-inert", action=argparse.BooleanOptionalAction, default=False, help="approximate (speed audit 2026-09-18; off by default: the speed-both-2 gate failed, -6.4 points for -10%% time): a candidate PoB scored inert (value AND violation unchanged) is not sent again until a floor breaks, its path is touched, a keystone or charge generator is taken, or 10 steps pass")
    ap.add_argument("--fulldps-shortcut", action=argparse.BooleanOptionalAction, default=False, help="approximate (speed audit 2026-09-18; off by default: the speed-both-2 gate failed, -6.4 points for -10%% time): a fast trial batch asking for FullDPS runs without PoB's full-DPS roll-up (2-4x the cost of one without it) and reports FullDPS as ratio x the main skill's own DPS, the ratio measured with one real roll-up per batch")
    ap.add_argument("--fixed-point-check", action=argparse.BooleanOptionalAction, default=True, help="7.3: after the final lanes, run one more pass of the loop's local moves (no kicks, no lane tuning) on the finished build; the build keeps what it gains and a gain above 1%% is an audit error (\"not at a fixed point\")")
    ap.add_argument("--record-calls", metavar="DIR", help="#569: record every PoB call of each build to DIR/<slug>-s<seed>[-no-<keystone>].calls.jsonl (junkroan.recording_pob; identity-row transcript)")
    ap.add_argument("--rereport", help="rewrite a finished run's report.md from results.json only; accepts a run directory or tag")
    ap.add_argument("--resume", help="#38: write into this existing run folder and run only the builds without a complete row under rows/; accepts a run directory or tag")
    ap.add_argument("--row", metavar="STEM", help="#748: with --resume, make exactly this one row (rows/<stem>.json and its .pob.txt only; never results.json or the report); a stem already in the folder exits 0 with no build")
    ap.add_argument("--missing", action="store_true", help="#748: with --resume, print one stem per line for the rows the folder lacks and that can start now; starts no PoB")
    ap.add_argument("--pobbin-backfill", help="#573: upload the link-less ok rows of a finished or in-flight run (from their .pob.txt) to pobb.in and write the links into rows/ and results.json; accepts a run directory or tag")
    args = ap.parse_args()
    if (args.row or args.missing) and not args.resume:
        ap.error("--row and --missing are only valid with --resume")
    if args.row and args.missing:
        ap.error("--row and --missing are exclusive")
    if args.force_keystone:  # #1029: names resolved against the tree before any run; an unknown name is exit 2
        from junkroan.optimizer.tree_graph import TreeGraph
        try:
            args.force_keystone = list(dict.fromkeys(resolve_keystone_name(TreeGraph.load(), name)[1] for name in args.force_keystone))
        except ValueError as exc:
            ap.error(f"--force-keystone: {exc}")
    if args.pobbin_backfill:
        print(pobbin_backfill(_resolve_run(args.pobbin_backfill), args.pobbin_backfill))
        return 0
    args.gear = resolve_gear(args.gear)
    if args.rereport:
        print(f"report: {rereport(_resolve_run(args.rereport))}")
        return 0
    if args.resume:
        out_dir, stamp = _prepare_resume(args)
        if args.row or args.missing:
            return _single_rows(args, out_dir)
    else:
        if args.set:
            args.slugs = SETS[args.set] + [x for x in args.slugs if x not in SETS[args.set]]
        # no slugs and no --set keeps its old meaning: every Tuadh reference. The second set (ziz) is a
        # different campaign, named by `--set ziz` or by its slugs, never silently added to a bare run.
        args.slugs = args.slugs or fixture_slugs(FIXTURES)
        stamp = time.strftime("%Y%m%d-%H%M") + (f"-{args.tag}" if args.tag else "") + (f"-no-{args.ablate}" if args.ablate else "")
        out_dir = ROOT / "artifacts" / "benchmark" / stamp
        out_dir.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(out_dir / "args.json", json.dumps(resolve_run_config(args), indent=1))
    t_all = time.perf_counter()
    results: list[dict] = []
    seeds = list(range(args.seed, args.seed + args.seeds))
    # seed-major, as the submission order below: every reference's first seed comes before any second
    # seed, so the later seeds find the author memo the first one wrote (7.1h) -- unaffected by resume.
    base_pairs = [(slug, sd) for sd in seeds for slug in args.slugs]
    total_builds = len(base_pairs)
    pending_base = base_pairs
    forced = tuple(args.force_keystone or ())  # #1029
    if args.resume:
        pending_base = []
        for slug, sd in base_pairs:
            existing = _existing_row(out_dir, Job(slug, sd, force=forced).stem)
            if existing is not None:
                results.append(existing)
            else:
                pending_base.append((slug, sd))
        print(f"resumed: {len(base_pairs) - len(pending_base)} of {len(base_pairs)} builds already done", flush=True)

    def show(r: dict) -> None:
        tag = f"{r['slug']} s{r.get('seed')}" + (f" ({r['variant']})" if r.get("variant") else "")
        if r["ok"]:
            print(f"  {tag:40s} author {r['author_raw']:>10,.0f} (our lane {r['author_lane']:>10,.0f})  ours {r['ours']:>10,.0f}  = {r['ratio_lane']:.0%} of the author under our lane"
                   f"  life {r['ours_life']}/{r['author_life']}  ramp {r['ours_ramp'] if r['ours_ramp'] is None else human_duration(r['ours_ramp'])}  audit errors {r['audit_errors']}  {human_duration(r['seconds'])}"
                  + (f"  LOST: {'; '.join(lost)}" if (lost := lost_stages(r["stages"])) else ""), flush=True)
        else:
            print(f"  {tag:40s} FAILED {r['error']}", flush=True)

    pobbin_run = new_pobbin_run()
    author_cache = str(out_dir / "author")  # one author row per reference, shared by its seeds (7.1h)
    bench_root = ROOT / "artifacts" / "benchmark"
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        variant_jobs: list[tuple[str, int, str, str]] = []  # (slug, seed, keystone, stem of the base row it follows)
        base_done = len(base_pairs) - len(pending_base)
        variants_enabled = not args.no_variants and not args.construction_only and not forced  # #1029: forced run = no D40 variants
        if not variants_enabled:
            write_variants_plan(out_dir, len(base_pairs), base_done, [])
        def collect_variant_jobs(r: dict) -> list[tuple[str, int, str, str]]:
            nonlocal total_builds
            if not (r.get("ok") and variants_enabled):
                return []
            new_jobs = [(r["slug"], r["seed"], keystone, result_stem(r)) for keystone in _variant_keystones(r)]
            variant_jobs.extend(new_jobs)
            total_builds += len(new_jobs)
            return new_jobs

        def submit_job(job: Job):
            """Seed-major order is the order of `pending` (base_pairs'): every reference's first seed is submitted before any second seed, so the later seeds find the author memo the first one wrote."""

            return _submit_build(pool, job, args, out_dir, author_cache)

        def variants_to_run(new_jobs: list[tuple[str, int, str, str]]) -> list[Job]:
            """Every keystone the tree took that the author did not fix: rebuild without it (D40), the moment its base row ends."""

            todo: list[Job] = []
            for slug, seed, keystone, _after in new_jobs:
                existing = _existing_row(out_dir, result_stem({"slug": slug, "seed": seed, "variant": f"no {keystone}"})) if args.resume else None
                if existing is not None:
                    results.append(existing)
                else:
                    todo.append(Job(slug, seed, keystone))
            if new_jobs:
                print(f"  keystone variants: {len(new_jobs)} ({', '.join(f'{s} without {k}' for s, _sd, k, _a in new_jobs)})", flush=True)
            return todo

        def persist(r: dict, plan: Callable[[], None] | None = None) -> None:
            persist_completed_row(
                out_dir,
                stamp=stamp,
                results=results,
                row=r,
                total_builds=total_builds,
                workers=args.workers,
                seconds=time.perf_counter() - t_all,
                gear_mode=args.gear,
                pobbin_run=pobbin_run,
                plan=plan,
                loop_seconds=args.loop_seconds,
            )

        def handle(job: Job, r: dict) -> list[Job]:
            nonlocal base_done
            if job.keystone is not None:
                results.append(r)
                show(r)
                persist(r)
                return []
            new_jobs = collect_variant_jobs(r)
            base_done += 1
            results.append(r)
            show(r)
            persist(r, lambda: write_variants_plan(out_dir, len(base_pairs), base_done, variant_jobs))
            return variants_to_run(new_jobs)

        resumed_jobs: list[tuple[str, int, str, str]] = []
        for r in list(results):  # rows a --resume reused still feed variant discovery, exactly as a fresh completion does
            resumed_jobs += collect_variant_jobs(r)
        if args.resume and variants_enabled:
            write_variants_plan(out_dir, len(base_pairs), base_done, variant_jobs)
        initial = [Job(slug, sd, force=forced) for slug, sd in pending_base] + variants_to_run(resumed_jobs)
        run_pool(pool, initial, submit=submit_job, handle=handle, workers=args.workers, out_dir=out_dir,
                 estimate_seconds=lambda slug: estimate_build(slug, out_dir, args.loop_seconds, bench_root)[0])
    fixed_at_end = pobbin_retry_pass(out_dir, results, pobbin_run)
    n_up = sum(1 for r in results if r.get("pobbin_id"))
    n_err = sum(1 for r in results if r.get("pobbin_error"))
    print(f"pobbin: {n_up} uploaded, {n_err} errors, {fixed_at_end} fixed at the end", flush=True)
    results.sort(key=lambda r: (r["slug"], r.get("seed") or 0, r.get("variant") or ""))
    report = render_report(results, stamp=stamp, workers=args.workers, seconds=time.perf_counter() - t_all, gear_mode=args.gear, loop_seconds=args.loop_seconds)
    _write_text_atomic(out_dir / "report.md", report)
    _write_text_atomic(out_dir / "results.json", json.dumps([persisted_row(r) for r in results], indent=1, ensure_ascii=False))
    print("\n" + "\n".join(report.splitlines()[6 + len(results):]))
    print(f"\nreport: {out_dir / 'report.md'}")
    code = exit_code_for(results)
    if code:
        print("benchmark: 0 counted rows, exit 2", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
