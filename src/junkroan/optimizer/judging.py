"""The judging context: what a build is judged under at a given moment (#32 step 1, #35).

Its two lanes as PoB holds them, the objective with the ramp, self-cost and castability read from
the build as it stands, and the proof holders tree moves must respect -- plus the copies of that
objective the trees and the gear filler keep (the views).

Layer 1 is a set of functions moved verbatim out of `BuildPipeline`: reading and writing the lanes,
the merge order of a lane write (`plan_config`, pure), the proof holders (`compute_proof_holders`,
pure), the list-choice tuning, the lane memo, and the two small readbacks the self-cost needs.

Layer 2 (`Judging`, below the functions) owns the state that was spread over `BuildPipeline`:
the full objective, the castability context, the main skill's tags and gem levels, the attached
views and their proof holders. Every PoB call it makes goes through one of two ports -- `LaneSource`
and `ContextReads` -- whose production adapters make the calls in the order `BuildPipeline` made
them; the test adapters record them.

Nothing here changes a number: step 1a (#35) moves the knowledge, the drift fixes of #34 come later
and are measured one by one.
"""

from __future__ import annotations

import copy
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Callable, Iterator, Mapping, Protocol
from xml.etree import ElementTree as ET

from junkroan.optimizer.objective import MAX_HIT_KEYS, Objective, bossing_defence
from junkroan.optimizer.ramp_inputs import apply_ailment_stack_caps, apply_custom_mods, apply_mark_blocks

if TYPE_CHECKING:
    from junkroan.optimizer.castability import CastabilityContext

# Inputs a lane write never carries over from the build it overwrites (`plan_config`)
NATIVE_OVERRIDES = frozenset({"overrideBleedStackPotential", "overrideIgniteStackPotential"})
NEVER_PRESERVED = frozenset({"bandit", "pantheonMajorGod", "pantheonMinorGod", "enemyIsBoss"})


# -- layer 1: functions ---------------------------------------------------------------------------


def worse_input(before: object, after: object) -> bool:
    """Did a conservative config input change for the worse: off, or a smaller number?

    The one rule both the proof-holder test and the replay's labels read, so "the input the tree
    paid for is gone" means the same thing in both.
    """

    if before is None or before is False:
        return False  # the lane held nothing: nothing to lose
    if after is None or after is False:
        return True
    if isinstance(before, bool) or isinstance(after, bool):
        return False  # True -> True
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return float(after) < float(before)
    return False  # strings (enemyIsBoss, a stance) are choices, not amounts


def read_lanes(pob: Any, **options: Any):
    """The two lanes as the rules derive them from the build PoB holds now (`derive_config` with
    the rules preferred). `options` pass through (the benchmark's `cap_ailment_stacks`)."""

    from junkroan.optimizer.config_rules import derive_config

    return derive_config(pob, prefer_rules=True, **options)


@dataclass(slots=True)
class ConfigWrite:
    """Exactly what one lane write hands `set_config` (the skeleton's bandit and pantheons aside),
    plus what follows the write: the native stack caps, the custom mods, and the fixture vars
    dropped because PoB does not know them."""

    inputs: dict[str, Any]
    conditional: dict[str, Any]
    stack_caps: dict[str, Any]
    custom_mods: Any = ()
    dropped: list[str] = field(default_factory=list)
    enemy_state: dict[str, Any] = field(default_factory=lambda: {"is_boss": "Pinnacle"})
    preserve: str = "none"


def plan_config(current_inputs: Mapping[str, Any], lanes: Any, *, tuned_choices: Mapping[str, Any] | None,
                user_config: Mapping[str, Any] | None, known_vars: set[str] | frozenset[str]) -> ConfigWrite:
    """The merge order of a lane write, pure: preserved numeric inputs < the lane (without
    `enemyIsBoss` and the native overrides) < the tuned choices < the user's own numbers, the
    user's poison count capped by the lane's counted poison stacks, and a var PoB does not know
    dropped instead of preserved (the body of the pipeline's lane write)."""

    remembered = dict(tuned_choices or {})  # the list values PoB judged, re-applied across re-derivations (D60)
    user = dict(user_config or {})  # the user's own numbers win over both
    poison = getattr(lanes, "ailment_stack_caps", {}).get("poison")
    if poison is not None and isinstance(user.get("multiplierPoisonOnEnemy"), (int, float)) and not isinstance(user["multiplierPoisonOnEnemy"], bool):
        user["multiplierPoisonOnEnemy"] = min(int(user["multiplierPoisonOnEnemy"]), poison.counted)
    # Preserve unrelated numeric inputs explicitly, rather than asking
    # `set_config` to preserve them. Native ailment overrides are a
    # baseline-only outcome and must never leak from the previous baseline
    # into the optimistic lane through numeric preservation.
    native_overrides = NATIVE_OVERRIDES
    stack_caps = {key: value for key, value in lanes.conservative.inputs.items() if key in native_overrides}
    if "overrideBleedStackPotential" in stack_caps and "multiplierBleedsOnEnemy" in lanes.conservative.inputs:
        stack_caps["multiplierBleedsOnEnemy"] = lanes.conservative.inputs["multiplierBleedsOnEnemy"]
    preserved: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in current_inputs.items():
        if isinstance(value, bool) or key in native_overrides or key in NEVER_PRESERVED:
            continue
        # a fixture's own config can carry a var name from an older PoB (game mechanics
        # change): preserving it verbatim would fail the `set_config` contract check, which
        # must stay strict for our own code (spec 2026-09-22, requirement 1).
        if key not in known_vars:
            dropped.append(key)
            continue
        preserved[key] = value
    return ConfigWrite(
        inputs={**preserved, **{k: v for k, v in lanes.conservative.inputs.items() if k != "enemyIsBoss" and k not in native_overrides}, **remembered, **user},
        conditional={"inputs": {**preserved, **{k: v for k, v in lanes.optimistic.inputs.items() if k != "enemyIsBoss" and k not in native_overrides}, **remembered, **user}},
        stack_caps=stack_caps,
        custom_mods=getattr(lanes, "custom_mods", ()),
        dropped=dropped,
    )


def write_lanes(pob: Any, skeleton: Any, lanes: Any, *, log: Callable[[str], None]) -> ConfigWrite:
    """Write both lanes into PoB (the pipeline's lane write, `PobLanes.write`):
    `plan_config`, `set_config`, the
    dropped-var log line, the custom mods and the native ailment stack caps."""

    from junkroan.optimizer.config_rules import config_surfaces

    tuned_choices = getattr(skeleton, "tuned_choices", None)
    user_config = skeleton.user_config
    current_inputs = pob.config_inputs() if hasattr(pob, "config_inputs") else {}
    plan = plan_config(current_inputs, lanes, tuned_choices=tuned_choices, user_config=user_config,
                       known_vars=set(config_surfaces()))
    for key in plan.dropped:
        log(f"fixture config var dropped: {key} (unknown to PoB)")
    apply_config_plan(pob, skeleton, plan)
    return plan


def apply_config_plan(pob: Any, skeleton: Any, plan: ConfigWrite) -> None:
    """Put a `plan_config` result into PoB: `set_config`, the custom mods, the native ailment stack caps and the red-line
    marks (the second half of `write_lanes`; the fill step writes a held plan back through it, #1156)."""

    # and one hook the ramp's custom modifiers need (D62 amendment): PoB keeps them in the build
    # XML, not in a config var, and `set_config` rebuilds the config sets and drops them, so they
    # are written again after each apply -- and only for a build that has one (Pride)
    pob.set_config(
        bandit=skeleton.bandit,
        pantheon_major=skeleton.pantheon_major,
        pantheon_minor=skeleton.pantheon_minor,
        enemy_state=plan.enemy_state,
        inputs=plan.inputs,
        conditional=plan.conditional,
        preserve=plan.preserve,
    )
    if hasattr(pob, "export_xml") and hasattr(pob, "load_xml"):
        apply_custom_mods(pob, plan.custom_mods, replace_ailment_stacks=True)
        apply_ailment_stack_caps(pob, plan.stack_caps)
        write_marks(pob)  # last: `apply_custom_mods` strips every `junkroan` block, the marks block included


def write_lanes_preserving_numbers(pob: Any, derived: Any) -> None:
    """The pipeline's lane application reduced to the data already on this build.

    Numeric values (including list choices tuned by PoB) survive, while a removed
    passive gets a fresh conservative proof decision.

    The second lane writer (moved from `tree_hygiene._apply_derived_config`, the dead-leaf proof
    check's), and how it differs from `write_lanes` (#35 Q12, a drift #34 measures): the bandit and
    the pantheons are read back from PoB instead of taken from a skeleton, `set_config` preserves
    the numeric inputs itself (`preserve="numeric"`), and there are no tuned choices, no user
    numbers, no poison cap and no dropped-var check.
    """

    build_state = pob.read_state()
    state = build_state.get("config_state") or {}
    native = {"overrideBleedStackPotential", "overrideIgniteStackPotential"}
    baseline = {key: value for key, value in derived.conservative.inputs.items() if key != "enemyIsBoss" and key not in native}
    conditional = {key: value for key, value in derived.optimistic.inputs.items() if key != "enemyIsBoss" and key not in native}
    stack_caps = {key: value for key, value in derived.conservative.inputs.items() if key in native}
    if "overrideBleedStackPotential" in stack_caps and "multiplierBleedsOnEnemy" in derived.conservative.inputs:
        stack_caps["multiplierBleedsOnEnemy"] = derived.conservative.inputs["multiplierBleedsOnEnemy"]
    pob.set_config(
        bandit=state.get("bandit") or "None",
        pantheon_major=state.get("pantheon_major") or "None",
        pantheon_minor=state.get("pantheon_minor") or "None",
        enemy_state={"is_boss": "Pinnacle"},
        inputs=baseline,
        conditional={"inputs": conditional},
        preserve="numeric",
    )
    # (`apply_custom_mods` / `apply_ailment_stack_caps` were imported here lazily in tree_hygiene;
    # this module imports them at the top)
    apply_custom_mods(pob, getattr(derived, "custom_mods", ()), replace_ailment_stacks=True)
    apply_ailment_stack_caps(pob, stack_caps)
    write_marks(pob, build_state)  # the state read above still holds: `set_config` changes no item and no node


def write_marks(pob: Any, state: Mapping[str, Any] | None = None) -> dict[str, list[str]]:
    """Write the red-line marks block (#1124) of the build's held red lines into each lane: `boss` lines into Baseline,
    `optimistic` lines into Conditional (`apply_mark_blocks`). Returns each lane's block lines, `{}` when nothing is
    written.

    The held lines are `audit.held_mod_entries` of `state` (item affixes, allocated notables / keystones / ascendancy
    nodes, taken mastery effects; flasks are item slots), read from `pob.read_state()` when no `state` is handed in --
    that read is the one extra PoB call, made only when the marks store has a record. No record, or no held line with
    one, or none marked on either lane: no PoB call is made, no block written (rules 4 and 5, D95).

    A `formula` record takes its value from `pob.stats(<the formula's names>)`, read once from the Baseline as the
    lane writer left it, before the block is written: a formula is a number of the build, not of a lane.

    Trace classes (`trace.mark_class`): `mark:<held line, whitespace collapsed>`. Generated = the lanes whose block
    carries the line's mark, counted when the block is built; evaluated = the same count once `load_xml` has put the
    block in PoB's config set. A held line whose record gives it no lane counts 0 / 0."""

    import ast

    from junkroan.optimizer.red_line_marks import LANES, PLACEHOLDER, load_marks
    from junkroan.optimizer.trace import count_marks_evaluated, count_marks_generated

    marks = load_marks()
    if not marks.records:
        return {}
    if not (hasattr(pob, "export_xml") and hasattr(pob, "load_xml")):
        return {}
    if state is None:
        if not hasattr(pob, "read_state"):
            return {}
        state = pob.read_state()
    from junkroan.optimizer.audit import held_mod_entries

    held: list[tuple[str, str]] = []
    for line, source in held_mod_entries(dict(state)):
        held.append((line, source))
        if "\n" in line:  # a node's stat line is looked up whole and by its parts, as the audit reads it
            held.extend((part.strip(), source) for part in line.split("\n") if part.strip())
    held = [(line, source) for line, source in held if marks.has_record(line)]
    if not held:
        return {}
    names: list[str] = []
    for line in dict.fromkeys(line for line, _ in held):
        record = marks.record(line)
        if record and record.get("formula") and any(PLACEHOLDER in entry for key in ("boss_lane", "optimistic_lane") for entry in record[key]):
            names.extend(node.id for node in ast.walk(ast.parse(record["formula"], mode="eval")) if isinstance(node, ast.Name))
    outputs = pob.stats(tuple(dict.fromkeys(names))) if names else None
    blocks = {lane: marks.block_for(held, lane, outputs) for lane in LANES}
    written = {line: sum(1 for lane in LANES if marks.is_marked(line, lane)) for line in dict.fromkeys(line for line, _ in held)}
    if not any(blocks.values()):
        count_marks_generated({line: 0 for line in written})
        count_marks_evaluated({line: 0 for line in written})
        return {}
    count_marks_generated(written)
    apply_mark_blocks(pob, blocks)
    count_marks_evaluated(written)
    return {lane: lines for lane, lines in blocks.items() if lines}


def switch_off_unproven_charges(pob: Any) -> list[str]:
    """The delivered Baseline obeys the audit's own proof for charges (#908): every `use<Kind>Charges` the audit flags as
    "<var> is on in Baseline but ..." is dropped from the Baseline config set together with its `override<Kind>Charges`,
    and the build is loaded back. Returns the vars it switched off (empty: nothing loaded, nothing changed).

    The proof is `audit_conservative_generator_proofs` as it stands, run on the build PoB holds now: the lane a build
    carries was derived before the steps that still change the gems (the Vaal delivery of #802 turned Frenzy's own
    `Speed` from 0.72 to 0.00 on impale_ballista s4), so what the audit will say about the final build is asked here, once,
    and the lane is made to agree with it. Only the Baseline is touched; the optimistic lane stays as derived."""

    from junkroan.optimizer.audit import audit_conservative_generator_proofs, baseline_config_inputs
    from junkroan.optimizer.config_rules import CHARGE_VARS

    xml = pob.export_xml()
    held = baseline_config_inputs(xml) or {}
    if not any(held.get(var) is True for var in CHARGE_VARS):
        return []  # the audit flags only a var that is on: nothing to read, nothing to ask PoB
    findings = audit_conservative_generator_proofs(pob, xml, pob.stats())
    flagged = [var for var in CHARGE_VARS if any(f.detail.startswith(f"{var} is on in Baseline but") for f in findings)]
    if not flagged:
        return []
    names = set(flagged) | {var.replace("use", "override", 1) for var in flagged}  # `useFrenzyCharges` + `overrideFrenzyCharges`
    root = ET.fromstring(xml)
    config = root.find("Config")
    baseline = next((s for s in config.findall("ConfigSet") if (s.get("title") or "").strip().lower() == "baseline"), None) if config is not None else None
    if baseline is None:
        return []
    for node in list(baseline):
        if node.tag == "Input" and node.get("name") in names:
            baseline.remove(node)
    pob.load_xml(ET.tostring(root, encoding="unicode"))
    return flagged


def compute_proof_holders(graph: Any, allocated: set[int], masteries: Mapping[int, int], lanes: Any,
                          build_text: str | Callable[[], str]) -> tuple[dict[int | tuple[int, int], dict[str, object]], dict[str, str]]:
    """The allocated nodes / mastery effects the conservative lane NEEDS, pure (D87): the body of
    `Judging.post_holders` without its PoB read and its log lines. Returns the holders
    and the vars whose rule cannot be re-run here (with the rule's name).

    A node holds a proof when that input's OWN rule, re-run over this same derivation's
    evidence with the node's lines masked out and every other source (an ascendancy node, an
    item, a gem, another passive) left standing, turns the input off or lowers its number.
    Sole ownership is not the test: winter_orb's `usePowerCharges` stands on the SUM of an
    Occultist ascendancy line and a Caster Mastery line, so neither line is sole -- and yet
    removing the mastery alone cost the build 14% under honest lanes (v2's replay,
    95,411 -> 81,692). Lines whose only owner is something a tree move cannot remove are
    fixed evidence: they are simply never masked.

    `build_text` is the build's whole mod text, or a callable that reads it: it is read only when a
    rule cannot be re-run (the sole-proof fallback), and then once.
    """

    proof_lines: Mapping[str, tuple[str, ...]] = getattr(lanes.conservative, "proof_lines", {}) or {}
    selected = masteries

    def normalize(line: object) -> str:
        return str(line).strip().lower()

    vars_of_line: dict[str, set[str]] = {}
    for var, lines in proof_lines.items():
        for line in lines:
            vars_of_line.setdefault(normalize(line), set()).add(var)

    # what each allocated node / selected mastery effect contributes to the build text, counted:
    # two nodes carrying the same line are two proofs, and masking one must leave the other
    owned: dict[int | tuple[int, int], Counter] = {}
    for node_id in sorted(allocated):
        node = graph.node(node_id)
        if node is None:
            continue
        for line in node.stats or ():
            if normalize(line) in vars_of_line:
                owned.setdefault(node_id, Counter())[normalize(line)] += 1
        effect_id = selected.get(node_id)
        if effect_id is not None:
            for candidate_id, lines in node.mastery_effects or ():
                if candidate_id == effect_id:
                    for line in lines or ():
                        if normalize(line) in vars_of_line:
                            owned.setdefault((node_id, effect_id), Counter())[normalize(line)] += 1

    recheck = getattr(lanes, "recheck", None)
    inputs_now = lanes.conservative.inputs
    holders: dict[int | tuple[int, int], dict[str, object]] = {}
    undecidable: dict[str, str] = {}
    source_counts: Counter | None = None
    for holder, lines in owned.items():
        touched = sorted({var for line in lines for var in vars_of_line.get(line, ())})
        changed: dict[str, object] = {}
        for var in touched:
            result = recheck(var, lines) if callable(recheck) else None
            if result is None or result.inputs is None:
                # the rule cannot be re-run here: fall back to the sole-proof test (v2)
                if source_counts is None:
                    text = build_text() if callable(build_text) else build_text
                    source_counts = Counter(normalize(line) for line in text.splitlines() if line.strip())
                undecidable[var] = result.rule if result is not None else "unknown rule"
                if all(source_counts[normalize(line)] == 1 for line in proof_lines.get(var, ())) and \
                        {normalize(line) for line in proof_lines.get(var, ())} <= set(lines):
                    changed[var] = (inputs_now.get(var), None)
                continue
            for key in result.keys:
                before, after = inputs_now.get(key), result.inputs.get(key)
                if worse_input(before, after):
                    changed[key] = (before, after)
        if changed:
            holders[holder] = changed
    return holders, undecidable


def tree_selection(state: Mapping[str, Any]) -> tuple[set[int], dict[int, int]]:
    """The allocated passives and the selected mastery effects (node -> effect) of a `read_state`."""

    tree_state = state.get("tree_state") or {}
    allocated = {int(node) for node in tree_state.get("user_allocated_node_ids") or ()}
    selected: dict[int, int] = {}
    for raw in tree_state.get("mastery_effect_ids") or ():
        node, _, effect = str(raw).partition(":")
        if node.isdigit() and effect.isdigit():
            selected[int(node)] = int(effect)
    return allocated, selected


def proof_holder_lines(graph: Any, holders: Mapping[Any, Mapping[str, object]], undecidable: Mapping[str, str], seconds: float) -> list[str]:
    """The log lines written after posting the holders (`Judging.post_holders`)."""

    lines: list[str] = []
    if holders:
        labels = []
        for holder, inputs in sorted(holders.items(), key=lambda item: str(item[0])):
            node_id = holder[0] if isinstance(holder, tuple) else holder
            node = graph.node(node_id)
            effect = f" [effect {holder[1]}]" if isinstance(holder, tuple) else ""
            shown = ", ".join(f"{key} {pair[0]!r} -> {pair[1]!r}" if isinstance(pair, tuple) else str(key)
                              for key, pair in sorted(inputs.items()))
            labels.append(f"{node.name if node else node_id}{effect} -> {shown}")
        lines.append(f"proof holders: {'; '.join(labels)} ({seconds * 1000:.0f} ms)")
    for var, rule in sorted(undecidable.items()):
        lines.append(f"proof holders: {var}: not decidable without PoB ({rule})")
    return lines


def main_group(pob: Any) -> tuple[list[str], bool, tuple[tuple[str, int], ...]]:
    """The main socket group as PoB holds it: its gem names, whether its active skill is
    triggered (Spellslinger, Cast when Damage Taken, a trigger craft ...), and the link's PoB skill
    ids with their levels. A triggered skill is not used by the player. The gems come from PoB and
    not from the skeleton because a pick being tried is on the build before it is on the skeleton.

    The levels are what a per-gem cost needs (Trauma's per-stack damage is a number of the gem's
    own level)."""

    def is_triggered(group: dict) -> bool:
        return any(isinstance(e, dict) and e.get("triggered") is True for e in group.get("active_skill_entries") or [])

    state = pob.read_state()
    skills = state.get("skills_state") or {}
    main_id = skills.get("main_socket_group_id") or (state.get("build_state") or {}).get("main_socket_group_id")
    groups = [g for g in (skills.get("socket_groups") or []) if isinstance(g, dict)]
    main = next((g for g in groups if g.get("socket_group_id") == main_id), None) if main_id else (groups[0] if groups else None)
    entries = [g for g in (main or {}).get("gems") or [] if isinstance(g, dict)]
    gems = [str(g.get("gem_name") or g.get("name") or "") for g in entries]
    gem_levels = tuple((str(g.get("skill_id") or ""), int(g["level"]) if isinstance(g.get("level"), (int, float)) else 20) for g in entries if g.get("skill_id"))
    # PoB names no main group (a build mid-apply): any triggered skill means the player is not the one using it
    triggered = is_triggered(main) if main is not None and main_id else any(is_triggered(g) for g in groups)
    return gems, triggered, gem_levels


def trauma_stacks(pob: Any) -> float:
    """The Trauma stacks the conservative lane holds (PoB's `traumaStacks`, written by the
    stack-option rules), 0 for a build that applies no Trauma."""

    if not hasattr(pob, "config_inputs"):
        return 0.0  # a stand-in session in the unit harnesses: no config surface at all
    raw = pob.config_inputs().get("traumaStacks")
    return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0.0


def lane_memo(lanes: Any) -> tuple[dict, dict, dict, dict]:
    return (dict(lanes.conservative.inputs), dict(lanes.optimistic.inputs),
            dict(lanes.conservative.reasons), dict(lanes.optimistic.reasons))


def restore_lanes(lanes: Any, memo: tuple[dict, dict, dict, dict]) -> None:
    for target, saved in ((lanes.conservative.inputs, memo[0]), (lanes.optimistic.inputs, memo[1]),
                          (lanes.conservative.reasons, memo[2]), (lanes.optimistic.reasons, memo[3])):
        target.clear()
        target.update(saved)


def tune_choices(pob: Any, skeleton: Any, lanes: Any, *, objective: Objective, write: Callable[[Any, Any], None],
                 log: Callable[[str], None], guard: bool = False,
                 tie_break: Callable[[Mapping[str, object]], float] = bossing_defence,
                 tie_keys: tuple[str, ...] = MAX_HIT_KEYS) -> dict[str, str]:
    """List-type skill options (stance, exposure type, ...): try every value,
    keep the one PoB scores best. A choice, so judged, not assumed (D24).

    `guard` (set by `_finish`, D66): each choice is also compared with the state it started from,
    and a value that is the best of its list but still less feasible than the build had been is
    put back -- the delivered build is never less feasible than the fixed point the loop reached.
    The loop's own `_tune_lanes` does not guard: it is allowed to tune into a violation and then
    buy the floor back with the tree (D60), because its result is judged by a whole pass after it.

    The judged values are remembered on the skeleton (`tuned_choices`, D60), so the loop keeps
    them across its re-derivations; a var under trial is dropped from that memory for the length
    of its own trials, or the lane write would merge the remembered value over the value being
    tried and every tuning after the first would compare a build with itself and keep the first
    value of the list (the reverted first attempt at D60: bleed_bow 127.7 -> 56.9, burning_arrow
    214.4 -> 135.2).

    `tie_break` reads the number that ranks two values the objective scores alike (from the stats of `tie_keys`); the
    default is the bossing defence, the fill step (`tune_given_choices`) passes TotalEHP.

    `write(skeleton, lanes)` writes the lanes (a `LaneSource.write`, or `write_lanes`)."""

    from junkroan.optimizer.pipeline import broken_floors, keep_if_feasible  # the D66 rule; pipeline imports this module

    derived = lanes
    chosen: dict[str, str] = {}
    remembered = getattr(skeleton, "tuned_choices", None)
    for var, values in derived.choices.items():
        followers = [f"conditionEnemy{e}Exposure" for e in ("Fire", "Cold", "Lightning")] if var == "elementalArmyExposureType" else []
        base = None
        if guard:
            write(skeleton, derived)  # the choices decided so far, so the comparison is with this build
            base_stats = pob.stats(objective.stat_keys)
            base = (objective.score(base_stats), objective.violations(base_stats),
                    {k: (derived.conservative.inputs.get(k), derived.optimistic.inputs.get(k), dict(remembered or {}).get(k)) for k in (var, *followers)})
        if remembered is not None:
            for key in (var, *followers):
                remembered.pop(key, None)  # the value under trial wins over the one this var was left at
        best = None
        for value in values:
            derived.conservative.inputs[var] = value
            derived.optimistic.inputs[var] = value
            write(skeleton, derived)
            stats = pob.stats((*objective.stat_keys, *tie_keys))
            score = (objective.score(stats), tie_break(stats))  # ties (stance: 0 DPS) go to the safer value
            if best is None or score > best[0]:
                best = (score, value)
        if best is not None and base is not None and not keep_if_feasible(base[0], best[0][0]):
            # the best value of the list is still worse than the build was: keep what it had (D66)
            derived.conservative.inputs[var] = derived.optimistic.inputs[var] = best[1]
            write(skeleton, derived)
            note = broken_floors(objective, base[1], pob.stats(objective.stat_keys))
            for key, (cons, opt, was) in base[2].items():
                for target, value in ((derived.conservative.inputs, cons), (derived.optimistic.inputs, opt)):
                    if value is None:
                        target.pop(key, None)
                    else:
                        target[key] = value
                if remembered is not None and was is not None:
                    remembered[key] = was
            write(skeleton, derived)
            log(f"reverted: choice {var} = {best[1]!r} broke {note}")
            continue
        if best is not None:
            derived.conservative.inputs[var] = derived.optimistic.inputs[var] = best[1]
            derived.conservative.reasons[var] = derived.optimistic.reasons[var] = f"best of {values} by objective"
            chosen[var] = best[1]
            if remembered is not None:
                remembered[var] = best[1]  # re-applied by every reconfigure until it is judged again (D60)
            if var == "elementalArmyExposureType":
                # the chosen element's exposure is applied by the support; the others are not
                for element in ("Fire", "Cold", "Lightning"):
                    key = f"conditionEnemy{element}Exposure"
                    on = str(best[1]) == element
                    derived.conservative.inputs[key] = derived.optimistic.inputs[key] = on
                    if remembered is not None:
                        remembered[key] = on
                    derived.conservative.reasons[key] = derived.optimistic.reasons[key] = f"{'follows' if on else 'off:'} Elemental Army exposure type {best[1]}"
    if chosen:
        write(skeleton, derived)
    return chosen


def tune_given_choices(pob: Any, skeleton: Any, lanes: Any, choices: Mapping[str, list[str]], *, objective: Objective,
                       write: Callable[[Any, Any], None], log: Callable[[str], None]) -> dict[str, str]:
    """`tune_choices` over the given list choices instead of the ones the lanes carry (#1156): the fill step tries a candidate
    gem's own config vars (Flesh and Stone under Blood and Sand stance), each value judged by PoB. A tie in the objective
    goes to the value with the higher TotalEHP, the number the fill step keeps a gem by."""

    return tune_choices(pob, skeleton, replace(lanes, choices=dict(choices)), objective=objective, write=write, log=log,
                        tie_break=lambda stats: float(stats.get("TotalEHP") or 0.0), tie_keys=("TotalEHP",))


# -- layer 2: the judging context ------------------------------------------------------------------

# The refreshes a view can follow. Each is named data: which view follows which refresh is a quirk
# of today's pipeline that a test pins (#35 Q1), not an accident of a loop.
SELF_COST = "self_cost"
CASTABILITY = "castability"
RAMP = "ramp"


@dataclass(frozen=True, slots=True)
class View:
    """One copy of the full objective a component keeps: how it is cut from the full objective when
    the component is built, which refreshes reach it afterwards, and whether it receives the proof
    holders."""

    name: str
    cut: Callable[[Objective], Objective]
    follows: frozenset[str]
    receives_holders: bool


def _without_movement_and_sustain(objective: Objective) -> Objective:
    # movement speed is a gear floor (boots, D28), and resource sustain is cheaper from gear than
    # from the tree: the construction tree optimizes without both (BuildPipeline.run)
    return objective.without("EffectiveMovementSpeedMod").without_sustain()


def _without_movement(objective: Objective) -> Objective:
    return objective.without("EffectiveMovementSpeedMod")


def _identity(objective: Objective) -> Objective:
    return objective


VIEWS: Mapping[str, View] = {
    # the construction tree: without movement, without sustain; follows every refresh, receives holders
    "tree_construction": View("tree_construction", _without_movement_and_sustain, frozenset({SELF_COST, CASTABILITY, RAMP}), True),
    # the loop's tree: without movement; follows every refresh, receives holders
    "tree": View("tree", _without_movement, frozenset({SELF_COST, CASTABILITY, RAMP}), True),
    # the gear filler: the full objective; follows every refresh, like the trees, so LootGear /
    # WishlistGear rank rolls under the same self-cost, castability and ramp contexts the loop
    # judges with (#34 fact 1); does not receive holders
    "gear": View("gear", _identity, frozenset({SELF_COST, CASTABILITY, RAMP}), False),
}


class _Unset:
    """Nothing attached / never set: what a `Judging` field holds before its first write (the
    objective, the main skill's tags and gem levels). It is falsy; `main_tags` still UNSET means
    `run` has not reached the config lanes yet, so there is no self-cost to price (Q5)."""

    _instance: "_Unset | None" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET: Any = _Unset()

# mark scopes
MOVE = "move"  # everything the judging context holds (the loop's move snapshot)
TREE = "tree"  # the objective, the trees' objectives and their holders (the tree optimizer's restore hook)
CASTABILITY_SCOPE = "castability"  # the frozen skill-cost context alone


@dataclass(frozen=True, slots=True)
class Mark:
    """What `Judging.mark` took: restored by `Judging.restore` without a PoB call."""

    scope: str
    parts: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Opening:
    """What `Judging.open` leaves: the lanes of its second write, and whether the main skill is
    triggered (the main group read)."""

    lanes: Any
    triggered: bool


class Rejudge(Protocol):
    """The generator's port (#42 B4): re-judge the build after a pick -- in full (`Judging.rejudge`)
    or the costs only (`Judging.refresh_costs`) -- with the generator's castability context, and
    return the full objective. Always called with both keywords."""

    def __call__(self, *, full: bool, castability_context: "CastabilityContext | None") -> "Objective | None":  # pragma: no cover - interface
        ...


class LaneSource:
    """Port: the two lanes as PoB holds them. `read` derives them from the build, `write` writes
    them into PoB; `snapshot` / `restore` are the XML round trip that carries them (a trial)."""

    def read(self) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def write(self, skeleton: Any, lanes: Any) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def snapshot(self) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def restore(self, snapshot: Any) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def written(self) -> Any:
        """The last config write as `(skeleton, plan)`, or None when this source holds none (a trial's way back, #1156)."""

        return None

    def rewrite(self, skeleton: Any, plan: Any) -> None:  # pragma: no cover - interface
        """Write a plan `written()` returned back into PoB."""

        raise NotImplementedError


class ContextReads:
    """Port: the reads the objective's contexts are built from (minion counts, the main group and
    its self-cost, castability, ramp, proof holders)."""

    def minion_counts(self, skeleton: Any) -> bool:  # pragma: no cover - interface
        """Refresh the skeleton's instance counts (D49); True when they changed."""
        raise NotImplementedError

    def main_group(self) -> tuple[list[str], bool, tuple]:  # pragma: no cover - interface
        raise NotImplementedError

    def self_cost(self, main_tags: Any, triggered: bool, gems: list[str], gem_levels: tuple) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def castability(self) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    def ramp(self, skeleton: Any, lanes: Any) -> dict[str, object]:  # pragma: no cover - interface
        raise NotImplementedError

    def holders(self, lanes: Any, graph: Any) -> tuple[dict, dict]:  # pragma: no cover - interface
        raise NotImplementedError


class PobLanes(LaneSource):
    """The production LaneSource over a PobSession."""

    def __init__(self, pob: Any, *, log: Callable[[str], None] = lambda _m: None) -> None:
        self._pob, self._log = pob, log
        self._written: tuple[Any, ConfigWrite] | None = None

    @property
    def pob(self) -> Any:
        return self._pob

    def log(self, message: str) -> None:
        self._log(message)

    def read(self) -> Any:
        return read_lanes(self.pob)

    def write(self, skeleton: Any, lanes: Any) -> None:
        self._written = (skeleton, write_lanes(self.pob, skeleton, lanes, log=self.log))

    def written(self) -> Any:
        return self._written

    def rewrite(self, skeleton: Any, plan: Any) -> None:
        apply_config_plan(self.pob, skeleton, plan)
        self._written = (skeleton, plan)

    def snapshot(self) -> Any:
        return self.pob.export_xml()

    def restore(self, snapshot: Any) -> None:
        self.pob.load_xml(snapshot)


class PobReads(ContextReads):
    """The production ContextReads over a PobSession: every read in the order `BuildPipeline` made it."""

    def __init__(self, pob: Any, *, gems: Any, log: Callable[[str], None] = lambda _m: None, metrics: Any = None) -> None:
        self._pob, self._gems, self._log, self._metrics = pob, gems, log, metrics

    @property
    def pob(self) -> Any:
        return self._pob

    @property
    def gems(self) -> Any:
        """The rails' gem levels and qualities (`Rails.gems`)."""
        return self._gems

    @property
    def metrics(self) -> Any:
        return self._metrics

    def log(self, message: str) -> None:
        self._log(message)

    def minion_counts(self, skeleton: Any) -> bool:
        counts_before = dict(skeleton.gem_counts)
        gems = self.gems
        # The link PoB holds, not the skeleton's: a pick being tried is on the build before it is on the skeleton (as in
        # `main_group`). Refreshing the skeleton's own link here re-applied it over the trial, so the support re-pick's
        # `full` re-derivation scored the skeleton's link for every candidate (#550: 130,021 -> 130,021 on the spectre witness).
        # A Vaal gem PoB holds is the skeleton's plain gem (`Skeleton.__post_init__`, #802): the held link is named the
        # skeleton's way before it is compared, else the build's own Vaal link read as a trial and the counts were
        # derived for the Vaal skill (Vaal Absolution has no limit stat: 3 -> 1, #1024).
        from junkroan.search.vaal_twin import plain_of_vaal

        held = [plain_of_vaal(name) or name for name in main_group(self.pob)[0]] if callable(getattr(self.pob, "read_state", None)) else []
        skeleton.refresh_minion_counts(self.pob, gem_level=gems.level, gem_quality=gems.quality,
                                       main_quality=gems.main_quality, main_link=held if held and held != list(skeleton.main_link) else None,
                                       log=self.log)  # limits move with the tree (D49)
        return counts_before != skeleton.gem_counts

    def main_group(self) -> tuple[list[str], bool, tuple]:
        return main_group(self.pob)

    def self_cost(self, main_tags: Any, triggered: bool, gems: list[str], gem_levels: tuple) -> Any:
        from junkroan.optimizer.config_rules import build_text
        from junkroan.optimizer.self_cost import context_for

        return context_for(build_text(self.pob), main_tags, triggered, gems, gem_levels=gem_levels, trauma_stacks=trauma_stacks(self.pob))

    def castability(self) -> Any:
        from junkroan.optimizer.castability import castability_context

        return castability_context(self.pob, metrics=self.metrics)

    def ramp(self, skeleton: Any, lanes: Any) -> dict[str, object]:
        from junkroan.optimizer.ramp import context_changes
        from junkroan.search.generator import current_part_name

        return context_changes(skeleton.main_link, current_part_name(self.pob, skeleton.main_link[0]), lanes.conservative.inputs, lanes.stack_caps, ailment_stack_caps=lanes.ailment_stack_caps)

    def holders(self, lanes: Any, graph: Any) -> tuple[dict, dict]:
        pob = self.pob
        allocated, selected = tree_selection(pob.read_state())

        def text() -> str:
            from junkroan.optimizer.config_rules import build_text

            return build_text(pob, graph)

        return compute_proof_holders(graph, allocated, selected, lanes, text)


class Judging:
    """What a build is judged under right now, and the operations callers perform on it.

    State: the full objective, the castability context, the main skill's tags and gem levels, and
    the attached views -- one per role of `VIEWS`: the construction tree, the loop's tree, the gear
    filler -- with their proof holders. Every PoB call goes through `lanes` (a `LaneSource`) or
    `reads` (a `ContextReads`), in the order `BuildPipeline` made them; the views are Python objects.
    """

    def __init__(self, lanes: LaneSource, reads: ContextReads, *, objective: Any = UNSET,
                 log: Callable[[str], None] | None = None) -> None:
        self.lanes = lanes
        self.reads = reads
        self.log = log or (lambda _m: None)
        self.objective: Any = objective
        self.main_tags: Any = UNSET
        self.main_gem_levels: Any = UNSET
        self.castability_context: Any = None
        self._views: dict[str, Any] = {}

    # -- the views ---------------------------------------------------------------------------

    def attach(self, role: str, view: Any) -> None:
        """Attach `view` at `role` (a key of `VIEWS`), replacing what was there; None detaches."""

        if role not in VIEWS:
            raise ValueError(f"unknown view role {role!r}: one of {', '.join(VIEWS)}")
        if view is None:
            self._views.pop(role, None)
        else:
            self._views[role] = view

    def view(self, role: str) -> Any:
        """The view attached at `role`, or None."""

        return self._views.get(role)

    def _attached(self) -> list[tuple[str, Any]]:
        """The attached views with their roles, in `VIEWS` order (tree_construction, tree, gear)."""

        return [(role, self._views[role]) for role in VIEWS if role in self._views]

    def trees(self) -> tuple:
        """The attached tree views: the construction tree, then the loop's tree."""

        return tuple(view for role, view in self._attached() if role in ("tree_construction", "tree"))

    def cut(self, role: str) -> Objective:
        """The objective a view at `role` is built with, cut from the full objective as it is now."""

        return VIEWS[role].cut(self.objective)

    def followers(self, refresh: str) -> list[Any]:
        """The attached views a refresh reaches, in the order the pipeline wrote them: the roles in
        `VIEWS` order -- the construction tree, the loop's tree, then the gear filler."""

        return [view for role, view in self._attached() if refresh in VIEWS[role].follows]

    def holder_targets(self) -> tuple:
        return tuple(view for role, view in self._attached() if VIEWS[role].receives_holders)

    def _install(self, refresh: str, change: Callable[[Objective], Objective]) -> None:
        self.objective = change(self.objective)
        for view in self.followers(refresh):
            view.objective = change(view.objective)

    # -- the operations ----------------------------------------------------------------------

    def rejudge(self, skeleton: Any, *, castability: Any = None) -> Objective:
        """Re-judge after a move: the instance counts, the
        lanes derived and written again, the self-cost, the castability when the counts moved (or
        the given context), the ramp, the proof holders. Self-cost before ramp (#35 Q11)."""

        from junkroan.optimizer.ramp import with_ramp

        counts_changed = self.reads.minion_counts(skeleton)
        lanes = self.lanes.read()  # our own numbers are never authored: derived again (poison count, stack caps)
        self.lanes.write(skeleton, lanes)
        self.refresh_self_cost()
        if counts_changed:
            self.refresh_castability()
        elif castability is not None:
            self.refresh_castability(castability)
        # The ramp follows the lanes: a node or rare can change either stack
        # caps or an ailment's application rate, so update every objective on
        # every re-derivation rather than only when a skill option exists.
        changes = self.reads.ramp(skeleton, lanes)
        self._install(RAMP, lambda objective: with_ramp(objective, **changes))
        self.post_holders(lanes)
        return self.objective

    def refresh_costs(self, *, castability: Any = None) -> Objective:
        """The costs only: the self-cost, and the given
        castability context."""

        self.refresh_self_cost()
        if castability is not None:
            self.refresh_castability(castability)
        return self.objective

    def refresh_self_cost(self) -> None:
        """The self-costs of the build as it now stands, into every objective in use. Derived once
        from the empty build (the old behaviour) it could only ever see what the skeleton brought:
        the Chaos Mastery the tree went on to take seven times on soulrend s1, and the Sacrifice
        support a pick added to poison_spark, were both free in the numbers that judged them."""

        from junkroan.optimizer.self_cost import with_self_cost

        if self.main_tags is UNSET:
            return  # `run` has not reached the config lanes yet: there is no main skill to price (#35 Q5)
        gems, triggered, gem_levels = self.reads.main_group()
        self.main_gem_levels = gem_levels
        ctx = self.reads.self_cost(self.main_tags, triggered, gems, gem_levels)
        self._install(SELF_COST, lambda objective: with_self_cost(objective, ctx))

    def refresh_castability(self, context: Any = None) -> None:
        """Install one frozen skill-cost read into every objective in use (the gear filler's too)."""

        from junkroan.optimizer.castability import with_castability_floors

        self.castability_context = context or self.reads.castability()
        frozen = self.castability_context
        # the frozen context is always given here, so the floors read nothing from PoB
        self._install(CASTABILITY, lambda objective: with_castability_floors(None, objective, context=frozen))

    def post_holders(self, lanes: Any, targets: Any = None) -> None:
        """Give every tree the allocated nodes / mastery effects the conservative lane NEEDS (D87,
        `compute_proof_holders`); `targets` defaults to the attached trees."""

        trees = self.holder_targets() if targets is None else tuple(targets)
        graph = trees[0].graph if trees else None
        if graph is None:
            for tree in trees:
                tree.proof_holders = {}
            return
        t0 = time.perf_counter()
        holders, undecidable = self.reads.holders(lanes, graph)
        for tree in trees:
            tree.proof_holders = copy.deepcopy(holders)
        for line in proof_holder_lines(graph, holders, undecidable, time.perf_counter() - t0):
            self.log(line)

    def refresh_main_group(self) -> tuple[list[str], bool, tuple]:
        """The main group read again: its gem names, whether its
        active skill is triggered, and the link's gem levels -- which are kept, as the self-cost
        reads them."""

        gems, triggered, levels = self.reads.main_group()
        self.main_gem_levels = levels
        return gems, triggered, levels

    def hold_config(self, skeleton: Any) -> Callable[[], None]:
        """Take the config as the last lane write left it; the returned closure writes it back (#1156: a fill trial tunes
        config choices into PoB and a rejected candidate must leave none behind). A no-op when nothing was written."""

        held = self.lanes.written()
        if held is None:
            return lambda: None
        held_skeleton, plan = held

        def restore() -> None:
            self.lanes.rewrite(held_skeleton, plan)

        return restore

    def rejudger(self, skeleton: Any) -> Rejudge:
        """The generator's port for `skeleton`: `full` re-judges (`rejudge`, with the given castability
        context), otherwise the costs only (`refresh_costs`). Both keywords are required; their
        names are also what today's generator looks for in the callback's signature."""

        def rejudge(*, full: bool, castability_context: "CastabilityContext | None") -> Objective:
            if full:
                return self.rejudge(skeleton, castability=castability_context)
            return self.refresh_costs(castability=castability_context)

        return rejudge

    # -- the lanes and the opening -----------------------------------------------------------

    def relane(self, skeleton: Any) -> Any:
        """Derive the lanes from the build and write them, and nothing else (the `derive_config` +
        lane-write pair of `_finish` and `_tune_lanes`): no ramp, no self-cost, no proof
        holders reach the objective or a view (#35 Q4). Returns the lanes."""

        lanes = self.lanes.read()
        self.lanes.write(skeleton, lanes)
        return lanes

    def open(self, skeleton: Any) -> Opening:
        """`run`'s opening: the lanes derived and written TWICE (#35 Q10), then `open_contexts` with
        the second lanes. Writes the full objective only, never a view."""

        self.relane(skeleton)
        # A cap can depend on ordinary conservative inputs (bleed chance,
        # attack rate, duration). Set those once, then derive the cap from the
        # lane it will actually accompany; subsequent re-derivations strip
        # only the D78 cap and are stable.
        lanes = self.relane(skeleton)
        triggered = self.open_contexts(skeleton, lanes)
        return Opening(lanes, triggered)

    def open_contexts(self, skeleton: Any, lanes: Any) -> bool:
        """The opening's contexts on the full objective: the ramp, the main skill's tags, the main
        group read (its gem levels kept), the self-cost. Returns whether the main skill is triggered.

        RAMP BEFORE SELF-COST here; `rejudge` does the self-cost before the ramp (#35 Q11). It writes
        the FULL objective only, never a view: the old opening ran before any view existed, and a
        second `run` on the same pipeline must not refresh the previous run's views."""

        from junkroan.optimizer.ramp import with_ramp
        from junkroan.optimizer.self_cost import with_self_cost
        from junkroan.search.hypothesis import active_gems

        # the ramp rail (D39) needs what the build itself says about its stack multipliers:
        # the skill part's stage count and withered-per-hit from the lane; fixed from here on
        changes = self.reads.ramp(skeleton, lanes)
        self.objective = with_ramp(self.objective, **changes)
        # self-costs on use ("Lose 10% of Life when you use a Chaos Skill"): PoB cannot see them, the net-recovery floor does
        self.main_tags = frozenset(active_gems().get(skeleton.main_link[0].lower(), {}).get("tag_keys") or [])
        gems, triggered, levels = self.reads.main_group()
        self.main_gem_levels = levels
        self.objective = with_self_cost(self.objective, self.reads.self_cost(self.main_tags, triggered, gems, levels))
        return triggered

    # -- lending and re-cutting the views ----------------------------------------------------

    @contextmanager
    def lend(self, role: str, objective: Objective) -> Iterator[Any]:
        """The view at `role` holds `objective` inside the block and gets its own objective back on
        exit, also on an exception (`_joint_round`'s objective swaps). LookupError when nothing is
        attached at `role`.

        A refresh made during the lend reaches the LENT objective and is DROPPED when the lend ends:
        the view gets back exactly the objective it had before (#35 Q7, a drift #34 measures)."""

        view = self.view(role)
        if view is None:
            raise LookupError(f"no view attached at {role!r}")
        own = view.objective
        view.objective = objective
        try:
            yield view
        finally:
            view.objective = own

    def recut(self) -> None:
        """Every attached view gets its role's cut of the full objective as it is now (#35 Q8: the
        replay bench re-cuts its views after its last re-judge; only the bench calls this)."""

        for role, view in self._attached():
            view.objective = VIEWS[role].cut(self.objective)

    # -- marks -------------------------------------------------------------------------------

    def mark(self, scope: str) -> Mark:
        """What `restore` puts back, taken without a PoB call. TREE: the objective, and every tree's
        objective and holders, and the gear filler's objective when attached (it follows the ramp and the
        self-cost refreshes, #34); no castability refold (#35 Q6).
        CASTABILITY: the frozen skill-cost context. MOVE: all of it, the gear filler's objective and
        the main gem levels included."""

        if scope == TREE:
            gear = self.view("gear")
            return Mark(TREE, {"objective": self.objective,
                               "gear": (gear, gear.objective) if gear is not None else None,
                               "trees": [(tree, tree.objective, copy.deepcopy(tree.proof_holders)) for tree in self.trees()]})
        if scope == CASTABILITY_SCOPE:
            return Mark(CASTABILITY_SCOPE, {"castability": self.castability_context})
        if scope == MOVE:
            gear = self.view("gear")
            return Mark(MOVE, {
                "gear": (gear, gear.objective) if gear is not None else None,
                "trees": [(tree, tree.objective, copy.deepcopy(getattr(tree, "proof_holders", None))) for tree in self.trees()],
                "objective": self.objective,
                "main_gem_levels": self.main_gem_levels,
                "castability": self.castability_context,
            })
        raise ValueError(f"unknown mark scope {scope!r}: one of {MOVE}, {TREE}, {CASTABILITY_SCOPE}")

    def restore(self, mark: Mark, *, only: Any = None) -> None:
        """Put back what `mark` took (the parts named in `only`, or all of them), without a PoB call:
        an XML restore includes its lanes, so nothing is derived again."""

        parts = mark.parts if only is None else {name: value for name, value in mark.parts.items() if name in set(only)}
        if mark.scope == TREE:
            objective = parts.get("objective")
            if isinstance(objective, Objective):
                self.objective = objective
            if parts.get("gear") is not None:
                gear, gear_objective = parts["gear"]
                gear.objective = gear_objective
            for tree, saved_objective, holders in parts.get("trees") or ():
                tree.objective = saved_objective
                tree.proof_holders = copy.deepcopy(holders)
            return
        if mark.scope == CASTABILITY_SCOPE:
            if parts.get("castability") is not None:
                self.refresh_castability(parts["castability"])
            return
        if parts.get("gear") is not None:
            gear, objective = parts["gear"]
            gear.objective = objective
        for tree, objective, holders in parts.get("trees") or ():
            tree.objective = objective
            if holders is not None:
                tree.proof_holders = copy.deepcopy(holders)
        if "objective" in parts:
            self.objective = parts["objective"]
        if "main_gem_levels" in parts:
            self.main_gem_levels = parts["main_gem_levels"]
        if parts.get("castability") is not None:
            self.refresh_castability(parts["castability"])

    # -- a trial -----------------------------------------------------------------------------

    def trial(self) -> "_Trial":
        """A context manager for a what-if on the real build (the enabler hook): the lanes' XML is
        exported on entry and loaded back on exit, whatever happens inside. It writes no view: a
        trial scores new lanes under the contexts the views already hold (#35 Q9)."""

        return _Trial(self.lanes)


class _Trial:
    def __init__(self, lanes: LaneSource) -> None:
        self._lanes = lanes
        self._snapshot: Any = None

    def __enter__(self) -> "_Trial":
        self._snapshot = self._lanes.snapshot()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._lanes.restore(self._snapshot)


__all__ = [
    "CASTABILITY", "CASTABILITY_SCOPE", "ConfigWrite", "ContextReads", "Judging", "LaneSource", "MOVE", "Mark",
    "Opening", "PobLanes", "PobReads", "RAMP", "Rejudge", "SELF_COST", "TREE", "UNSET", "VIEWS", "View",
    "compute_proof_holders", "lane_memo", "main_group", "plan_config", "proof_holder_lines", "read_lanes",
    "apply_config_plan", "restore_lanes", "switch_off_unproven_charges", "trauma_stacks", "tree_selection", "tune_choices", "tune_given_choices", "worse_input", "write_lanes", "write_lanes_preserving_numbers",
]
