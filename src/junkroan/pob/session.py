"""Thin, ergonomic wrapper over the headless PoB runtime.

This is the only entry point new code (optimizer, search) should use to talk to
Path of Building. Everything below it (host_runtime, headless_runtime_adapter,
headless_runtime_worker, headless_wrapper.lua) is the stable inherited harness.

Usage::

    with PobSession(run_id="smoke") as pob:
        pob.set_identity(level=90)
        pob.set_tree(class_id="Witch", ascendancy_id="Elementalist", nodes=[...])
        pob.set_skills(main_link=["Fireball", "Spell Echo", ...])
        pob.set_items({"Boots": "Rarity: Rare\\n..."})
        pob.set_config(enemy_state={"is_boss": "Pinnacle"})
        stats = pob.calc()          # flat dict of PoB stats
        xml = pob.export_xml()
        code = encode_import_code(xml)
"""

from __future__ import annotations

import base64
import copy
import re
import textwrap
import time
import zlib
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.etree import ElementTree

from .artifacts import DEFAULT_RUNS_ROOT
from .brand_instances import brand_gems_at_count_one_xml, is_brand_gem, note_brand_gems
from .bench_mod_ids import bench_mod_candidates, bench_mod_families, bench_mod_id
from junkroan.mechanics.bench_unlocks import lookup as bench_unlock_lookup, lowest_requirement
from .headless_runtime_adapter import PinnedPoBHeadlessRuntimeAdapter
from .host_runtime import PoBHeadlessHostRequest, create_headless_proof_run
from .mod_families import families_of
from .release_manager import PoBReleaseManager
from junkroan.optimizer.trace import TRACE, TRACED_CONFIG_INPUTS
from junkroan.optimizer.trace_1158 import stamp_of as base_swap_stamp_of
from junkroan.optimizer.tree_trace import stamps_of
from .slot_budget import SlotHandle, acquire_slot

WRAPPER_ENTRYPOINT_REF = "src/junkroan/pob/headless_wrapper.lua"
_RUN_ID_PATTERN = re.compile(r"[^a-z0-9._-]+")
_STAT_MARKERS = ("FullDPS", "TotalDPS", "Life", "TotalEHP")


def encode_import_code(xml_text: str) -> str:
    """Encode PoB XML into the pasteable PoB import string."""

    if not xml_text.strip():
        raise ValueError("PoB XML must be non-empty text.")
    raw = base64.b64encode(zlib.compress(xml_text.encode("utf-8"), level=9)).decode("ascii")
    return raw.replace("+", "-").replace("/", "_")


def decode_import_code(import_code: str) -> str:
    """Decode a PoB import string back into XML."""

    raw = import_code.strip().replace("-", "+").replace("_", "/")
    return zlib.decompress(base64.b64decode(raw)).decode("utf-8")


def _run_id(prefix: str) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return _RUN_ID_PATTERN.sub("-", f"{prefix}-{stamp}".lower())


# Adapter calls that leave the build as it was. Everything else (every setter, a tree mutation, an
# equip, a load, a full-mode trial, a call added later and not listed here) drops the cached state:
# a missed reader costs a read, a missed mutator would cost a wrong decision.
_READ_ONLY_ADAPTER_CALLS = frozenset({
    "read_state", "read_stats", "read_stats_uncapped", "checkpoint_config", "read_active_skill_stats", "read_mana_cost_warnings", "read_granted_passives", "read_calc_snapshot", "read_config_options", "read_node_power_report",
    "list_item_mods", "cluster_graph", "list_bench_mods", "random_rares", "craft_rare", "recraft", "parse_mods", "uniques",
    "unsupported_gems", "read_tree_light", "read_config_inputs", "read_ascendancy_node_report", "export_build_artifact", "launch_session",
    "shutdown_session", "close",
})


# The only writes that provably leave the items, the passive tree and the identity alone: the
# worker writes them straight into `build.skillsTab` / `build.configTab` and touches nothing else
# (`_apply_skill_state_inplace`, `_apply_config_state_inplace`). Every other call bumps
# `PobSession.build_epoch`; see it for what that number is for.
_SKILLS_OR_CONFIG_ONLY_ADAPTER_CALLS = frozenset({"apply_skill_state", "apply_config_state", "rollback_config", "flask_flags_derived"})

# The "reads" that derive the Flask flags from PoB's uptime (#575) and so may write a flag (`slot.active` + the
# active item set's row) into the live build. The worker's reply to each says whether a flag changed over the call
# (`take_flask_flags_changed` on the adapter); the cached state is dropped only then, under the name
# "flask_flags_derived" (an items-surface detail the state carries, no new build: `build_epoch` stays).
_FLASK_DERIVING_ADAPTER_CALLS = frozenset({"read_stats", "read_stats_uncapped", "read_active_skill_stats", "trial_stats", "export_build_artifact"})


class _StateCacheAdapter:
    """The adapter with one addition: any call that may change the build clears the session's cached
    `read_state` (0.9 s per read: a full export of every surface; the tree optimizer asked for it on
    every greedy step and `derive_config` four times per derivation)."""

    def __init__(self, inner: Any, invalidate: Any) -> None:
        self._inner, self._invalidate = inner, invalidate

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr) or (name in _READ_ONLY_ADAPTER_CALLS and name not in _FLASK_DERIVING_ADAPTER_CALLS):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            request = args[1] if len(args) > 1 else kwargs.get("request")
            if name not in _READ_ONLY_ADAPTER_CALLS and not (name == "trial_stats" and isinstance(request, Mapping) and request.get("mode") == "fast"):
                self._invalidate(name)  # before the call: a call that raises half-way has still touched the build
            if name not in _FLASK_DERIVING_ADAPTER_CALLS:
                return attr(*args, **kwargs)
            try:
                return attr(*args, **kwargs)
            finally:
                take = getattr(self._inner, "take_flask_flags_changed", None)
                if callable(take) and take() is True:
                    self._invalidate("flask_flags_derived")

        return call


_CLUSTER_BASE_LINE = re.compile(r"(?:Small|Medium|Large) Cluster Jewel")


def is_cluster_jewel_raw(raw: str) -> bool:
    """True when a raw item text names a Small / Medium / Large Cluster Jewel base (a magic one carries affix words around it)."""

    return any(_CLUSTER_BASE_LINE.search(line) for line in raw.splitlines()[:4])


def raw_with_sockets(raw: str, sockets: str) -> str:
    """``raw`` item text with its ``Sockets:`` line set to ``sockets`` (inserted when absent)."""

    lines = [ln.strip() for ln in raw.splitlines()]
    new_line = f"Sockets: {sockets}"
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("Sockets:")), None)
    if idx is not None:
        lines[idx] = new_line
    else:
        at = next((i for i, ln in enumerate(lines) if ln.startswith(("LevelReq:", "Implicits:"))), len(lines))
        lines.insert(at, new_line)
    return chr(10).join(lines)


class PobSession:
    """One live headless PoB process holding one build state."""

    mean_parts: tuple[int, ...] | None = None  # class default: a session built without __init__ (tests) reads the selected part
    _condition_flag_cache: dict[str, list[dict[str, Any]]] = {}
    # Every call that can change a surface other than the skills and the config ones -- items, the
    # passive tree, the identity, a whole-build load -- bumps this counter. A caller that derives
    # something from those surfaces can remember it against the number and skip the derivation while
    # it stands (`Skeleton.derived_counts`' brand-attach count). Skill and config writes go straight
    # into their own tab in the worker, so they leave it alone; the `read_state` cache is dropped by
    # every one of them either way.
    build_epoch: int = 0
    # The machine-wide PoB slot this session holds between `__enter__` and `close()`
    # (`slot_budget.py`). A class default so a session built without `__init__` (tests) closes
    # cleanly, and a no-op handle whenever the mechanism is off or failed.
    _slot: SlotHandle | None = None

    def __init__(
        self,
        run_id: str = "session",
        *,
        artifacts_root: Path = DEFAULT_RUNS_ROOT,
        release_manager: PoBReleaseManager | None = None,
    ) -> None:
        self._manager = release_manager or PoBReleaseManager()
        self._state_cache: dict[str, Any] | None = None
        self._adapter = _StateCacheAdapter(PinnedPoBHeadlessRuntimeAdapter(release_manager=self._manager), self._drop_state_cache)
        self._run = create_headless_proof_run(
            PoBHeadlessHostRequest(
                pob_run_id=_run_id(run_id),
                export_surface_kind="pob_xml",
                wrapper_entrypoint_ref=WRAPPER_ENTRYPOINT_REF,
            ),
            release_manager=self._manager,
            artifacts_root=Path(artifacts_root),
        )
        self._handle = None
        self._live = False
        self._base_families: dict[tuple[str, int | None, str], dict[str, list[str]]] = {}
        self._call_counts: dict[str, int] = {}
        self._call_seconds: dict[str, float] = {}
        # Approximate speed-up, off by default (see `trial_stats`): a fast batch that asks for
        # FullDPS costs 2-4x one that does not, because PoB rebuilds and re-performs the whole
        # full-DPS roll-up per trial. Counters for the caller's report.
        self.fulldps_shortcut = False
        self.fulldps_shortcut_batches = 0
        self.fulldps_full_batches = 0
        self.fulldps_shortcut_unsafe = False  # a ratio that moved between batches: the shortcut is off for good
        self.fulldps_shortcut_disabled = 0
        self._fulldps_last_ratio: tuple[str, float] | None = None
        # Skill parts every `stats` / fast `trial_stats` readback averages over (a random-element
        # main skill: `optimizer/random_parts.py`); None = the selected part alone. The caller sets
        # it when it knows the main skill (the pipeline after the part pick, the benchmark for the
        # author's build); a build load does not reset it, so a config reload mid-pipeline keeps it.
        self.mean_parts: tuple[int, ...] | None = None

    def _measured_call(self, kind: str, fn: Any, *args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            counts = getattr(self, "_call_counts", None)
            seconds = getattr(self, "_call_seconds", None)
            if counts is None:
                counts = self._call_counts = {}
            if seconds is None:
                seconds = self._call_seconds = {}
            counts[kind] = counts.get(kind, 0) + 1
            seconds[kind] = seconds.get(kind, 0.0) + time.perf_counter() - started

    def pob_calls(self) -> dict[str, dict[str, float | int]]:
        """Return report-only counts and time spent in the main PoB call kinds."""

        counts = getattr(self, "_call_counts", {})
        seconds = getattr(self, "_call_seconds", {})
        kinds = set(counts) | set(seconds)
        return {
            kind: {"count": counts.get(kind, 0), "seconds": seconds.get(kind, 0.0)}
            for kind in sorted(kinds)
        }

    def reset_pob_calls(self) -> None:
        """Start a fresh report interval without changing the live PoB build."""

        self._call_counts = {}
        self._call_seconds = {}

    # -- lifecycle -----------------------------------------------------------

    def __enter__(self) -> "PobSession":
        # One machine-wide slot BEFORE the ~1 GB runtime process exists; released in `close()`,
        # and by the OS if this process is killed (the lock dies with it).
        self._slot = acquire_slot()
        try:
            handle = self._run.bootstrap_session("normal")
            self._handle = self._run.launch_session(handle, launcher=self._adapter.launch_session)
            self._live = True
            self._adapter.create_blank_build(self._handle)
        except BaseException:
            self._release_slot()
            raise
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _release_slot(self) -> None:
        slot, self._slot = self._slot, None
        if slot is not None:
            try:
                slot.release()
            except Exception:
                pass

    def close(self) -> None:
        try:
            self._close_runtime()
        finally:
            self._release_slot()

    def _close_runtime(self) -> None:
        if self._live:
            self._live = False
            try:
                shutdown = self._adapter.shutdown_session(self._handle)
                self._run.seal_session(
                    self._handle,
                    exit_code=shutdown.exit_code,
                    termination=shutdown.termination,
                    process_exit_observed=shutdown.process_exit_observed,
                )
            except Exception:
                # A desynced or dead worker must not mask the original error;
                # adapter.close() below terminates whatever is left.
                pass
        self._adapter.close()

    @property
    def run_root(self) -> Path:
        return self._run.layout.run_root

    # -- whole-build load ----------------------------------------------------

    def load_xml(self, xml_text: str) -> None:
        """Replace the live build with a full PoB build XML."""

        self._fulldps_last_ratio = None  # another build: its ratio is its own
        # #963: a brand gem enters PoB with count 1, PoB multiplies by the attached brands itself
        self._measured_call("load_xml", self._adapter.load_build_xml, self._handle, brand_gems_at_count_one_xml(xml_text))

    def load_import_code(self, import_code: str) -> None:
        """Replace the live build with a PoB import code (pobb.in / pastebin payload)."""

        self.load_xml(decode_import_code(import_code))

    # -- state mutation ------------------------------------------------------

    def set_identity(self, *, level: int) -> None:
        self._measured_call("set_identity", self._adapter.apply_identity_state, self._handle, {"level": int(level), "character_level_auto_mode": False})

    def set_tree(
        self,
        *,
        class_id: str | int,
        ascendancy_id: str | int = 0,
        nodes: Sequence[int] = (),
        ascendancy_nodes: Sequence[int] = (),
        keystones: Sequence[int] = (),
        masteries: Sequence[str] = (),
        jewels: Mapping[int, str] | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        """Replace the passive tree (and the jewels in its sockets) with the given state.

        ``jewels`` = {socket node_id: raw item text}, sent as the payload field ``socketed_jewel_items``; a raw
        whose base line is a Small / Medium / Large Cluster Jewel goes as ``cluster_jewel_items`` instead.
        ``set_tree`` clears EVERY tree socket first and re-applies only ``jewels``: a jewel put there earlier
        with ``put_jewel`` is gone after a ``set_tree`` that does not list it again. Each listed socket is
        allocated by the worker (like a node in ``nodes``).
        """

        payload: dict[str, Any] = {
            "class_id": class_id,
            "ascendancy_id": ascendancy_id,
            "user_allocated_node_ids": [int(n) for n in nodes],
            "ascendancy_node_ids": [int(n) for n in ascendancy_nodes],
            "keystone_node_ids": [int(n) for n in keystones],
            "mastery_effect_ids": list(masteries),
        }
        if jewels:
            if extra and ("socketed_jewel_items" in extra or "cluster_jewel_items" in extra):
                raise ValueError("pass the socket jewels either as `jewels` or as extra['socketed_jewel_items'] / extra['cluster_jewel_items'], not both")
            entries = [{"node_id": int(node_id), "raw_item_text": raw} for node_id, raw in jewels.items()]
            # a cluster jewel goes through `cluster_jewel_items`: the worker applies those BEFORE it allocates `nodes`,
            # so the node ids of its subgraph (>= 65536) resolve; the order of `jewels` is kept (a Large before the Medium in its socket)
            clusters = [e for e in entries if is_cluster_jewel_raw(e["raw_item_text"])]
            plain = [e for e in entries if not is_cluster_jewel_raw(e["raw_item_text"])]
            if clusters:
                payload["cluster_jewel_items"] = clusters
            if plain:
                payload["socketed_jewel_items"] = plain
        if extra:
            payload.update(dict(extra))
        self._measured_call("set_tree", self._adapter.apply_tree_state, self._handle, payload)

    def add_nodes(self, node_ids: Sequence[int], *, mastery_effects: Mapping[int, int] | None = None) -> dict[str, Any]:
        """Allocate nodes (PoB allocates the shortest connecting path itself).

        Mastery nodes need their effect: ``mastery_effects={node_id: effect_id}``.
        """

        return self.mutate_nodes(add=node_ids, mastery_effects=mastery_effects)

    def remove_nodes(self, node_ids: Sequence[int]) -> dict[str, Any]:
        """Deallocate nodes and everything that depended on them for connectivity."""

        return self._measured_call("mutate_nodes", self._adapter.mutate_tree_nodes, self._handle, {"remove_node_ids": [int(n) for n in node_ids]})

    def mutate_nodes(
        self,
        *,
        add: Sequence[int] = (),
        remove: Sequence[int] = (),
        mastery_effects: Mapping[int, int] | None = None,
    ) -> dict[str, Any]:
        """Remove then add nodes. Returns allocated set, added/removed diff (removal
        cascades to dependants), removed_mastery_effects ("node:effect"), points_used."""

        return self._measured_call(
            "mutate_nodes",
            self._adapter.mutate_tree_nodes,
            self._handle,
            {
                "add_node_ids": [int(n) for n in add],
                "remove_node_ids": [int(n) for n in remove],
                "mastery_effects": {str(int(k)): int(v) for k, v in (mastery_effects or {}).items()},
            },
        )

    def set_skills(
        self,
        *,
        main_link: Sequence[str],
        slot: str = "Body Armour",
        level: int = 20,
        quality: int = 20,
        main_quality: int | None = None,
        main_part: int | None = None,
        extra_groups: Sequence[Mapping[str, Any]] = (),
        main_counts: Mapping[str, int] | None = None,
        main_instance_counts: Sequence[int] = (),
        main_minion_skills: Mapping[str, int] | None = None,
        main_disabled_indices: Sequence[int] = (),
        gem_levels: Mapping[str, int] | None = None,
        main_skill_minion: Mapping[str, str] | None = None,
        spectres: Sequence[str] | None = None,
    ) -> None:
        """Write the skills surface.

        ``main_skill_minion`` maps a main-link gem name to the minion id PoB's ``skillMinion`` names (the
        Raise Spectre gem: a ``Metadata/Monsters/...`` spectre id); an extra group's gem dict takes the
        ``skill_minion`` key itself. ``spectres`` is the build's spectre list (the ``<Spectre id=.../>``
        children of ``<Build>``): PoB computes a spectre only while the list holds its id and the gem's
        ``skillMinion`` names it. ``None`` leaves the list the build holds; a sequence replaces it (an
        unknown id raises). Both are absent from the payload when unused.
        """

        self._fulldps_last_ratio = None  # the skills surface decides the ratio: it has just changed

        brand_counts: list[int] = []  # #963: the count each brand gem came with; PoB is handed 1

        def instances(name: str, count: Any) -> int:
            count = max(1, int(count))
            if is_brand_gem(name):
                brand_counts.append(count)
                return 1
            return count

        def gem(name: str, index: int, q: int = quality, part: int | None = None, enabled: bool = True) -> dict[str, Any]:
            count = main_instance_counts[index] if index < len(main_instance_counts) else (main_counts or {}).get(name, 1)
            out = {"gem_name": name, "level": int((gem_levels or {}).get(name, level)), "quality": q, "enabled": enabled, "count": instances(name, count)}
            if (main_minion_skills or {}).get(name):
                out["skill_minion_skill_index"] = int(main_minion_skills[name])
            if (main_skill_minion or {}).get(name):
                out["skill_minion"] = str(main_skill_minion[name])
            if part is not None:
                out["skill_part"] = int(part)
            return out

        groups: list[dict[str, Any]] = [
            {
                "label": "Main",
                "slot": slot,
                "enabled": True,
                "include_in_full_dps": True,
                "group_count": 1,
                "main_active_skill_index": 1,
                "gems": [gem(name, i, main_quality if (i == 0 and main_quality is not None) else quality,
                             main_part if i == 0 else None, i not in set(main_disabled_indices)) for i, name in enumerate(main_link)],
            }
        ]
        for raw_group in extra_groups:
            group = dict(raw_group)
            group["gems"] = [
                {**dict(raw_gem), "count": instances(str(dict(raw_gem).get("gem_name") or ""), dict(raw_gem).get("count", 1))}
                for raw_gem in raw_group.get("gems", ())
            ]
            groups.append(group)
        payload: dict[str, Any] = {
            "active_skill_set_id": "skills.main",
            "main_socket_group_id": "skills.main.socket_group.1",
            # #1022: the Main group is rewritten, never re-picked: the worker finds the main active skill the build held
            # (by its granted effect's name, among the skills of the group's new first gem) and keeps it
            "keep_main_active_skill": True,
            "skill_sets": [{"skill_set_id": "skills.main", "title": "Main", "socket_groups": groups}],
        }
        if spectres is not None:
            payload["spectre_list"] = [str(s) for s in spectres]
        note_brand_gems(brand_counts)
        self._measured_call("set_skills", self._adapter.apply_skill_state, self._handle, payload)

    def set_items(self, items_by_slot: Mapping[str, str], *, use_second_weapon_set: bool = False) -> None:
        """Equip items given as raw PoB item text keyed by slot name (e.g. "Boots")."""

        self._measured_call(
            "set_items",
            self._adapter.apply_item_state,
            self._handle,
            {
                "active_item_set_id": "itemset.main",
                "item_sets": [
                    {
                        "item_set_id": "itemset.main",
                        "use_second_weapon_set": use_second_weapon_set,
                        "slots": [{"slot": slot, "raw_item_text": text} for slot, text in items_by_slot.items()],
                    }
                ],
            },
        )

    def set_flasks_active(self, active: bool | Mapping[str, bool]) -> None:
        """Set PoB's slot `active` flag (the checkbox left of a flask slot) for Flask 1..5 and recalculate.

        A bool sets all five slots; a mapping ("Flask 1" -> bool) sets the named slots only. A flask's
        or tincture's mods count only while its slot is active. `set_items` resets every flag to
        inactive (PoB's item-set reset), so call this after it. `read_state()["items_state"]
        ["flasks_active"]` reads the flags back; the export writes them as `<Slot ... active="true"/>`.
        """

        names = [f"Flask {i}" for i in range(1, 6)]
        flags = {name: bool(active) for name in names} if isinstance(active, bool) else {str(k): v for k, v in active.items()}
        self._measured_call("set_flasks_active", self._adapter.set_flasks_active, self._handle, flags)

    def flask_uptimes(self) -> dict[str, dict[str, Any]]:
        """Per Flask slot holding a flask: {"line": PoB's "Flask uptime: ..." line or None, "full": bool, "active": bool}.

        Derives the flags first (the worker does it before every stats read and the export too): `active`
        is True iff `line` is "Flask uptime: 100%".
        """

        return self._measured_call("flask_uptimes", self._adapter.flask_uptimes, self._handle)

    def flasks_active(self) -> dict[str, bool]:
        """Per Flask slot: is it active, as the slots hold the flag right now (a fresh `read_state`).

        Every stats read, every trial and the export first derive the flags from PoB's uptime (`flask_uptimes`),
        so a flag forced with `set_flasks_active` lasts only until the next of them.
        """

        # a derivation that changed a flag has dropped the cached state itself (`_StateCacheAdapter`)
        return dict(self.read_state()["items_state"].get("flasks_active") or {})

    def config_inputs(self) -> dict[str, Any]:
        """Current inputs of the active config set (var -> bool | number | str).

        Read straight off `build.configTab.input` with PoB's own "differs from the default"
        filter, the one `ConfigTab:Save` applies when it writes <Config>: the same rows
        `config_inputs_from_xml` finds in the export, without the 39 ms export and parse.
        """

        return dict(self._adapter.read_config_inputs(self._handle, {}).get("inputs") or {})

    def set_config(
        self,
        *,
        bandit: str = "None",
        pantheon_major: str = "None",
        pantheon_minor: str = "None",
        buffs: Mapping[str, Any] | None = None,
        combat_conditions: Mapping[str, Any] | None = None,
        enemy_state: Mapping[str, Any] | None = None,
        inputs: Mapping[str, Any] | None = None,
        conditional: Mapping[str, Any] | None = None,
        preserve: str = "numeric",
    ) -> None:
        """Set PoB config.

        The inherited worker snapshots two config sets per calc: "Baseline" and
        "Conditional". By default both are identical. Pass ``conditional`` with
        any of the same keys (buffs / combat_conditions / enemy_state) to make
        the conditional lane differ (e.g. enemy ignited, flask up).

        ``preserve``: "numeric" (default) keeps the build's existing non-boolean
        inputs (poison stacks, brand counts, exposure type, ...) unless overridden;
        "all" keeps every existing input; "none" starts from PoB defaults.
        Bandit / pantheon / boss are always taken from the arguments.

        ``inputs`` takes any PoB config var by its ConfigOptions.lua name
        (e.g. {"usePowerCharges": True, "conditionEnemyIgnited": True,
        "enemyIsBoss": "Uber", "multiplierPoisonOnEnemy": 5}). Names are
        validated against corpus_data/config_surfaces.json. The typed keyword
        arguments remain as shortcuts for the common ones.
        """

        existing: dict[str, Any] = {}
        if preserve in {"numeric", "all"}:
            for name, value in self.config_inputs().items():
                if name in {"bandit", "pantheonMajorGod", "pantheonMinorGod", "enemyIsBoss"}:
                    continue
                if preserve == "all" or not isinstance(value, bool):
                    existing[name] = value
        elif preserve != "none":
            raise ValueError("preserve must be 'numeric', 'all' or 'none'")

        def config_set(set_id: str, title: str, overrides: Mapping[str, Any]) -> dict[str, Any]:
            merged_inputs = {**existing, **dict(inputs or {}), **dict(overrides.get("inputs", {}))}
            # a charge count without its use flag is dead weight PoB ignores while the UI shows
            # it (a preserved overrideFrenzyCharges rode into a lane whose charges were off)
            for kind in ("Power", "Frenzy", "Endurance"):
                if not merged_inputs.get(f"use{kind}Charges"):
                    merged_inputs.pop(f"override{kind}Charges", None)
            return {
                "config_set_id": set_id,
                "title": title,
                "bandit": bandit,
                "pantheon_major": pantheon_major,
                "pantheon_minor": pantheon_minor,
                "buffs": {**dict(buffs or {}), **dict(overrides.get("buffs", {}))},
                "combat_conditions": {
                    **dict(combat_conditions or {}),
                    **dict(overrides.get("combat_conditions", {})),
                },
                "enemy_state": {
                    **dict(enemy_state or {"is_boss": "Pinnacle"}),
                    **dict(overrides.get("enemy_state", {})),
                },
                "inputs": merged_inputs,
            }

        sets = [config_set("config.main", "Baseline", {}), config_set("config.2", "Conditional", conditional or {})]
        self._measured_call("set_config", self._adapter.apply_config_state, self._handle, {"active_config_set_id": "config.main", "config_sets": sets})
        for one in sets:  # #702: a traced config input that reaches PoB's config set is evaluated (generated where a lane wrote it)
            TRACE.add_evaluated(var for var in TRACED_CONFIG_INPUTS if isinstance(one["inputs"].get(var), (int, float)) and not isinstance(one["inputs"].get(var), bool))

    # -- readback ------------------------------------------------------------

    def tree_version(self) -> str:
        """The passive tree version the active spec is on ("3_25" ... "3_29").

        PoB builds a spec at the version its XML declares and never converts on its own
        (`TreeTab.lua:511`; `ConvertToVersion` is a UI button), so a loaded reference build stays
        on the author's tree while a build we create starts on `latest_tree_version()`.
        """

        return str(self._measured_call("tree_light", self._adapter.read_tree_light, self._handle, {})["tree_version"])

    def latest_tree_version(self) -> str:
        """PoB's own `latestTreeVersion` (GameVersions.lua), read from the running release."""

        return str(self._measured_call("tree_light", self._adapter.read_tree_light, self._handle, {})["latest_tree_version"])

    def convert_tree(self, version: str | None = None) -> dict[str, Any]:
        """Convert the active spec to ``version`` (default: PoB's `latestTreeVersion`) and recalc.

        Uses PoB's own conversion (`TreeTab:ConvertToVersion`): a fresh spec at the target version
        with the old spec's class, hash list, mastery selections, tattoos and jewels replayed onto
        it. Ids the target tree does not have are dropped and anything that lost its path to the
        class start is pruned; both are reported as ``lost_node_ids``.

        Returns {"from", "to", "converted", "nodes_before", "nodes_after", "lost_node_ids"}.
        Not done by `load_xml`: a read-only load stays faithful to the build it was given.
        """

        return self._adapter.convert_tree(self._handle, {"version": version})

    def tree_light(self) -> dict[str, Any]:
        """{"class_id", "user_allocated_node_ids", "mastery_effect_ids"}: the `tree_state` fields the
        tree optimizer needs on every step, read from `build.spec` in milliseconds instead of the
        ~0.9 s full `read_state`. The same values, the same formats."""

        return dict(self._measured_call("tree_light", self._adapter.read_tree_light, self._handle, {}))

    def ascendancy_node_names(self) -> dict[int, str]:
        """{node id: display name} of every node of the currently selected ascendancy, at
        whichever tree version the active spec holds (`build.spec.tree.nodes`, not the pinned
        latest tree) -- allocated or not, notable or small. Read this before `convert_tree`
        to keep a fixture's own (pre-conversion) node names, which a converted id can no longer
        answer for itself (spec 2026-09-22, requirement 2)."""

        report = self._adapter.read_ascendancy_node_report(self._handle)
        return {int(row["node_id"]): str(row["node_name"]) for row in report.get("rows") or []}

    def _drop_state_cache(self, adapter_call: str = "") -> None:
        self._state_cache = None
        if adapter_call not in _SKILLS_OR_CONFIG_ONLY_ADAPTER_CALLS:
            self.build_epoch += 1

    def read_state(self) -> dict[str, Any]:
        """Every surface of the build as PoB holds it. Cached until a call that may change the build
        (`_StateCacheAdapter`); each caller gets its own copy."""

        if self._state_cache is None:
            self._state_cache = self._measured_call("read_state", self._adapter.read_state, self._handle)
        return copy.deepcopy(self._state_cache)

    def calc_raw(self) -> dict[str, Any]:
        """Full raw calc snapshot as returned by the worker (everything PoB computes)."""

        return self._measured_call("calc", self._adapter.read_calc_snapshot, self._handle)

    def calc(self, lane: str = "baseline") -> dict[str, Any]:
        """Flat dict of PoB main output stats (FullDPS, Life, TotalEHP, FireResist, ...).

        ``lane`` is "baseline" or "conditional" (see set_config).
        """

        return flatten_calc_snapshot(self.calc_raw(), lane=lane)

    # -- gear primitives (PoB's item mod database and crafter) ----------------

    def parse_mods(self, lines: Sequence[str]) -> list[dict[str, Any]]:
        """PoB's mod parser on arbitrary mod text lines.

        Each result: {"line", "ok", "unsupported", "extra", "mods": [{"name", "type"
        (BASE/INC/MORE/FLAG/LIST/OVERRIDE), "value", "flags", "keyword_flags",
        "tags": [{"type": "PerStat"|"Condition"|"Multiplier"|..., ...}]}]}.
        Unsupported lines (PoB's red text) come back with ok=False or extra set.
        """

        return list(self._adapter.parse_mods(self._handle, {"lines": [str(l) for l in lines]}).get("results") or [])

    def unique_item(self, name: str) -> dict[str, Any]:
        """A unique from PoB's database by name ("Tabula Rasa") or key ("Tabula Rasa, Simple Robe").

        Returns {"name", "base", "type", "raw", "req_level", "explicit_lines", "implicit_lines"}.
        """

        return self._adapter.uniques(self._handle, {"name": name})

    def list_uniques(self) -> list[dict[str, Any]]:
        """Every unique PoB knows: {"key", "name", "base", "type", "req_level", "lines"}. ~1,300 rows."""

        return list(self._adapter.uniques(self._handle, {}).get("uniques") or [])

    def config_options(
        self,
        predicates: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        condition_flag_vars: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        """PoB's own view of the config tab for the current build.

        One row per config var: {"var", "shown" (PoB's predicate says the build
        references it), "value" (current input), "refs": [{"kind", "key", "sources"}],
        "condition_flags"}.  ``condition_flags`` are the player ``Condition:``
        flags PoB adds when that input is enabled.  They map a config checkbox to
        the parser flag without duplicating ConfigOptions.lua in Python.
        Pass the corpus predicates (config_surfaces.json) to get the refs.
        """

        requested = tuple(dict.fromkeys(str(var) for var in condition_flag_vars))
        uncached = [var for var in requested if var not in self._condition_flag_cache]
        result = self._adapter.read_config_options(
            self._handle,
            {"predicates": dict(predicates or {}), "condition_flag_vars": uncached},
        )
        rows = list(result.get("options") or [])
        for row in rows:
            var = row.get("var")
            if isinstance(var, str) and var in uncached:
                self._condition_flag_cache[var] = copy.deepcopy(list(row.get("condition_flags") or []))
        for row in rows:
            var = row.get("var")
            if isinstance(var, str) and var in self._condition_flag_cache:
                row["condition_flags"] = copy.deepcopy(self._condition_flag_cache[var])
        return rows

    def list_bench_mods(self, base: str, *, ilvl: int | None = None, range_: float = 0.5) -> dict[str, Any]:
        """Crafting bench mods for the base's item type: {"mods": [{"index", "type", "affix",
        "lines", "rolled_lines", "level", "group", "mod_tags", "mod_id", "families", "unlock"}]}. Append
        a rolled line as "{crafted}<line>" to a rare's raw text to bench-craft it (one per item).

        PoB's own bench table carries no mod id, so "mod_id" (None when the text
        matches several crafted mods) and "families" (the game mod families the
        craft occupies, empty when unknown) come from `bench_mod_ids.py`: an item
        cannot carry two mods of one family, and PoB's `group` is not that family.
        """

        result = self._adapter.list_bench_mods(self._handle, {"base": base, "ilvl": ilvl, "range": range_})
        for row in result.get("mods") or []:
            row["mod_id"] = bench_mod_id(row)
            row["families"] = list(bench_mod_families(row))
            candidates = bench_mod_candidates(row)
            unlocks = [bench_unlock_lookup(mod_id=mod_id) for mod_id in candidates]
            row["unlock"] = bench_unlock_lookup(mod_id=row["mod_id"], name=row.get("name")) or lowest_requirement([entry for entry in unlocks if entry])
        return result

    def unsupported_gems(self) -> list[dict[str, Any]]:
        """Support gems PoB's own calc applies to nothing: [{"group", "label", "slot", "gem",
        "reason"}], reason "cannot apply to any of the active skills" (the skills tab's red
        text: `supportEffect.isSupporting` empty in a group that has active skills) or
        "superseded" (a stronger copy of the same support in the group). Disabled gems and
        groups are not judged; a group with no active gem at all is the audit's "dead
        support group", not this."""

        result = self._adapter.unsupported_gems(self._handle, {})
        return list(result.get("unsupported") or [])

    def base_families(self, base: str, *, ilvl: int | None = None, pool: str = "explicit") -> dict[str, list[str]]:
        """{mod id: [game mod family, ...]} for every mod PoB allows on ``base``.

        An item cannot carry two mods of the same family; PoB's own ``group`` is
        not that family (mod_families.py). Cached per base: one PoB round trip.
        """

        key = (base, ilvl, pool)
        if key not in self._base_families:
            mods = self.list_item_mods(base, ilvl=ilvl, pool=pool)["mods"]
            self._base_families[key] = {m["mod_id"]: list(families_of(m["mod_id"])) for m in mods if families_of(m["mod_id"])}
        return self._base_families[key]

    def random_rares(
        self,
        base: str,
        *,
        n: int = 100,
        ilvl: int = 70,
        quality: int = 20,
        sockets: str | None = None,
        seed: int = 1,
        mod_counts: Sequence[int] = (4, 4, 4, 5, 5, 6),
        pool: str = "explicit",
        forced: Sequence[Sequence[str]] = (),
    ) -> list[dict[str, Any]]:
        """Loot simulation: N random rares on ``base`` rolled with PoB's spawn weights.

        Each entry: {"raw": PoB item text, "mod_ids": [...]}. Combine with item
        trials to answer "how good is the best of N drops for this build".

        Two mods of one game mod family never land on the same item (the families
        come from the corpus; a mod the corpus does not know keeps PoB's group).

        ``forced``: per mod line every roll must carry, the candidate mod ids (the line's tiers).
        Each roll places one mod per entry first, chosen among its ids by the same spawn weights,
        inside the roll's own mod count and families; empty (the default) rolls exactly as before.
        """

        request: dict[str, Any] = {
            "base": base,
            "n": n,
            "ilvl": ilvl,
            "quality": quality,
            "sockets": sockets,
            "seed": seed,
            "mod_counts": list(mod_counts),
            "pool": pool,
            "families": self.base_families(base, ilvl=ilvl, pool=pool),
        }
        if forced:
            request["forced"] = [list(ids) for ids in forced]
        result = self._measured_call("random_rares", self._adapter.random_rares, self._handle, request)
        return list(result.get("items") or [])

    def equip(self, items_by_slot: Mapping[str, str | None], *, drop_replaced: bool = False) -> dict[str, Any]:
        """Equip raw item text per slot, leaving other slots as they are (None unequips).

        Unlike ``set_items`` this does not replace the whole item set. Incremental
        and cheap; use it in gear loops. Returns {"equipped": [{slot, item_id, name}]}.

        PoB keeps an item that left its slot in the item list, and the export writes it. ``drop_replaced=True``
        takes the item a slot held out of the list when nothing else points at it (a loop that equips hundreds of
        trial items would otherwise export hundreds of orphans); the default leaves every call as it was.
        """

        request: dict[str, Any] = {"items": [{"slot": slot, "raw": raw} for slot, raw in items_by_slot.items()]}
        if drop_replaced:
            request["drop_replaced"] = True
        return self._measured_call("equip", self._adapter.equip_items, self._handle, request)

    def put_jewel(self, node_id: int, raw: str) -> dict[int, str]:
        """Put a Jewel's raw item text (a cluster jewel too: PoB builds its subgraph, see ``cluster_graph``) into
        the ALLOCATED passive-tree socket ``node_id``, replacing what sat there (a replaced cluster jewel
        leaves with its inner nodes and the jewels in its inner sockets); the full calculation sees it at once.
        A socket that is not allocated (or not a jewel socket, or a raw that is not a Jewel) raises; allocate it
        first with ``add_nodes``.
        ``equip`` rejects socket slots on purpose, this is the way in. Returns ``socketed_jewels()``."""

        return self._socket_jewels({"put": [{"node_id": int(node_id), "raw": raw}]})

    def remove_jewel(self, node_id: int) -> dict[int, str]:
        """Take the jewel out of socket ``node_id`` (an empty socket is a no-op). Returns ``socketed_jewels()``."""

        return self._socket_jewels({"remove": [int(node_id)]})

    def cluster_graph(self, node_id: int) -> list[dict[str, Any]]:
        """The subgraph PoB built for the cluster jewel in socket ``node_id``, read from PoB: a list of
        {id, kind, name, linked, allocated} (kind: entry | small | notable | socket | keystone); empty when the
        socket holds no cluster jewel."""

        result = self._measured_call("cluster_graph", self._adapter.cluster_graph, self._handle, {"socket_id": int(node_id)})
        return list(result.get("nodes") or [])

    def socketed_jewels(self) -> dict[int, str]:
        """{socket node_id: raw item text} of every jewel PoB holds in a tree socket (what the export lists
        as ``socketed_jewel_items``, cluster jewels included). A jewel in a socket that was deallocated stays
        listed but counts for nothing in the calculation."""

        return self._socket_jewels({})

    def _socket_jewels(self, request: dict[str, Any]) -> dict[int, str]:
        result = self._measured_call("socket_jewels", self._adapter.socket_jewels, self._handle, request)
        return {int(j["node_id"]): str(j["raw"]) for j in result.get("jewels") or []}

    def equipped_item_raws(self) -> dict[str, str]:
        """Raw text of every item PoB holds in the active item set, by slot name (one export)."""

        root = ElementTree.fromstring(self.export_xml())
        items = root.find("Items")
        if items is None:
            return {}
        item_sets = items.findall("ItemSet")
        active = items.get("activeItemSet")
        item_set = next((s for s in item_sets if s.get("id") == active), item_sets[0] if item_sets else items)
        texts = {i.get("id"): i.text for i in items.iter("Item")}
        out: dict[str, str] = {}
        for s in item_set.iter("Slot"):
            text = texts.get(s.get("itemId")) if s.get("itemId") not in (None, "0") else None
            if text and s.get("name"):
                out[str(s.get("name"))] = textwrap.dedent(text).strip()
        return out

    def _equipped_item_raw(self, slot: str) -> str | None:
        """Raw text of the item PoB holds in ``slot`` of the active item set (None: empty slot)."""

        return self.equipped_item_raws().get(slot)

    def item_sockets(self, slot: str) -> str | None:
        """The ``Sockets:`` string of the item equipped in ``slot`` (None: no item or no Sockets line)."""

        raw = self._equipped_item_raw(slot)
        for line in (raw or "").splitlines():
            if line.strip().startswith("Sockets:"):
                return line.split(":", 1)[1].strip()
        return None

    def set_item_sockets(self, slot: str, sockets: str) -> None:
        """Rewrite the ``Sockets:`` line of the item in ``slot`` (insert it when absent) and re-equip it.

        The socket groups stay on the slot with their gems, so PoB's matchesSocket (the socket at the
        gem's index on the group's item) is recomputed against the new sockets by the equip's rebuild.
        """

        raw = self._equipped_item_raw(slot)
        if raw is None:
            raise ValueError(f"no item equipped in slot {slot!r}")
        self.equip({slot: raw_with_sockets(raw, sockets)})

    def list_item_mods(self, base: str, *, ilvl: int | None = None, pool: str = "explicit") -> dict[str, Any]:
        """Every prefix/suffix mod PoB allows on ``base`` (at ``ilvl`` if given).

        pool="explicit" (default): the regular drop pool (Data/ModExplicit.lua); influence-only
        and essence-only mods fall out through their zero weight. pool="all": PoB's merged
        table including delve, synthesis, scourge, corrupted and eldritch mods (not regular drops).

        Returns {"base", "type", "sub_type", "base_tags", "implicit", "mods": [
            {"mod_id", "type", "affix", "lines", "level", "group", "weight", "mod_tags"}]}.
        Tier = rank within a group by level (highest level = T1).
        """

        return self._measured_call("list_item_mods", self._adapter.list_item_mods, self._handle, {"base": base, "ilvl": ilvl, "pool": pool})

    def craft_rare(
        self,
        base: str,
        *,
        prefixes: Sequence[str | Mapping[str, Any]] = (),
        suffixes: Sequence[str | Mapping[str, Any]] = (),
        ilvl: int | None = None,
        quality: int | None = None,
        sockets: str | None = None,
        name: str | None = None,
        implicit_range: float = 0.5,
        extra_lines: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Craft a rare through PoB from mod ids (each entry a mod id or {"mod_id", "range"}).

        Returns {"raw": PoB item text, "name", "explicit_lines", "unsupported_lines",
        "problems": [legality issues], "level_req"}. Use ``raw`` with set_items or
        as an item trial. Two mods of one game mod family are a problem
        ("duplicate mod family <family>"), as the game does not allow them together.
        """

        listed_prefixes = [p if isinstance(p, str) else dict(p) for p in prefixes]
        listed_suffixes = [s if isinstance(s, str) else dict(s) for s in suffixes]
        mod_ids = [a if isinstance(a, str) else str(a.get("mod_id") or "") for a in (*listed_prefixes, *listed_suffixes)]
        return self._measured_call(
            "craft_rare",
            self._adapter.craft_rare,
            self._handle,
            {
                "base": base,
                "prefixes": listed_prefixes,
                "suffixes": listed_suffixes,
                "families": {mod_id: list(families_of(mod_id)) for mod_id in mod_ids if families_of(mod_id)},
                "ilvl": ilvl,
                "quality": quality,
                "sockets": sockets,
                "name": name,
                "implicit_range": implicit_range,
                "extra_lines": list(extra_lines),
            },
        )

    def recraft(self, raw: str) -> str:
        """The raw with its affix text re-rendered by PoB's own ``Item:Craft()`` from its ``Prefix:`` /
        ``Suffix:`` headers (``{crafted}`` and ``{custom}`` lines are kept). Used after lines were removed
        with ``useful_lines.without_lines``; a trial item with ``"recraft": True`` does the same in Lua."""

        result = self._measured_call("recraft", self._adapter.recraft, self._handle, {"raw": raw})
        return str(result["raw"])

    def trial_stats(
        self,
        trials: Sequence[Mapping[str, Any]],
        keys: Sequence[str],
        *,
        mode: str = "full",
    ) -> list[dict[str, Any]]:
        """Evaluate candidate allocations without applying them.

        ``trials``: [{"add": [node_ids], "remove": [node_ids], "mastery": {node_id: effect_id}}, ...].
        Removal happens first. Returns one entry per trial:
        {"ok", "error", "added_node_ids", "removed_node_ids", "stats"}.
        The build is restored exactly after each trial. ~0.05 s per trial.

        With `fulldps_shortcut` on, a fast batch that asks for FullDPS is run without PoB's
        full-DPS roll-up and FullDPS is reported as `ratio x base` instead; see
        `_fulldps_ratio`. Approximate, so it is off by default. With `mean_parts` set, a fast
        trial is evaluated once per listed skill part and reports the mean (a random-element
        main skill); full mode reads the selected part.
        """

        if mode == "fast" and self.fulldps_shortcut and "FullDPS" in keys:
            shortcut = self._fulldps_ratio()
            if shortcut is not None:
                self.fulldps_shortcut_batches += 1
                return self._trial_stats_via_ratio(trials, keys, shortcut)
            self.fulldps_full_batches += 1

        trials = list(trials)  # read twice: the payload and the trace count (#511)
        payload = {
            "trials": [
                {
                    "add": [int(n) for n in t.get("add", ())],
                    "remove": [int(n) for n in t.get("remove", ())],
                    "mastery": {str(int(k)): int(v) for k, v in (t.get("mastery") or {}).items()},
                    "item": (
                        {"slot": str(t["item"]["slot"]), "raw": str(t["item"]["raw"]), "recraft": bool(t["item"].get("recraft"))}
                        if t.get("item")
                        else None
                    ),
                }
                for t in trials
            ],
            "keys": list(keys),
            "mode": mode,
            "parts": list(self.mean_parts) if (self.mean_parts and mode == "fast") else [],
        }
        for t, orig in zip(payload["trials"], trials):
            # #1124 unit 4: the red-line marks a tree trial carries ({"add"|"remove": {held line: [mark lines]}}) go to the
            # worker as flat lines, and only when there are some: a trial without marks has no `marks` key at all
            marks = orig.get("marks") if isinstance(orig, Mapping) else None
            if marks:
                lines = {side: list(dict.fromkeys(m for ms in (marks.get(side) or {}).values() for m in ms)) for side in ("add", "remove")}
                if lines["add"] or lines["remove"]:
                    t["marks"] = lines
        kind = "fast_trials" if mode == "fast" else "full_trials"
        result = self._measured_call(kind, self._adapter.trial_stats, self._handle, payload)
        for t, orig in zip(payload["trials"], trials):
            # `path` (nodes a greedy move allocates on the way), `attribute_cap_over` and the tree_trace stamps are trace-only: never in the payload
            path = orig.get("path") if isinstance(orig, Mapping) else None
            over = bool(orig.get("attribute_cap_over")) if isinstance(orig, Mapping) else False  # trace-only (#516)
            held = orig.get("marks") if isinstance(orig, Mapping) and "marks" in t else None  # held lines for the trace; `t["marks"]` is the flat payload form
            TRACE.count_trial({**t, **({"marks": held} if held else {}), **({"path": list(path)} if path else {}), **({"attribute_cap_over": True} if over else {}), **stamps_of(orig), **base_swap_stamp_of(orig)})  # #1038 stamps; #1158 base-swap stamp
        return result

    _FULLDPS_BASES = ("TotalDPS", "Minion.TotalDPS")

    def _fulldps_ratio(self) -> tuple[str, float] | None:
        """PoB's FullDPS for the build as it stands over the main skill's own DPS, measured
        with one real roll-up in the trial lane (13-25 ms, once per batch of 150-400 trials).

        A build we generate flags exactly one socket group "include in full DPS" -- the main
        link, one active gem (`set_skills`) -- so PoB's FullDPS is that skill's own DPS times
        the gem's instance count (brands, totems, minions at their limit, corpses eaten;
        D49/D57) plus the ailment roll-ups that skill carries, which scale with it. Measured
        2026-09-18: stormbrand 2.000000 over 40 node-removal trials (stdev 0), Summon Raging
        Spirits 20.14-20.15 against the minion's own DPS. It is *not* constant for a build
        with two flagged groups (an author's build can have several), which is why the
        shortcut is a flag and the ratio is re-measured for every batch. None when there is
        nothing to scale (no flagged group, a zero base): the batch then runs whole.

        Two guards, so a build whose FullDPS aggregates several skills can never be mispriced
        in silence: the shortcut is refused up front when the build flags more than one socket
        group (read off the cached `read_state`), and a ratio that moves by more than 2%
        between two consecutive batches of the same skills surface turns it off for the rest
        of the session (`fulldps_shortcut_unsafe`).
        """

        if self.fulldps_shortcut_unsafe or self._flagged_full_dps_groups() > 1:
            return None
        probe = self._measured_call(
            "fast_trials",
            self._adapter.trial_stats,
            self._handle,
            {
                "trials": [{"add": [], "remove": [], "mastery": {}, "item": None}],
                "keys": ["FullDPS", *self._FULLDPS_BASES],
                "mode": "fast",
            },
        )
        stats = (probe[0].get("stats") or {}) if probe and probe[0].get("ok") else {}
        full = float(stats.get("FullDPS") or 0.0)
        if full <= 0:
            return None
        for base_key in self._FULLDPS_BASES:
            base = float(stats.get(base_key) or 0.0)
            if base > 0:
                return self._fulldps_checked(base_key, full / base)
        return None

    def _flagged_full_dps_groups(self) -> int:
        """Enabled socket groups of the active skill set flagged "include in full DPS". More
        than one and PoB's FullDPS is a sum over several skills that no single base tracks
        (measured 2026-09-18 on the authors' own builds: absolution_minions off by 56%,
        impale_ballista 19%, toxic_rain 15%)."""

        skills = self.read_state().get("skills_state") or {}
        sets = [s for s in (skills.get("skill_sets") or []) if isinstance(s, dict)]
        active = [s for s in sets if s.get("skill_set_id") == skills.get("active_skill_set_id")] or sets
        return sum(
            1
            for skill_set in active
            for group in (skill_set.get("socket_groups") or [])
            if isinstance(group, dict) and group.get("include_in_full_dps") and group.get("enabled", True)
        )

    def _fulldps_checked(self, base_key: str, ratio: float) -> tuple[str, float] | None:
        """The batch's ratio against the previous batch's on the same skills surface: a move of
        more than 2% means it is not the constant this shortcut assumes, so the session stops
        using it (one line through the session's logger if it has one, and a counter)."""

        previous = self._fulldps_last_ratio
        if previous is not None and previous[0] == base_key and previous[1] > 0 and abs(ratio - previous[1]) > 0.02 * previous[1]:
            self.fulldps_shortcut_unsafe = True
            self.fulldps_shortcut_disabled += 1
            self._fulldps_last_ratio = None
            log = getattr(self, "log", None)
            if callable(log):
                log(f"fulldps shortcut off: FullDPS / {base_key} moved {previous[1]:.4f} -> {ratio:.4f} between batches")
            return None
        self._fulldps_last_ratio = (base_key, ratio)
        return base_key, ratio

    def _trial_stats_via_ratio(
        self,
        trials: Sequence[Mapping[str, Any]],
        keys: Sequence[str],
        shortcut: tuple[str, float],
    ) -> list[dict[str, Any]]:
        """The batch without PoB's full-DPS roll-up, with FullDPS = ratio x base per trial."""

        base_key, ratio = shortcut
        drop_base = base_key not in keys
        wanted = [k for k in keys if k != "FullDPS"]
        if drop_base:
            wanted.append(base_key)
        results = self.trial_stats(trials, wanted, mode="fast")
        for result in results:
            stats = result.get("stats")
            if not isinstance(stats, dict):
                continue
            base = stats.get(base_key)
            if isinstance(base, (int, float)) and not isinstance(base, bool):
                stats["FullDPS"] = ratio * float(base)
            if drop_base:
                stats.pop(base_key, None)
        return results

    def stats(self, keys: Sequence[str] | None = None, *, keep_flask_flags: bool = False) -> dict[str, Any]:
        """Fast path for optimizers: recalc if needed, return scalar stats.

        Uses the active config set only. ``keys`` limits the result (e.g.
        ("CombinedDPS", "Life", "FireResist")). Prefer this over ``calc()`` in
        hot loops; ``calc()`` is the full two-lane snapshot.

        ``keep_flask_flags`` skips the Flask-flag derivation (#575) for this read, so flags just set by
        `set_flasks_active` hold (#589); the next default read derives them again.
        """

        parts = list(self.mean_parts) if self.mean_parts else None
        if keep_flask_flags:
            return self._measured_call("stats", self._adapter.read_stats, self._handle, list(keys) if keys else None, parts, keep_flask_flags=True)
        return self._measured_call("stats", self._adapter.read_stats, self._handle, list(keys) if keys else None, parts)

    def stats_without_ailment_caps(self, keys: Sequence[str] | None = None) -> dict[str, Any] | None:
        """`stats()` of the build without D78's ailment-stack surfaces (the native bleed / ignite
        stack-potential overrides, `multiplierBleedsOnEnemy` next to them, the "junkroan: poison stacks"
        custom block), or None when its Baseline config set holds none of them.

        The worker lifts them out of the live config set, reads, puts them back and recalculates: the
        reading `ramp_inputs.uncapped_ailment_stack_xml` + two `load_xml` gave, without the loads, and
        the build the next call sees is the one this call started from.
        """

        result = self._measured_call("stats_uncapped", self._adapter.read_stats_uncapped, self._handle, list(keys) if keys else None, list(self.mean_parts) if self.mean_parts else None)
        return dict(result["stats"]) if result.get("changed") else None

    def config_checkpoint(self) -> None:
        """Remember the build's whole config state (every config set, its custom blocks, the active
        set, bandit / pantheon) in the worker, for one `config_rollback` after probes that write config."""

        self._measured_call("config_checkpoint", self._adapter.checkpoint_config, self._handle)

    def config_rollback(self) -> None:
        """Put the config state of the last `config_checkpoint` back and recalculate: what
        `load_xml(export_xml())` taken at the checkpoint gave, without the whole-build load (#540)."""

        self._measured_call("config_rollback", self._adapter.rollback_config, self._handle)

    def active_skill_stats(self, skill_ids: Sequence[str], keys: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Read selected active skills' PoB output without changing the build's selections.

        Each selector may be a granted-effect id (all matching active skills share the
        returned key, preserving the original API) or an observed
        ``active_skill_id`` from ``read_state`` for one exact linked skill.
        """

        return self._adapter.read_active_skill_stats(self._handle, [str(skill_id) for skill_id in skill_ids], [str(key) for key in keys])

    def mana_cost_warnings(self) -> tuple[str, ...]:
        """The current MAIN calculation's `ManaCostWarningList`, in PoB's order."""

        return tuple(self._adapter.read_mana_cost_warnings(self._handle))

    def granted_passives(self) -> tuple[int, ...]:
        """Node ids the current calculation holds through a `GrantedPassive` mod (an amulet anoint),
        which `mutate_nodes` and its `points_used` do not see."""

        return tuple(self._adapter.read_granted_passives(self._handle))

    def node_power(self, **request: Any) -> dict[str, Any]:
        """PoB native node power report: marginal value of every reachable node."""

        return self._measured_call("node_power", self._adapter.read_node_power_report, self._handle, request or None)

    def export_xml(self) -> str:
        return self._measured_call("export_xml", self._adapter.export_build_artifact, self._handle)

    def verify_import_code(self, import_code: str) -> dict[str, Any]:
        return self._adapter.verify_pob_import_code_string(self._handle, import_code)


def config_inputs_from_xml(xml_text: str) -> dict[str, Any]:
    """The active config set's inputs read out of a PoB export.

    The pre-2026-09-18 body of `PobSession.config_inputs`, kept as the reference the live read
    is proven against (tests/test_pob_inplace_writes.py) and as the way to read the inputs of a
    build that is not loaded.
    """

    from xml.etree import ElementTree as ET

    root = ET.fromstring(xml_text)
    cfg = root.find("Config")
    if cfg is None:
        return {}
    active = cfg.get("activeConfigSet") or "1"
    sets = cfg.findall("ConfigSet")
    node = next((c for c in sets if c.get("id") == active), sets[0] if sets else cfg)
    out: dict[str, Any] = {}
    for inp in node.findall("Input"):
        name = inp.get("name")
        if not name:
            continue
        if inp.get("boolean") is not None:
            out[name] = inp.get("boolean") == "true"
        elif inp.get("number") is not None:
            raw = inp.get("number")
            out[name] = float(raw) if "." in raw else int(raw)
        elif inp.get("string") is not None:
            out[name] = inp.get("string")
    return out


def flatten_calc_snapshot(raw: Mapping[str, Any], *, lane: str = "baseline") -> dict[str, Any]:
    """Find the player main-output stat table for one config lane inside a raw calc snapshot."""

    def looks_like_stats(value: Any) -> bool:
        return isinstance(value, Mapping) and any(marker in value for marker in _STAT_MARKERS)

    section = raw.get(lane) if isinstance(raw, Mapping) else None
    stack: list[Any] = [section if isinstance(section, Mapping) else raw]
    while stack:
        current = stack.pop(0)
        if not isinstance(current, Mapping):
            continue
        for key in ("main_output", "mainOutput"):
            if looks_like_stats(current.get(key)):
                return {str(k): v for k, v in current[key].items()}
        for value in current.values():
            if isinstance(value, Mapping):
                stack.append(value)
    raise KeyError("calc snapshot does not contain a main_output stat table")


__all__ = ["PobSession", "config_inputs_from_xml", "decode_import_code", "encode_import_code", "flatten_calc_snapshot"]
