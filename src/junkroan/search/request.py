"""Build request: the checklist in docs/REQUEST.md as data.

Every item of a request is fixed, constrained (a list) or free ("auto"). Names
are resolved against the corpora through `hypothesis.validate`; the request
expands into one hypothesis per (ascendancy, mode) combination and the echo
says what was understood, what could not be, and how big the run is.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from junkroan.optimizer.rails import Rails
from junkroan.report_format import human_duration
from junkroan.search.hypothesis import LOADOUTS, Hypothesis, Validation, active_gems, alternate_ascendancies, ascendancy, ascendancy_aliases, check_ascendancy_for_loadout, resolve_affix_key, search_ascendancies, support_gems, validate
from junkroan.search.modes import MODES

AUTO = "auto"
# Measured on the D58 loop, 2026-09-18: the one full build down the request path (Storm Brand,
# `junkroan build`) took 2,686 s = 45 min on one worker while a 5-worker benchmark ran, so 45 is
# an upper bound; benchmark builds on the same code take 32-45 min, median 32 (rules-smoke).
MINUTES_PER_FULL_BUILD = 40.0
# The screen is the cheap pipeline (loot N=60, greedy tree, no loop): ~3 min per candidate,
# the figure search.py's variant screen is budgeted on.
MINUTES_PER_SCREEN = 3.0
# D71 / ROADMAP 7.3: the expected best of K seeds of one skeleton is 153.6 / 165.5 / 171.0 /
# 174.4 % of the author for K = 1..4, so a finalist is built three times and the best kept.
DEFAULT_SEEDS = 3


def _waves(jobs: int, workers: int) -> int:
    return -(-max(0, int(jobs)) // max(1, int(workers)))


def mutation_variants(finalists: int) -> int:
    """Upper bound of the mutation round's variants (scripts/search.py): per finalist one per
    structural keystone taken, up to 2 weapon alternatives, one unique mutation."""

    return max(0, int(finalists)) * 3


def mutation_minutes(finalists: int, *, workers: int) -> float:
    """The mutation round: every variant screened, then the kept ones built once each on one
    seed (one wave). Measured 2026-10-03 on 5 workers: request 1 = 9 variants, 7 kept, 47 min;
    request 2 = 6 variants, 5 kept, 51 min; this model gives 2*3+40 = 46 min for 2 finalists."""

    if finalists <= 0:
        return 0.0
    return _waves(mutation_variants(finalists), workers) * MINUTES_PER_SCREEN + MINUTES_PER_FULL_BUILD


def estimate_minutes(candidates: int, *, finalists: int, seeds: int, workers: int, extra: float = 0.0, unique_variants: bool = False, mutation: bool = False) -> float:
    """Wall clock of a request: every candidate screened, then the finalists (plus, with
    `unique_variants`, up to one unique variant each) built `seeds` times each, both in waves
    of `workers` (the full jobs all sit in one pool, so 2 finalists x 3 seeds on 5 workers is
    two waves), then with `mutation` the mutation round."""

    skeletons = max(0, int(finalists)) * (2 if unique_variants else 1)
    total = _waves(candidates, workers) * MINUTES_PER_SCREEN + _waves(skeletons * max(1, int(seeds)), workers) * MINUTES_PER_FULL_BUILD + extra
    if mutation:
        total += mutation_minutes(finalists, workers=workers)
    return total


def minutes_text(minutes: float) -> str:
    """`~N min` up to 90 min, then hours and minutes (CLAUDE.md principle 7)."""

    return f"~{minutes:.0f} min" if minutes <= 90 else "~" + human_duration(minutes * 60)


def rig_supports_line(class_name: str, ascendancy: str, seconds: float, supports: Any) -> str:
    return f"supports by PoB on {class_name}/{ascendancy} rig ({human_duration(seconds)}): {supports}"


def prepared_line(count: int, seconds: float) -> str:
    return f"prepared {count} skeletons ({human_duration(seconds)})"


def screen_done_line(seconds: float) -> str:
    return f"screen done ({human_duration(seconds)})"


def full_done_line(seconds: float, skeletons: int, seeds: int) -> str:
    return f"full optimize done ({human_duration(seconds)}; {skeletons} skeletons x {seeds} seeds)"


def mutation_done_line(seconds: float, kept: int, variants: int) -> str:
    return f"mutation round done ({human_duration(seconds)}; {kept} of {variants} variants fully optimized)"


def total_line(seconds: float) -> str:
    return f"total {human_duration(seconds)}"


def full_optimize_line(skeletons: int, seeds: int, *, workers: int, mutation_finalists: int = 0) -> str:
    """The `screen done` line: the exact full builds now known and what is left of the run."""

    builds = skeletons * max(1, seeds)
    left = _waves(builds, workers) * MINUTES_PER_FULL_BUILD
    line = f"full optimize: {skeletons} skeletons x {seeds} seeds = {builds} full builds, {minutes_text(left)} left"
    if mutation_finalists:
        line += f" (+ mutation round {minutes_text(mutation_minutes(mutation_finalists, workers=workers))})"
    return line


def _as_list(value: Any) -> list[Any]:
    if value is None or value == AUTO:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


@dataclass(slots=True)
class BuildRequest:
    raw: dict[str, Any]
    why: str = ""
    level: int = 77
    skill: str | None = None
    modes: list[str] = field(default_factory=list)  # [] = auto
    delivery: str | None = None  # a trigger/totem/trap/mine support, or an active trigger skill (Spellslinger); None = self-cast
    trigger_with: str | None = None  # the skill that fires an active trigger delivery (Kinetic Blast for Spellslinger)
    ascendancies: list[str] = field(default_factory=list)  # [] = auto (all)
    ascendancy_nodes: list[str] = field(default_factory=list)
    scaling: dict[str, Any] | None = None
    keystones: list[str] = field(default_factory=list)
    forbid_keystones: list[str] = field(default_factory=list)
    nodes: list[str] = field(default_factory=list)  # passive names (notable, keystone, mastery effect), forced; `keystones` is an alias whose names are added here
    affixes: dict[str, list[str]] = field(default_factory=dict)  # {slot or item class: [mod line text]}, forced on that slot's rare
    uniques: dict[str, str] = field(default_factory=dict)
    unique_slots: str = AUTO
    jewels: dict[str, str] = field(default_factory=dict)
    rare_bases: dict[str, str] = field(default_factory=dict)
    weapon_types: list[str] = field(default_factory=list)
    spectres: list[str] = field(default_factory=list)  # Raise Spectre: spectre ids or names (Spectres.lua), forced
    supports: list[str] = field(default_factory=list)
    forbid_supports: list[str] = field(default_factory=list)
    utilities: list[str] = field(default_factory=list)
    forbid_utilities: list[str] = field(default_factory=list)
    utility_groups: int | None = None
    damage_links: dict[str, Any] | None = None
    config: dict[str, Any] = field(default_factory=dict)
    floors: dict[str, float] = field(default_factory=dict)
    top: int = 2
    seeds: int = DEFAULT_SEEDS  # full builds per finalist skeleton; the best by Score is delivered (D71)
    workers: int = 5
    max_builds: int = 24
    gear: str = "loot"
    loadout: str = "day1"  # day1 | t16 | endgame: which ascendancies the search covers (rulebook c-ascendancy)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "BuildRequest":
        r = dict(raw)
        keystones = [str(k) for k in _as_list(r.get("keystones"))]
        nodes = list(dict.fromkeys([str(n) for n in _as_list(r.get("nodes"))] + keystones))
        affixes = {str(k): [str(x) for x in _as_list(v)] for k, v in (r.get("affixes") or {}).items()}
        return cls(
            raw=r, why=str(r.get("why") or r.get("request") or ""), level=int(r.get("level") or 77),
            skill=(str(r["skill"]) if r.get("skill") else None),
            modes=[str(m) for m in _as_list(r.get("mode"))],
            delivery=(None if r.get("delivery") in (None, "self", AUTO) else str(r.get("delivery"))),
            trigger_with=(str(r["trigger_with"]) if r.get("trigger_with") else None),
            ascendancies=[str(a) for a in _as_list(r.get("ascendancy"))],
            ascendancy_nodes=[str(a) for a in _as_list(r.get("ascendancy_nodes"))],
            scaling=(dict(r["scaling"]) if isinstance(r.get("scaling"), Mapping) else None),
            keystones=keystones, nodes=nodes, affixes=affixes, forbid_keystones=[str(k) for k in _as_list(r.get("forbid_keystones"))],
            uniques={str(k): str(v) for k, v in (r.get("uniques") or {}).items()}, unique_slots=str(r.get("unique_slots") or AUTO),
            jewels={str(k): str(v) for k, v in (r.get("jewels") or {}).items()},
            rare_bases={str(k): str(v) for k, v in (r.get("rare_bases") or {}).items()},
            weapon_types=[str(w) for w in _as_list(r.get("weapon_types"))], spectres=[str(s) for s in _as_list(r.get("spectres"))],
            supports=[str(s) for s in _as_list(r.get("supports"))], forbid_supports=[str(s) for s in _as_list(r.get("forbid_supports"))],
            utilities=[str(u) for u in _as_list(r.get("utilities"))], forbid_utilities=[str(u) for u in _as_list(r.get("forbid_utilities"))],
            utility_groups=(int(r["utility_groups"]) if r.get("utility_groups") is not None else None),
            damage_links=(dict(r["damage_links"]) if isinstance(r.get("damage_links"), Mapping) else None),
            config=dict(r.get("config") or {}), floors={str(k): float(v) for k, v in (r.get("floors") or {}).items()},
            top=int(r.get("top") or 2), seeds=max(1, int(r.get("seeds") or DEFAULT_SEEDS)), workers=int(r.get("workers") or 5), max_builds=int(r.get("max_builds") or 24), gear=str(r.get("gear") or "loot"), loadout=str(r.get("loadout") or "day1"),
        )


@dataclass(slots=True)
class Expansion:
    hypotheses: list[Hypothesis]
    validations: list[Validation]
    problems: list[str]
    notes: list[str]
    echo: str

    @property
    def ok(self) -> bool:
        return not self.problems and bool(self.hypotheses)


def _fixed_lines(request: BuildRequest, asc_ids: list[str]) -> list[str]:
    """One `fixed ...` line per forced direction: what every build of the search must carry (D114 amd 1)."""

    out = [f"fixed ascendancy: {a}" for a in asc_ids] if request.ascendancies and [a for a in request.ascendancies if a != AUTO] else []
    out += [f"fixed node: {n}" for n in request.nodes]
    for key, lines in request.affixes.items():
        slot, item_class, problem = resolve_affix_key(key, request.weapon_types)
        out += [f"fixed affix: {slot} ({item_class}): {line}" if not problem else f"fixed affix: {key}: {line}" for line in lines]
    out += [f"fixed unique: {slot} = {name}" for slot, name in request.uniques.items()]
    out += [f"fixed base: {slot} = {base}" for slot, base in request.rare_bases.items()]
    out += [f"fixed spectre: {s}" for s in request.spectres]
    return out


def expand(request: BuildRequest, rails: Rails | None = None, *, composition: Mapping[str, float] | None = None, unique_variants: bool = False, mutation: bool = False) -> Expansion:
    """Request -> hypotheses (one per ascendancy x mode). `composition` (from the
    mode probe) resolves mode=auto; without it auto means "hit or the skill's own
    DoT, whichever PoB gives more" is left to the pipeline and reported as such."""

    rails = rails or Rails.load()
    problems: list[str] = []
    notes: list[str] = []
    if not request.skill:
        problems.append("skill is required (skill_from is not implemented yet)")
    elif request.skill.lower() not in active_gems():
        problems.append(f"unknown active skill {request.skill!r}")
    if request.gear not in {"loot", "wishlist"}:
        problems.append(f"unknown gear model {request.gear!r}; known: loot, wishlist")
    # modes
    modes = [m for m in request.modes if m != AUTO]
    for m in modes:
        if m not in MODES:
            problems.append(f"unknown mode {m!r}; known: {', '.join(MODES)}")
    if not modes:
        if composition:
            primary = max((k for k in composition if k not in ("minion",)), key=lambda k: composition.get(k, 0.0))
            modes = [primary]
            notes.append(f"mode auto -> {primary} (composition: " + ", ".join(f"{k} {v:,.0f}" for k, v in composition.items() if v) + ")")
        else:
            modes = [AUTO]
            notes.append("mode auto: the pipeline maximizes CombinedDPS (run scripts/probe_modes.py to see the composition and fix a mode)")
    # ascendancies
    asc_ids = [a for a in request.ascendancies if a != AUTO]
    known = ascendancy_aliases()  # both PoB ids and display names ("Raider" / "Warden")
    if request.loadout not in LOADOUTS:
        problems.append(f"unknown loadout {request.loadout!r}; known: {', '.join(LOADOUTS)}")
    for a in asc_ids:
        try:
            check_ascendancy_for_loadout(a, request.loadout)
        except ValueError as e:
            problems.append(str(e))
            continue
        if a.lower() not in known and a.lower() not in alternate_ascendancies():
            problems.append(f"unknown ascendancy {a!r}")
    # an id and its display name are the same ascendancy: dict.fromkeys keeps the first, in order
    asc_ids = list(dict.fromkeys(known.get(a.lower(), a) for a in asc_ids)) or search_ascendancies(request.loadout if request.loadout in LOADOUTS else "day1")
    if not request.ascendancies:
        notes.append(f"ascendancy auto: all {len(asc_ids)} (expensive; name a few to cut the run)")
    # delivery / supports
    fixed_supports = list(request.supports)
    link_head: list[str] = []  # an active trigger skill goes in front of the damage skill in the same link
    trigger_groups: list[list[str]] = []
    if request.delivery:
        rec = support_gems().get(request.delivery.lower())
        act = active_gems().get(request.delivery.lower())
        if rec is not None:
            fixed_supports.insert(0, rec["name"])
        elif act is not None:
            link_head = [act["name"]]
            notes.append(f"delivery {act['name']} is an active trigger skill: it heads the main link and the damage skill is triggered by it")
            if request.trigger_with:
                tw = active_gems().get(request.trigger_with.lower())
                if tw is None:
                    problems.append(f"unknown trigger_with skill {request.trigger_with!r}")
                else:
                    trigger_groups.append([tw["name"]])
            else:
                notes.append("trigger_with not given: PoB needs the firing skill (Kinetic Blast, Barrage...) for the trigger rate")
        else:
            problems.append(f"unknown delivery {request.delivery!r} (neither a support nor an active skill)")
    needs_enabler: set[str] = set()
    for mode in modes:
        enabler = MODES.get(mode, (None, None))[1]
        if enabler and enabler not in fixed_supports and mode in ("ignite", "poison", "bleed"):
            if composition is not None and composition.get(mode, 0.0) > 0:
                notes.append(f"mode {mode}: the skill inflicts {mode} by itself (PoB: {composition[mode]:,.0f} on the rig); no enabler needed")
            else:
                needs_enabler.add(mode)
                notes.append(f"mode {mode}: {enabler} is fixed in the link as the enabler" + ("" if composition is not None else " (run with the composition probe to check whether the skill inflicts it by itself)"))
    # not-yet-modelled items are named, not ignored
    if request.damage_links:
        notes.append("damage_links: picker not implemented yet; the request is accepted but extra damage links are not chosen")
    if request.jewels:
        notes.append("jewels: carried as fixed raw items; their socket is not yet forced into the tree")
    if request.scaling:
        stat = request.scaling.get("stat")
        if not stat:
            problems.append("scaling needs a 'stat' (a PoB stat name such as Dex, Int, Life, Mana)")
    if request.config:
        notes.append(f"config: {sorted(request.config)} taken as the user's assumptions in both lanes")
    if request.floors:
        notes.append(f"floors overridden: {request.floors}")

    hypotheses: list[Hypothesis] = []
    validations: list[Validation] = []
    for asc in asc_ids:
        rec = ascendancy(asc)
        if rec is None:
            notes.append(f"ascendancy {asc} (alternate) has no class mapping yet; not expanded")
            continue
        for mode in modes:
            supports = list(fixed_supports)
            enabler = MODES.get(mode, (None, None))[1]
            if enabler and mode in needs_enabler and enabler not in supports:
                supports.append(enabler)
            h = Hypothesis.from_dict({
                "name": f"{request.skill} {mode} {asc}", "class": rec["class_name"], "ascendancy": rec["ascendancy_id"], "main_skill": request.skill,
                "supports": supports, "keystones": request.keystones, "ascendancy_nodes": request.ascendancy_nodes, "uniques": request.uniques,
                "rare_bases": request.rare_bases, "level": request.level, "why": request.why,
                "nodes": [n for n in request.nodes if n.lower() not in {k.lower() for k in request.keystones}],
                "affixes": request.affixes, "weapon_types": request.weapon_types, "spectres": request.spectres,
            })
            h.extra_groups = [*trigger_groups, *[[u] for u in request.utilities]]
            v = validate(h)
            if v.ok and link_head:
                v.skeleton.main_link = [*link_head, *v.skeleton.main_link]
                v.skeleton.cap_links(rails)
            if v.ok:
                v.skeleton.mode = None if mode == AUTO else mode
                v.skeleton.scaling = dict(request.scaling) if request.scaling else None
                v.skeleton.forbid_supports = list(request.forbid_supports)
                v.skeleton.forbid_utilities = list(request.forbid_utilities)
                v.skeleton.forbid_keystones = list(request.forbid_keystones)
                v.skeleton.jewels = dict(request.jewels)
                v.skeleton.user_config = dict(request.config)
                v.skeleton.utility_groups = request.utility_groups
                v.skeleton.unique_slots = request.unique_slots
                hypotheses.append(h)
                validations.append(v)
            else:
                problems.extend(p for p in v.problems if p not in problems)
    n = len(hypotheses)
    seeds = max(1, request.seeds)
    finalists = min(request.top, n)  # the screen keeps `top`; each is built `seeds` times and the best delivered
    skeletons = finalists * (2 if unique_variants else 1)  # + up to one unique variant per finalist
    full_builds = skeletons * seeds
    extra = 10 if len(asc_ids) > 3 else 0
    minutes = estimate_minutes(n, finalists=finalists, seeds=seeds, workers=request.workers, extra=extra, unique_variants=unique_variants)
    if max(n, full_builds) > request.max_builds:
        problems.append(f"expands to {n} candidates and {full_builds} full builds, above max_builds={request.max_builds}; narrow ascendancy/mode, lower top/seeds or raise max_builds")
    lines = [f"skill: {request.skill} | mode: {', '.join(modes)} | delivery: {request.delivery or 'self'}{' fired by ' + request.trigger_with if request.trigger_with else ''}",
             f"ascendancy: {', '.join(asc_ids) if request.ascendancies else 'auto (' + str(len(asc_ids)) + ')'} | nodes fixed: {request.ascendancy_nodes or 'auto'}",
             f"scaling: {request.scaling or 'none'} | keystones: {request.keystones or 'auto'} | forbid: {request.forbid_keystones or '-'}",
             f"uniques: {request.uniques or 'none fixed'}; screen: {request.unique_slots} (rails tiers {list(rails.unique_allowed_tiers)}) | jewels: {list(request.jewels) or '-'}",
              f"bases: {request.rare_bases or 'auto'} | weapon types: {request.weapon_types or 'auto'}",
              f"gear: {request.gear}",
             f"supports fixed: {fixed_supports or '-'} forbid: {request.forbid_supports or '-'} | utilities fixed: {request.utilities or '-'} forbid: {request.forbid_utilities or '-'} groups: {request.utility_groups or rails.utility_max_groups}",
             f"expands to {n} candidates (ascendancies {len(asc_ids)} x modes {len(modes)}) screened, top {finalists} x {seeds} seeds = {'up to ' if unique_variants else ''}{full_builds} full builds{' (finalists + unique variants)' if unique_variants else ''}, {minutes_text(minutes)} on {request.workers} workers"]
    if mutation:
        mut = mutation_minutes(finalists, workers=request.workers)
        total = estimate_minutes(n, finalists=finalists, seeds=seeds, workers=request.workers, extra=extra, unique_variants=unique_variants, mutation=True)
        lines[-1] += f" + mutation round (up to ~{mutation_variants(finalists)} variants screened, the kept ones built once): {minutes_text(mut)}; total {minutes_text(total)}"
    lines.extend(_fixed_lines(request, asc_ids))
    if notes:
        lines.append("notes: " + " | ".join(notes))
    if problems:
        lines.append("PROBLEMS: " + " | ".join(problems))
    return Expansion(hypotheses=hypotheses, validations=validations, problems=problems, notes=notes, echo="\n".join(lines))


def load_request(path: Path) -> BuildRequest:
    # utf-8-sig, as the CLI reads a request file: a request written by a Windows editor
    # (or by `... --print-request | Out-File`) carries a BOM and json.loads refuses it
    return BuildRequest.from_dict(json.loads(Path(path).read_text(encoding="utf-8-sig")))


__all__ = ["BuildRequest", "Expansion", "expand", "estimate_minutes", "full_optimize_line", "load_request", "mutation_minutes"]
