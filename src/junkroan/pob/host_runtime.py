"""Headless PoB proof host runtime surfaces for bootstrap, launch, and teardown."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from uuid import uuid4

from .artifacts import DEFAULT_RUNS_ROOT, sha256_bytes, sha256_file, validate_token, write_json
from .release_manager import PoBReleaseManager, utc_now_iso

HEADLESS_PROOF_CONTRACT_NAME = "pob_headless_proof_runtime"
HEADLESS_PROOF_CONTRACT_VERSION = "1.0.0"
HEADLESS_PROOF_SLICE = "minimal_boots_only"
HEADLESS_PROOF_SUPPORTED_PATH = "pob_headless_proof_host_runtime_v1"

SessionRole = Literal["normal", "reopen"]
ExportSurfaceKind = Literal["pob_xml", "pob_string", "pob_import_bundle"]

_SESSION_ROLES: tuple[SessionRole, ...] = ("normal", "reopen")
_EXPORT_SURFACE_FILENAMES: dict[ExportSurfaceKind, str] = {
    "pob_xml": "ready-pob-import.xml",
    "pob_string": "ready-pob-import.txt",
    "pob_import_bundle": "ready-pob-import",
}
_RECEIPT_STATE_BOOTSTRAP_WRITTEN = "bootstrap_written"
_RECEIPT_STATE_LAUNCH_RECORDED = "launch_recorded"
_RECEIPT_STATE_TEARDOWN_SEALED = "teardown_sealed"
_TEARDOWN_STATUS_BOOTSTRAP_PENDING = "bootstrap_pending"
_TEARDOWN_STATUS_PROCESS_LIVE = "process_live"
_TEARDOWN_STATUS_SEALED_PROCESS_EXIT_OBSERVED = "sealed_process_exit_observed"


class PoBHeadlessHostContractError(RuntimeError):
    """Raised when the headless PoB proof host contract fails closed."""

    def __init__(self, failure_state: str, message: str) -> None:
        super().__init__(message)
        self.failure_state = failure_state


def _require_non_empty_string(value: str, field_name: str, failure_state: str = "invalid_request") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PoBHeadlessHostContractError(failure_state, f"{field_name} must be a non-empty string.")
    return value.strip()


def _path_string(path: Path) -> str:
    return path.resolve(strict=False).as_posix()


def _load_json_object(path: Path, *, failure_state: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PoBHeadlessHostContractError(failure_state, f"JSON surface is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PoBHeadlessHostContractError(failure_state, f"JSON surface is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise PoBHeadlessHostContractError(failure_state, f"JSON surface must decode to an object: {path}")
    return payload


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _validate_session_role(value: str) -> SessionRole:
    role = _require_non_empty_string(value, "session_role")
    if role not in _SESSION_ROLES:
        raise PoBHeadlessHostContractError(
            "invalid_session_role",
            f"session_role must be one of {', '.join(_SESSION_ROLES)}.",
        )
    return role


def _validate_export_surface_kind(value: str) -> ExportSurfaceKind:
    normalized = _require_non_empty_string(value, "export_surface_kind")
    if normalized not in _EXPORT_SURFACE_FILENAMES:
        raise PoBHeadlessHostContractError(
            "invalid_export_surface_kind",
            f"export_surface_kind must be one of {', '.join(sorted(_EXPORT_SURFACE_FILENAMES))}.",
        )
    return normalized  # type: ignore[return-value]


def _process_instance_id(session_role: SessionRole, existing_ids: set[str]) -> str:
    while True:
        candidate = f"process.{session_role}.{uuid4().hex}"
        if candidate not in existing_ids:
            return candidate


@dataclass(frozen=True, slots=True)
class PoBPinnedReleaseRef:
    """Pinned PoB release reference recorded into the run manifest and receipts."""

    lock_path: Path
    repo: str
    tag: str
    asset_name: str
    asset_sha256: str
    lock_fingerprint: str

    def to_dict(self) -> dict[str, str]:
        return {
            "lock_path": _path_string(self.lock_path),
            "repo": self.repo,
            "tag": self.tag,
            "asset_name": self.asset_name,
            "asset_sha256": self.asset_sha256,
            "lock_fingerprint": self.lock_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class PoBHeadlessHostRequest:
    """Inputs required to allocate one headless proof run root."""

    pob_run_id: str
    export_surface_kind: ExportSurfaceKind
    wrapper_entrypoint_ref: str
    runtime_substrate: str = "headless_only"
    visible_gui_fallback: bool = False
    shared_desktop_fallback: bool = False

    def __post_init__(self) -> None:
        try:
            validate_token(self.pob_run_id, "pob_run_id")
        except RuntimeError as exc:
            raise PoBHeadlessHostContractError("invalid_request", str(exc)) from exc
        _validate_export_surface_kind(self.export_surface_kind)
        _require_non_empty_string(self.wrapper_entrypoint_ref, "wrapper_entrypoint_ref")
        if self.runtime_substrate != "headless_only":
            raise PoBHeadlessHostContractError(
                "visible_gui_fallback_forbidden",
                "runtime_substrate must stay headless_only for the accepted proof slice.",
            )
        if self.visible_gui_fallback:
            raise PoBHeadlessHostContractError(
                "visible_gui_fallback_forbidden",
                "Visible GUI fallback is out of contract for the accepted headless runtime lane.",
            )
        if self.shared_desktop_fallback:
            raise PoBHeadlessHostContractError(
                "shared_desktop_fallback_forbidden",
                "Shared-desktop fallback is out of contract for the accepted headless runtime lane.",
            )


@dataclass(frozen=True, slots=True)
class PoBHeadlessReopenSource:
    """Durable reopen input captured from the normal session boundary."""

    export_locator: Path
    export_payload_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.export_locator, Path):
            raise PoBHeadlessHostContractError("invalid_request", "export_locator must be a Path.")
        if self.export_payload_hash is not None:
            _require_non_empty_string(self.export_payload_hash, "export_payload_hash")


@dataclass(frozen=True, slots=True)
class PoBHeadlessManifestPaths:
    """Exact durable manifest paths for one proof run."""

    run_manifest_path: Path
    primary_proof_path: Path
    live_control_result_path: Path
    workspace_manifest_path: Path
    next_run_handoff_path: Path


@dataclass(frozen=True, slots=True)
class PoBHeadlessSessionLayout:
    """Exact durable paths for one isolated session root."""

    session_role: SessionRole
    session_root: Path
    temp_root: Path
    session_receipt_path: Path


@dataclass(frozen=True, slots=True)
class PoBHeadlessRunLayout:
    """Stable durable layout for one headless proof run."""

    pob_run_id: str
    run_root: Path
    exports_root: Path
    export_locator: Path
    sessions_root: Path
    manifest_paths: PoBHeadlessManifestPaths

    def session(self, session_role: SessionRole) -> PoBHeadlessSessionLayout:
        session_root = self.sessions_root / session_role
        return PoBHeadlessSessionLayout(
            session_role=session_role,
            session_root=session_root,
            temp_root=session_root / "temp",
            session_receipt_path=session_root / "session-receipt.json",
        )


@dataclass(frozen=True, slots=True)
class PoBHeadlessSessionReceipt:
    """Typed receipt surface persisted for one isolated headless session."""

    pob_run_id: str
    session_role: SessionRole
    process_instance_id: str
    os_pid: int | None
    session_root: Path
    temp_root: Path
    fresh_process: bool
    fresh_workspace: bool
    recompute_events: tuple[dict[str, Any], ...]
    teardown_status: str
    receipt_state: str
    bootstrap_created_at: str
    export_locator: Path | None = None
    export_payload_hash: str | None = None
    blank_state_verified: bool | None = None
    reopen_source_locator: Path | None = None
    reopen_source_hash: str | None = None
    parity_verified: bool | None = None
    launched_at: str | None = None
    sealed_at: str | None = None
    dependency_fingerprints: dict[str, str] = field(default_factory=dict)
    launch_command: tuple[str, ...] = ()
    launch_cwd: Path | None = None
    process_exit_observed: bool = False
    exit_code: int | None = None
    termination: str | None = None
    clean_session_marker: dict[str, Any] = field(default_factory=dict)

    def with_launch(
        self,
        *,
        os_pid: int,
        launched_at: str,
        dependency_fingerprints: dict[str, str],
        launch_command: tuple[str, ...],
        launch_cwd: Path,
    ) -> "PoBHeadlessSessionReceipt":
        return replace(
            self,
            os_pid=os_pid,
            launched_at=launched_at,
            dependency_fingerprints=dict(dependency_fingerprints),
            launch_command=tuple(launch_command),
            launch_cwd=launch_cwd,
            receipt_state=_RECEIPT_STATE_LAUNCH_RECORDED,
            teardown_status=_TEARDOWN_STATUS_PROCESS_LIVE,
        )

    def with_teardown(
        self,
        *,
        sealed_at: str,
        teardown_status: str,
        process_exit_observed: bool,
        exit_code: int,
        termination: str,
    ) -> "PoBHeadlessSessionReceipt":
        return replace(
            self,
            sealed_at=sealed_at,
            teardown_status=teardown_status,
            receipt_state=_RECEIPT_STATE_TEARDOWN_SEALED,
            process_exit_observed=process_exit_observed,
            exit_code=exit_code,
            termination=termination,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pob_run_id": self.pob_run_id,
            "session_role": self.session_role,
            "process_instance_id": self.process_instance_id,
            "os_pid": self.os_pid,
            "session_root": _path_string(self.session_root),
            "temp_root": _path_string(self.temp_root),
            "fresh_process": self.fresh_process,
            "fresh_workspace": self.fresh_workspace,
            "recompute_events": list(self.recompute_events),
            "teardown_status": self.teardown_status,
            "receipt_state": self.receipt_state,
            "bootstrap_created_at": self.bootstrap_created_at,
            "launched_at": self.launched_at,
            "sealed_at": self.sealed_at,
            "dependency_fingerprints": dict(self.dependency_fingerprints),
            "launch_command": list(self.launch_command),
            "launch_cwd": None if self.launch_cwd is None else _path_string(self.launch_cwd),
            "process_exit_observed": self.process_exit_observed,
            "exit_code": self.exit_code,
            "termination": self.termination,
            "clean_session_marker": dict(self.clean_session_marker),
        }
        if self.session_role == "normal":
            payload.update(
                {
                    "blank_state_verified": bool(self.blank_state_verified),
                    "export_locator": None if self.export_locator is None else _path_string(self.export_locator),
                    "export_payload_hash": self.export_payload_hash,
                }
            )
        else:
            payload.update(
                {
                    "reopen_source_locator": (
                        None if self.reopen_source_locator is None else _path_string(self.reopen_source_locator)
                    ),
                    "reopen_source_hash": self.reopen_source_hash,
                    "parity_verified": bool(self.parity_verified),
                }
            )
        return payload


@dataclass(frozen=True, slots=True)
class PoBHeadlessLaunchRequest:
    """Typed launch boundary passed to the actual PoB process launcher."""

    pob_run_id: str
    session_role: SessionRole
    process_instance_id: str
    run_root: Path
    session_root: Path
    temp_root: Path
    export_surface_kind: ExportSurfaceKind
    export_locator: Path
    session_receipt_path: Path
    run_manifest_path: Path
    primary_proof_path: Path
    live_control_result_path: Path
    workspace_manifest_path: Path
    next_run_handoff_path: Path
    pinned_pob_release_ref: PoBPinnedReleaseRef
    wrapper_entrypoint_ref: str
    reopen_source_locator: Path | None = None
    reopen_source_hash: str | None = None


@dataclass(frozen=True, slots=True)
class PoBHeadlessLaunchResult:
    """Observed process launch boundary for one headless session."""

    os_pid: int
    command: tuple[str, ...]
    cwd: Path
    dependency_fingerprints: dict[str, str] = field(default_factory=dict)
    visible_gui_required: bool = False
    shared_desktop_assumed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.os_pid, int) or self.os_pid <= 0:
            raise PoBHeadlessHostContractError("invalid_launch_result", "os_pid must be a positive integer.")
        if not self.command or any(not isinstance(part, str) or not part.strip() for part in self.command):
            raise PoBHeadlessHostContractError(
                "invalid_launch_result",
                "command must contain at least one non-empty launch token.",
            )
        if not isinstance(self.cwd, Path):
            raise PoBHeadlessHostContractError("invalid_launch_result", "cwd must be a Path.")


@dataclass(slots=True)
class PoBHeadlessSessionHandle:
    """Typed runtime surface for one bootstraped or launched headless session."""

    pob_run_id: str
    session_role: SessionRole
    process_instance_id: str
    run_layout: PoBHeadlessRunLayout
    session_layout: PoBHeadlessSessionLayout
    manifest_paths: PoBHeadlessManifestPaths
    export_locator: Path
    receipt: PoBHeadlessSessionReceipt
    reopen_source: PoBHeadlessReopenSource | None = None

    @property
    def run_root(self) -> Path:
        return self.run_layout.run_root

    @property
    def session_root(self) -> Path:
        return self.session_layout.session_root

    @property
    def temp_root(self) -> Path:
        return self.session_layout.temp_root

    @property
    def session_receipt_path(self) -> Path:
        return self.session_layout.session_receipt_path

    @property
    def os_pid(self) -> int | None:
        return self.receipt.os_pid


@dataclass(slots=True)
class PoBHeadlessProofRun:
    """Canonical headless proof run owner for bootstrap, launch, and teardown."""

    request: PoBHeadlessHostRequest
    layout: PoBHeadlessRunLayout
    release_ref: PoBPinnedReleaseRef
    sessions: dict[SessionRole, PoBHeadlessSessionHandle] = field(default_factory=dict)
    active_session_role: SessionRole | None = None

    def bootstrap_session(
        self,
        session_role: SessionRole,
        *,
        reopen_source: PoBHeadlessReopenSource | None = None,
        bootstrapped_at: str | None = None,
    ) -> PoBHeadlessSessionHandle:
        role = _validate_session_role(session_role)
        self._ensure_run_surfaces_exist()
        if self.active_session_role is not None:
            raise PoBHeadlessHostContractError(
                "same_process_reuse_forbidden",
                f"Cannot bootstrap {role} while {self.active_session_role} is still active.",
            )
        session_layout = self.layout.session(role)
        if role in self.sessions or session_layout.session_root.exists():
            raise PoBHeadlessHostContractError(
                "reused_session_root",
                f"Session root is already allocated and cannot be reused: {session_layout.session_root}",
            )

        resolved_reopen_source = self._validate_reopen_source(reopen_source) if role == "reopen" else None
        if role == "normal" and reopen_source is not None:
            raise PoBHeadlessHostContractError(
                "invalid_request",
                "reopen_source is only valid for the reopen session.",
            )

        session_layout.session_root.mkdir(parents=True, exist_ok=False)
        session_layout.temp_root.mkdir(parents=True, exist_ok=False)

        bootstrap_created_at = bootstrapped_at or utc_now_iso()
        process_instance_id = _process_instance_id(role, {handle.process_instance_id for handle in self.sessions.values()})
        clean_session_marker = {
            "receipt_path": _path_string(session_layout.session_receipt_path),
            "session_root": _path_string(session_layout.session_root),
            "temp_root": _path_string(session_layout.temp_root),
            "receipt_state": _RECEIPT_STATE_BOOTSTRAP_WRITTEN,
            "session_root_fresh": True,
            "temp_root_empty": True,
        }
        receipt = PoBHeadlessSessionReceipt(
            pob_run_id=self.request.pob_run_id,
            session_role=role,
            process_instance_id=process_instance_id,
            os_pid=None,
            session_root=session_layout.session_root,
            temp_root=session_layout.temp_root,
            fresh_process=True,
            fresh_workspace=True,
            recompute_events=(),
            teardown_status=_TEARDOWN_STATUS_BOOTSTRAP_PENDING,
            receipt_state=_RECEIPT_STATE_BOOTSTRAP_WRITTEN,
            bootstrap_created_at=bootstrap_created_at,
            export_locator=self.layout.export_locator if role == "normal" else None,
            export_payload_hash=None,
            blank_state_verified=False if role == "normal" else None,
            reopen_source_locator=None if resolved_reopen_source is None else resolved_reopen_source.export_locator,
            reopen_source_hash=None if resolved_reopen_source is None else resolved_reopen_source.export_payload_hash,
            parity_verified=False if role == "reopen" else None,
            clean_session_marker=clean_session_marker,
        )
        handle = PoBHeadlessSessionHandle(
            pob_run_id=self.request.pob_run_id,
            session_role=role,
            process_instance_id=process_instance_id,
            run_layout=self.layout,
            session_layout=session_layout,
            manifest_paths=self.layout.manifest_paths,
            export_locator=self.layout.export_locator,
            receipt=receipt,
            reopen_source=resolved_reopen_source,
        )
        self.sessions[role] = handle
        self._write_session_receipt(handle)
        self._write_run_surfaces()
        return handle

    def launch_session(
        self,
        handle: PoBHeadlessSessionHandle,
        *,
        launcher: Callable[[PoBHeadlessLaunchRequest], PoBHeadlessLaunchResult],
        launched_at: str | None = None,
    ) -> PoBHeadlessSessionHandle:
        tracked_handle = self._require_tracked_handle(handle)
        if tracked_handle.receipt.receipt_state != _RECEIPT_STATE_BOOTSTRAP_WRITTEN:
            raise PoBHeadlessHostContractError(
                "same_process_reuse_forbidden",
                f"Session {tracked_handle.session_role} is already launched or sealed.",
            )
        if self.active_session_role is not None:
            raise PoBHeadlessHostContractError(
                "same_process_reuse_forbidden",
                f"Cannot launch {tracked_handle.session_role} while {self.active_session_role} is still active.",
            )
        self._validate_clean_session_bootstrap(tracked_handle)

        launch_result = launcher(self._launch_request(tracked_handle))
        if launch_result.visible_gui_required:
            raise PoBHeadlessHostContractError(
                "visible_gui_fallback_forbidden",
                "Launch boundary attempted to require a visible GUI path.",
            )
        if launch_result.shared_desktop_assumed:
            raise PoBHeadlessHostContractError(
                "shared_desktop_fallback_forbidden",
                "Launch boundary attempted to require a shared-desktop runtime.",
            )

        dependency_fingerprints = dict(launch_result.dependency_fingerprints)
        dependency_fingerprints.setdefault("pinned_pob_lock_sha256", self.release_ref.lock_fingerprint)
        dependency_fingerprints.setdefault(
            "wrapper_entrypoint_ref_sha256",
            sha256_bytes(self.request.wrapper_entrypoint_ref.encode("utf-8")),
        )
        tracked_handle.receipt = tracked_handle.receipt.with_launch(
            os_pid=launch_result.os_pid,
            launched_at=launched_at or utc_now_iso(),
            dependency_fingerprints=dependency_fingerprints,
            launch_command=launch_result.command,
            launch_cwd=launch_result.cwd,
        )
        self.active_session_role = tracked_handle.session_role
        self._write_session_receipt(tracked_handle)
        self._write_run_surfaces()
        return tracked_handle

    def seal_session(
        self,
        handle: PoBHeadlessSessionHandle,
        *,
        sealed_at: str | None = None,
        teardown_status: str = _TEARDOWN_STATUS_SEALED_PROCESS_EXIT_OBSERVED,
        process_exit_observed: bool = True,
        exit_code: int = 0,
        termination: str = "process_exit_observed",
    ) -> PoBHeadlessSessionHandle:
        tracked_handle = self._require_tracked_handle(handle)
        if tracked_handle.receipt.receipt_state != _RECEIPT_STATE_LAUNCH_RECORDED:
            raise PoBHeadlessHostContractError(
                "session_not_live",
                f"Session {tracked_handle.session_role} is not in a live launch state.",
            )
        if tracked_handle.receipt.os_pid is None:
            raise PoBHeadlessHostContractError(
                "session_not_live",
                f"Session {tracked_handle.session_role} does not have a launched PID.",
            )
        if not process_exit_observed:
            raise PoBHeadlessHostContractError(
                "process_exit_not_observed",
                "Teardown cannot be sealed until process exit is observed.",
            )

        tracked_handle.receipt = tracked_handle.receipt.with_teardown(
            sealed_at=sealed_at or utc_now_iso(),
            teardown_status=teardown_status,
            process_exit_observed=True,
            exit_code=exit_code,
            termination=_require_non_empty_string(termination, "termination", "invalid_teardown"),
        )
        self.active_session_role = None
        self._write_session_receipt(tracked_handle)
        self._write_run_surfaces()
        return tracked_handle

    def _ensure_run_surfaces_exist(self) -> None:
        for path in (
            self.layout.manifest_paths.run_manifest_path,
            self.layout.manifest_paths.primary_proof_path,
            self.layout.manifest_paths.live_control_result_path,
            self.layout.manifest_paths.workspace_manifest_path,
            self.layout.manifest_paths.next_run_handoff_path,
        ):
            if not path.is_file():
                raise PoBHeadlessHostContractError(
                    "run_manifest_missing",
                    f"Required durable run surface is missing: {path}",
                )

    def _require_tracked_handle(self, handle: PoBHeadlessSessionHandle) -> PoBHeadlessSessionHandle:
        if not isinstance(handle, PoBHeadlessSessionHandle):
            raise PoBHeadlessHostContractError("invalid_request", "handle must be a PoBHeadlessSessionHandle.")
        tracked_handle = self.sessions.get(handle.session_role)
        if tracked_handle is None or tracked_handle.process_instance_id != handle.process_instance_id:
            raise PoBHeadlessHostContractError(
                "unknown_session",
                f"Session is not tracked by run {self.request.pob_run_id}: {handle.session_role}",
            )
        return tracked_handle

    def _validate_reopen_source(self, reopen_source: PoBHeadlessReopenSource | None) -> PoBHeadlessReopenSource:
        normal_handle = self.sessions.get("normal")
        if normal_handle is None:
            raise PoBHeadlessHostContractError(
                "reopen_source_missing",
                "reopen session requires an accepted normal-session bootstrap first.",
            )
        if normal_handle.receipt.receipt_state != _RECEIPT_STATE_TEARDOWN_SEALED:
            raise PoBHeadlessHostContractError(
                "same_process_reuse_forbidden",
                "reopen session requires the normal session to be fully sealed before reuse can end.",
            )
        if reopen_source is None:
            raise PoBHeadlessHostContractError(
                "reopen_source_missing",
                "reopen session requires the exact export locator or export payload hash from normal.",
            )

        exact_export_locator = self.layout.export_locator.resolve(strict=False)
        candidate_locator = reopen_source.export_locator.resolve(strict=False)
        if candidate_locator != exact_export_locator:
            if any(_is_within(candidate_locator, self.layout.session(role).temp_root) for role in _SESSION_ROLES):
                raise PoBHeadlessHostContractError(
                    "hidden_temp_export_routing_forbidden",
                    "reopen must not route through sessions/*/temp instead of the published exports/ boundary.",
                )
            raise PoBHeadlessHostContractError(
                "non_exact_durable_path_routing_forbidden",
                "reopen must use the exact canonical export locator under run_root/exports/.",
            )
        if not candidate_locator.exists() and reopen_source.export_payload_hash is None:
            raise PoBHeadlessHostContractError(
                "reopen_source_missing",
                "reopen requires an existing exact export locator or an explicit export_payload_hash.",
            )
        return reopen_source

    def _validate_clean_session_bootstrap(self, handle: PoBHeadlessSessionHandle) -> None:
        receipt_payload = _load_json_object(handle.session_receipt_path, failure_state="missing_clean_session_markers")
        marker = receipt_payload.get("clean_session_marker")
        expected_entries = {"session-receipt.json", "temp"}
        observed_entries = {path.name for path in handle.session_root.iterdir()}
        if not isinstance(marker, dict):
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                f"Session receipt is missing clean_session_marker: {handle.session_receipt_path}",
            )
        if observed_entries != expected_entries:
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                f"Session root contains unexpected pre-launch entries: {handle.session_root}",
            )
        if not handle.temp_root.is_dir() or any(handle.temp_root.iterdir()):
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                f"Session temp root must exist and start empty: {handle.temp_root}",
            )
        expected_marker = {
            "receipt_path": _path_string(handle.session_receipt_path),
            "session_root": _path_string(handle.session_root),
            "temp_root": _path_string(handle.temp_root),
            "receipt_state": _RECEIPT_STATE_BOOTSTRAP_WRITTEN,
            "session_root_fresh": True,
            "temp_root_empty": True,
        }
        if marker != expected_marker:
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                "Session clean markers do not match the expected bootstrap state.",
            )
        if receipt_payload.get("receipt_state") != _RECEIPT_STATE_BOOTSTRAP_WRITTEN:
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                "Session receipt is not in bootstrap_written state before launch.",
            )
        if receipt_payload.get("teardown_status") != _TEARDOWN_STATUS_BOOTSTRAP_PENDING:
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                "Session teardown_status must remain bootstrap_pending before launch.",
            )
        if receipt_payload.get("os_pid") is not None:
            raise PoBHeadlessHostContractError(
                "missing_clean_session_markers",
                "Bootstrap receipt must not carry a live PID before launch.",
            )

    def _launch_request(self, handle: PoBHeadlessSessionHandle) -> PoBHeadlessLaunchRequest:
        return PoBHeadlessLaunchRequest(
            pob_run_id=handle.pob_run_id,
            session_role=handle.session_role,
            process_instance_id=handle.process_instance_id,
            run_root=handle.run_root,
            session_root=handle.session_root,
            temp_root=handle.temp_root,
            export_surface_kind=self.request.export_surface_kind,
            export_locator=handle.export_locator,
            session_receipt_path=handle.session_receipt_path,
            run_manifest_path=self.layout.manifest_paths.run_manifest_path,
            primary_proof_path=self.layout.manifest_paths.primary_proof_path,
            live_control_result_path=self.layout.manifest_paths.live_control_result_path,
            workspace_manifest_path=self.layout.manifest_paths.workspace_manifest_path,
            next_run_handoff_path=self.layout.manifest_paths.next_run_handoff_path,
            pinned_pob_release_ref=self.release_ref,
            wrapper_entrypoint_ref=self.request.wrapper_entrypoint_ref,
            reopen_source_locator=None if handle.reopen_source is None else handle.reopen_source.export_locator,
            reopen_source_hash=None if handle.reopen_source is None else handle.reopen_source.export_payload_hash,
        )

    def _write_session_receipt(self, handle: PoBHeadlessSessionHandle) -> None:
        write_json(handle.session_receipt_path, handle.receipt.to_dict())

    def _write_run_surfaces(self) -> None:
        write_json(self.layout.manifest_paths.run_manifest_path, self._run_manifest_payload())
        write_json(self.layout.manifest_paths.primary_proof_path, self._primary_proof_payload())
        write_json(self.layout.manifest_paths.live_control_result_path, self._live_control_result_payload())
        write_json(self.layout.manifest_paths.workspace_manifest_path, self._workspace_manifest_payload())
        write_json(self.layout.manifest_paths.next_run_handoff_path, self._next_run_handoff_payload())

    def _artifact_locator_payload(self) -> dict[str, Any]:
        return {
            "artifact_kind": self.request.export_surface_kind,
            "locator": _path_string(self.layout.export_locator),
            "workspace_locator": _path_string(self.layout.manifest_paths.workspace_manifest_path),
            "handoff_locator": _path_string(self.layout.manifest_paths.next_run_handoff_path),
        }

    def _run_manifest_payload(self) -> dict[str, Any]:
        return {
            "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
            "pob_run_id": self.request.pob_run_id,
            "contract_name": HEADLESS_PROOF_CONTRACT_NAME,
            "contract_version": HEADLESS_PROOF_CONTRACT_VERSION,
            "proof_slice": HEADLESS_PROOF_SLICE,
            "export_surface_kind": self.request.export_surface_kind,
            "run_root": _path_string(self.layout.run_root),
            "artifact_locator": self._artifact_locator_payload(),
            "primary_proof_locator": _path_string(self.layout.manifest_paths.primary_proof_path),
            "live_control_result_locator": _path_string(self.layout.manifest_paths.live_control_result_path),
            "workspace_manifest_locator": _path_string(self.layout.manifest_paths.workspace_manifest_path),
            "next_run_handoff_locator": _path_string(self.layout.manifest_paths.next_run_handoff_path),
            "pinned_pob_release_ref": self.release_ref.to_dict(),
            "wrapper_entrypoint_ref": self.request.wrapper_entrypoint_ref,
            "session_receipt_locators": {
                role: _path_string(self.layout.session(role).session_receipt_path) for role in _SESSION_ROLES
            },
            "session_process_instance_ids": {
                role: None if self.sessions.get(role) is None else self.sessions[role].process_instance_id
                for role in _SESSION_ROLES
            },
            "active_session_role": self.active_session_role,
        }

    def _primary_proof_payload(self) -> dict[str, Any]:
        normal_handle = self.sessions.get("normal")
        reopen_handle = self.sessions.get("reopen")
        return {
            "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
            "pob_run_id": self.request.pob_run_id,
            "primary_proof_kind": "pob_headless_minimal_proof",
            "normal_process_instance_id": None if normal_handle is None else normal_handle.process_instance_id,
            "reopen_process_instance_id": None if reopen_handle is None else reopen_handle.process_instance_id,
            "blank_baseline_assertion": {
                "status": "pending" if normal_handle is None or not normal_handle.receipt.blank_state_verified else "verified",
                "session_receipt_locator": _path_string(self.layout.session("normal").session_receipt_path),
            },
            "final_export_assertion": {
                "status": "pending" if normal_handle is None or normal_handle.receipt.export_payload_hash is None else "recorded",
                "export_locator": _path_string(self.layout.export_locator),
            },
            "reopen_parity_assertion": {
                "status": "pending" if reopen_handle is None or not reopen_handle.receipt.parity_verified else "verified",
                "session_receipt_locator": _path_string(self.layout.session("reopen").session_receipt_path),
            },
            "export_locator": _path_string(self.layout.export_locator),
            "export_payload_hash": None if normal_handle is None else normal_handle.receipt.export_payload_hash,
            "supporting_receipts": [
                _path_string(self.layout.session("normal").session_receipt_path),
                _path_string(self.layout.session("reopen").session_receipt_path),
            ],
        }

    def _live_control_result_payload(self) -> dict[str, Any]:
        return {
            "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
            "pob_run_id": self.request.pob_run_id,
            "normal_readback_summary": {"status": "pending"},
            "reopen_readback_summary": {"status": "pending"},
            "authoritative_output_boundary": {
                "surface_kind": self.request.export_surface_kind,
                "locator": _path_string(self.layout.export_locator),
                "reopen_required": True,
            },
            "artifact_locator": self._artifact_locator_payload(),
        }

    def _workspace_manifest_payload(self) -> dict[str, Any]:
        return {
            "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
            "pob_run_id": self.request.pob_run_id,
            "run_root": _path_string(self.layout.run_root),
            "normal_session_root": _path_string(self.layout.session("normal").session_root),
            "reopen_session_root": _path_string(self.layout.session("reopen").session_root),
            "durable_export_paths": [_path_string(self.layout.export_locator)],
            "durable_proof_paths": [
                _path_string(self.layout.manifest_paths.primary_proof_path),
                _path_string(self.layout.manifest_paths.live_control_result_path),
            ],
            "temp_paths": [
                _path_string(self.layout.session("normal").temp_root),
                _path_string(self.layout.session("reopen").temp_root),
            ],
            "shared_read_only_dependencies": [
                self.release_ref.to_dict(),
                {"wrapper_entrypoint_ref": self.request.wrapper_entrypoint_ref},
            ],
            "forbidden_shared_writable_paths": [
                _path_string(self.layout.session("normal").session_root),
                _path_string(self.layout.session("reopen").session_root),
                _path_string(self.layout.session("normal").temp_root),
                _path_string(self.layout.session("reopen").temp_root),
            ],
            "cleanup_scope": {
                "durable_paths": [
                    _path_string(self.layout.manifest_paths.run_manifest_path),
                    _path_string(self.layout.manifest_paths.primary_proof_path),
                    _path_string(self.layout.manifest_paths.live_control_result_path),
                    _path_string(self.layout.manifest_paths.workspace_manifest_path),
                    _path_string(self.layout.manifest_paths.next_run_handoff_path),
                    _path_string(self.layout.export_locator),
                ],
                "session_temp_paths": [
                    _path_string(self.layout.session("normal").temp_root),
                    _path_string(self.layout.session("reopen").temp_root),
                ],
            },
        }

    def _next_run_handoff_payload(self) -> dict[str, Any]:
        reopen_handle = self.sessions.get("reopen")
        return {
            "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
            "source_pob_run_id": self.request.pob_run_id,
            "ready_pob_import": {
                "surface_kind": self.request.export_surface_kind,
                "locator": _path_string(self.layout.export_locator),
                "payload": None,
            },
            "artifact_locator": self._artifact_locator_payload(),
            "reopen_requirement_satisfied": False if reopen_handle is None else bool(reopen_handle.receipt.parity_verified),
            "next_run_must_start_clean": True,
            "forbidden_reuse_paths": [
                _path_string(self.layout.session("normal").session_root),
                _path_string(self.layout.session("reopen").session_root),
                _path_string(self.layout.session("normal").temp_root),
                _path_string(self.layout.session("reopen").temp_root),
            ],
        }


def validate_parallel_headless_proof_runs(runs: Iterable[PoBHeadlessProofRun]) -> dict[str, Any]:
    """Fail closed unless multiple headless proof runs have disjoint mutable anchors."""

    run_list = list(runs)
    if len(run_list) < 2:
        raise PoBHeadlessHostContractError(
            "insufficient_parallel_runs",
            "Parallel headless proof isolation requires at least two proof runs.",
        )

    seen_run_ids: dict[str, int] = {}
    seen_mutable_paths: dict[str, tuple[int, str]] = {}
    seen_process_instance_ids: dict[str, tuple[int, SessionRole]] = {}
    isolated_runs: list[dict[str, Any]] = []

    for run_index, run in enumerate(run_list):
        if not isinstance(run, PoBHeadlessProofRun):
            raise PoBHeadlessHostContractError("invalid_parallel_run", "runs must contain PoBHeadlessProofRun objects.")

        pob_run_id = run.request.pob_run_id
        if pob_run_id in seen_run_ids:
            raise PoBHeadlessHostContractError(
                "reused_pob_run_id",
                f"pob_run_id is reused across parallel proof runs: {pob_run_id}",
            )
        seen_run_ids[pob_run_id] = run_index

        run_root = run.layout.run_root.resolve(strict=False)
        mutable_paths = {
            "run_root": run.layout.run_root,
            "exports_root": run.layout.exports_root,
            "export_locator": run.layout.export_locator,
            "sessions_root": run.layout.sessions_root,
            "run_manifest_path": run.layout.manifest_paths.run_manifest_path,
            "primary_proof_path": run.layout.manifest_paths.primary_proof_path,
            "live_control_result_path": run.layout.manifest_paths.live_control_result_path,
            "workspace_manifest_path": run.layout.manifest_paths.workspace_manifest_path,
            "next_run_handoff_path": run.layout.manifest_paths.next_run_handoff_path,
            "normal_session_root": run.layout.session("normal").session_root,
            "reopen_session_root": run.layout.session("reopen").session_root,
            "normal_temp_root": run.layout.session("normal").temp_root,
            "reopen_temp_root": run.layout.session("reopen").temp_root,
        }
        resolved_mutable_paths: dict[str, str] = {}
        for field_name, path in mutable_paths.items():
            resolved_path = path.resolve(strict=False)
            if field_name != "run_root" and not _is_within(resolved_path, run_root):
                raise PoBHeadlessHostContractError(
                    "non_package_owned_mutable_path",
                    f"{field_name} must stay package-owned under run_root for {pob_run_id}: {resolved_path}",
                )
            path_key = _path_string(resolved_path)
            if path_key in seen_mutable_paths:
                previous_run_index, previous_field_name = seen_mutable_paths[path_key]
                raise PoBHeadlessHostContractError(
                    "shared_mutable_path",
                    "Parallel proof runs must not share mutable path anchors: "
                    f"run[{previous_run_index}].{previous_field_name} == run[{run_index}].{field_name} == {path_key}",
                )
            seen_mutable_paths[path_key] = (run_index, field_name)
            resolved_mutable_paths[field_name] = path_key

        for role, handle in run.sessions.items():
            process_instance_id = handle.process_instance_id
            if process_instance_id in seen_process_instance_ids:
                previous_run_index, previous_role = seen_process_instance_ids[process_instance_id]
                raise PoBHeadlessHostContractError(
                    "shared_process_instance_id",
                    "Parallel proof runs must not share process_instance_id values: "
                    f"run[{previous_run_index}].{previous_role} == run[{run_index}].{role} == {process_instance_id}",
                )
            seen_process_instance_ids[process_instance_id] = (run_index, role)

        isolated_runs.append(
            {
                "pob_run_id": pob_run_id,
                "run_root": resolved_mutable_paths["run_root"],
                "workspace_manifest_locator": resolved_mutable_paths["workspace_manifest_path"],
                "primary_proof_locator": resolved_mutable_paths["primary_proof_path"],
                "live_control_result_locator": resolved_mutable_paths["live_control_result_path"],
                "next_run_handoff_locator": resolved_mutable_paths["next_run_handoff_path"],
                "export_locator": resolved_mutable_paths["export_locator"],
                "session_process_instance_ids": {
                    role: handle.process_instance_id for role, handle in sorted(run.sessions.items())
                },
            }
        )

    return {
        "supported_path": HEADLESS_PROOF_SUPPORTED_PATH,
        "parallel_run_count": len(run_list),
        "parallel_isolation_verified": True,
        "runs": isolated_runs,
    }


def _build_release_ref(release_manager: PoBReleaseManager) -> PoBPinnedReleaseRef:
    release_lock = release_manager.load_lock()
    lock_path = release_manager.lock_path.resolve(strict=False)
    return PoBPinnedReleaseRef(
        lock_path=lock_path,
        repo=release_lock.repo,
        tag=release_lock.tag,
        asset_name=release_lock.asset_name,
        asset_sha256=release_lock.asset_sha256,
        lock_fingerprint=sha256_file(lock_path),
    )


def _prepare_run_layout(
    *,
    pob_run_id: str,
    export_surface_kind: ExportSurfaceKind,
    artifacts_root: Path,
) -> PoBHeadlessRunLayout:
    safe_run_id = validate_token(pob_run_id, "pob_run_id")
    run_root = (Path(artifacts_root) / safe_run_id / "pob").resolve(strict=False)
    if run_root.exists():
        raise PoBHeadlessHostContractError(
            "run_root_exists",
            f"run_root already exists and cannot be reused: {run_root}",
        )
    exports_root = run_root / "exports"
    proof_root = run_root / "proof"
    workspace_root = run_root / "workspace"
    handoff_root = run_root / "handoff"
    sessions_root = run_root / "sessions"
    for path in (exports_root, proof_root, workspace_root, handoff_root, sessions_root):
        path.mkdir(parents=True, exist_ok=False)
    manifest_paths = PoBHeadlessManifestPaths(
        run_manifest_path=run_root / "run-manifest.json",
        primary_proof_path=proof_root / "primary-proof.json",
        live_control_result_path=proof_root / "live-control-result.json",
        workspace_manifest_path=workspace_root / "workspace-manifest.json",
        next_run_handoff_path=handoff_root / "next-run-handoff.json",
    )
    return PoBHeadlessRunLayout(
        pob_run_id=safe_run_id,
        run_root=run_root,
        exports_root=exports_root,
        export_locator=exports_root / _EXPORT_SURFACE_FILENAMES[export_surface_kind],
        sessions_root=sessions_root,
        manifest_paths=manifest_paths,
    )


def create_headless_proof_run(
    request: PoBHeadlessHostRequest,
    *,
    release_manager: PoBReleaseManager | None = None,
    artifacts_root: Path = DEFAULT_RUNS_ROOT,
) -> PoBHeadlessProofRun:
    """Allocate the canonical headless proof run layout and emit placeholder manifests."""

    manager = release_manager or PoBReleaseManager()
    run = PoBHeadlessProofRun(
        request=request,
        layout=_prepare_run_layout(
            pob_run_id=request.pob_run_id,
            export_surface_kind=request.export_surface_kind,
            artifacts_root=Path(artifacts_root),
        ),
        release_ref=_build_release_ref(manager),
    )
    run._write_run_surfaces()
    return run


__all__ = [
    "HEADLESS_PROOF_CONTRACT_NAME",
    "HEADLESS_PROOF_CONTRACT_VERSION",
    "HEADLESS_PROOF_SLICE",
    "HEADLESS_PROOF_SUPPORTED_PATH",
    "PoBHeadlessHostContractError",
    "PoBHeadlessHostRequest",
    "PoBHeadlessLaunchRequest",
    "PoBHeadlessLaunchResult",
    "PoBHeadlessManifestPaths",
    "PoBHeadlessProofRun",
    "PoBHeadlessReopenSource",
    "PoBHeadlessRunLayout",
    "PoBHeadlessSessionHandle",
    "PoBHeadlessSessionLayout",
    "PoBHeadlessSessionReceipt",
    "PoBPinnedReleaseRef",
    "create_headless_proof_run",
    "validate_parallel_headless_proof_runs",
]
