"""Real pinned headless PoB adapter for the minimal proof loop."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import queue
import shutil
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..report_format import human_duration
from .artifacts import PROJECT_ROOT, sha256_file
from .host_runtime import (
    PoBHeadlessHostContractError,
    PoBHeadlessLaunchRequest,
    PoBHeadlessLaunchResult,
    PoBHeadlessSessionHandle,
)
from .no_pob_switch import guard_pob_launch
from .release_manager import PoBReleaseManager

_WORKER_READY_TIMEOUT_SECONDS = 30.0
_WORKER_COMMAND_TIMEOUT_SECONDS = 30.0
_WORKER_NODE_POWER_TIMEOUT_SECONDS = 60.0
_WORKER_SHUTDOWN_TIMEOUT_SECONDS = 10.0
_WORKER_MODULE = "junkroan.pob.headless_runtime_worker"
_SOURCE_ROOT = Path(__file__).resolve().parents[2]  # .../src, so the worker subprocess can import junkroan
_WINDOWS_CREATEPROCESS_CWD_LIMIT = 259
_NATIVE_POB_IMPORT_STRING_PROOF_KIND = "pinned_pob_import_tab_import_string"
_NATIVE_POB_IMPORT_STRING_SURFACE_KIND = "pob_import_ui_import_code"
POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION = "1.0.0"
POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND = "pob_headless_node_power_report"
POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND = "pob_native_node_power_report"
POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH = "pob_native_node_power_report_hint_v1"
_NODE_POWER_REPORT_STATUSES = {"accepted", "unavailable"}
_FORBIDDEN_NODE_POWER_PAYLOAD_FIELDS = {
    "Direct" "BuildOutput",
    "direct_build_output",
    "ready_import",
    "ready_" "pob_import",
    "pob_code",
    "pob" "code",
    "pob" "code_txt",
    "xml",
    "path_of_building_xml",
    "public_url",
}

def _is_vaal_gem_name(name: str) -> bool:
    """The corpus's own `is_vaal_gem` (game_corpus); the "Vaal " prefix only when the corpus does not know the name."""

    from ..search.hypothesis import active_gems

    record = active_gems().get(str(name).strip().lower())
    if record is not None:
        return bool(record.get("is_vaal_gem"))
    return str(name).startswith("Vaal ")


def vaal_gem_flags(skill_payload: dict[str, Any]) -> dict[str, Any]:
    """#802 rule 1: the Vaal skill's own effect (`enable_global_1`) is never counted, the plain gem's (`enable_global_2`) is.

    A Vaal gem written without the flags gets (False, True); one written with global_1 true or global_2 false is refused
    before PoB. Every other gem is left as written (the worker's own defaults)."""

    sets = skill_payload.get("skill_sets")
    if not isinstance(sets, list):
        return skill_payload
    out_sets = []
    for skill_set in sets:
        groups = []
        for group in skill_set.get("socket_groups", ()):
            gems = []
            for gem in group.get("gems", ()):
                name = gem.get("gem_name", "")
                if _is_vaal_gem_name(name):
                    if gem.get("enable_global_1", False) is not False or gem.get("enable_global_2", True) is not True:
                        _fail(
                            "runtime_protocol_failed",
                            f"Vaal gem {name!r}: enable_global_1 must be false and enable_global_2 true (the Vaal half is never counted, #802).",
                        )
                    gem = {**gem, "enable_global_1": False, "enable_global_2": True}
                gems.append(gem)
            groups.append({**group, "gems": gems})
        out_sets.append({**skill_set, "socket_groups": groups})
    return {**skill_payload, "skill_sets": out_sets}



@dataclass(frozen=True, slots=True)
class PoBHeadlessSessionShutdown:
    """Observed session shutdown boundary for one headless worker."""

    exit_code: int
    termination: str
    process_exit_observed: bool = True


@dataclass(slots=True)
class _WorkerProcess:
    process: subprocess.Popen[str]
    request: PoBHeadlessLaunchRequest


def _fail(failure_state: str, message: str) -> None:
    raise PoBHeadlessHostContractError(failure_state, message)


def _normalize_unified_state_payload(raw_state: Any, *, failure_state: str) -> dict[str, Any]:
    if not isinstance(raw_state, dict):
        _fail(failure_state, "Headless PoB worker returned a non-object unified state payload.")
    state = dict(raw_state)
    identity_state = state.get("identity_state")
    items_state = state.get("items_state")
    gear_slots = state.get("gear_slots")
    if items_state is None:
        items_state = gear_slots
    if gear_slots is None:
        gear_slots = items_state
    tree_state = state.get("tree_state")
    skills_state = state.get("skills_state")
    config_state = state.get("config_state")
    if identity_state is not None and not isinstance(identity_state, dict):
        _fail(failure_state, "Headless PoB worker returned an invalid identity_state payload.")
    if not isinstance(items_state, dict) or not isinstance(gear_slots, dict):
        _fail(failure_state, "Headless PoB worker must expose repo-owned items_state and gear_slots objects.")
    if not isinstance(tree_state, dict) or not isinstance(skills_state, dict) or not isinstance(config_state, dict):
        _fail(failure_state, "Headless PoB worker returned an invalid unified state payload.")
    if isinstance(identity_state, dict):
        state["identity_state"] = dict(identity_state)
    state["items_state"] = dict(items_state)
    state["gear_slots"] = dict(gear_slots)
    return state


def _legacy_minimal_state_payload(raw_state: Any, *, failure_state: str) -> dict[str, Any]:
    state = _normalize_unified_state_payload(raw_state, failure_state=failure_state)
    state.pop("items_state", None)
    state.pop("state_contract_version", None)
    return state


_CPU_WAIT_CAP_INTERVALS = 10  # #724: a computing worker is waited for at most this many limit-sized intervals


def _tree_cpu_seconds(process: Any) -> float:
    """User + system CPU seconds of the worker process and its children; raises when the worker is unreadable."""

    import psutil

    root = psutil.Process(process.pid)
    total = 0.0
    for member in [root, *root.children(recursive=True)]:
        try:
            times = member.cpu_times()
        except (psutil.NoSuchProcess, psutil.ZombieProcess):
            if member is root:
                raise
            continue
        total += times.user + times.system
    return total


def _day_priority_flag() -> int:
    """#839: BELOW_NORMAL creation flag when this host's mode says BelowNormal now (day); else 0."""

    try:
        from junkroan.runs import hosts

        return hosts.day_priority_flag()
    except Exception:
        return 0


def _is_idle_priority(process: Any) -> bool:
    """True while the worker's own priority class is Idle (the runs daemon sets it while a merge suite runs)."""

    import psutil

    idle_class = getattr(psutil, "IDLE_PRIORITY_CLASS", None)
    return idle_class is not None and psutil.Process(process.pid).nice() == idle_class


def _readline_with_timeout(handle: Any, timeout_seconds: float, process: Any = None) -> str:
    """One stdout line, or `runtime_protocol_timeout`.

    Without `process` the wait ends at `timeout_seconds`. With it, at each limit the worker tree's CPU time is read:
    a worker whose CPU advanced since the last check is waited for another interval (hard cap
    `_CPU_WAIT_CAP_INTERVALS` intervals); one with no CPU is ended. While the worker's priority class is Idle
    (a merge suite runs) a worker is not ended and the interval does not count toward the cap. Unreadable
    CPU or priority means the plain end at the limit.
    """

    output: queue.Queue[str] = queue.Queue(maxsize=1)

    def _reader() -> None:
        try:
            line = handle.readline()
        except Exception:
            line = ""
        output.put(line)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    last_cpu: float | None = None
    if process is not None:
        try:
            last_cpu = _tree_cpu_seconds(process)
        except Exception:
            last_cpu = None
    counted_intervals = 0
    while True:
        try:
            return output.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            timeout_error = PoBHeadlessHostContractError(
                "runtime_protocol_timeout",
                "Timed out waiting for the headless PoB worker protocol.",
            )
            if process is None or last_cpu is None:
                raise timeout_error from exc
            try:
                cpu = _tree_cpu_seconds(process)
                idle = _is_idle_priority(process)
            except Exception:
                raise timeout_error from exc
            advanced = cpu > last_cpu
            last_cpu = cpu
            if idle:
                continue
            counted_intervals += 1
            if not advanced or counted_intervals >= _CPU_WAIT_CAP_INTERVALS:
                raise timeout_error from exc


_DEAD_WORKER_EXIT_WAIT_SECONDS = 2.0  # #805: how long a dead worker's exit code is waited for
_STDERR_TAIL_LINES = 5
_STDERR_TAIL_LINE_CHARS = 300


def _stderr_tail(process: Any) -> str:
    """The last `_STDERR_TAIL_LINES` lines of an ENDED worker's stderr pipe ('' when none or unreadable).

    The pipe is not read while the worker lives (unchanged); this runs once, after the process ended, in a thread
    that is given 2 s (a grandchild holding the pipe open must not hold the report)."""

    stream = getattr(process, "stderr", None)
    if stream is None:
        return ""
    box: list[str] = []

    def _read() -> None:
        try:
            box.append(stream.read())
        except Exception:
            pass

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout=2.0)
    if not box or not isinstance(box[0], str):
        return ""
    lines = [line.strip()[:_STDERR_TAIL_LINE_CHARS] for line in box[0].splitlines() if line.strip()]
    return " | ".join(lines[-_STDERR_TAIL_LINES:])


_CALL_LOG_ENV = "JUNKROAN_POB_CALL_LOG"
_CALL_LOG_ALL_ENV = "JUNKROAN_POB_CALL_LOG_ALL"  # "1": log every call, not only over half the limit


def _log_slow_call(call: str, trials: int | None, limit: float, elapsed: float, pid: int | None) -> None:
    """Append one JSON line for a call that used over half its limit; never raises."""

    path = os.environ.get(_CALL_LOG_ENV)
    if not path:
        return
    if elapsed <= 0.5 * limit and os.environ.get(_CALL_LOG_ALL_ENV) != "1":
        return
    try:
        record = {"ts": time.time(), "call": call, "trials": trials, "limit": limit, "elapsed": elapsed, "pid": pid}
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def _parse_worker_message(raw_line: str, *, failure_state: str) -> dict[str, Any]:
    stripped = raw_line.strip()
    if not stripped:
        _fail(failure_state, "Headless PoB worker returned an empty protocol message.")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        _fail(failure_state, f"Headless PoB worker returned invalid JSON: {stripped}")
        raise AssertionError from exc
    if not isinstance(payload, dict):
        _fail(failure_state, "Headless PoB worker returned a non-object protocol message.")
    return payload


def _diagnostic_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _offending_path_summary(diagnostics: dict[str, Any]) -> str:
    entries = diagnostics.get("offending_paths")
    if not isinstance(entries, list):
        return ""
    parts: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        field = str(entry.get("field") or "unknown")
        reason = str(entry.get("reason") or "invalid")
        path = str(entry.get("path") or "")
        parts.append(f"{field}={path} ({reason})")
    return "; ".join(parts)


def _resolved_executable_path(executable: str) -> Path | None:
    if not isinstance(executable, str) or not executable.strip():
        return None
    candidate = Path(executable)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.resolve(strict=False)
    resolved = shutil.which(executable)
    if resolved:
        return Path(resolved).resolve(strict=False)
    return candidate


def _resolved_worker_script_path() -> Path | None:
    spec = importlib.util.find_spec(_WORKER_MODULE)
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).resolve(strict=False)


def _directory_creatable(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    marker = path / f".pob-headless-path-probe-{uuid4().hex}.tmp"
    try:
        marker.write_text("probe\n", encoding="utf-8")
        return True
    except OSError:
        return False
    finally:
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass


def _path_status(
    *,
    field: str,
    path: Path | None,
    expected_kind: str,
    windows_cwd_limit: int | None,
) -> dict[str, Any]:
    if path is None:
        return {
            "field": field,
            "path": None,
            "exists": False,
            "is_directory": False,
            "is_file": False,
            "is_creatable": False,
            "path_length": 0,
            "expected_kind": expected_kind,
        }

    resolved = path.resolve(strict=False)
    exists = resolved.exists()
    is_directory = resolved.is_dir()
    is_file = resolved.is_file()
    status: dict[str, Any] = {
        "field": field,
        "path": str(resolved),
        "exists": exists,
        "is_directory": is_directory,
        "is_file": is_file,
        "is_creatable": _directory_creatable(resolved) if expected_kind == "directory" else False,
        "path_length": len(str(resolved)),
        "expected_kind": expected_kind,
    }
    if expected_kind == "file":
        status["parent_creatable"] = _directory_creatable(resolved.parent)
    if field == "cwd" and windows_cwd_limit is not None:
        status["windows_createprocess_cwd_limit"] = windows_cwd_limit
        status["windows_createprocess_cwd_safe"] = len(str(resolved)) <= windows_cwd_limit
    return status


def build_headless_worker_launch_path_diagnostics(
    *,
    python_executable: str,
    worker_script_path: Path | None,
    cwd: Path,
    session_root: Path,
    temp_root: Path,
    output_dir: Path,
    windows_cwd_limit: int | None = None,
) -> dict[str, Any]:
    if windows_cwd_limit is None and sys.platform.startswith("win"):
        windows_cwd_limit = _WINDOWS_CREATEPROCESS_CWD_LIMIT
    statuses = [
        _path_status(
            field="worker_executable",
            path=_resolved_executable_path(python_executable),
            expected_kind="file",
            windows_cwd_limit=windows_cwd_limit,
        ),
        _path_status(
            field="worker_script",
            path=worker_script_path,
            expected_kind="file",
            windows_cwd_limit=windows_cwd_limit,
        ),
        _path_status(field="cwd", path=cwd, expected_kind="directory", windows_cwd_limit=windows_cwd_limit),
        _path_status(
            field="session_root",
            path=session_root,
            expected_kind="directory",
            windows_cwd_limit=windows_cwd_limit,
        ),
        _path_status(field="temp_root", path=temp_root, expected_kind="directory", windows_cwd_limit=windows_cwd_limit),
        _path_status(field="output_dir", path=output_dir, expected_kind="directory", windows_cwd_limit=windows_cwd_limit),
    ]
    offending: list[dict[str, Any]] = []
    for status in statuses:
        expected_kind = status["expected_kind"]
        if expected_kind == "file" and not status["is_file"]:
            offending.append(
                {
                    "field": status["field"],
                    "path": status["path"],
                    "reason": "expected_existing_file",
                }
            )
        if expected_kind == "directory":
            if not status["is_directory"]:
                offending.append(
                    {
                        "field": status["field"],
                        "path": status["path"],
                        "reason": "expected_existing_directory",
                    }
                )
            elif not status["is_creatable"]:
                offending.append(
                    {
                        "field": status["field"],
                        "path": status["path"],
                        "reason": "directory_not_creatable",
                    }
                )
        if status["field"] == "cwd" and status.get("windows_createprocess_cwd_safe") is False:
            offending.append(
                {
                    "field": status["field"],
                    "path": status["path"],
                    "reason": "windows_createprocess_cwd_path_too_long",
                    "path_length": status["path_length"],
                    "limit": status["windows_createprocess_cwd_limit"],
                }
            )
    return {
        "record_kind": "pob_headless_worker_launch_path_diagnostics",
        "worker_module": _WORKER_MODULE,
        "paths": statuses,
        "offending_paths": offending,
    }


def validate_headless_worker_launch_paths(
    *,
    python_executable: str,
    cwd: Path,
    session_root: Path,
    temp_root: Path,
    output_dir: Path,
    windows_cwd_limit: int | None = None,
) -> dict[str, Any]:
    diagnostics = build_headless_worker_launch_path_diagnostics(
        python_executable=python_executable,
        worker_script_path=_resolved_worker_script_path(),
        cwd=cwd,
        session_root=session_root,
        temp_root=temp_root,
        output_dir=output_dir,
        windows_cwd_limit=windows_cwd_limit,
    )
    if diagnostics["offending_paths"]:
        _fail(
            "runtime_launch_path_invalid",
            "Headless PoB worker launch path validation failed: "
            + _offending_path_summary(diagnostics)
            + "; launch_path_diagnostics="
            + _diagnostic_json(diagnostics),
        )
    return diagnostics


class PinnedPoBHeadlessRuntimeAdapter:
    """Proof-loop adapter backed by a real pinned PoB worker process."""

    def __init__(
        self,
        *,
        release_manager: PoBReleaseManager | None = None,
        python_executable: str | None = None,
    ) -> None:
        self._release_manager = release_manager or PoBReleaseManager()
        self._python_executable = python_executable or sys.executable
        self._workers: dict[str, _WorkerProcess] = {}
        # #724: per handle ended by a protocol timeout, the first timeout text: the cleanup that calls the dead
        # handle next is refused with it, so the error a build records is the timeout and not "no live worker"
        self._dropped_workers: dict[str, str] = {}
        self._flask_flags_changed = False

    def take_flask_flags_changed(self) -> bool:
        """True when a worker reply since the last call said the Flask flags in the live build changed (#575: a stats
        read, a fast trial, an active-skill read or the export derives them from PoB's uptime); clears the mark."""

        changed, self._flask_flags_changed = self._flask_flags_changed, False
        return changed

    def launch_session(self, request: PoBHeadlessLaunchRequest) -> PoBHeadlessLaunchResult:
        guard_pob_launch()  # hard stop (#114): never start the real worker process under JUNKROAN_NO_POB
        runtime_root = self._resolve_runtime_root(request)
        wrapper_path = self._resolve_wrapper_path(request.wrapper_entrypoint_ref)
        self._validate_wrapper_path(wrapper_path)
        path_diagnostics = validate_headless_worker_launch_paths(
            python_executable=self._python_executable,
            cwd=request.session_root,
            session_root=request.session_root,
            temp_root=request.temp_root,
            output_dir=request.export_locator.parent,
        )

        command = (
            self._python_executable,
            "-m",
            _WORKER_MODULE,
            "--runtime-root",
            str(runtime_root),
            "--session-root",
            str(request.session_root),
            "--wrapper-path",
            str(wrapper_path),
            "--session-role",
            request.session_role,
        )
        if request.reopen_source_locator is not None:
            command = command + ("--reopen-source", str(request.reopen_source_locator))

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | _day_priority_flag()
        worker_env = dict(os.environ)
        worker_env["PYTHONPATH"] = os.pathsep.join(
            [str(_SOURCE_ROOT)] + [p for p in worker_env.get("PYTHONPATH", "").split(os.pathsep) if p]
        )
        try:
            process = subprocess.Popen(
                command,
                cwd=request.session_root,
                env=worker_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            _fail(
                "runtime_launch_failed",
                f"Could not start the headless PoB worker: {exc}; "
                f"launch_path_diagnostics={_diagnostic_json(path_diagnostics)}",
            )
            raise AssertionError from exc

        try:
            # #939: the ready wait is the command wait (#724): a starting worker whose CPU advances is waited for
            # up to _CPU_WAIT_CAP_INTERVALS intervals; one without CPU ends at the first limit.
            raw_ready = _readline_with_timeout(process.stdout, _WORKER_READY_TIMEOUT_SECONDS, process)
            ready_payload = _parse_worker_message(raw_ready, failure_state="runtime_protocol_failed")
            if ready_payload.get("status") != "ready":
                failure_state = str(ready_payload.get("failure_state") or "runtime_launch_failed")
                message = str(ready_payload.get("message") or "Headless PoB worker failed to start.")
                _fail(failure_state, message)
        except Exception:
            self._terminate_process(process)
            raise

        self._workers[request.process_instance_id] = _WorkerProcess(process=process, request=request)
        dependency_fingerprints = {
            "lua51_dll_sha256": sha256_file(runtime_root / "lua51.dll"),
            "headless_wrapper_sha256": sha256_file(wrapper_path),
            "runtime_manifest_sha256": sha256_file(runtime_root / "manifest.xml"),
        }
        return PoBHeadlessLaunchResult(
            os_pid=process.pid,
            command=command,
            cwd=request.session_root,
            dependency_fingerprints=dependency_fingerprints,
        )

    def create_blank_build(self, handle: PoBHeadlessSessionHandle) -> None:
        self._call_worker(handle, {"action": "create_blank_build"})

    def apply_identity_state(self, handle: PoBHeadlessSessionHandle, identity_payload: dict[str, Any]) -> None:
        self._call_worker(handle, {"action": "apply_identity_state", "identity_payload": dict(identity_payload)})

    def parse_mods(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "parse_mods", "request": dict(request)}, timeout_seconds=300.0))

    def uniques(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "uniques", "request": dict(request)}, timeout_seconds=120.0))

    def read_config_options(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "read_config_options", "request": dict(request)}))

    def list_bench_mods(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "list_bench_mods", "request": dict(request)}))

    def read_tree_light(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "read_tree_light", "request": dict(request)}))

    def convert_tree(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "convert_tree", "request": dict(request)}, timeout_seconds=120.0))

    def read_config_inputs(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "read_config_inputs", "request": dict(request)}))

    def unsupported_gems(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "unsupported_gems", "request": dict(request)}))

    def random_rares(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "random_rares", "request": dict(request)}, timeout_seconds=120.0))

    def equip_items(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "equip_items", "request": dict(request)}))

    def socket_jewels(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "socket_jewels", "request": dict(request)}))

    def cluster_graph(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "cluster_graph", "request": dict(request)}))

    def list_item_mods(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "list_item_mods", "request": dict(request)}))

    def craft_rare(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "craft_rare", "request": dict(request)}))

    def recraft(self, handle: PoBHeadlessSessionHandle, request: dict[str, Any]) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "recraft", "request": dict(request)}))

    def trial_stats(self, handle: PoBHeadlessSessionHandle, trial_payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate candidate allocations in one round trip; the build is left unchanged."""

        trial_count = len(trial_payload.get("trials") or ())
        result = self._worker_result(
            self._call_worker(
                handle,
                {"action": "trial_stats", "trial_payload": dict(trial_payload)},
                timeout_seconds=max(60.0, 0.5 * trial_count),
            )
        )
        return list(result.get("results") or [])

    def read_stats(self, handle: PoBHeadlessSessionHandle, keys: list[str] | None = None, parts: list[int] | None = None, keep_flask_flags: bool = False) -> dict[str, Any]:
        """Fast scalar stat read (recalcs if the build is dirty). See worker.read_stats."""

        return self._worker_result(self._call_worker(handle, {"action": "read_stats", "keys": list(keys) if keys else None, "parts": list(parts) if parts else None, **({"keep_flask_flags": True} if keep_flask_flags else {})}))

    def read_stats_uncapped(self, handle: PoBHeadlessSessionHandle, keys: list[str] | None = None, parts: list[int] | None = None) -> dict[str, Any]:
        """`read_stats` without D78's ailment-stack surfaces, in place. See worker.read_stats_uncapped."""

        return self._worker_result(self._call_worker(handle, {"action": "read_stats_uncapped", "keys": list(keys) if keys else None, "parts": list(parts) if parts else None}))

    def read_active_skill_stats(self, handle: PoBHeadlessSessionHandle, skill_ids: list[str], keys: list[str]) -> dict[str, dict[str, Any]]:
        """Calculated output for named active skill effects; the worker restores the selected skill."""

        result = self._worker_result(self._call_worker(handle, {"action": "read_active_skill_stats", "skill_ids": list(skill_ids), "keys": list(keys)}))
        return {str(skill_id): dict(values) for skill_id, values in result.items() if isinstance(values, dict)}

    def read_mana_cost_warnings(self, handle: PoBHeadlessSessionHandle) -> list[str]:
        result = self._worker_result(self._call_worker(handle, {"action": "read_mana_cost_warnings"}))
        return [str(name) for name in result.get("warnings") or []]

    def read_granted_passives(self, handle: PoBHeadlessSessionHandle) -> list[int]:
        result = self._worker_result(self._call_worker(handle, {"action": "read_granted_passives"}))
        return [int(n) for n in result.get("node_ids") or []]

    def mutate_tree_nodes(self, handle: PoBHeadlessSessionHandle, mutation_payload: dict[str, Any]) -> dict[str, Any]:
        """Incrementally add/remove passive nodes; returns the allocated set and point counts."""

        return self._worker_result(
            self._call_worker(handle, {"action": "mutate_tree_nodes", "mutation_payload": dict(mutation_payload)})
        )

    def load_build_xml(self, handle: PoBHeadlessSessionHandle, xml_text: str) -> None:
        """Replace the live build with a full PoB build XML (import path)."""

        self._call_worker(handle, {"action": "load_build_xml", "xml_text": xml_text})

    def apply_tree_state(self, handle: PoBHeadlessSessionHandle, tree_payload: dict[str, Any]) -> None:
        self._call_worker(handle, {"action": "apply_tree_state", "tree_payload": dict(tree_payload)})

    def apply_item_state(self, handle: PoBHeadlessSessionHandle, item_payload: dict[str, Any]) -> None:
        self._call_worker(handle, {"action": "apply_item_state", "item_payload": dict(item_payload)})

    def flask_uptimes(self, handle: PoBHeadlessSessionHandle) -> dict[str, dict[str, Any]]:
        return self._worker_result(self._call_worker(handle, {"action": "flask_uptimes"}))

    def set_flasks_active(self, handle: PoBHeadlessSessionHandle, flasks_active: dict[str, bool]) -> None:
        self._call_worker(handle, {"action": "set_flasks_active", "flasks_active": dict(flasks_active)})

    def apply_skill_state(self, handle: PoBHeadlessSessionHandle, skill_payload: dict[str, Any]) -> None:
        skill_payload = vaal_gem_flags(skill_payload)
        self._call_worker(handle, {"action": "apply_skill_state", "skill_payload": dict(skill_payload)})

    def apply_config_state(self, handle: PoBHeadlessSessionHandle, config_payload: dict[str, Any]) -> None:
        self._call_worker(handle, {"action": "apply_config_state", "config_payload": dict(config_payload)})

    def checkpoint_config(self, handle: PoBHeadlessSessionHandle) -> None:
        self._call_worker(handle, {"action": "checkpoint_config"})

    def rollback_config(self, handle: PoBHeadlessSessionHandle) -> None:
        self._call_worker(handle, {"action": "rollback_config"})

    def read_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _normalize_unified_state_payload(
            self._worker_result(self._call_worker(handle, {"action": "read_state"})),
            failure_state="runtime_protocol_failed",
        )

    def read_blank_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _legacy_minimal_state_payload(
            self._worker_result(self._call_worker(handle, {"action": "read_state"})),
            failure_state="runtime_protocol_failed",
        )

    def read_calc_snapshot(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return self._worker_result(
            self._call_worker(handle, {"action": "read_calc_snapshot"})
        )

    def read_node_power_report(
        self,
        handle: PoBHeadlessSessionHandle,
        node_power_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        request = dict(node_power_request or {})
        return _native_node_power_report_result(
            self._worker_result(
                self._call_worker(
                    handle,
                    {"action": "read_node_power_report", "node_power_request": request},
                    timeout_seconds=_WORKER_NODE_POWER_TIMEOUT_SECONDS,
                )
            )
        )

    def read_ascendancy_node_report(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return self._worker_result(self._call_worker(handle, {"action": "read_ascendancy_node_report"}))

    def equip_item(
        self,
        handle: PoBHeadlessSessionHandle,
        prepared_item_ref: str,
        normalized_item: dict[str, Any],
    ) -> None:
        # The accepted proof slice has exactly one item contract. The worker
        # materializes the pinned PoB-valid raw item text that normalizes back
        # to the prepared proof payload.
        if normalized_item.get("slot") != "Boots":
            _fail("invalid_boots_item", "The real headless adapter only supports the accepted Boots proof item.")
        self._call_worker(handle, {"action": "equip_boots_item", "prepared_item_ref": prepared_item_ref})

    def read_equipped_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _legacy_minimal_state_payload(
            self._worker_result(self._call_worker(handle, {"action": "read_state"})),
            failure_state="runtime_protocol_failed",
        )

    def export_build_artifact(self, handle: PoBHeadlessSessionHandle) -> str:
        payload = self._call_worker(handle, {"action": "export_build_xml"})
        result = payload.get("result")
        if not isinstance(result, str) or not result.strip():
            _fail("missing_export_payload", "Headless PoB worker did not return a non-empty XML export.")
        return result

    def verify_pob_import_code_string(self, handle: PoBHeadlessSessionHandle, import_code: str) -> dict[str, Any]:
        if not isinstance(import_code, str):
            _fail("runtime_protocol_failed", "import_code must be a string.")
        return _native_import_code_string_result(
            self._worker_result(
                self._call_worker(
                    handle,
                    {"action": "verify_pob_import_code_string", "import_code": import_code},
                )
            ),
            import_code=import_code,
        )

    def read_reopened_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _normalize_unified_state_payload(self.read_state(handle), failure_state="runtime_protocol_failed")

    def shutdown_session(self, handle: PoBHeadlessSessionHandle) -> PoBHeadlessSessionShutdown:
        worker = self._require_worker(handle, "shutdown")
        if worker.process.poll() is None:
            try:
                payload = self._call_worker(handle, {"action": "shutdown"}, timeout_seconds=_WORKER_SHUTDOWN_TIMEOUT_SECONDS)
                termination = str(payload.get("termination") or "process_exit_observed")
                worker.process.wait(timeout=_WORKER_SHUTDOWN_TIMEOUT_SECONDS)
                exit_code = worker.process.returncode if worker.process.returncode is not None else 0
                return PoBHeadlessSessionShutdown(exit_code=exit_code, termination=termination)
            except Exception:
                self._terminate_process(worker.process)
                raise
            finally:
                self._workers.pop(handle.process_instance_id, None)

        exit_code = worker.process.returncode if worker.process.returncode is not None else 0
        self._workers.pop(handle.process_instance_id, None)
        return PoBHeadlessSessionShutdown(exit_code=exit_code, termination="process_exit_observed")

    def close(self) -> None:
        for process_instance_id in list(self._workers):
            worker = self._workers.pop(process_instance_id)
            self._terminate_process(worker.process)

    def _resolve_runtime_root(self, request: PoBHeadlessLaunchRequest) -> Path:
        fetch_report = self._release_manager.fetch()
        verify_report = self._release_manager.verify()
        lock_fingerprint = sha256_file(self._release_manager.lock_path)

        if request.pinned_pob_release_ref.lock_fingerprint != lock_fingerprint:
            _fail(
                "runtime_dependency_mismatch",
                "Pinned PoB lock fingerprint drifted away from the launch request receipt.",
            )
        if request.pinned_pob_release_ref.tag != verify_report.tag:
            _fail(
                "runtime_dependency_mismatch",
                "Pinned PoB tag drifted away from the launch request receipt.",
            )

        runtime_root = fetch_report.extract_dir.resolve(strict=False)
        required_paths = (
            runtime_root / "lua51.dll",
            runtime_root / "Launch.lua",
            runtime_root / "manifest.xml",
        )
        missing = [str(path) for path in required_paths if not path.is_file()]
        if missing or not verify_report.extracted_runtime_present:
            _fail(
                "runtime_dependency_missing",
                "Pinned PoB runtime is not fully materialized for headless launch: " + ", ".join(missing),
            )
        return runtime_root

    def _resolve_wrapper_path(self, wrapper_entrypoint_ref: str) -> Path:
        candidate = Path(wrapper_entrypoint_ref)
        if candidate.is_absolute():
            return candidate.resolve(strict=False)
        return (PROJECT_ROOT / candidate).resolve(strict=False)

    def _validate_wrapper_path(self, wrapper_path: Path) -> None:
        if not wrapper_path.is_file():
            _fail("runtime_entrypoint_missing", f"Headless wrapper entrypoint is missing: {wrapper_path}")

    def _require_worker(self, handle: PoBHeadlessSessionHandle, action: str = "?") -> _WorkerProcess:
        worker = self._workers.get(handle.process_instance_id)
        if worker is None:
            first_timeout = self._dropped_workers.get(handle.process_instance_id)
            if first_timeout is not None:
                _fail(
                    "unknown_session",
                    f"{first_timeout} (the worker was ended by that failure; later call {action}"
                    f" on {handle.process_instance_id} refused)",
                )
            _fail("unknown_session", f"No live headless PoB worker exists for {handle.process_instance_id}.")
        return worker

    def _call_worker(
        self,
        handle: PoBHeadlessSessionHandle,
        payload: dict[str, Any],
        *,
        timeout_seconds: float = _WORKER_COMMAND_TIMEOUT_SECONDS,
    ) -> dict[str, Any]:
        worker = self._require_worker(handle, str(payload.get("action")))
        if worker.process.poll() is not None:
            self._drop_dead_worker(
                handle, worker, str(payload.get("action")), "runtime_exited_early",
                f"Headless PoB worker exited before action {payload.get('action')!r} could complete.",
            )
        if worker.process.stdin is None or worker.process.stdout is None:
            _fail("runtime_protocol_failed", "Headless PoB worker pipes are not available.")

        call_name = str(payload.get("action"))
        trial_list = (payload.get("trial_payload") or {}).get("trials") if isinstance(payload.get("trial_payload"), dict) else None
        trial_count = len(trial_list) if trial_list is not None else None
        pid = worker.process.pid
        started = time.monotonic()
        try:
            worker.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            worker.process.stdin.flush()
        except (OSError, ValueError) as exc:
            # #805: the worker is gone (a dead pipe); end it like a timed-out one so the first text is the one kept
            self._drop_dead_worker(
                handle, worker, call_name, "runtime_protocol_failed",
                f"Headless PoB worker pipe is broken ({type(exc).__name__}: {exc}).", cause=exc,
            )
        try:
            raw_response = _readline_with_timeout(worker.process.stdout, timeout_seconds, worker.process)
        except PoBHeadlessHostContractError as exc:
            elapsed = time.monotonic() - started
            _log_slow_call(call_name, trial_count, timeout_seconds, elapsed, pid)
            # The protocol is now desynced (the reply may still arrive later):
            # kill the worker so no later call reads a stale message.
            self._terminate_process(worker.process)
            self._workers.pop(handle.process_instance_id, None)
            if exc.failure_state != "runtime_protocol_timeout":
                raise
            trials_text = f", trials {trial_count}" if trial_count is not None else ""
            timeout_message = (
                f"{exc.args[0] if exc.args else 'Timed out waiting for the headless PoB worker protocol.'}"
                f" Call {call_name}{trials_text}, limit {human_duration(timeout_seconds)},"
                f" elapsed {human_duration(elapsed)}."
            )
            self._dropped_workers.setdefault(handle.process_instance_id, timeout_message)
            raise PoBHeadlessHostContractError("runtime_protocol_timeout", timeout_message) from exc
        _log_slow_call(call_name, trial_count, timeout_seconds, time.monotonic() - started, pid)
        if raw_response == "":  # stdout hit EOF: the worker died (#805)
            self._drop_dead_worker(
                handle, worker, call_name, "runtime_protocol_failed",
                "Headless PoB worker returned an empty protocol message.",
            )
        response = _parse_worker_message(raw_response, failure_state="runtime_protocol_failed")
        if response.get("flask_flags_changed") is True:
            self._flask_flags_changed = True
        if response.get("ok") is not True:
            failure_state = str(response.get("failure_state") or "runtime_protocol_failed")
            message = str(response.get("message") or "Headless PoB worker returned an error.")
            _fail(failure_state, message)
        return response

    def _drop_dead_worker(
        self,
        handle: PoBHeadlessSessionHandle,
        worker: _WorkerProcess,
        call_name: str,
        failure_state: str,
        message: str,
        *,
        cause: BaseException | None = None,
    ) -> None:
        """#805: a worker that died (EOF, a dead pipe, exited before the call) is ended like a timed-out one: the
        process terminated, the handle popped, the first text (with the call, the exit code and the last stderr
        lines) stored so a later call on the handle is refused with it, and that text raised."""

        process = worker.process
        try:
            exit_code: int | None = process.wait(timeout=_DEAD_WORKER_EXIT_WAIT_SECONDS)
        except Exception:
            exit_code = None
        self._terminate_process(process)
        self._workers.pop(handle.process_instance_id, None)
        exit_text = f"exit code {exit_code}" if exit_code is not None else "exit code unknown (still running when ended)"
        text = f"{message} Call {call_name}, worker {exit_text}."
        tail = _stderr_tail(process)
        if tail:
            text += f" Worker stderr, last lines: {tail}"
        self._dropped_workers.setdefault(handle.process_instance_id, text)
        raise PoBHeadlessHostContractError(failure_state, text) from cause

    def _worker_result(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = payload.get("result")
        if not isinstance(result, dict):
            _fail("runtime_protocol_failed", "Headless PoB worker did not return an object state payload.")
        return result

    def _terminate_process(self, process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=_WORKER_SHUTDOWN_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=_WORKER_SHUTDOWN_TIMEOUT_SECONDS)


class PoBHeadlessCallbackRuntimeAdapter:
    """Compatibility adapter for the explicit callback harness used in tests."""

    def __init__(self, callbacks: Any) -> None:
        self._callbacks = callbacks

    def launch_session(self, request: PoBHeadlessLaunchRequest) -> PoBHeadlessLaunchResult:
        return self._callbacks.launcher(request)

    def create_blank_build(self, handle: PoBHeadlessSessionHandle) -> None:
        self._callbacks.create_blank_build(handle)

    def apply_identity_state(self, handle: PoBHeadlessSessionHandle, identity_payload: dict[str, Any]) -> None:
        callback = getattr(self._callbacks, "apply_identity_state", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement apply_identity_state.")
        callback(handle, identity_payload)

    def apply_tree_state(self, handle: PoBHeadlessSessionHandle, tree_payload: dict[str, Any]) -> None:
        callback = getattr(self._callbacks, "apply_tree_state", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement apply_tree_state.")
        callback(handle, tree_payload)

    def apply_item_state(self, handle: PoBHeadlessSessionHandle, item_payload: dict[str, Any]) -> None:
        callback = getattr(self._callbacks, "apply_item_state", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement apply_item_state.")
        callback(handle, item_payload)

    def apply_skill_state(self, handle: PoBHeadlessSessionHandle, skill_payload: dict[str, Any]) -> None:
        callback = getattr(self._callbacks, "apply_skill_state", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement apply_skill_state.")
        callback(handle, vaal_gem_flags(skill_payload))

    def apply_config_state(self, handle: PoBHeadlessSessionHandle, config_payload: dict[str, Any]) -> None:
        callback = getattr(self._callbacks, "apply_config_state", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement apply_config_state.")
        callback(handle, config_payload)

    def read_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        callback = getattr(self._callbacks, "read_state", None)
        if callback is not None:
            return _normalize_unified_state_payload(callback(handle), failure_state="runtime_protocol_failed")
        return _normalize_unified_state_payload(
            self._callbacks.read_equipped_state(handle),
            failure_state="runtime_protocol_failed",
        )

    def read_blank_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _legacy_minimal_state_payload(
            self._callbacks.read_blank_state(handle),
            failure_state="runtime_protocol_failed",
        )

    def read_calc_snapshot(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        callback = getattr(self._callbacks, "read_calc_snapshot", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement read_calc_snapshot.")
        result = callback(handle)
        if not isinstance(result, dict):
            _fail("runtime_protocol_failed", "Callback runtime read_calc_snapshot must return an object payload.")
        return dict(result)

    def read_node_power_report(
        self,
        handle: PoBHeadlessSessionHandle,
        node_power_request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        callback = getattr(self._callbacks, "read_node_power_report", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement read_node_power_report.")
        return _native_node_power_report_result(callback(handle, dict(node_power_request or {})))

    def read_ascendancy_node_report(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        callback = getattr(self._callbacks, "read_ascendancy_node_report", None)
        if callback is None:
            _fail("runtime_protocol_failed", "Callback runtime does not implement read_ascendancy_node_report.")
        result = callback(handle)
        if not isinstance(result, dict):
            _fail("runtime_protocol_failed", "Callback runtime read_ascendancy_node_report must return an object payload.")
        return dict(result)

    def equip_item(
        self,
        handle: PoBHeadlessSessionHandle,
        prepared_item_ref: str,
        normalized_item: dict[str, Any],
    ) -> None:
        self._callbacks.equip_item(handle, prepared_item_ref, normalized_item)

    def read_equipped_state(self, handle: PoBHeadlessSessionHandle) -> dict[str, Any]:
        return _legacy_minimal_state_payload(
            self._callbacks.read_equipped_state(handle),
            failure_state="runtime_protocol_failed",
        )

    def export_build_artifact(self, handle: PoBHeadlessSessionHandle) -> str | bytes:
        return self._callbacks.export_build_artifact(handle)

    def verify_pob_import_code_string(self, handle: PoBHeadlessSessionHandle, import_code: str) -> dict[str, Any]:
        return _native_import_code_string_result(
            self._callbacks.verify_pob_import_code_string(handle, import_code),
            import_code=import_code,
        )

    def read_reopened_state(self, handle: PoBHeadlessSessionHandle) -> Any:
        result = self._callbacks.read_reopened_state(handle)
        if isinstance(result, dict):
            return _normalize_unified_state_payload(result, failure_state="runtime_protocol_failed")
        return result

    def shutdown_session(self, handle: PoBHeadlessSessionHandle) -> PoBHeadlessSessionShutdown:
        return PoBHeadlessSessionShutdown(exit_code=0, termination="process_exit_observed")

    def close(self) -> None:
        return None


__all__ = [
    "POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND",
    "POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION",
    "POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND",
    "POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH",
    "PinnedPoBHeadlessRuntimeAdapter",
    "PoBHeadlessCallbackRuntimeAdapter",
    "PoBHeadlessSessionShutdown",
]


def _native_node_power_report_result(raw_result: Any) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        _fail("runtime_protocol_failed", "Native node-power report result must be an object.")
    result = dict(raw_result)
    forbidden = sorted(field for field in _FORBIDDEN_NODE_POWER_PAYLOAD_FIELDS if field in result)
    if forbidden:
        _fail(
            "publication_boundary_failed",
            "Native node-power report result must not carry publication payload field(s): " + ", ".join(forbidden),
        )

    result.setdefault("schema_version", POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION)
    result.setdefault("record_kind", POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND)
    result.setdefault("source_kind", POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND)
    result.setdefault("supported_path", POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH)
    if result.get("schema_version") != POB_HEADLESS_NODE_POWER_REPORT_SCHEMA_VERSION:
        _fail("runtime_protocol_failed", "Native node-power report schema_version is unsupported.")
    if result.get("record_kind") != POB_HEADLESS_NODE_POWER_REPORT_RECORD_KIND:
        _fail("runtime_protocol_failed", "Native node-power report record_kind is unsupported.")
    if result.get("source_kind") != POB_NATIVE_NODE_POWER_REPORT_SOURCE_KIND:
        _fail("runtime_protocol_failed", "Native node-power report source_kind is unsupported.")
    if result.get("supported_path") != POB_NATIVE_NODE_POWER_REPORT_SUPPORTED_PATH:
        _fail("runtime_protocol_failed", "Native node-power report supported_path is unsupported.")

    status = _string_value(result.get("status"))
    if status not in _NODE_POWER_REPORT_STATUSES:
        _fail("runtime_protocol_failed", "Native node-power report status must be accepted or unavailable.")
    rows = result.get("rows")
    if not isinstance(rows, list):
        _fail("runtime_protocol_failed", "Native node-power report rows must be an array.")
    normalized_rows = [_normalize_node_power_row(row, index=index) for index, row in enumerate(rows)]
    result["rows"] = normalized_rows
    result["row_count"] = len(normalized_rows)

    selected_metric = result.get("selected_metric")
    if not isinstance(selected_metric, dict):
        _fail("runtime_protocol_failed", "Native node-power report selected_metric must be an object.")
    metric_name = _string_value(selected_metric.get("stat"))
    if not metric_name and status == "accepted":
        _fail("runtime_protocol_failed", "Accepted native node-power report selected_metric.stat must be non-empty.")
    if not isinstance(result.get("source_refs"), list) or not result["source_refs"]:
        _fail("runtime_protocol_failed", "Native node-power report must include source_refs.")
    result["source_refs"] = [_normalize_proof_ref(ref, field_name="source_refs[]") for ref in result["source_refs"]]
    result["limitations"] = _string_list(result.get("limitations"))
    result["unavailable_metrics"] = _string_list(result.get("unavailable_metrics"))
    if status == "unavailable" and not result["limitations"]:
        _fail("runtime_protocol_failed", "Unavailable native node-power report must include limitations.")
    return result


def _normalize_node_power_row(row: Any, *, index: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        _fail("runtime_protocol_failed", "Native node-power report rows must be objects.")
    item = dict(row)
    required = ("row_id", "source_id", "node_name", "target_kind", "metric_lane", "metric_name", "metric_label", "source_locator")
    missing = [field for field in required if not _string_value(item.get(field))]
    if missing:
        _fail("runtime_protocol_failed", "Native node-power report row is missing field(s): " + ", ".join(missing))
    if _optional_int(item.get("node_id")) is None:
        _fail("runtime_protocol_failed", "Native node-power report row.node_id must be an integer.")
    if _optional_float(item.get("node_power_score")) is None:
        _fail("runtime_protocol_failed", "Native node-power report row.node_power_score must be numeric.")
    path_power = _optional_float(item.get("path_power_score"))
    if path_power is None and item.get("path_power_score") is not None:
        _fail("runtime_protocol_failed", "Native node-power report row.path_power_score must be numeric or null.")
    item["row_index"] = index
    item["node_id"] = int(item["node_id"])
    item["node_power_score"] = float(item["node_power_score"])
    item["path_power_score"] = path_power
    item["stats_or_supporting_text"] = _string_list(item.get("stats_or_supporting_text"))
    item["metric_tags"] = _string_list(item.get("metric_tags"))
    item["facets"] = item.get("facets") if isinstance(item.get("facets"), list) else []
    item["matched_branch_axes"] = item.get("matched_branch_axes") if isinstance(item.get("matched_branch_axes"), list) else []
    if not isinstance(item.get("source_context"), dict):
        item["source_context"] = {}
    return item


def _normalize_proof_ref(value: Any, *, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        _fail("runtime_protocol_failed", f"{field_name} must be an object.")
    ref = {
        "ref_id": _string_value(value.get("ref_id")),
        "ref_kind": _string_value(value.get("ref_kind")),
        "locator": _string_value(value.get("locator")),
        "json_pointer": _string_value(value.get("json_pointer")),
        "summary": _string_value(value.get("summary")),
    }
    missing = [key for key, current in ref.items() if not current]
    if missing:
        _fail("runtime_protocol_failed", f"{field_name} is missing field(s): " + ", ".join(missing))
    return ref


def _native_import_code_string_result(raw_result: Any, *, import_code: str) -> dict[str, Any]:
    if not isinstance(raw_result, dict):
        _fail("runtime_protocol_failed", "Native import-code verifier result must be an object.")
    if not isinstance(import_code, str):
        _fail("runtime_protocol_failed", "import_code must be a string.")
    result = dict(raw_result)
    result.pop("import_code", None)
    result.pop("payload", None)
    result.pop("literal_payload", None)
    import_code_valid = result.get("import_code_valid") is True
    native_semantics_valid = result.get("native_pob_import_string_semantics_valid") is True
    accepted = import_code_valid and native_semantics_valid and _string_value(result.get("status")) == "accepted"
    missing_inputs = _string_list(result.get("missing_inputs"))
    invalid_reasons = _string_list(result.get("invalid_reasons"))
    if not accepted and not invalid_reasons and not missing_inputs:
        invalid_reasons = ["native_import_code_invalid"]
    return {
        "status": "accepted" if accepted else "invalid",
        "payload_sha256": hashlib.sha256(import_code.encode("utf-8")).hexdigest(),
        "proof_kind": _NATIVE_POB_IMPORT_STRING_PROOF_KIND,
        "surface_kind": _NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
        "import_code_valid": import_code_valid,
        "native_pob_import_string_semantics_valid": native_semantics_valid,
        "import_code_detail": _string_value(result.get("import_code_detail")),
        "decoded_xml_char_count": _int_or_zero(result.get("decoded_xml_char_count")),
        "imported_build_active": result.get("imported_build_active") is True,
        "missing_inputs": missing_inputs,
        "invalid_reasons": [] if accepted else invalid_reasons,
    }


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    return None
