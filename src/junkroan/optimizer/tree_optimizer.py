"""Greedy passive tree allocation with PoB as the objective function.

Each round:
  1. enumerate candidates from the pure-Python graph (frontier nodes at cost 1,
     payoff nodes within max_depth);
  2. evaluate them all in one PoB round trip (trial_stats), each trial being
     "allocate this node and its path" (masteries: one trial per effect);
  3. pick the best by (constraint violation, objective gain per point);
  4. apply it for real (mutate_nodes) and repeat until the point budget is spent.

No game knowledge lives here. The optimizer only knows graph connectivity and
what PoB says about each trial.
"""

from __future__ import annotations

import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from junkroan.optimizer.objective import Objective, Score, better_score, bossing_defence
from junkroan.optimizer.red_line_marks import PLACEHOLDER, RedLineMarks, load_marks
from junkroan.optimizer.seeds import PURPOSE_TREE_TIES, tie_rank
from junkroan.optimizer.trace import TRACE
from junkroan.optimizer.tree_trace import ATTRIBUTE_CAP_EXCEEDED, FORBIDDEN_NODE_TEXT
from junkroan.optimizer.tree_graph import Candidate, Links, TreeGraph
from junkroan.pob.session import PobSession

TAG_DATA_ROOT = Path(__file__).resolve().parents[1] / "pob" / "tag_data"
CLUSTER_FACETS = ("ailment", "charge", "mechanic", "scaling_stat")  # facets a cluster of notables is grouped by
_ATTRIBUTE_REQUIREMENT = re.compile(r"^\+30 to (?:Strength|Dexterity|Intelligence)$", re.IGNORECASE)


def is_attribute_requirement_node(node: "TreeNode | None") -> bool:
    """Identify the one +30 requirement payment from the passives corpus text."""

    return bool(node and any(_ATTRIBUTE_REQUIREMENT.fullmatch(str(line).strip()) for line in node.stats))


def attribute_requirement_node_ids(graph: "TreeGraph") -> frozenset[int]:
    """Return corpus node ids whose own passive text is a +30 attribute line."""

    return frozenset(node_id for node_id, node in graph.nodes.items() if is_attribute_requirement_node(node))


@lru_cache(maxsize=1)
def _cluster_tag_index() -> dict[int, frozenset[tuple[str, str]]]:
    """node id -> {(facet, value)} from the passives tag corpus, restricted to CLUSTER_FACETS.
    Read once per process; nodes absent from the corpus carry no keys."""

    payload = json.loads((TAG_DATA_ROOT / "passives.json").read_text(encoding="utf-8"))
    index: dict[int, frozenset[tuple[str, str]]] = {}
    for rec in payload.get("records") or []:
        node_id = str(rec.get("source_id") or "").rpartition(":")[2]
        if not node_id.isdigit():
            continue
        keys = {
            (str(facet["facet"]), str(value))
            for facet in rec.get("scaling_facets") or []
            if isinstance(facet, dict) and facet.get("facet") in CLUSTER_FACETS
            for value in facet.get("values") or []
        }
        if keys:
            index[int(node_id)] = frozenset(keys)
    return index


def corpus_cluster_tags(node_id: int) -> set[tuple[str, str]]:
    return set(_cluster_tag_index().get(int(node_id), ()))


@dataclass(frozen=True, slots=True)
class ClusterCandidate:
    """Several notables sharing a mechanic tag, tried as one trial and allocated as one step
    (ROADMAP 7.2 rule 5). Ducks `Candidate` for everything that reads `meta["candidate"]`."""

    node_id: int  # the first member id, so a cluster step still names a node
    cost: int  # points the whole cluster needs (its member paths, deduplicated)
    path: tuple[int, ...]  # union of the member paths, first-seen order
    name: str  # the member names joined
    node_ids: tuple[int, ...]  # the members, sorted
    key: tuple[str, str]  # the (facet, value) the members share
    kind: str = "cluster"


@dataclass(frozen=True, slots=True)
class Corridor:
    """A maximal run of ordinary allocated nodes between two KEY nodes (plan B, move 1).

    `inner` is in walk order from `a` to `b`; every inner node has exactly two allocated
    neighbours and is none of the things `TreeOptimizer.key_nodes` calls key, so the run is
    exactly the piece of trunk that can be exchanged for another connection without touching
    anything the build was chosen for.
    """

    a: int
    b: int
    inner: tuple[int, ...]

    @property
    def points(self) -> int:
        return len(self.inner)


@dataclass(slots=True)
class Step:
    node_id: int
    name: str
    kind: str
    cost: int
    added_node_ids: list[int]
    mastery_effect: int | None
    before: Score
    after: Score
    candidates_evaluated: int
    seconds: float
    candidates_skipped: int = 0  # candidates PoB was not asked about again (skip_inert)
    removed_node_ids: list[int] = field(default_factory=list)  # exact removals, needed to replay a rejected path batch
    added_mastery_effects: dict[int, int] = field(default_factory=dict)

    @property
    def gain(self) -> float:
        return self.after.value - self.before.value


@dataclass(slots=True)
class AllocationResult:
    steps: list[Step] = field(default_factory=list)
    points_spent: int = 0
    final_score: Score | None = None
    final_stats: dict = field(default_factory=dict)
    stopped_reason: str = ""

    def summary(self) -> str:
        lines = [f"spent {self.points_spent} points in {len(self.steps)} steps; stop: {self.stopped_reason}"]
        for s in self.steps:
            eff = f" effect={s.mastery_effect}" if s.mastery_effect else ""
            lines.append(
                f"  +{s.cost:2d} {s.kind:9s} {s.name:32s}{eff} value {s.before.value:,.0f} -> {s.after.value:,.0f} "
                f"(viol {s.before.violation:.3f} -> {s.after.violation:.3f}) [{s.candidates_evaluated} cands"
                + (f", {s.candidates_skipped} skipped" if s.candidates_skipped else "")
                + f", {s.seconds:.1f}s]"
            )
        if self.final_score:
            lines.append(f"final: value {self.final_score.value:,.0f} violation {self.final_score.violation:.3f}")
        return "\n".join(lines)


class TreeOptimizer:
    def __init__(
        self,
        pob: PobSession,
        objective: Objective,
        *,
        graph: TreeGraph | None = None,
        max_depth: int = 6,
        max_trials: int = 300,
        mastery_max_cost: int = 2,
        cluster_candidates: bool = False,
        cluster_max_size: int = 4,
        cluster_max_trials: int = 24,
        cluster_tags: Callable[[int], set[tuple[str, str]]] | None = None,
        skip_inert: bool = False,
        inert_refresh: int = 10,
        attribute_requirement_nodes_max: int | None = None,
        log: Callable[[str], None] | None = None,
    ) -> None:
        self.pob = pob
        self.objective = objective
        self.graph = graph or TreeGraph.load()
        self.max_depth = max_depth
        self.max_trials = max_trials
        self.mastery_max_cost = mastery_max_cost
        # cluster candidates (7.2 rule 5): some mechanics pay only when several notables are taken
        # together (impale: chance x effect x stacks), which a one-node-at-a-time greedy never sees
        self.cluster_candidates = cluster_candidates
        self.cluster_max_size = cluster_max_size
        self.cluster_max_trials = cluster_max_trials
        self.cluster_tags = cluster_tags or corpus_cluster_tags
        # skip_inert (speed audit 2026-09-18, approximate, default off): 74-90% of a step's
        # candidate evaluations come back with the build's own value and 33-57% are fully inert
        # (value AND violation unchanged) on stormbrand / bleed_bow. An inert candidate is not sent
        # again while nothing that could wake it has happened: the set of violated floors is the
        # one it was judged under (the only way an inert candidate came alive in the instrumented
        # runs), its path is untouched by what was allocated since, no keystone or charge generator
        # was taken, and its last real evaluation is fewer than `inert_refresh` steps old.
        self.skip_inert = skip_inert
        self.inert_refresh = inert_refresh
        # D79 rule 7: the cap of one +30 attribute node. The pipeline sets it from the rails
        # `tree.attribute_plus30_nodes_max` (1 on day-1, #430); None = no cap, and PoB decides
        # how many attribute nodes a tree wants. Its effect is measured by the paired benchmark
        # after the merge. A caller may pass 0 to forbid them entirely.
        self.attribute_requirement_nodes_max = (
            None if attribute_requirement_nodes_max is None else max(0, int(attribute_requirement_nodes_max))
        )
        self._inert: dict[tuple[int, int | None, frozenset[int]], tuple[frozenset[str], int]] = {}  # candidate -> (violated floors, step judged)
        self._inert_step = 0
        self.inert_skipped = 0  # candidate evaluations PoB was spared
        self.inert_sent = 0  # candidate evaluations PoB was asked for
        self.inert_revived = 0  # candidates that stopped being inert on a real evaluation
        self.log = log or (lambda _msg: None)
        # node ids no move may remove (#510: the request's forced nodes); filled by the pipeline
        self.protected: frozenset[int] = frozenset()
        # the extra edges of the cluster jewels the build carries (#433), read fresh by every connectivity question;
        # filled by the pipeline, None = no cluster = the static graph alone
        self.cluster_links: Callable[[], Links | None] | None = None
        self.skipped_errors: dict[str, int] = {}
        self.excluded_nodes: set[int] = set()  # corpus nodes PoB reports as unknown/unreachable, and the rails' forbidden lines
        self.excluded_mastery_effects: set[int] = set()  # mastery effects the rails forbid (forbid_text)
        # trace-only (#1038): what the trace counters `forbidden_node_text` / `attribute_cap_exceeded` look for, set apart
        # from the enforcement above so a tree optimizer wired without the rails still counts what it sends to PoB
        self.audit_forbidden_text: tuple[str, ...] = ()
        self.audit_attribute_cap: int | None = None
        self._audit_text_nodes: tuple[frozenset[int], frozenset[int]] | None = None  # (nodes, mastery effects) of audit_forbidden_text, read lazily
        self.repair_margin = 3  # points kept in reserve beyond the estimated repair cost
        # #619: a seed breaks an exact tie of the greedy's pick between candidates PoB scored the same (None = the first
        # listed wins, as before); set by the pipeline from the build seed, so two seeds of one build can part ways
        self.tie_seed: int | None = None
        self.trial_mode = "fast"  # PoB what-if calculator (~7 ms/trial); "full" = real allocate + recalc (~100 ms)
        self._unswappable: set[int] = set()  # leaves whose real removal cascaded (graph/PoB disagreement)
        self.last_repair_estimate: int | None = None
        self.repair_estimate_mode = "sum"  # "sum": optimistic (every candidate's total reduction summed); "cover": greedy cover of each missed constraint
        self.history: list[Step] = []  # every kept step of every call, for the build explanation
        # a node whose text generates a state PoB models through a config toggle (charges on hit) is worth nothing in a
        # what-if trial under the current config; the pipeline's enabler_hook judges it with the toggle it enables turned
        # on (a real allocate + lanes + calc), and after_apply_hook re-derives the lanes once such a node is taken
        self.restore_failures = 0  # snapshot restores that did not bring the value back (see _restore)
        self.enabler_hook: Callable[[Candidate, dict], Score | None] | None = None
        self.after_apply_hook: Callable[[Candidate], None] | None = None
        # Only a removal which takes a conservative input's sole tree proof away
        # pays the full derive-config judgement. Every other removal stays a fast
        # frozen-config what-if and restores with the inverse mutation.
        self.proof_holders: dict[int | tuple[int, int], dict[str, object]] = {}
        self.after_proof_removal_hook: Callable[[Mapping[str, object]], None] | None = None
        self.snapshot_context_hook: Callable[[], object] | None = None
        self.restore_context_hook: Callable[[object], None] | None = None
        self._generator_text: dict[int, dict[int | None, frozenset[str]]] | None = None  # node id -> {mastery effect id (None: the node's own lines): charge kinds it grants}
        # the enabler hook is the most expensive thing a greedy step can do (a real allocate, a
        # config re-derivation and an XML reload, ~3 s), and 86% of its calls only learn that
        # nothing was enabled (speed audit 2026-09-18): its answers are kept across `allocate`
        # calls, keyed by the charge lanes they were derived under, and a candidate that cannot
        # flip a toggle that is off is never handed to it at all
        self._hooked: dict[tuple, Score | None] = {}  # (config generation, build generation, node, effect, removed nodes) -> hook answer
        self._config_generation = 0
        self._build_generation = 0  # #34: bumped by a kept gear move; part of the enabler-hook cache key
        self._charge_toggles: dict[str, object] = {}  # use*Charges inputs as of this generation; {} = unknown
        self.hook_calls = 0  # enabler_hook calls actually made
        self.hook_skipped_cached = 0  # answered from `_hooked`
        self.hook_skipped_inert = 0  # skipped because no toggle the candidate grants is off
        self._rejected_subtrees: set[tuple[frozenset[int], frozenset[int]]] = set()  # (allocated set, subtree) path swaps already proven not to pay
        self.subtree_retries_skipped = 0
        self.restore_fast = 0  # restores done by the inverse mutation
        self.restore_fallback = 0  # restores that had to reload the XML
        # trials PoB has already answered on the build as it stands (speed audit 2026-09-18,
        # "what refine re-sends unchanged"): a stage that starts where the last one ended, and a
        # round that follows a swap PoB refused, re-send a whole batch for answers already in hand
        self._config_fp: tuple | None = None  # the config inputs as of this stage; part of the state key
        self._trial_state: tuple | None = None  # the build the memo below was measured on
        self._trial_memo: dict[tuple, dict] = {}  # trial -> outcome, on that build
        self._trial_carry: "OrderedDict[tuple, dict[tuple, dict]]" = OrderedDict()  # the batches the last stages ended on
        self.trial_carry_states = 4  # how many of those to keep (~400 outcomes each)
        self.trials_measured = 0  # trials sent to PoB
        self.trials_reused = 0  # trials answered from the memo
        self._stage_depth = 0  # allocate / refine inside swap_subtrees or reoptimize are not stage ends
        self._barren: set[tuple] = set()  # (build, refine parameters) where a full round found no swap
        self.refine_skipped = 0  # refine calls that returned on a remembered verdict
        # plan B (2026-09-20): the trunk's own moves and what they reached. 22% of a delivered
        # tree's nodes drop 13 or more allocated nodes when cut and no move ever reconsidered them
        # after construction; `considered_removals` is every allocated node that has been inside
        # the removal set of a candidate PoB was actually asked about, which is what the acceptance
        # counts that share against.
        self.plan_b_counts: dict[str, int] = {
            "corridors": 0, "corridors_with_bypass": 0, "corridors_no_bypass": 0,
            "corridor_candidates": 0, "corridor_applied": 0, "corridor_kept": 0, "corridor_unpriceable": 0,
            "regions": 0, "region_candidates": 0, "regions_challenged": 0, "regions_kept": 0,
            "honest_removals": 0,
        }
        self.considered_removals: set[int] = set()
        self.region_bucket_kept: dict[str, int] = {}  # "4-6" / "7-12" / "13-20" / "21-30" -> kept
        self.region_policy_kept: dict[str, int] = {}  # "target-first" / "greedy" -> kept

    def _keep(self, result: "AllocationResult") -> "AllocationResult":
        """The single exit of every stage: the steps go into the build's history, and the batch the
        stage ended on is kept for the next stage that starts on that same build."""

        self.history.extend(result.steps)
        self._stage_depth = max(0, self._stage_depth - 1)
        if self._stage_depth == 0:  # an allocate inside swap_subtrees / reoptimize is not a stage end
            self._carry_trials()
        return result

    def _snapshot(self) -> dict:
        """What a restore needs: the build XML, the tree as PoB holds it, and the config
        generation, so a tree-only move can be undone by its inverse mutation (~0.14 s) instead
        of reloading the whole build from XML (0.5-0.75 s, speed audit 2026-09-18)."""

        light = getattr(self.pob, "tree_light", None)
        return {
            "xml": self.pob.export_xml(),
            "tree": dict(light()) if callable(light) else None,
            "generation": self._config_generation,
            "context": self.snapshot_context_hook() if self.snapshot_context_hook is not None else None,
        }

    def _undo_tree(self, snapshot: dict) -> bool:
        """Put the tree back by the inverse mutation and say whether it worked. Refuses (returns
        False, nothing changed) when anything outside the tree moved since the snapshot, when a
        mastery effect changed on a node that stays allocated (a mutation cannot re-select it), or
        when the result is not node-for-node the snapshot's tree."""

        before = snapshot.get("tree")
        light = getattr(self.pob, "tree_light", None)
        if not before or not callable(light) or snapshot.get("generation") != self._config_generation:
            return False
        now = dict(light())
        if now.get("class_id") != before.get("class_id"):
            return False
        before_nodes = {int(n) for n in before.get("user_allocated_node_ids") or ()}
        now_nodes = {int(n) for n in now.get("user_allocated_node_ids") or ()}

        def effects(state: dict) -> dict[int, int]:
            out: dict[int, int] = {}
            for entry in state.get("mastery_effect_ids") or []:
                node, _, effect = str(entry).partition(":")
                if node.isdigit() and effect.isdigit():
                    out[int(node)] = int(effect)
            return out

        before_eff, now_eff = effects(before), effects(now)
        kept = before_nodes & now_nodes
        if any(before_eff.get(n) != now_eff.get(n) for n in kept):
            return False  # a re-selected mastery effect: only a reload puts that back
        add, remove = sorted(before_nodes - now_nodes), sorted(now_nodes - before_nodes)
        if not add and not remove:
            return True
        self.pob.mutate_nodes(add=add, remove=remove, mastery_effects={n: before_eff[n] for n in add if n in before_eff} or None)
        after = dict(light())
        return ({int(n) for n in after.get("user_allocated_node_ids") or ()} == before_nodes
                and effects(after) == before_eff)

    def _restore(self, snapshot: "dict | str", expected: "Score", what: str) -> None:
        """Put the build back and check it came back. The loop-smoke run (2026-09-15) judged
        every tree move of Bleed Bow (3 seeds x 3 passes) at the value of its last failed path
        swap (181,185 on a 263,905 build) as if the restore had not happened, while the same
        sequence on a finished build restores exactly; until the cause is found, a drift is
        logged, the snapshot is loaded once more, and a persisting drift is counted.

        A tree-only move is undone by its inverse mutation and the tree is compared node for node
        with the snapshot; anything else -- and any mismatch -- reloads the XML, so the restored
        build is identical either way."""

        if isinstance(snapshot, str):
            snapshot = {"xml": snapshot, "tree": None, "generation": self._config_generation}
        snapshot_xml = snapshot["xml"]
        self._invalidate_inert(everything=True)  # the build is not the one those verdicts were measured on
        lanes_changed = snapshot.get("generation") != self._config_generation

        def load_snapshot() -> None:
            self.pob.load_xml(snapshot_xml)
            if lanes_changed:
                if self.restore_context_hook is not None:
                    self.restore_context_hook(snapshot.get("context"))
                self.note_config_change()

        if self._undo_tree(snapshot):
            self.restore_fast += 1
        else:
            self.restore_fallback += 1
            load_snapshot()
        back, _ = self.current_score()
        tolerance = 0.005 * max(1.0, abs(expected.value))
        if abs(back.value - expected.value) > tolerance:
            self.log(f"restore drift after {what}: {back.value:,.0f} vs {expected.value:,.0f} expected; loading the snapshot again")
            load_snapshot()
            back, _ = self.current_score()
            if abs(back.value - expected.value) > tolerance:
                self.restore_failures += 1
                self.log(f"RESTORE FAILED after {what}: {back.value:,.0f} vs {expected.value:,.0f} expected")

    def _proof_holder_inputs(self, applied: Mapping[str, object]) -> dict[str, object]:
        """Inputs whose unique allocated proof was actually removed by this mutation."""

        removed_nodes = {int(n) for n in applied.get("removed_node_ids") or ()}
        removed_effects: set[tuple[int, int]] = set()
        for raw in applied.get("removed_mastery_effects") or ():
            node, _, effect = str(raw).partition(":")
            if node.isdigit() and effect.isdigit():
                removed_effects.add((int(node), int(effect)))
        out: dict[str, object] = {}
        for holder, inputs in self.proof_holders.items():
            hit = holder in removed_nodes if isinstance(holder, int) else holder in removed_effects or holder[0] in removed_nodes
            if hit:
                out.update(inputs)
        return out

    def after_real_removal(self, applied: Mapping[str, object]) -> bool:
        """Re-derive lanes only if this exact removal withdraws a sole proof."""

        inputs = self._proof_holder_inputs(applied)
        if not inputs or self.after_proof_removal_hook is None:
            return False
        self.after_proof_removal_hook(applied)
        self.note_config_change()
        names = ", ".join(sorted(inputs))
        self.log(f"proof-holder removal judged with {names} re-derived")
        return True

    def needs_honest_removal(self, node_ids: Iterable[int]) -> bool:
        """Whether a planned node removal can withdraw a known sole proof."""

        removed = {int(node) for node in node_ids}
        return any((holder in removed if isinstance(holder, int) else holder[0] in removed) for holder in self.proof_holders)

    def _links(self) -> Links | None:
        provider = getattr(self, "cluster_links", None)
        return provider() if provider is not None else None

    def _cuts_protected(self, allocated: Iterable[int], remove: Iterable[int]) -> bool:
        """Whether removing `remove` would drop a protected node or the path that connects it (#510)."""

        return bool(self.protected) and not self.graph.keeps_connected(allocated, remove, self.protected, self._links())

    def _dropped_protected(self, removed: Mapping[str, object]) -> bool:
        """Whether PoB's real removal took a protected node with it (its cascade went past the graph's estimate)."""

        return bool(self.protected) and any(int(n) in self.protected for n in removed.get("removed_node_ids") or ())

    def invalidate_after_recovery(self, *, keep_rejections: bool = False) -> None:
        """Forget answers measured on a move that was abandoned after a full XML restore.

        The XML is authoritative after a recoverable worker contract error.  Caches derived from
        the transient build must not steer the next move, while graph/corpus lookup caches remain
        intact.

        `keep_rejections` is the plain revert of a judged move: the build and its lanes are back
        exactly where the move started, so the verdicts this optimizer measured ON THAT SAME
        build still hold. `_rejected_subtrees` is keyed by the allocated set itself, so it can
        only ever match the tree it was measured on. Clearing it made winter_orb's passes 4 and 5
        re-try the identical five path-swap candidates for 97 s (v2, measured); only a contract
        error -- where the build PoB holds is not the build those answers were measured on --
        throws them away.
        """

        self._config_generation += 1
        self._config_fp = None
        self._charge_toggles = {}
        self._hooked.clear()
        self._invalidate_inert(everything=True)
        if not keep_rejections:
            self._unswappable.clear()
            self._rejected_subtrees.clear()
        self._trial_state = None
        self._trial_memo = {}
        self._trial_carry.clear()
        self._barren.clear()
        self.last_repair_estimate = None
        self._stage_depth = 0

    def forbid(self, names: Iterable[str]) -> set[int]:
        """Never allocate (or path through) nodes with these names: the skeleton's
        forbid_keystones, and the keystone variants of the search (D40)."""

        wanted = {n.lower() for n in names}
        ids = {n.node_id for n in self.graph.nodes.values() if n.name.lower() in wanted}
        self.excluded_nodes |= ids
        return ids

    def _text_matches(self, patterns: Iterable[str]) -> tuple[list[int], list[int]]:
        """(node ids whose every line matches a pattern, mastery effect ids with a matching line)."""

        import re

        regs = [re.compile(p, re.IGNORECASE) for p in patterns]
        if not regs:
            return ([], [])

        def hit(line: str) -> bool:
            return any(r.search(line) for r in regs)

        nodes: list[int] = []
        effects: list[int] = []
        for node in self.graph.nodes.values():
            if node.kind in ("notable", "normal", "keystone") and node.stats and all(hit(s) for s in node.stats):
                nodes.append(node.node_id)
            for effect_id, stats in node.mastery_effects or []:
                if stats and any(hit(s) for s in stats):
                    effects.append(effect_id)
        return (nodes, effects)

    def forbid_text(self, patterns: Iterable[str]) -> tuple[int, int]:
        """Never allocate a node whose every line matches one of the patterns, nor a mastery
        effect that matches (the node stays for its other effects): rails "tree.forbidden_text",
        e.g. accuracy conditional on the enemy being unique or marked, which caps the boss-judged
        hit chance while maps are hit at 70%. Returns (nodes, mastery effects) excluded."""

        nodes, effects = self._text_matches(patterns)
        self.excluded_nodes.update(nodes)
        self.excluded_mastery_effects.update(effects)
        return (len(nodes), len(effects))

    CHARGE_KINDS = ("Frenzy", "Power", "Endurance")
    RAGE_KIND = "Rage"  # not a charge: a node gaining Rage on hit, judged with the `multiplierRage` the ramp derives once it is allocated

    def _generator_index(self) -> dict[int, dict[int | None, frozenset[str]]]:
        """node id -> {mastery effect id (None: the node's own lines): the charge kinds that text
        generates on hit, crit, a timer, a block or a kill (config_rules.charge_sources), plus
        `RAGE_KIND` when it gains Rage on hit (ramp_inputs.grants_rage_on_hit)}. Computed once per graph."""

        if self._generator_text is None:
            from junkroan.optimizer.config_rules import charge_sources
            from junkroan.optimizer.ramp_inputs import grants_rage_on_hit

            found: dict[int, dict[int | None, frozenset[str]]] = {}

            def kinds(lines: Sequence[str]) -> frozenset[str]:
                text = "\n".join(lines)
                got = {k for k in self.CHARGE_KINDS if charge_sources(k, text)}
                if grants_rage_on_hit(text):
                    got.add(self.RAGE_KIND)
                return frozenset(got)

            for node in self.graph.nodes.values():
                own = kinds(node.stats or ())
                if own:
                    found.setdefault(node.node_id, {})[None] = own
                for effect_id, stats in node.mastery_effects or []:
                    got = kinds(stats or ())
                    if got:
                        found.setdefault(node.node_id, {})[effect_id] = got
            self._generator_text = found
        return self._generator_text

    def rage_source_nodes(self) -> frozenset[int]:
        """Nodes whose own lines gain Rage on hit. `TreeGraph.candidates` offers an ordinary node only on
        the frontier, so one a step behind it ("Rage on Hit" behind a "Strength") was never a candidate
        and only ever sat on the path of a notable (#632); these are offered at any depth."""

        return frozenset(n for n, by_effect in self._generator_index().items() if self.RAGE_KIND in by_effect.get(None, ()))

    def generator_effects(self, node_id: int) -> set[int | None]:
        """Mastery effect ids (None for the node's own lines) whose text generates charges."""

        return set(self._generator_index().get(node_id, {}))

    def generator_kinds(self, node_ids: Iterable[int], effects: Mapping[int, int] | None = None) -> set[str]:
        """The charge kinds ("Frenzy" / "Power" / "Endurance") that allocating these nodes can
        generate: each node's own lines, plus the mastery effect chosen for it. Used to skip the
        enabler hook when every kind the candidate could grant is already switched on."""

        index = self._generator_index()
        out: set[str] = set()
        for node_id in node_ids:
            entry = index.get(int(node_id))
            if not entry:
                continue
            out |= entry.get(None, frozenset())
            effect = (effects or {}).get(int(node_id))
            if effect is not None:
                out |= entry.get(int(effect), frozenset())
        return out

    # -- inert candidates (skip_inert) ----------------------------------------

    @staticmethod
    def _inert_key(meta: dict) -> tuple[int, int | None, frozenset[int]]:
        """What makes two evaluations of a candidate the same question: the node, the mastery
        effect chosen for it, and the exact set of nodes the trial allocates. A candidate whose
        path moved is a different key and is always evaluated again."""

        cand = meta["candidate"]
        trial = meta["trial"]
        return (
            int(cand.node_id),
            (trial.get("mastery") or {}).get(cand.node_id),
            frozenset(int(n) for n in (trial.get("add") or ())) | frozenset(int(n) for n in (getattr(cand, "path", ()) or ())),
        )

    def violated_floors(self, stats: Mapping[str, object] | None) -> frozenset[str]:
        """Which constraints are missed right now. An inert candidate is only re-sent when this
        set changes: in the instrumented runs every candidate that came back alive after being
        inert did so because a floor broke and its +life / +resist path suddenly mattered."""

        return frozenset(self.objective.violations(stats)) if stats is not None else frozenset()

    def _filter_inert(self, trials: list[dict], violated: frozenset[str]) -> tuple[list[dict], int]:
        if not self.skip_inert or not self._inert:
            self.inert_sent += len(trials)
            return trials, 0
        sent: list[dict] = []
        for meta in trials:
            record = self._inert.get(self._inert_key(meta))
            if record is not None and record[0] == violated and self._inert_step - record[1] < self.inert_refresh:
                continue
            sent.append(meta)
        if not sent:
            # every candidate is inert by an old verdict: measure them rather than assume it, so a
            # stage never ends on a belief PoB was not asked to confirm
            for meta in trials:
                self._inert.pop(self._inert_key(meta), None)
            self.inert_sent += len(trials)
            return trials, 0
        skipped = len(trials) - len(sent)
        self.inert_skipped += skipped
        self.inert_sent += len(sent)
        return sent, skipped

    @staticmethod
    def _count_filtered(before: list[dict], after: list[dict]) -> None:
        """Generated-only count of the candidates `_filter_inert` dropped; `_measure` counts the rest."""

        kept = {id(m) for m in after}
        TRACE.count_candidates(m["trial"] for m in before if id(m) not in kept)

    def _mark_inert(self, evaluated: list[tuple[dict, dict, Score, int]], score: Score, violated: frozenset[str]) -> None:
        """Record the candidates PoB just said change nothing, and forget the ones that woke up."""

        if not self.skip_inert:
            return
        self._inert_step += 1
        for meta, _outcome, trial_score, _cost in evaluated:
            key = self._inert_key(meta)
            if trial_score.value == score.value and trial_score.neg_violation == score.neg_violation:
                self._inert[key] = (violated, self._inert_step)
            elif self._inert.pop(key, None) is not None:
                self.inert_revived += 1

    def _invalidate_inert(self, added: Iterable[int] = (), *, everything: bool = False) -> None:
        """Forget what the build has moved under. `everything` after a config change, a restore or
        a keystone / charge generator (any of which can change what a far-away node is worth);
        otherwise only the candidates whose path touches, or sits next to, what was just allocated."""

        if everything:
            self._inert.clear()
            return
        if not self._inert:
            return
        touched: set[int] = set()
        for node_id in added:
            touched.add(int(node_id))
            touched |= {int(n) for n in self.graph.neighbours(int(node_id))}
        for key in [k for k in self._inert if k[2] & touched]:
            del self._inert[key]

    # -- config generation (the lanes the hook's answers were derived under) ---

    def note_config_change(self, toggles: Mapping[str, object] | None = None) -> None:
        """The config lanes moved: enabler-hook answers derived under the old ones are dropped,
        and so is every inert verdict measured under them."""

        self._config_generation += 1
        self._hooked.clear()
        self._charge_toggles = dict(toggles) if toggles is not None else {}
        self._invalidate_inert(everything=True)
        if toggles is None:
            self._read_config()  # the lanes the trial memo keys on moved with them

    def note_build_change(self) -> None:
        """A gear move was kept (#34): a hook Score is an absolute number measured on the gear it was
        asked on, so the cached ones are dropped. Narrower than `note_config_change`: the lanes, the
        charge toggles and the inert verdicts stay."""

        self._build_generation += 1
        self._hooked.clear()

    def _read_config(self) -> dict | None:
        """The config inputs PoB holds, and the fingerprint the trial memo keys on. One read per
        stage (~40 ms): a lane the pipeline rewrote between two stages can change what a trial is
        worth without moving a single objective stat."""

        reader = getattr(self.pob, "config_inputs", None)
        if not callable(reader):
            self._config_fp = None
            return None
        try:
            inputs = dict(reader())
        except Exception:  # a test double without a usable config surface keeps the old behaviour
            self._config_fp = None
            return None
        self._config_fp = tuple(sorted((str(k), repr(v)) for k, v in inputs.items()))  # the values, not a hash of them
        return inputs

    def _refresh_charge_toggles(self) -> None:
        """Read the use*Charges inputs once per `allocate` call (~40 ms) so the hook skip below
        never costs a PoB call per candidate; a change bumps the generation, which is what makes
        answers kept from an earlier `allocate` call safe to reuse."""

        inputs = self._read_config()
        if inputs is None or self.enabler_hook is None:
            return
        toggles = {k: v for k, v in inputs.items() if str(k).startswith("use") and str(k).endswith("Charges")}
        if toggles != self._charge_toggles:
            self.note_config_change(toggles)

    # -- trials PoB has already answered on this very build --------------------

    @staticmethod
    def _trial_key(trial: Mapping[str, object]) -> tuple:
        """Two trials are the same question only when they are literally the same trial. A trial that carries red-line
        marks (#1124) is a different question from the same trial without them, or with other lines."""

        key = (
            tuple(int(n) for n in (trial.get("add") or ())),
            tuple(int(n) for n in (trial.get("remove") or ())),
            tuple(sorted((int(k), int(v)) for k, v in (trial.get("mastery") or {}).items())),
        )
        marks = trial.get("marks")
        if not marks:
            return key  # no marks: the key is as before
        return key + (tuple(
            tuple(sorted((line, tuple(mods)) for line, mods in (marks.get(side) or {}).items())) for side in ("add", "remove")
        ),)

    # -- the red-line marks of the nodes a trial adds or removes (#1124, unit 4) ---------------------------------------

    red_marks: RedLineMarks | None = None  # the marks store; None = `load_marks()` (the default file / env override)
    mark_lane = "boss"  # the lane the build is judged under: Baseline holds the `boss` marks (judging.write_marks)
    MARK_NODE_KINDS = ("notable", "keystone", "ascendancy")  # the kinds whose lines `audit.held_mod_entries` reads

    def _node_red_lines(self, node_id: int, effect_id: int | None, marks: RedLineMarks) -> list[str]:
        """The held lines of one node that have a record, as `judging.write_marks` looks them up: the stat line whole and
        by its newline parts. A mastery node holds the lines of its one chosen effect (`effect_id`), never its own."""

        node = self.graph.node(node_id)
        if node is None:
            return []
        if node.kind == "mastery":
            stats = next((list(lines or ()) for eid, lines in (node.mastery_effects or ()) if effect_id is not None and int(eid) == int(effect_id)), [])
        elif node.kind in self.MARK_NODE_KINDS:
            stats = list(node.stats or ())
        else:
            return []
        found: list[str] = []
        for line in stats:
            line = str(line)
            parts = [part.strip() for part in line.split("\n") if part.strip()] if "\n" in line else []
            for one in (line, *parts):
                if marks.has_record(one) and one not in found:
                    found.append(one)
        return found

    def _lane_mark_lines(self, line: str, marks: RedLineMarks, outputs: Callable[[Sequence[str]], Mapping[str, object]]) -> list[str]:
        """The PoB lines the lane writes for `line` (comments left out); a formula takes its value from `outputs`."""

        record = marks.record(line)
        if record is None:
            return []
        field = "boss_lane" if self.mark_lane == "boss" else "optimistic_lane"
        if not record[field]:
            return []
        values = None
        if record.get("formula") and any(PLACEHOLDER in entry for entry in record[field]):
            import ast

            names = tuple(dict.fromkeys(n.id for n in ast.walk(ast.parse(record["formula"], mode="eval")) if isinstance(n, ast.Name)))
            values = outputs(names)
        try:
            block = marks.block_for([(line, "trial")], self.mark_lane, values)
        except (KeyError, ValueError):
            return []  # a formula number PoB did not give: the line carries nothing, never a wrong number
        return [entry for entry in block if not entry.startswith("#")]

    def _stamp_marks(self, trials: list[dict]) -> list[dict]:
        """Stamp each trial with `marks`: `{"add": {held line: [lane lines]}, "remove": {...}}`, the marks of the nodes the
        trial newly allocates (its `add` and its `path`, and the taken mastery effect) and of the nodes it removes, net of
        what the build holds anyway. `PobSession.trial_stats` sends the lane lines to the worker, which applies them to that
        one what-if calculation only. A line held by another allocated node stays marked (the lane writers write a line
        once); an item slot holding the same line is not seen here. No store records, or no touched node with a marked
        line: the trials come back untouched and PoB is asked nothing."""

        marks = self.red_marks if self.red_marks is not None else load_marks()
        if not len(marks) or self.trial_mode != "fast":  # a full trial is a real allocation: the worker carries marks in fast mode only
            return trials
        lines_of: dict[tuple[int, int | None], list[str]] = {}

        def lines_for(node_id: int, effect_id: int | None) -> list[str]:
            key = (node_id, effect_id)
            if key not in lines_of:
                lines_of[key] = self._node_red_lines(node_id, effect_id, marks)
            return lines_of[key]

        def effects_of(trial: Mapping[str, object]) -> dict[int, int]:
            return {int(k): int(v) for k, v in (trial.get("mastery") or {}).items()}

        if not any(
            lines_for(int(n), effects_of(t).get(int(n)))
            for t in trials
            for n in (*(t.get("add") or ()), *(t.get("path") or ()), *(t.get("remove") or ()))
        ):
            return trials
        state = self._tree_state()
        allocated = {int(n) for n in state.get("user_allocated_node_ids") or ()}
        taken: dict[int, int] = {}
        for entry in state.get("mastery_effect_ids") or ():
            try:
                nid, eff = str(entry).split(":")
                taken[int(nid)] = int(eff)
            except ValueError:
                continue
        held_by: dict[int, list[str]] = {n: lines_for(n, taken.get(n)) for n in allocated}
        before = {line for lines in held_by.values() for line in lines}
        outputs_cache: dict[tuple[str, ...], Mapping[str, object]] = {}

        def outputs(names: Sequence[str]) -> Mapping[str, object]:
            key = tuple(names)
            if key not in outputs_cache:
                outputs_cache[key] = self.pob.stats(key)
            return outputs_cache[key]

        out: list[dict] = []
        for trial in trials:
            effects = effects_of(trial)
            removed = {int(n) for n in (trial.get("remove") or ()) if int(n) in allocated}
            added: list[int] = []
            for n in (*(trial.get("add") or ()), *(trial.get("path") or ())):
                if int(n) not in allocated and int(n) not in added:
                    added.append(int(n))
            after = {line for n, lines in held_by.items() if n not in removed for line in lines}
            after |= {line for n in added for line in lines_for(n, effects.get(n))}
            stamp: dict[str, dict[str, list[str]]] = {"add": {}, "remove": {}}
            for side, lines in (("add", sorted(after - before)), ("remove", sorted(before - after))):
                for line in lines:
                    mods = self._lane_mark_lines(line, marks, outputs)
                    if mods:
                        stamp[side][line] = mods
            out.append({**trial, "marks": stamp} if (stamp["add"] or stamp["remove"]) else trial)
        return out

    def _state_key(self, stats: Mapping[str, object] | None, keys: Sequence[str]) -> tuple | None:
        """What makes two trial batches the same question: the tree PoB holds, the config inputs
        it holds, the objective being asked, and the build's own readback on every key of it.

        The exported XML cannot serve as the fingerprint -- PoB reorders the allocated node list,
        the config inputs and the placeholder block on every `load_xml` round trip (measured
        2026-09-18: two exports of an untouched build are equal, an export after
        `load_xml(export)` is not), which is exactly how a move the pipeline reverted comes back.
        The tree readback is milliseconds and the stats are the ones the caller already fetched,
        so the key costs nothing a stage was not paying anyway."""

        if stats is None:
            return None
        tree = self._tree_state()
        return (
            str(tree.get("class_id") or ""),
            tuple(sorted(int(n) for n in tree.get("user_allocated_node_ids") or ())),
            tuple(sorted(str(m) for m in tree.get("mastery_effect_ids") or ())),
            tuple(sorted((str(k), repr(v)) for k, v in stats.items())),
            tuple(keys),
            self.trial_mode,
            self._config_fp,
            self.objective.describe(),
        )

    def _over_cap(self, trials: list[dict], cap: int | None) -> list[bool]:
        """Per trial: does it take the tree past `cap` +30 attribute nodes. Read against the tree PoB holds (one
        light read, and only when a trial touches an attribute node); no cap, no read."""

        if cap is None:
            return [False] * len(trials)
        allocated: set[int] | None = None
        held: set[int] = set()
        out: list[bool] = []
        for trial in trials:
            touched = {int(n) for n in (*(trial.get("add") or ()), *(trial.get("path") or ()))}
            if not any(is_attribute_requirement_node(self.graph.node(n)) for n in touched):
                out.append(False)
                continue
            if allocated is None:
                allocated = self.current_allocated()
                held = self.attribute_requirement_nodes(allocated)
            added = {n for n in touched - allocated if is_attribute_requirement_node(self.graph.node(n))}
            kept = held - {int(n) for n in (trial.get("remove") or ())}
            out.append(bool(added) and len(kept) + len(added) > cap)
        return out

    def _audit_text(self) -> tuple[frozenset[int], frozenset[int]]:
        if self._audit_text_nodes is None:
            nodes, effects = self._text_matches(self.audit_forbidden_text)
            self._audit_text_nodes = (frozenset(nodes), frozenset(effects))
        return self._audit_text_nodes

    def _text_forbidden(self, trial: Mapping[str, object]) -> bool:
        """Does the trial add a node, or a mastery effect, whose text the rails forbid (`audit_forbidden_text`)."""

        if not self.audit_forbidden_text:
            return False
        nodes, effects = self._audit_text()
        touched = {int(n) for n in (*(trial.get("add") or ()), *(trial.get("path") or ()))}
        return bool(touched & nodes) or any(int(v) in effects for v in (trial.get("mastery") or {}).values())

    def _flag_trace(self, trials: list[dict]) -> list[dict]:
        """Trace-only stamps on copies of the trials (the memo key and the PoB payload never see them):
        `attribute_cap_over` (#516, the enforced cap; the key `trace.classify` turns into `attribute-cap:over`) and
        the #1038 pair, `attribute_cap_exceeded` (against `audit_attribute_cap`) and `forbidden_node_text`. The plain
        `node-kind:attribute+30` class counts every +30 add, and a +30 add is legal while the tree holds fewer than
        the cap (a ruin that cut the held node makes every +30 candidate legal again); only an add beyond the cap
        is a call the rail forbids."""

        enforced = self.attribute_requirement_nodes_max
        over = self._over_cap(trials, enforced)
        exceeded = over if self.audit_attribute_cap == enforced else self._over_cap(trials, self.audit_attribute_cap)
        out: list[dict] = []
        for trial, is_over, is_exceeded in zip(trials, over, exceeded):
            stamps = {
                **({"attribute_cap_over": True} if is_over else {}),
                **({ATTRIBUTE_CAP_EXCEEDED: True} if is_exceeded else {}),
                **({FORBIDDEN_NODE_TEXT: True} if self._text_forbidden(trial) else {}),
            }
            out.append({**trial, **stamps} if stamps else trial)
        return out

    def _measure(self, trials: list[dict], keys: Sequence[str], stats: Mapping[str, object] | None) -> list[dict]:
        """One trial batch, minus the trials PoB already answered on this very build. The batch
        the caller sees is unchanged: same trials, same order, same outcomes."""

        trials = self._stamp_marks(self._flag_trace(trials))  # #1124 unit 4: the node valuation takes the marks here
        TRACE.count_candidates(trials)  # every trial reaching a measure was generated, memo hits included
        state = self._state_key(stats, keys)
        if state is None:
            self._trial_state, self._trial_memo = None, {}
            self.trials_measured += len(trials)
            return list(self.pob.trial_stats(trials, keys, mode=self.trial_mode))
        if state != self._trial_state:
            self._trial_state = state
            self._trial_memo = self._trial_carry.get(state) or {}
        memo = self._trial_memo
        wanted = [self._trial_key(t) for t in trials]
        fresh: list[dict] = []
        pending: set[tuple] = set()
        for trial, key in zip(trials, wanted):
            if key not in memo and key not in pending:
                pending.add(key)
                fresh.append(trial)
        if fresh:
            for trial, outcome in zip(fresh, self.pob.trial_stats(fresh, keys, mode=self.trial_mode)):
                memo[self._trial_key(trial)] = outcome
        self.trials_measured += len(fresh)
        self.trials_reused += len(trials) - len(fresh)
        return [memo[key] for key in wanted]

    def _carry_trials(self) -> None:
        """Keep the batch the stage just ended on. The improvement loop judges a tree move, reverts
        the whole pass when it lost and asks the next pass the same question on the same build, with
        a path-swap pass in between that walks a hundred other builds -- so the live memo alone
        would have been thrown away by the time the question comes back."""

        if self._trial_state is None or not self._trial_memo:
            return
        self._trial_carry.pop(self._trial_state, None)
        self._trial_carry[self._trial_state] = self._trial_memo
        while len(self._trial_carry) > self.trial_carry_states:
            self._trial_carry.popitem(last=False)

    def _hook_can_flip(self, cand: "Candidate | ClusterCandidate", trial: dict) -> bool:
        """Can allocating this candidate turn a charge toggle from off to on? The hook's own early
        return asks exactly that, at the price of a real allocate plus a config re-derivation. When
        every kind the candidate's nodes and its chosen mastery effect can grant is already on,
        the answer is no and the hook is not called.

        PoB may path to the node by a different shortest route than the graph's, so the union below
        can miss a generator on the road. A missed hook call costs the candidate its optimistic
        judgement -- it is then scored by its plain trial, like every non-generator candidate -- and
        can never corrupt a number: no PoB output changes, only the hypothesis set."""

        if not self._charge_toggles:
            return True  # toggles unknown (no config surface, a test double): behave exactly as before
        node_ids = list(getattr(cand, "node_ids", ()) or (cand.node_id,)) + list(getattr(cand, "path", ()) or ())
        kinds = self.generator_kinds(node_ids, trial.get("mastery") or {})
        if self.RAGE_KIND in kinds:
            return True  # the Rage the ramp derives for it shows only with the node allocated: the hook asks
        universe = {f"use{kind}Charges" for kind in self.CHARGE_KINDS} | set(self._charge_toggles)
        off = {k for k in universe if self._charge_toggles.get(k) is not True}
        if not off:
            return False
        return any(f"use{kind}Charges" in off for kind in kinds)

    def _judge_with_enablers(self, evaluated: list[tuple[dict, dict, Score, int]]) -> None:
        """Generator nodes (charges, Rage on hit) judged with the toggle they enable, in place: each entry whose
        node generates something is asked of `enabler_hook` and takes the answer when it beats the plain trial.
        Once per config generation per node, effect and removal (a swap trial's `remove` is part of the question).
        Shared by `allocate` (the add batch) and `refine` (the add batch and the swap batch)."""

        if self.enabler_hook is None:
            return
        for idx, (meta, outcome, trial_score, cost) in enumerate(evaluated):
            cand = meta["candidate"]
            effects = self.generator_effects(cand.node_id)
            if not effects:
                continue
            effect = (meta["trial"].get("mastery") or {}).get(cand.node_id)
            if effect not in effects and not (effect is None and None in effects):
                continue
            key = (self._config_generation, self._build_generation, cand.node_id, effect, tuple(meta["trial"].get("remove") or ()))
            if key in self._hooked:
                self.hook_skipped_cached += 1
            elif not self._hook_can_flip(cand, meta["trial"]):
                self.hook_skipped_inert += 1
                self._hooked[key] = None
            else:
                self.hook_calls += 1
                self._hooked[key] = self.enabler_hook(cand, meta["trial"])
            hooked_score = self._hooked[key]
            if hooked_score is not None and hooked_score > trial_score:
                evaluated[idx] = (meta, outcome, hooked_score, cost)

    # -- state ---------------------------------------------------------------

    def _tree_state(self) -> dict:
        """Allocated nodes, class and mastery selections: the light readback where the session has one
        (milliseconds), the full `read_state` otherwise (test doubles). Asked for on every greedy step."""

        light = getattr(self.pob, "tree_light", None)
        if callable(light):
            return light()
        return self.pob.read_state().get("tree_state") or {}

    def current_allocated(self) -> set[int]:
        """All allocated node ids including class start and ascendancy (graph roots)."""

        tree_state = self._tree_state()
        allocated = {int(n) for n in tree_state["user_allocated_node_ids"]}
        start = self.graph.class_starts.get(str(tree_state.get("class_id") or ""))
        if start is not None:
            allocated.add(start)  # PoB readback omits the class start; the graph needs it as a root
        return allocated

    def attribute_requirement_nodes(self, allocated: Iterable[int] | None = None) -> set[int]:
        """The +30 attribute nodes currently allocated, identified by corpus text."""

        ids = set(allocated if allocated is not None else self.current_allocated())
        return {node_id for node_id in ids if is_attribute_requirement_node(self.graph.node(node_id))}

    def _attribute_cap_blocks(self, candidate: Candidate | ClusterCandidate, allocated: set[int]) -> bool:
        """Do not spend a second +30 node when one requirement payment is present."""

        if self.attribute_requirement_nodes_max is None:  # the default: no cap, and no per-candidate scan of the tree
            return False
        current = self.attribute_requirement_nodes(allocated)
        path = set(getattr(candidate, "path", ()) or ()) | set(getattr(candidate, "node_ids", ()) or ()) | {candidate.node_id}
        additions = path - allocated
        attribute_additions = sum(
            is_attribute_requirement_node(self.graph.node(node_id)) for node_id in additions
        )
        return (
            self.attribute_requirement_nodes_max is not None
            and attribute_additions > 0
            and len(current) + attribute_additions > self.attribute_requirement_nodes_max
        )

    def current_score(self) -> tuple[Score, dict]:
        stats = self.pob.stats(self.objective.stat_keys)
        return self.objective.score(stats), stats

    # -- main loop -----------------------------------------------------------

    def allocate(self, points: int, *, allocated: set[int] | None = None, spend_on_tie: bool = False) -> AllocationResult:
        """Greedy allocation of up to `points`. `spend_on_tie` is the spare-point step's rule only (#865): where the
        search would stop because no candidate raises the value, the round's candidates are judged again
        (`_spare_pick`) and a point is spent unless every candidate lowers the Score. Default: the stop stays."""

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        result = AllocationResult()
        allocated = set(allocated) if allocated is not None else self.current_allocated()
        score, stats = self.current_score()
        points_left = int(points)
        self._refresh_charge_toggles()  # one read per call; a change bumps the generation and drops stale hook answers

        while points_left > 0:
            t0 = time.perf_counter()
            candidates = [
                c
                for c in self.graph.candidates(allocated, max_depth=self.max_depth, payoff_ids=self.rage_source_nodes())
                if c.cost <= points_left and not (c.kind == "mastery" and c.cost > self.mastery_max_cost)
                and not self._attribute_cap_blocks(c, allocated)
            ]
            trials = self._trials_for(candidates)[: self.max_trials]  # candidates are sorted by cost
            if self.cluster_candidates:
                trials = trials + self._cluster_trials(candidates, points_left, allocated)  # after the singles: a tie keeps the single
            if not trials:
                result.stopped_reason = "no candidates"
                break
            violated = self.violated_floors(stats)
            proposed = len(trials)
            before_filter = trials
            trials, skipped = self._filter_inert(trials, violated)  # never returns an empty batch: see _filter_inert
            self._count_filtered(before_filter, trials)
            outcomes = self._measure([t["trial"] for t in trials], self.objective.stat_keys, stats)

            evaluated: list[tuple[dict, dict, Score, int]] = []
            for meta, outcome in zip(trials, outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    self._note_failure(meta["candidate"], outcome)
                    continue
                cost = len(outcome.get("added_node_ids") or ()) or meta["candidate"].cost
                if cost > points_left:
                    continue
                evaluated.append((meta, outcome, self.objective.score(outcome["stats"]), cost))
            self._mark_inert(evaluated, score, violated)
            if not evaluated:
                result.stopped_reason = "no evaluable candidate"
                break
            self._judge_with_enablers(evaluated)
            best = self._choose(score, evaluated, points_left, stats)
            if best is None:
                result.stopped_reason = "no evaluable candidate"
                break
            meta, outcome, trial_score, cost = best
            if spend_on_tie and score.feasible and not (trial_score.feasible and trial_score.value > score.value):
                picked = self._spare_pick(score, evaluated)
                if picked is None:
                    result.stopped_reason = "no candidate improves the objective"
                    break
                meta, outcome, trial_score, cost = picked
            elif trial_score.feasible and score.feasible and trial_score.value <= score.value:
                result.stopped_reason = "no candidate improves the objective"
                break

            cand: Candidate | ClusterCandidate = meta["candidate"]
            cluster = cand if isinstance(cand, ClusterCandidate) else None
            if cluster is not None:
                applied = self.pob.mutate_nodes(add=list(cluster.node_ids), mastery_effects=None)
            else:
                applied = self.pob.mutate_nodes(add=[cand.node_id], mastery_effects=meta["trial"].get("mastery") or None)
            added = [int(n) for n in applied["added_node_ids"]]
            allocated.update(added)
            points_left -= len(added)
            # a keystone or a charge generator rewrites what every other node is worth; anything
            # else only moves the nodes it touches or sits next to
            self._invalidate_inert(added, everything=cand.kind == "keystone" or bool(self.generator_effects(cand.node_id)))
            if self.after_apply_hook is not None and self.generator_effects(cand.node_id):
                self.after_apply_hook(cand)  # the lanes now see the generator: its toggle turns on
                self.note_config_change()  # answers derived under the old lanes are gone; the toggles are re-read below
                self._refresh_charge_toggles()
            new_score, stats = self.current_score()
            step = Step(
                node_id=cand.node_id,
                name=f"cluster {cluster.key[0]}={cluster.key[1]}: {cluster.name}" if cluster is not None else cand.name,
                kind=cand.kind,
                cost=len(added),
                added_node_ids=added,
                mastery_effect=None if cluster is not None else (meta["trial"].get("mastery") or {}).get(cand.node_id),
                before=score,
                after=new_score,
                candidates_evaluated=proposed,
                candidates_skipped=skipped,
                seconds=time.perf_counter() - t0,
                added_mastery_effects=({cand.node_id: int((meta["trial"].get("mastery") or {})[cand.node_id])}
                                       if cluster is None and cand.node_id in (meta["trial"].get("mastery") or {}) else {}),
            )
            result.steps.append(step)
            result.points_spent += len(added)
            if cluster is not None:
                self.log(
                    f"cluster kept: {cluster.name} ({cluster.key[0]}={cluster.key[1]}) {len(added)} points: "
                    f"{score.value:,.0f} -> {new_score.value:,.0f}"
                )
            score = new_score
            self.log(result.summary().splitlines()[-1])

        result.final_score = score
        result.final_stats = stats
        if not result.stopped_reason:
            result.stopped_reason = "budget spent"
        return self._keep(result)

    # -- refine: swap weak leaves for better candidates -----------------------

    def refine(self, *, max_rounds: int = 30, max_swap_cost: int = 6, top_candidates: int = 80, min_gain: float = 0.002, repair_rounds: int = 60) -> AllocationResult:
        """Local search: free k points by dropping the k least valuable leaves and
        spend them on the best candidate of cost k. Accept when PoB says the
        objective improved (or a violation shrank). Repeat until no swap helps.

        While a floor is missed the swaps are a repair, and the point budget is
        already spent, so the cost of a swap is the DPS it loses, not its points:
        the swap chosen is the one with the most violation removed per DPS lost
        (a free repair first). Ranking repairs by violation removed per point took
        Quick Recovery for 45k and Wind Dancer for 36k on a Cold DoT seed whose
        regrown tree then lost to the old one (232k -> 133k). Repair rounds have
        their own budget (`repair_rounds`); `max_rounds` counts feasible rounds.

        A round costs one trial per removable leaf, one per candidate (up to `max_trials`) and one
        per swap (up to `top_candidates`) -- ~400 on a finished tree, 27 s in the campaign -- and
        the pipeline runs the move once per loop pass, so a pass that reverts everything hands the
        next one the very same build (speed audit 2026-09-18, finding 5). A round that measured
        every candidate and found no swap records the build it found nothing on; a later call that
        starts there returns at once instead of buying the same verdict again.
        """

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        self._read_config()  # the lanes the state key below carries, once per call
        result = AllocationResult()
        allocated = self.current_allocated()
        roots = {n for n in allocated if n not in self.graph.allocatable and not self.graph.is_inner_socket(n)}
        score, stats = self.current_score()
        keys = self.objective.stat_keys
        params = (int(max_swap_cost), int(top_candidates), float(min_gain))
        self._unswappable = set()  # blacklist is per refine call, not per optimizer lifetime
        state = self._state_key(stats, keys)
        if state is not None and (state, params) in self._barren:
            self.refine_skipped += 1
            result.stopped_reason = "no improving swap (measured on this build before)"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)

        def nothing_here(measured_everything: bool) -> None:
            """This build, under these parameters, has no swap for refine. Recorded only when the
            round that said so asked PoB about every leaf and every candidate: a verdict reached on
            a batch `skip_inert` had thinned, or with leaves blacklisted by a swap PoB refused, is
            a verdict about less than the whole neighbourhood and is not remembered."""

            if not measured_everything or self._unswappable:
                return
            key = self._state_key(stats, keys)
            if key is not None:
                self._barren.add((key, params))

        feasible_rounds = repair_rounds_done = 0
        while True:
            if score.feasible:
                if feasible_rounds >= max_rounds:
                    result.stopped_reason = "max rounds"
                    break
                feasible_rounds += 1
            else:
                if repair_rounds_done >= repair_rounds:
                    result.stopped_reason = "repair rounds"
                    break
                repair_rounds_done += 1
            t0 = time.perf_counter()
            leaves = [n for n in self.graph.removable_leaves(allocated, protected=self.protected, links=self._links())
                      if n in self.graph.allocatable and n not in self._unswappable]
            if not leaves:
                result.stopped_reason = "no removable leaves"
                nothing_here(True)
                break
            leaf_outcomes = self._measure([{"remove": [leaf]} for leaf in leaves], keys, stats)
            leaf_scores: list[tuple[Score, int]] = []
            for leaf, outcome in zip(leaves, leaf_outcomes):
                if outcome.get("ok") and outcome.get("stats") and len(outcome.get("removed_node_ids") or ()) == 1:
                    leaf_scores.append((self.objective.score(outcome["stats"]), leaf))
            # cheapest leaves first: those whose removal hurts least (higher score after removal)
            leaf_scores.sort(key=lambda item: (item[0].neg_violation, item[0].value), reverse=True)
            cheap_leaves = [leaf for _s, leaf in leaf_scores]

            candidates = [
                c
                for c in self.graph.candidates(allocated, max_depth=self.max_depth)
                if c.cost <= max_swap_cost and not (c.kind == "mastery" and c.cost > self.mastery_max_cost)
                and not self._attribute_cap_blocks(c, allocated)  # the probe adds `c` to the tree as it stands (#516)
            ]
            add_trials = self._trials_for(candidates)[: self.max_trials]
            proposed_adds = len(add_trials)
            violated = self.violated_floors(stats)
            before_filter = add_trials
            add_trials, add_skipped = self._filter_inert(add_trials, violated)  # the add batch only: leaves and swaps are always measured
            self._count_filtered(before_filter, add_trials)
            if not add_trials or not cheap_leaves:
                result.stopped_reason = "nothing to swap"
                nothing_here(add_skipped == 0)
                break
            add_outcomes = self._measure([t["trial"] for t in add_trials], keys, stats)
            ranked: list[tuple[tuple, dict, int]] = []
            scored: list[tuple[dict, dict, Score, int]] = []
            for meta, outcome in zip(add_trials, add_outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    self._note_failure(meta["candidate"], outcome)
                    continue
                cost = len(outcome.get("added_node_ids") or ()) or meta["candidate"].cost
                trial_score = self.objective.score(outcome["stats"])
                scored.append((meta, outcome, trial_score, cost))
            self._mark_inert(scored, score, violated)
            self._judge_with_enablers(scored)  # a Rage / charge generator is ranked with what it enables, as in allocate (#716)
            current_defence = bossing_defence(stats)
            for meta, outcome, trial_score, cost in scored:
                if cost > max_swap_cost or cost > len(cheap_leaves):
                    continue
                # #1167: candidates whose gain ties (a Life / maximum-hit notable gains 0.0 CombinedDPS) are ordered by the
                # bossing defence their add probe gives per point, the number the swap's accept tie-break reads; the
                # gain order of every untied candidate is the old one
                defence_per_point = (bossing_defence(outcome["stats"]) - current_defence) / max(1, cost)
                ranked.append(((*self._rank_key(score, trial_score, cost), defence_per_point), meta, cost))
            ranked.sort(key=lambda item: item[0], reverse=True)

            swap_trials = []
            for _key, meta, cost in ranked[:top_candidates]:
                to_remove = [leaf for leaf in cheap_leaves if leaf not in meta["trial"]["add"]][:cost]
                if len(to_remove) < cost:
                    continue
                if self._attribute_cap_blocks(meta["candidate"], allocated - set(to_remove)):
                    continue
                if self._cuts_protected(allocated, to_remove):
                    continue  # leaves that are each removable can still be a protected node's two ways round
                trial = dict(meta["trial"])
                trial["remove"] = to_remove
                swap_trials.append({"candidate": meta["candidate"], "trial": trial, "removed": to_remove})
            if not swap_trials:
                result.stopped_reason = "no affordable swap"
                nothing_here(add_skipped == 0)
                break
            swap_outcomes = self._measure([t["trial"] for t in swap_trials], keys, stats)
            best = None
            swapped: list[tuple[dict, dict, Score, int]] = []
            for meta, outcome in zip(swap_trials, swap_outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    continue
                net = len(outcome.get("added_node_ids") or ()) - len(outcome.get("removed_node_ids") or ())
                if net > 0:
                    continue
                swapped.append((meta, outcome, self.objective.score(outcome["stats"]), len(meta["removed"])))
            self._judge_with_enablers(swapped)  # the swap trial carries its `remove`: the hook judges the tree after the swap
            for meta, outcome, trial_score, _cost in swapped:
                better = trial_score > score and (
                    not score.feasible or trial_score.value >= score.value * (1.0 + min_gain)
                )
                if not better and not self._swap_ties_higher(score, stats, trial_score, outcome["stats"]):
                    continue
                if score.feasible:
                    if best is None or trial_score > best[0] or (
                        trial_score == best[0] and bossing_defence(outcome["stats"]) > bossing_defence(best[2]["stats"])
                    ):
                        best = (trial_score, meta, outcome)
                elif best is None or self.repair_key(score, trial_score) > self.repair_key(score, best[0]):
                    best = (trial_score, meta, outcome)
            if best is None:
                result.stopped_reason = "no improving swap"
                nothing_here(add_skipped == 0)
                break
            trial_score, meta, outcome = best
            cand: Candidate = meta["candidate"]
            snapshot = self._snapshot()
            if self.needs_honest_removal(meta["removed"]):
                removed = self.pob.mutate_nodes(remove=meta["removed"])
                self.after_real_removal(removed)
                if len(removed["removed_node_ids"]) != len(meta["removed"]):
                    self._restore(snapshot, score, f"refine removal {cand.name}")
                    score, stats = self.current_score()
                    allocated = self.current_allocated()
                    self.skipped_errors["swap did not verify"] = self.skipped_errors.get("swap did not verify", 0) + 1
                    self._unswappable.update(meta["removed"])
                    continue
                applied = self.pob.mutate_nodes(add=[cand.node_id], mastery_effects=meta["trial"].get("mastery") or None)
                applied = {**applied, "removed_node_ids": removed["removed_node_ids"],
                           "removed_mastery_effects": removed.get("removed_mastery_effects") or ()}
            else:
                applied = self.pob.mutate_nodes(
                    add=[cand.node_id], remove=meta["removed"], mastery_effects=meta["trial"].get("mastery") or None
                )
            if self.after_apply_hook is not None and self.generator_effects(cand.node_id):
                # as in allocate: the swap was judged with the generator's toggle, so the lanes must see it before the verdict
                self.after_apply_hook(cand)
                self.note_config_change()
                self._refresh_charge_toggles()
            prior_stats = stats
            new_score, stats = self.current_score()
            cascaded = len(applied["removed_node_ids"]) != len(meta["removed"])
            if cascaded or not (new_score > score or self._swap_ties_higher(score, prior_stats, new_score, stats)):
                # PoB disagreed with the trial (e.g. a removal cascaded beyond the
                # graph's leaf estimate). Restore the exact prior build from XML.
                self._restore(snapshot, score, f"refine swap {cand.name}")
                score, stats = self.current_score()
                allocated = self.current_allocated()
                self.skipped_errors["swap did not verify"] = self.skipped_errors.get("swap did not verify", 0) + 1
                for leaf in meta["removed"]:
                    self._unswappable.add(leaf)
                continue
            allocated = set(int(n) for n in applied["allocated_node_ids"]) | roots
            # a swap both adds and removes: every candidate near either end is worth measuring again
            self._invalidate_inert([int(n) for n in applied["added_node_ids"]] + [int(n) for n in applied["removed_node_ids"]],
                                   everything=cand.kind == "keystone" or bool(self.generator_effects(cand.node_id)))
            step = Step(
                node_id=cand.node_id,
                name=f"{cand.name} (swap -{len(meta['removed'])})",
                kind=cand.kind,
                cost=len(applied["added_node_ids"]),
                added_node_ids=[int(n) for n in applied["added_node_ids"]],
                mastery_effect=(meta["trial"].get("mastery") or {}).get(cand.node_id),
                before=score,
                after=new_score,
                candidates_evaluated=len(leaves) + proposed_adds + len(swap_trials),
                candidates_skipped=add_skipped,
                seconds=time.perf_counter() - t0,
                removed_node_ids=[int(n) for n in applied["removed_node_ids"]],
                added_mastery_effects=({cand.node_id: int((meta["trial"].get("mastery") or {})[cand.node_id])}
                                       if cand.node_id in (meta["trial"].get("mastery") or {}) else {}),
            )
            result.steps.append(step)
            score = new_score
            self.log(result.summary().splitlines()[-1])

        result.final_score = score
        result.final_stats = stats
        if not result.stopped_reason:
            result.stopped_reason = "max rounds"
        return self._keep(result)

    @staticmethod
    def _swap_ties_higher(current: Score, current_stats: Mapping[str, object], trial: Score, trial_stats: Mapping[str, object]) -> bool:
        """#1167: the swap's tie-break. At a value no lower than the current, with both builds feasible (every floor
        held, so a Life 4,499 against the floor 4,500 never gets here), the swap is kept when the bossing defence (the
        smallest maximum hit taken, `bossing_defence`) is higher. `Score` alone cannot rank it: equal value and
        violation 0 compare equal, and `min_gain` is not asked of a tie. The objective reports TotalEHP only, so the
        loop's stats do not carry it; the maximum hits are floors and are always there."""

        return (current.feasible and trial.feasible and current.value > 0.0 and trial.value >= current.value
                and bossing_defence(trial_stats) > bossing_defence(current_stats))

    @staticmethod
    def repair_key(current: Score, trial: Score) -> tuple[float, float, float]:
        """Ordering of swaps while a floor is missed (points already spent, so the
        cost is DPS): a free repair (violation down, value not down) first, by the
        violation removed; then paid repairs by violation removed per DPS lost;
        then swaps that only raise the value."""

        reduction = current.violation - trial.violation
        loss = current.value - trial.value
        if reduction <= 0:
            return (0.0, trial.value, 0.0)
        if loss <= 0:
            return (2.0, reduction, -loss)
        return (1.0, reduction / loss, reduction)

    # -- ruin and recreate ---------------------------------------------------

    REPAIR_POLICIES = ("greedy", "target-first")

    def reoptimize(self, *, rounds: int = 3, ruin_points: int = 20, refine_rounds: int = 10, seed: int = 0,
                   repair: str = "alternate") -> AllocationResult:
        """Iterated greedy (ruin and recreate): remove whole random branches worth
        about `ruin_points`, re-spend them with the greedy allocator that now sees
        the rest of the tree, then refine. Keep the round only if the objective
        improved; otherwise restore the previous tree. Random branches (not the
        cheapest leaves) so the recreate step explores a different region.

        `repair` names the recreate policy: "greedy", "target-first" (plan B move 3), or
        "alternate" -- round 1 greedy, round 2 target-first, and so on, because "a larger destroy
        set can still recreate the same greedy basin" (Ropke-Pisinger's regret repair; Astra A).
        The loop's kick draws call this with `rounds=1`, so they stay greedy exactly as before and
        remain the control the plan-B acceptance is measured against.
        """

        import random

        if repair != "alternate" and repair not in self.REPAIR_POLICIES:
            raise ValueError(f"unknown repair policy {repair!r}; legal: alternate, " + ", ".join(self.REPAIR_POLICIES))

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        result = AllocationResult()
        score, stats = self.current_score()
        rng = random.Random(seed)
        for round_index in range(rounds):
            t0 = time.perf_counter()
            snapshot = self._snapshot()
            allocated = self.current_allocated()
            victims = self._random_branches(allocated, ruin_points, rng)
            if not victims:
                result.stopped_reason = "no branch to ruin"
                break
            removed = self.pob.mutate_nodes(remove=victims)
            if self._dropped_protected(removed):
                self._restore(snapshot, score, f"reoptimize round {round_index + 1} (a forced node went with the ruin)")
                result.stopped_reason = "ruin reached a forced node"
                break
            self.after_real_removal(removed)
            points = len(removed["removed_node_ids"])
            self._invalidate_inert([int(n) for n in removed["removed_node_ids"]])
            remaining = self.current_allocated()
            policy = repair if repair != "alternate" else self.REPAIR_POLICIES[round_index % len(self.REPAIR_POLICIES)]
            self.log(f"reoptimize round {round_index + 1}: ruined {points} points from {len(victims)} leaves ({policy})")
            if policy == "target-first":
                anchors = {int(n) for victim in victims for n in self.graph.neighbours(int(victim))} & remaining
                alloc = self.repair_target_first(points, attachment=anchors or None)
            else:
                alloc = self.allocate(points, allocated=remaining)
            refine = self.refine(max_rounds=refine_rounds)
            new_score, new_stats = self.current_score()
            if not new_score.feasible and new_score.value > score.value:
                # Worth repairing: a second refine pass focused on feasibility.
                repair = self.refine(max_rounds=refine_rounds)
                refine.steps.extend(repair.steps)
                new_score, new_stats = self.current_score()
            self.log(
                f"reoptimize round {round_index + 1}: after recreate value {new_score.value:,.0f} viol {new_score.violation:.3f} "
                f"(alloc stop: {alloc.stopped_reason}; refine: {len(refine.steps)} swaps, stop: {refine.stopped_reason}; "
                f"skipped: {dict(self.skipped_errors)})"
            )
            if new_score > score:
                result.steps.extend(alloc.steps)
                result.steps.extend(refine.steps)
                result.points_spent += alloc.points_spent
                self.log(f"reoptimize round {round_index + 1}: {score.value:,.0f} -> {new_score.value:,.0f} kept ({time.perf_counter() - t0:.0f}s)")
                score, stats = new_score, new_stats
            else:
                self._restore(snapshot, score, f"reoptimize round {round_index + 1}")
                self.log(f"reoptimize round {round_index + 1}: {new_score.value:,.0f} <= {score.value:,.0f}, reverted ({time.perf_counter() - t0:.0f}s)")
        result.final_score = score
        result.final_stats = stats
        if not result.stopped_reason:
            result.stopped_reason = "rounds done"
        return self._keep(result)

    # -- path for path -------------------------------------------------------

    def swap_subtrees(self, *, max_size: int = 6, min_gain: float = 0.002, max_seconds: float | None = None,
                      max_failures: int = 12, max_candidates: int | None = None) -> AllocationResult:
        """Path-for-path finishing pass: every small hanging subtree (the nodes
        that fall off when one allocated node is cut, up to `max_size` of them)
        is removed whole and its points re-spent greedily wherever the tree now
        wants them. Kept only if PoB says the objective improved. Candidates are
        tried cheapest-loss-per-point first under a time budget, and the pass
        stops after `max_failures` consecutive non-improvements. ``max_candidates``
        is the deterministic alternative used by replay measurements: it limits
        started subtree replacements rather than elapsed seconds.
        """

        # #569: with neither budget the pass is still bounded: by `max_failures` in a row and the finite subtree list
        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        result = AllocationResult()
        t_all = time.perf_counter()
        self._read_config()  # the lanes the trial memo keys on, once per call
        score, stats = self.current_score()
        keys = self.objective.stat_keys
        allocated = self.current_allocated()
        subtrees: dict[frozenset[int], int] = {}
        for node in allocated:
            if node not in self.graph.allocatable:
                continue
            cascade = frozenset(self.graph.cascade_if_removed(allocated, node, self._links()))
            if 1 <= len(cascade) <= max_size and not (self.protected & cascade):
                subtrees.setdefault(cascade, node)
        if not subtrees:
            result.stopped_reason = "no small subtrees"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)
        order = list(subtrees)
        outcomes = self._measure([{"remove": sorted(sub)} for sub in order], keys, stats)
        ranked: list[tuple[float, frozenset[int]]] = []
        for sub, outcome in zip(order, outcomes):
            if not outcome.get("ok") or not outcome.get("stats"):
                continue
            after = self.objective.score(outcome["stats"])
            # subtrees whose removal alone breaks a floor (life clusters) go last: the
            # greedy re-spend repairs violations first, so they are still worth a try
            loss_pp = (score.value - after.value) / max(1, len(sub)) if (after.feasible or not score.feasible) else float("inf")
            ranked.append((loss_pp, sub))
        ranked.sort(key=lambda item: item[0])
        budget = (f"{max_candidates} candidates" if max_candidates is not None else f"{max_seconds:.0f}s" if max_seconds is not None
                  else f"{max_failures} failures in a row")
        self.log(f"path swaps: {len(ranked)} hanging subtrees <= {max_size} nodes (of {len(subtrees)}), budget {budget}")
        failures = 0
        attempts = 0
        worst_seen = 0.0  # the longest candidate so far: the budget check refuses to start one that would overrun
        skipped_here = 0
        fingerprint = frozenset(allocated)
        for loss_pp, sub in ranked:
            spent = time.perf_counter() - t_all
            if ((max_seconds is not None and spent + worst_seen > max_seconds)
                    or (max_candidates is not None and attempts >= max_candidates)
                    or failures >= max_failures):
                # D58 budget: a candidate costs 25-58 s, so checking only "am I already over" let a
                # 120 s pass run to 144 s (speed audit 2026-09-18). A candidate is started only when
                # the longest one measured so far still fits.
                if failures >= max_failures:
                    result.stopped_reason = "consecutive failures"
                elif max_candidates is not None and attempts >= max_candidates:
                    result.stopped_reason = "candidate budget"
                else:
                    result.stopped_reason = "time budget"
                break
            if (fingerprint, sub) in self._rejected_subtrees:
                # the same subtree on the same tree was already proven not to pay: the improvement
                # loop reverts a whole pass, so the next pass starts from exactly this tree and
                # would re-derive the same rejection at 25-58 s a time
                self.subtree_retries_skipped += 1
                skipped_here += 1
                continue
            t0 = time.perf_counter()
            attempts += 1
            snapshot = self._snapshot()
            removed = self.pob.mutate_nodes(remove=sorted(sub))
            if self._dropped_protected(removed):
                self._restore(snapshot, score, "path swap (a forced node went with the cut)")
                self._rejected_subtrees.add((fingerprint, sub))
                continue
            self.after_real_removal(removed)
            points = len(removed["removed_node_ids"])
            self._invalidate_inert([int(n) for n in removed["removed_node_ids"]])
            if points == 0:
                continue
            alloc = self.allocate(points, allocated=self.current_allocated())
            new_score, new_stats = self.current_score()
            better = new_score > score and (not score.feasible or new_score.value >= score.value * (1.0 + min_gain))
            names = ", ".join(self.graph.node(n).name for n in sorted(sub) if self.graph.node(n))[:80]
            if better:
                bought = ", ".join(st.name for st in alloc.steps)[:80]
                self.log(f"path swap kept: -{points} [{names}] -> +{alloc.points_spent} [{bought}]  value {score.value:,.0f} -> {new_score.value:,.0f} ({time.perf_counter() - t0:.0f}s)")
                result.steps.append(Step(node_id=subtrees[sub], name=f"path swap -{points} [{names[:40]}]", kind="path", cost=points, added_node_ids=[n for st in alloc.steps for n in st.added_node_ids], mastery_effect=None, before=score, after=new_score, candidates_evaluated=len(ranked), seconds=time.perf_counter() - t0, removed_node_ids=[int(n) for n in removed["removed_node_ids"]], added_mastery_effects={int(st.node_id): int(st.mastery_effect) for st in alloc.steps if st.mastery_effect is not None}))
                result.points_spent += points
                score, stats = new_score, new_stats
                failures = 0
                fingerprint = frozenset(self.current_allocated())  # a kept swap is a different tree: earlier rejections do not apply to it
            else:
                self._restore(snapshot, score, f"path swap -{points} [{names[:40]}]")
                failures += 1
                self._rejected_subtrees.add((fingerprint, sub))
                self.log(f"path swap no gain: -{points} [{names}] loss/pt {loss_pp:,.0f}: {new_score.value:,.0f} vs {score.value:,.0f} ({time.perf_counter() - t0:.0f}s)")
            worst_seen = max(worst_seen, time.perf_counter() - t0)
        if skipped_here:
            self.log(f"path swaps: {skipped_here} subtrees skipped, rejected before on this tree")
        result.final_score, result.final_stats = self.current_score()
        if not result.stopped_reason:
            result.stopped_reason = "all subtrees tried"
        return self._keep(result)

    # -- plan B: moves of the trunk's own ------------------------------------
    #
    # 22% of a delivered tree's allocated nodes drop 13 or more nodes when cut and no move ever
    # reconsidered them after construction (measured over the 14 best builds of `core14-rules`).
    # The three moves below are the ones the Steiner literature calls key-path exchange and
    # key-vertex elimination, with PoB as the judge: the graph only proposes, every accepted
    # change is a real mutation the caller judges under re-derived lanes.

    KEY_KINDS = ("notable", "keystone", "mastery", "jewel", "class_start", "ascendancy")
    REGION_BUCKETS = ((4, 6), (7, 12), (13, 20), (21, 30))

    def key_nodes(self, allocated: Iterable[int]) -> set[int]:
        """Allocated nodes a corridor may not run through: the graph roots (class start,
        ascendancy), every branch point (three or more allocated neighbours), every node the build
        was chosen FOR (notable, keystone, jewel socket, mastery anchor) and every proof holder of
        D87. Everything else is an ordinary point on the way to somewhere."""

        allocated_set = {int(n) for n in allocated}
        keys: set[int] = set()
        for node_id in allocated_set:
            node = self.graph.node(node_id)
            if (node_id not in self.graph.allocatable
                    or node is None
                    or node.kind in self.KEY_KINDS
                    or len(self.graph.neighbours(node_id) & allocated_set) >= 3
                    or self.needs_honest_removal((node_id,))):
                keys.add(node_id)
        return keys

    def corridors(self, allocated: Iterable[int] | None = None) -> list[Corridor]:
        """Every maximal run of ordinary allocated nodes between two key nodes, each found once
        (the walk reaches it from both ends), longest first."""

        allocated_set = {int(n) for n in (allocated if allocated is not None else self.current_allocated())}
        keys = self.key_nodes(allocated_set)
        found: dict[tuple[frozenset[int], frozenset[int]], Corridor] = {}
        for start in sorted(keys):
            for first in sorted(self.graph.neighbours(start) & allocated_set):
                if first in keys:
                    continue
                inner: list[int] = []
                prev, cur = start, first
                while cur not in keys and len(self.graph.neighbours(cur) & allocated_set) == 2:
                    inner.append(cur)
                    onward = sorted((self.graph.neighbours(cur) & allocated_set) - {prev})
                    if not onward:
                        break
                    prev, cur = cur, onward[0]
                # a run that ends on an ordinary dangling node is a leaf branch (refine's job), and
                # one that comes back to its own start is a loop with nothing on the other side
                if cur in keys and inner and cur != start:
                    found.setdefault((frozenset({start, cur}), frozenset(inner)),
                                     Corridor(a=start, b=cur, inner=tuple(inner)))
        return sorted(found.values(), key=lambda c: (-len(c.inner), c.a, c.b))

    def _names(self, node_ids: Iterable[int], limit: int = 80) -> str:
        out = ", ".join(self.graph.node(int(n)).name if self.graph.node(int(n)) else str(n) for n in node_ids)
        return out[:limit]

    def _ball(self, anchors: Iterable[int], radius: int) -> set[int]:
        """Every graph node within `radius` steps of an anchor, allocation ignored."""

        seen = {int(n) for n in anchors}
        frontier = set(seen)
        for _step in range(max(0, int(radius))):
            nxt = {int(nb) for node_id in frontier for nb in self.graph.neighbours(node_id)} - seen
            if not nxt:
                break
            seen |= nxt
            frontier = nxt
        return seen

    def _weakest_leaves(self, allocated: set[int], stats: Mapping[str, object] | None) -> list[int]:
        """Removable leaves, least valuable first (refine's own ranking, one fast what-if each).
        A bypass longer than the corridor it replaces pays for the extra points out of this list."""

        leaves = [n for n in self.graph.removable_leaves(allocated, protected=self.protected, links=self._links()) if n in self.graph.allocatable]
        if not leaves:
            return []
        outcomes = self._measure([{"remove": [leaf]} for leaf in leaves], self.objective.stat_keys, stats)
        ranked: list[tuple[Score, int]] = []
        for leaf, outcome in zip(leaves, outcomes):
            if outcome.get("ok") and outcome.get("stats") and len(outcome.get("removed_node_ids") or ()) == 1:
                ranked.append((self.objective.score(outcome["stats"]), leaf))
        ranked.sort(key=lambda item: (item[0].neg_violation, item[0].value), reverse=True)
        return [leaf for _score, leaf in ranked]

    @staticmethod
    def _beats(score: Score, other: Score, min_gain: float) -> bool:
        """The loop's own acceptance rule (D58), taken from `objective.better_score` rather than
        written out a fourth time: while a floor is missed any improvement of the Score ordering
        counts -- feasibility first -- and once feasible the value must grow by `min_gain`."""

        return better_score(other, score, min_gain=min_gain)

    def exchange_corridors(self, *, k: int = 8, slack: int = 2, min_gain: float = 0.002,
                           max_corridors: int = 40, max_applied: int = 8, max_failures: int = 6,
                           max_seconds: float | None = None) -> AllocationResult:
        """Key-path exchange: swap a corridor for another way between the same two key nodes.

        For each corridor, up to `k` alternative connections through unallocated nodes (shortest
        first, at most `corridor + slack` points long); the extra points of a longer way are paid
        by dropping the currently weakest leaves. Every completed exchange is scored by ONE fast
        what-if -- PoB's fast calculator does not cascade, so a set that is momentarily
        disconnected is still evaluable, and the connectivity of the final set is ours to prove --
        and the best ones are applied for real, bypass first so that removing the corridor
        cascades nothing. The caller judges what this leaves behind.

        Budgets are COUNTS (`max_corridors`, `k`, `max_applied`, `max_failures`) so that a replay
        measurement is deterministic; `max_seconds` is the outer guard production passes in.
        """

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        self._read_config()  # the lanes the trial memo keys on, once per call
        result = AllocationResult()
        t_all = time.perf_counter()
        score, stats = self.current_score()
        keys = self.objective.stat_keys
        allocated = self.current_allocated()
        corridors = self.corridors(allocated)[:max_corridors]
        if not corridors:
            result.stopped_reason = "no corridors"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)
        # a mastery on the way would need an effect id chosen for it: it is a destination, never a
        # node a corridor runs through. Ascendancy and start nodes are not allocatable at all.
        pool = {
            n for n in self.graph.allocatable
            if n not in allocated and n not in self.excluded_nodes
            and (self.graph.node(n) is None or self.graph.node(n).kind != "mastery")
        }
        leaf_order = self._weakest_leaves(allocated, stats)
        trials: list[dict] = []
        no_bypass: list[Corridor] = []
        for corridor in corridors:
            self.plan_b_counts["corridors"] += 1
            if self.protected & set(corridor.inner):
                continue  # a forced node never leaves, even where it sits between two key nodes
            paths = self.graph.bypass_paths(corridor.a, corridor.b, allowed=pool,
                                            max_inner=corridor.points + slack, limit=k)
            if not paths:
                self.plan_b_counts["corridors_no_bypass"] += 1
                no_bypass.append(corridor)
                continue
            self.plan_b_counts["corridors_with_bypass"] += 1
            for path in paths:
                extra = len(path) - corridor.points
                drop: list[int] = []
                if extra > 0:
                    blocked = set(path) | set(corridor.inner) | {corridor.a, corridor.b} | set(self.protected)
                    drop = [leaf for leaf in leaf_order if leaf not in blocked][:extra]
                    if len(drop) < extra:
                        continue  # not enough spare leaves to pay for the longer way round
                trials.append({
                    "corridor": corridor, "path": path, "drop": drop,
                    "trial": {"add": list(path), "remove": sorted(set(corridor.inner) | set(drop)), "mastery": {}},
                })
        if no_bypass:
            self.log(f"no bypass: {len(no_bypass)} of {len(corridors)} corridors, e.g. "
                     + "; ".join(f"{self._names(c.inner, 40)} ({c.points}p)" for c in no_bypass[:5]))
        if not trials:
            result.stopped_reason = "no bypass anywhere"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)

        self.plan_b_counts["corridor_candidates"] += len(trials)
        outcomes = self._measure([t["trial"] for t in trials], keys, stats)
        ranked: list[tuple[Score, dict]] = []
        for meta, outcome in zip(trials, outcomes):
            if not outcome.get("ok") or not outcome.get("stats"):
                continue
            added = {int(n) for n in outcome.get("added_node_ids") or ()}
            removed = {int(n) for n in outcome.get("removed_node_ids") or ()}
            if added != set(meta["path"]) or removed != set(meta["trial"]["remove"]):
                # PoB reached a bypass node by its own shortest route from the whole allocation
                # rather than along this corridor, so the trial is not the exchange this candidate
                # names: it is not priced at all rather than priced as something else
                self.plan_b_counts["corridor_unpriceable"] += 1
                continue
            self.considered_removals |= removed
            ranked.append((self.objective.score(outcome["stats"]), meta))
        ranked.sort(key=lambda item: item[0], reverse=True)  # Score orders by violation, then value
        self.log(f"corridor exchange: {len(corridors)} corridors, {self.plan_b_counts['corridors_with_bypass']} with a bypass, "
                 f"{len(ranked)} priced candidates")

        applied = failures = 0
        for predicted, meta in ranked:
            if applied >= max_applied:
                result.stopped_reason = "candidate budget"
                break
            if failures >= max_failures:
                result.stopped_reason = "consecutive failures"
                break
            if max_seconds is not None and time.perf_counter() - t_all > max_seconds:
                result.stopped_reason = "time budget"
                break
            if not self._beats(score, predicted, min_gain):
                result.stopped_reason = "no exchange improves the objective"
                break  # ranked best first: nothing after this one can beat it either
            corridor, path = meta["corridor"], meta["path"]
            remove = [int(n) for n in meta["trial"]["remove"]]
            allocated_now = self.current_allocated()
            if (set(path) & allocated_now) or not set(remove) <= allocated_now:
                continue  # an exchange kept earlier in this pass already moved this piece of tree
            if not self.graph.is_connected((allocated_now | set(path)) - set(remove), self._links()):
                continue
            if self._cuts_protected(allocated_now | set(path), remove):
                continue
            t0 = time.perf_counter()
            applied += 1
            self.plan_b_counts["corridor_applied"] += 1
            honest = self.needs_honest_removal(remove)
            if honest:
                self.plan_b_counts["honest_removals"] += 1
            what = f"-{len(remove)} [{self._names(remove)}] -> +{len(path)} [{self._names(path)}]"
            snapshot = self._snapshot()
            # the bypass FIRST: PoB's real removal cascades, and the far side of a corridor is
            # everything hanging off its other end
            added_ids: list[int] = []
            if path:
                added_now = self.pob.mutate_nodes(add=list(path))
                added_ids = [int(n) for n in added_now.get("added_node_ids") or ()]
                if set(added_ids) != set(path):
                    self._restore(snapshot, score, f"corridor bypass {what}")
                    failures += 1
                    continue
            removed_now = self.pob.mutate_nodes(remove=remove)
            self.after_real_removal(removed_now)  # a dropped leaf can be a proof holder (D87)
            removed_ids = [int(n) for n in removed_now.get("removed_node_ids") or ()]
            if set(removed_ids) != set(remove):
                self._restore(snapshot, score, f"corridor removal {what}")
                failures += 1
                continue
            new_score, new_stats = self.current_score()
            net = len(added_ids) - len(removed_ids)
            if net < 0:  # a shorter way round frees points; they are spent before the move is judged
                fill = self.allocate(-net, allocated=self.current_allocated())
                added_ids += [int(n) for step in fill.steps for n in step.added_node_ids]
                new_score, new_stats = self.current_score()
            if net > 0 or not self._beats(score, new_score, min_gain):
                self._restore(snapshot, score, f"corridor exchange {what}")
                score, stats = self.current_score()
                failures += 1
                self.log(f"corridor exchange no gain: {what}: {new_score.value:,.0f} vs {score.value:,.0f} "
                         f"({time.perf_counter() - t0:.0f}s)")
                continue
            self._invalidate_inert(added_ids + removed_ids, everything=True)
            self.log(f"corridor exchange kept{' (honest)' if honest else ''}: {what} "
                     f"value {score.value:,.0f} -> {new_score.value:,.0f} ({time.perf_counter() - t0:.0f}s)")
            result.steps.append(Step(
                node_id=corridor.a, name=f"corridor -{len(remove)} [{self._names(remove, 40)}]", kind="corridor",
                cost=len(added_ids), added_node_ids=added_ids, mastery_effect=None, before=score, after=new_score,
                candidates_evaluated=len(ranked), seconds=time.perf_counter() - t0, removed_node_ids=removed_ids,
            ))
            result.points_spent += len(added_ids)
            self.plan_b_counts["corridor_kept"] += 1
            score, stats, failures = new_score, new_stats, 0
        result.final_score, result.final_stats = self.current_score()
        if not result.stopped_reason:
            result.stopped_reason = "all candidates tried"
        return self._keep(result)

    def repair_target_first(self, points: int, *, attachment: Iterable[int] | None = None, radius: int = 8,
                            max_targets: int | None = None) -> AllocationResult:
        """The second repair policy: commit to a destination instead of to the next cheap node.

        Among the unallocated notables, allowed keystones and mastery anchors within `radius` of
        the attachment, each is scored by one fast what-if and divided by the points its connection
        costs; the
        best target's whole connection is allocated, and the search repeats while points remain.
        Whatever is left over is spent by the greedy allocator. Greedy alone looks one node ahead
        and re-creates the basin it came from (Ropke-Pisinger's regret repair; Astra A priority 3).

        PoB's fast what-if cannot allocate a node without its path, so "the node's own value"
        here is the value of the whole connection and the division by its cost is exactly the
        ratio the policy ranks by.
        """

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        result = AllocationResult()
        score, stats = self.current_score()
        keys = self.objective.stat_keys
        points_left = int(points)
        ball = self._ball(attachment, radius) if attachment is not None else None
        targets_taken = 0
        while points_left > 0 and (max_targets is None or targets_taken < max_targets):
            t0 = time.perf_counter()
            allocated = self.current_allocated()
            candidates = [
                c for c in self.graph.candidates(allocated, max_depth=min(radius, points_left))
                if c.kind in ("notable", "keystone", "mastery") and c.cost <= points_left
                and not (c.kind == "mastery" and c.cost > self.mastery_max_cost)
                and (ball is None or c.node_id in ball)
                and not self._attribute_cap_blocks(c, allocated)  # (#516)
            ]
            trials = self._trials_for(candidates)[: self.max_trials]
            if not trials:
                result.stopped_reason = "no target in radius"
                break
            outcomes = self._measure([t["trial"] for t in trials], keys, stats)
            best: tuple[tuple[float, float], dict, dict, Score, int] | None = None
            for meta, outcome in zip(trials, outcomes):
                if not outcome.get("ok") or not outcome.get("stats"):
                    self._note_failure(meta["candidate"], outcome)
                    continue
                cost = len(outcome.get("added_node_ids") or ()) or meta["candidate"].cost
                if cost > points_left:
                    continue
                trial_score = self.objective.score(outcome["stats"])
                key = self._rank_key(score, trial_score, cost)
                if best is None or key > best[0]:
                    best = (key, meta, outcome, trial_score, cost)
            if best is None:
                result.stopped_reason = "no evaluable target"
                break
            _key, meta, _outcome, trial_score, _cost = best
            if score.feasible and trial_score.feasible and trial_score.value <= score.value:
                result.stopped_reason = "no target improves the objective"
                break
            cand: Candidate = meta["candidate"]
            applied = self.pob.mutate_nodes(add=[cand.node_id], mastery_effects=meta["trial"].get("mastery") or None)
            added = [int(n) for n in applied["added_node_ids"]]
            if not added:
                result.stopped_reason = "target did not allocate"
                break
            points_left -= len(added)
            targets_taken += 1
            self._invalidate_inert(added, everything=cand.kind == "keystone")
            new_score, stats = self.current_score()
            effect = (meta["trial"].get("mastery") or {}).get(cand.node_id)
            result.steps.append(Step(
                node_id=cand.node_id, name=f"target {cand.name}", kind=cand.kind, cost=len(added),
                added_node_ids=added, mastery_effect=effect, before=score, after=new_score,
                candidates_evaluated=len(trials), seconds=time.perf_counter() - t0,
                added_mastery_effects={cand.node_id: int(effect)} if effect is not None else {},
            ))
            result.points_spent += len(added)
            score = new_score
        if points_left > 0:
            fill = self.allocate(points_left, allocated=self.current_allocated())
            result.steps.extend(fill.steps)
            result.points_spent += fill.points_spent
            score, stats = self.current_score()
            if not result.stopped_reason:
                result.stopped_reason = fill.stopped_reason
        result.final_score, result.final_stats = score, stats
        if not result.stopped_reason:
            result.stopped_reason = "budget spent"
        return self._keep(result)

    def _regions(self, allocated: set[int]) -> list[tuple[str, int, frozenset[int]]]:
        """(bucket, cut node, the allocated set that detaches when the cut node goes), each
        detachable set once, in the spec's size buckets."""

        found: dict[frozenset[int], int] = {}
        for node_id in sorted(allocated):
            if node_id not in self.graph.allocatable:
                continue
            cascade = frozenset(self.graph.cascade_if_removed(allocated, node_id, self._links()))
            if self.protected & cascade:
                continue
            if any(low <= len(cascade) <= high for low, high in self.REGION_BUCKETS):
                found.setdefault(cascade, node_id)
        out: list[tuple[str, int, frozenset[int]]] = []
        for cascade, cut in found.items():
            bucket = next(f"{low}-{high}" for low, high in self.REGION_BUCKETS if low <= len(cascade) <= high)
            out.append((bucket, cut, cascade))
        return sorted(out, key=lambda item: (item[0], item[1]))

    def _replacement_chains(self, remaining: set[int], anchors: set[int], points: int, *,
                            count: int, radius: int) -> list[tuple[int, ...]]:
        """Up to `count` candidate regrowths of exactly `points` points near `anchors`, built from
        the graph alone: each starts at one payoff target's shortest connection, is topped up with
        the next nearest targets and then with the cheapest frontier nodes. A ranking probe only --
        PoB prices it, PoB never has to reproduce it."""

        if points <= 0:
            return []

        def usable(node_id: int) -> bool:
            """A chain is one fast what-if with no mastery effect chosen for it, so a mastery on
            the way would make PoB refuse the whole trial: it is left to the real regrow."""

            node = self.graph.node(node_id)
            return node_id not in self.excluded_nodes and (node is None or node.kind != "mastery")

        ball = self._ball(anchors, radius)
        costs = self.graph.bfs_costs(remaining, max_depth=min(points, radius))
        targets = sorted(
            (cost, int(node_id), tuple(int(n) for n in path))
            for node_id, (cost, path) in costs.items()
            if node_id in ball and cost <= points and all(usable(int(n)) for n in path)
            and (self.graph.node(node_id).kind if self.graph.node(node_id) else "normal") in ("notable", "keystone")
        )

        chains: list[tuple[int, ...]] = []
        seen: set[tuple[int, ...]] = set()
        for _cost, _node_id, seed_path in targets[:count]:
            chosen = list(seed_path)
            taken = set(chosen)
            for _c, _n, path in targets:
                if len(chosen) >= points:
                    break
                fresh = [n for n in path if n not in taken]
                if not fresh or len(chosen) + len(fresh) > points:
                    continue
                chosen.extend(fresh)
                taken.update(fresh)
            frontier = {n for n in self.graph.frontier(remaining | taken) if n not in taken}
            while len(chosen) < points:
                options = sorted(n for n in frontier if n not in taken and usable(n))
                if not options:
                    break
                pick = options[0]
                chosen.append(pick)
                taken.add(pick)
                frontier.discard(pick)
                frontier |= {int(n) for n in self.graph.neighbours(pick)
                             if n in self.graph.allocatable and n not in taken and n not in remaining}
            key = tuple(sorted(chosen))
            if len(chosen) == points and key not in seen:
                seen.add(key)
                chains.append(tuple(chosen))
        return chains

    def challenge_regions(self, *, replacements: int = 12, min_gain: float = 0.002, radius: int = 8,
                          per_bucket: int = 16, max_challenges: int = 4, max_failures: int = 4,
                          max_seconds: float | None = None) -> AllocationResult:
        """Key-vertex elimination: challenge whole detachable regions, ranked by what could
        REPLACE them rather than by what they cost to remove.

        "A branch with loss 100 and replacement recovery 150 is a better rebuild opportunity than
        a branch with loss 1 and recovery 1.2" (Astra A, 3.2): every region is given up to
        `replacements` cheap completed replacements of its own point count, each priced by one
        fast what-if, and the regions are ordered by the best of those. The top ones are then
        challenged for real -- the region removed, the points regrown with the region's own nodes
        FORBIDDEN for the first half (otherwise the greedy rebuilds the very trunk being
        challenged and the challenge tests nothing) -- alternating the two repair policies.
        """

        self._stage_depth += 1  # paired with the decrement in _keep, the single exit
        self._read_config()
        result = AllocationResult()
        t_all = time.perf_counter()
        score, stats = self.current_score()
        keys = self.objective.stat_keys
        allocated = self.current_allocated()
        regions = self._regions(allocated)
        pool: list[tuple[str, int, frozenset[int]]] = []
        for low, high in self.REGION_BUCKETS:
            bucket = f"{low}-{high}"
            pool.extend([r for r in regions if r[0] == bucket][:per_bucket])
        if not pool:
            result.stopped_reason = "no regions"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)

        trials: list[dict] = []
        for bucket, cut, cascade in pool:
            self.plan_b_counts["regions"] += 1
            remaining = allocated - set(cascade)
            anchors = {int(n) for node_id in cascade for n in self.graph.neighbours(int(node_id))} & remaining
            if not anchors:
                continue
            for chain in self._replacement_chains(remaining, anchors, len(cascade),
                                                  count=replacements, radius=radius):
                trials.append({
                    "bucket": bucket, "cut": cut, "cascade": cascade, "anchors": anchors,
                    "trial": {"add": list(chain), "remove": sorted(cascade), "mastery": {}},
                })
        if not trials:
            result.stopped_reason = "no replacement found"
            result.final_score, result.final_stats = score, stats
            return self._keep(result)
        self.plan_b_counts["region_candidates"] += len(trials)
        outcomes = self._measure([t["trial"] for t in trials], keys, stats)
        best_by_region: dict[frozenset[int], tuple[Score, dict]] = {}
        for meta, outcome in zip(trials, outcomes):
            if not outcome.get("ok") or not outcome.get("stats"):
                continue
            if len(outcome.get("added_node_ids") or ()) > len(outcome.get("removed_node_ids") or ()):
                continue  # the replacement costs more points than the region freed
            self.considered_removals |= {int(n) for n in outcome.get("removed_node_ids") or ()}
            trial_score = self.objective.score(outcome["stats"])
            current = best_by_region.get(meta["cascade"])
            if current is None or trial_score > current[0]:
                best_by_region[meta["cascade"]] = (trial_score, meta)
        ranked = sorted(best_by_region.values(), key=lambda item: item[0], reverse=True)
        best_line = f"best predicted {ranked[0][0].value:,.0f} against {score.value:,.0f}" if ranked else "nothing priced"
        self.log(f"region challenge: {len(pool)} regions, {len(trials)} cheap replacements priced, {best_line}")

        challenged = failures = 0
        for predicted, meta in ranked:
            if challenged >= max_challenges:
                result.stopped_reason = "challenge budget"
                break
            if failures >= max_failures:
                result.stopped_reason = "consecutive failures"
                break
            if max_seconds is not None and time.perf_counter() - t_all > max_seconds:
                result.stopped_reason = "time budget"
                break
            cascade = {int(n) for n in meta["cascade"]}
            if not cascade <= self.current_allocated():
                continue  # an earlier kept challenge already rebuilt this part of the tree
            policy = "target-first" if challenged % 2 == 0 else "greedy"
            t0 = time.perf_counter()
            challenged += 1
            self.plan_b_counts["regions_challenged"] += 1
            honest = self.needs_honest_removal(cascade)
            if honest:
                self.plan_b_counts["honest_removals"] += 1
            what = f"{meta['bucket']} [{self._names(sorted(cascade))}]"
            snapshot = self._snapshot()
            removed_now = self.pob.mutate_nodes(remove=sorted(cascade))
            if self._dropped_protected(removed_now):
                self._restore(snapshot, score, f"region challenge {what} (a forced node went with the cut)")
                failures += 1
                continue
            self.after_real_removal(removed_now)
            removed_ids = [int(n) for n in removed_now.get("removed_node_ids") or ()]
            points = len(removed_ids)
            if points == 0:
                self._restore(snapshot, score, f"region challenge {what}")
                continue
            self._invalidate_inert(removed_ids, everything=True)
            anchors = {int(n) for n in meta["anchors"]} & self.current_allocated()

            def regrow(budget: int) -> AllocationResult:
                if budget <= 0:
                    return AllocationResult()
                if policy == "target-first":
                    return self.repair_target_first(budget, attachment=anchors or None, radius=radius)
                return self.allocate(budget, allocated=self.current_allocated())

            half = max(1, points // 2)
            forbidden = {int(n) for n in cascade} - self.excluded_nodes
            self.excluded_nodes |= forbidden
            try:
                first = regrow(half)
            finally:
                self.excluded_nodes -= forbidden
            second = regrow(points - first.points_spent)
            new_score, new_stats = self.current_score()
            spent = first.points_spent + second.points_spent
            if spent > points or not self._beats(score, new_score, min_gain):
                self._restore(snapshot, score, f"region challenge {what}")
                score, stats = self.current_score()
                failures += 1
                self.log(f"region challenge no gain: -{points} {what} ({policy}): {new_score.value:,.0f} "
                         f"vs {score.value:,.0f}, the cheap replacement promised {predicted.value:,.0f} "
                         f"({time.perf_counter() - t0:.0f}s)")
                continue
            added_ids = [int(n) for step in (*first.steps, *second.steps) for n in step.added_node_ids]
            self._invalidate_inert(added_ids, everything=True)
            self.log(f"region challenge kept{' (honest)' if honest else ''}: -{points} {what} -> "
                     f"+{spent} [{self._names(added_ids)}] ({policy}) value {score.value:,.0f} -> "
                     f"{new_score.value:,.0f} ({time.perf_counter() - t0:.0f}s)")
            result.steps.append(Step(
                node_id=int(meta["cut"]), name=f"region -{points} [{self._names(sorted(cascade), 40)}] ({policy})",
                kind="region", cost=spent, added_node_ids=added_ids, mastery_effect=None, before=score,
                after=new_score, candidates_evaluated=len(ranked), seconds=time.perf_counter() - t0,
                removed_node_ids=removed_ids,
            ))
            result.points_spent += spent
            self.plan_b_counts["regions_kept"] += 1
            self.region_bucket_kept[meta["bucket"]] = self.region_bucket_kept.get(meta["bucket"], 0) + 1
            self.region_policy_kept[policy] = self.region_policy_kept.get(policy, 0) + 1
            score, stats, failures = new_score, new_stats, 0
        result.final_score, result.final_stats = self.current_score()
        if not result.stopped_reason:
            result.stopped_reason = "all regions challenged"
        return self._keep(result)

    def structural_counts(self, allocated: Iterable[int] | None = None, *, trunk_min: int = 13) -> dict[str, object]:
        """What the plan-B acceptance reports: the move counters, and the share of TRUNK nodes (a
        node whose removal drops `trunk_min` or more allocated nodes) that has been inside the
        removal set of at least one candidate PoB was asked about. Before plan B that share was 0."""

        allocated_set = {int(n) for n in (allocated if allocated is not None else self.current_allocated())}
        trunk = {
            node_id for node_id in allocated_set
            if node_id in self.graph.allocatable
            and len(self.graph.cascade_if_removed(allocated_set, node_id, self._links())) >= trunk_min
        }
        reached = trunk & self.considered_removals
        return {
            **self.plan_b_counts,
            "trunk_nodes": len(trunk),
            "trunk_considered": len(reached),
            "trunk_share": (len(reached) / len(trunk)) if trunk else None,
            "allocated": len(allocated_set),
            "region_bucket_kept": dict(self.region_bucket_kept),
            "region_policy_kept": dict(self.region_policy_kept),
        }

    def _random_branches(self, allocated: set[int], target_points: int, rng) -> list[int]:
        """Pick random branch roots whose cascades (2..12 nodes) sum to about target_points."""

        remaining = set(allocated)
        chosen: list[int] = []
        total = 0
        for _attempt in range(300):
            if total >= target_points:
                break
            pool = [n for n in remaining if n in self.graph.allocatable]
            if not pool:
                break
            node = rng.choice(pool)
            cascade = self.graph.cascade_if_removed(remaining, node, self._links())
            if not (2 <= len(cascade) <= 12) or total + len(cascade) > target_points + 4:
                continue
            if self.protected & cascade:
                continue
            remaining -= cascade
            chosen.extend(sorted(cascade))
            total += len(cascade)
        return chosen

    # -- helpers -------------------------------------------------------------

    def _choose(
        self,
        score: Score,
        evaluated: list[tuple[dict, dict, Score, int]],
        points_left: int,
        stats: dict | None = None,
    ) -> tuple[dict, dict, Score, int] | None:
        """Pick the next allocation with a repair reserve.

        Feasible: best objective gain per point among candidates that stay feasible.
        Infeasible: estimate how many points the cheapest repair needs, one missed
        constraint at a time (greedy over that constraint's reduction per point; the
        reductions of one constraint are not summed with another's, and five nodes
        that each fix the same shortfall count once). While the remaining budget
        covers that estimate plus a margin, spend on the best objective gain per
        point (never worsening the violation); otherwise repair by reduction per point.
        """

        if score.feasible:
            ranked = sorted(
                evaluated,
                key=lambda e: (1.0 if e[2].feasible else -e[2].violation, (e[2].value - score.value) / e[3], self._tie(e)),
                reverse=True,
            )
            return ranked[0]

        def reduction_pp(e: tuple[dict, dict, Score, int]) -> float:
            return (score.violation - e[2].violation) / e[3]

        repairers = sorted((e for e in evaluated if e[2].violation < score.violation), key=reduction_pp, reverse=True)
        estimate, repair_possible = self._repair_estimate(score, evaluated, stats)
        self.last_repair_estimate = estimate if repair_possible else None

        if repair_possible:
            spendable = points_left - estimate - self.repair_margin
            dps_options = [
                e for e in evaluated
                if e[2].violation <= score.violation + 1e-9 and e[2].value > score.value and e[3] <= spendable
            ]
            if dps_options:
                return max(dps_options, key=lambda e: ((e[2].value - score.value) / e[3], reduction_pp(e), self._tie(e)))
        if repairers:
            return max(repairers, key=lambda e: (reduction_pp(e), (e[2].value - score.value) / e[3], self._tie(e)))
        return max(evaluated, key=lambda e: (self._rank_key(score, e[2], e[3]), self._tie(e)))

    def _spare_pick(
        self, score: Score, evaluated: list[tuple[dict, dict, Score, int]]
    ) -> tuple[dict, dict, Score, int] | None:
        """The spare-point step's second judgement (#865 rules 1-3) of one round's measured candidates. A candidate
        that lowers the Score (lower `value`, or higher violation) is out; of the rest the one whose smallest relative
        margin over the objective's own constraints (`Objective.margins`) is largest wins, then `_tie`. None when
        every candidate lowers the Score: the point stays unspent and the log carries one line."""

        keep = [e for e in evaluated if e[2].value >= score.value and e[2].violation <= score.violation + 1e-9]
        if not keep:
            nearest = max((e[2] for e in evaluated), key=lambda s: s._key())
            self.log(
                f"spare point left unspent: {len(evaluated)} candidates measured, all lower the Score; smallest loss: "
                f"value {nearest.value - score.value:+,.0f}, violation {nearest.violation - score.violation:+.4f}"
            )
            return None
        return max(keep, key=lambda e: (min(self.objective.margins(e[1]["stats"]).values(), default=float("inf")), self._tie(e)))

    def _tie(self, entry: tuple[dict, dict, Score, int]) -> int:
        """The seeded priority of one evaluated candidate, the last element of every pick's key: 0 for all (the first
        listed wins an exact tie) while no `tie_seed` is set. Keyed by the node and its mastery effect, not by position."""

        if self.tie_seed is None:
            return 0
        meta = entry[0]
        mastery = meta["trial"].get("mastery") or {}
        label = f"{meta['candidate'].node_id}:{sorted(mastery.items())}"
        return tie_rank(self.tie_seed, PURPOSE_TREE_TIES, label)

    def _repair_estimate(self, score: Score, evaluated: list[tuple[dict, dict, Score, int]], stats: dict | None) -> tuple[int, bool]:
        """Points the cheapest repair of the current state needs, and whether the visible
        candidates can repair it at all.

        "sum" (the default, optimistic): every candidate's total violation reduction summed
        until the violation is covered. Five +Str nodes that each fix the same attribute
        count five times, so the greedy keeps buying damage and often ends the budget short
        of a floor; the refine then repairs. "cover": a greedy cover of every missed
        constraint at once, each candidate's worth the shortfall it removes summed over the
        constraints still missing (capped at what is missing), per point, a node paid once.
        Measured on eight finished builds regrown from scratch (final after the refine):
        the optimistic estimate won four (Absolution x2, Cold DoT s3, Poison ST), the cover
        two (Spark 861k vs 820k, Stormbrand 690k vs 654k), and the optimistic path twice
        ended where no swap could repair it (Cold DoT s1 186k short by 0.001, Bleed Bow
        368k after a -18% repair). Neither is right alone: the rebuild stage (D45) grows
        both and PoB keeps the better tree."""

        if self.repair_estimate_mode == "sum":
            repairers = sorted((e for e in evaluated if e[2].violation < score.violation), key=lambda e: (score.violation - e[2].violation) / e[3], reverse=True)
            estimate, covered, seen = 0, 0.0, set()
            for e in repairers:
                node_id = e[0]["candidate"].node_id
                if node_id in seen:
                    continue
                seen.add(node_id)
                estimate += e[3]
                covered += score.violation - e[2].violation
                if covered >= score.violation:
                    break
            return estimate, covered >= score.violation
        missing = {k: v for k, v in (self.objective.violations(stats) if stats is not None else {"": score.violation}).items() if v > 0}
        parts_of = {id(e): (self.objective.violations(e[1]["stats"]) if stats is not None else {"": e[2].violation}) for e in evaluated}
        estimate, seen_nodes = 0, set()
        while missing:
            best_pick, best_worth = None, 0.0
            for e in evaluated:
                node_id = e[0]["candidate"].node_id
                if node_id in seen_nodes:
                    continue
                parts = parts_of[id(e)]
                worth = sum(min(missing[k], missing[k] - parts.get(k, 0.0)) for k in missing if missing[k] - parts.get(k, 0.0) > 1e-12)
                if worth / e[3] > best_worth:
                    best_pick, best_worth = e, worth / e[3]
            if best_pick is None:
                break
            seen_nodes.add(best_pick[0]["candidate"].node_id)
            estimate += best_pick[3]
            parts = parts_of[id(best_pick)]
            missing = {k: v - (v - parts.get(k, 0.0)) for k, v in missing.items() if v - (v - parts.get(k, 0.0)) > 1e-12}
        return estimate, not missing

    @staticmethod
    def _rank_key(current: Score, trial: Score, cost: int) -> tuple[float, float]:
        """Ordering for candidate selection.

        Infeasible state: reduce violation as much as possible per point, then gain.
        Feasible state: stay feasible, then gain per point.
        """

        gain_per_point = (trial.value - current.value) / max(1, cost)
        if not current.feasible:
            return ((current.violation - trial.violation) / max(1, cost), gain_per_point)
        return (1.0 if trial.feasible else -trial.violation, gain_per_point)

    def _note_failure(self, cand: Candidate, outcome: dict) -> None:
        err = str(outcome.get("error") or "no stats").split(":")[-1].strip()[:60]
        self.skipped_errors[err] = self.skipped_errors.get(err, 0) + 1
        if ("unknown node" in err or "unreachable node" in err) and getattr(cand, "kind", "") != "cluster":
            self.excluded_nodes.add(cand.node_id)  # a failed cluster trial says nothing about its first member alone

    def taken_mastery_effects(self) -> set[int]:
        """Mastery effects already selected in the build: the game (and the PoB app)
        allow each effect once, even though two masteries of the same kind exist."""

        taken: set[int] = set()
        for entry in self._tree_state().get("mastery_effect_ids") or []:
            try:
                taken.add(int(str(entry).split(":")[1]))
            except (IndexError, ValueError):
                continue
        return taken

    def _trials_for(self, candidates: Sequence[Candidate]) -> list[dict]:
        trials: list[dict] = []
        taken = self.taken_mastery_effects() if any(c.kind == "mastery" for c in candidates) else set()
        for cand in candidates:
            if cand.node_id in self.excluded_nodes or (self.excluded_nodes and self.excluded_nodes.intersection(cand.path)):
                continue
            # the nodes the move allocates on the way, as `_attribute_cap_blocks` reads them; trace-only (#511)
            path = [int(n) for n in (*(getattr(cand, "path", ()) or ()), *(getattr(cand, "node_ids", ()) or ()))]
            node = self.graph.node(cand.node_id)
            if cand.kind == "mastery" and node is not None and node.mastery_effects:
                for effect_id, _stats in node.mastery_effects:
                    if effect_id in taken or effect_id in self.excluded_mastery_effects:
                        continue
                    trials.append({"candidate": cand, "trial": {"add": [cand.node_id], "mastery": {cand.node_id: effect_id}, "path": path}})
            else:
                trials.append({"candidate": cand, "trial": {"add": [cand.node_id], "mastery": {}, "path": path}})
        return trials

    def _cluster_trials(self, candidates: Sequence[Candidate], points_left: int, allocated: set[int] | None = None) -> list[dict]:
        """Small groups of notables that share a mechanic tag, each tried as ONE trial (7.2 rule 5).

        Impale pays chance x effect x stacks and crit chance x multiplier: one notable of such a
        pair is often worth nothing on its own, so the greedy never takes the first one. A cluster
        is kept only when PoB says it beats every single candidate per point (`_choose`), and the
        trials are appended after the singles so a tie keeps the cheaper single.
        """

        if self.cluster_max_trials <= 0 or self.cluster_max_size < 2:
            return []
        allocated = set(allocated or ())
        members = [
            c
            for c in candidates
            if c.kind == "notable"
            and c.cost <= points_left
            and c.node_id not in self.excluded_nodes
            and not (self.excluded_nodes and self.excluded_nodes.intersection(c.path))
            and not self.generator_effects(c.node_id)  # a charge generator is judged with its toggle on, not in a cluster
            and not self._attribute_cap_blocks(c, allocated)
        ]
        if len(members) < 2:
            return []
        groups: dict[tuple[str, str], list[Candidate]] = {}
        for cand in members:
            for key in self.cluster_tags(cand.node_id):
                groups.setdefault(key, []).append(cand)

        clusters: dict[frozenset[int], ClusterCandidate] = {}
        for key, group in sorted(groups.items()):  # sorted: a tag set has no stable iteration order, a seeded run must
            if len(group) < 2:
                continue
            chosen: list[Candidate] = []
            union: list[int] = []
            seen: set[int] = set()
            for cand in sorted(group, key=lambda c: (c.cost, c.node_id)):
                if len(chosen) + 1 > self.cluster_max_size:
                    break
                fresh = [n for n in cand.path if n not in seen]
                if len(union) + len(fresh) > points_left:
                    break
                chosen.append(cand)
                union.extend(fresh)
                seen.update(fresh)
            if len(chosen) < 2:
                continue
            node_ids = tuple(sorted(c.node_id for c in chosen))
            if self.attribute_requirement_nodes_max is not None and len(self.attribute_requirement_nodes(allocated) | {
                node_id for node_id in union if is_attribute_requirement_node(self.graph.node(node_id))
            }) > self.attribute_requirement_nodes_max:
                continue
            if frozenset(node_ids) in clusters:
                continue  # the same members under a second shared tag: one trial, the first key
            clusters[frozenset(node_ids)] = ClusterCandidate(
                node_id=node_ids[0],
                cost=len(union),
                path=tuple(union),
                name=" + ".join(c.name for c in chosen),
                node_ids=node_ids,
                key=key,
            )
        ordered = sorted(clusters.values(), key=lambda c: (c.cost, c.node_ids))[: self.cluster_max_trials]
        return [{"candidate": c, "trial": {"add": list(c.node_ids), "mastery": {}}} for c in ordered]


__all__ = ["TreeOptimizer", "AllocationResult", "Step", "ClusterCandidate", "Corridor"]
