"""Artifact helpers for Path of Building evaluation runs."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "artifacts" / "runs"
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class ArtifactContractError(RuntimeError):
    """Raised when a PoB artifact path or bundle violates the contract."""


def validate_token(value: str, field_name: str) -> str:
    """Validate a path token used for run ids and input file names."""

    normalized = value.strip()
    if not TOKEN_PATTERN.fullmatch(normalized):
        raise ArtifactContractError(
            f"{field_name} must match {TOKEN_PATTERN.pattern} and stay within the artifact root."
        )
    return normalized


def _stable_json(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    except ValueError as exc:
        raise ArtifactContractError("Artifact payload contains non-finite numeric values.") from exc


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    """Write a JSON artifact using stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_stable_json(payload), encoding="utf-8", newline="\n")
    return path


def write_text(path: Path, content: str) -> Path:
    """Write a UTF-8 text artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    return path


def sha256_bytes(payload: bytes) -> str:
    """Return the SHA-256 digest for in-memory bytes."""

    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest for a local file."""

    return sha256_bytes(path.read_bytes())


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Manifest entry for one persisted artifact."""

    relative_path: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class PoBRunLayout:
    """Stable artifact paths for one evaluation run."""

    run_id: str
    run_root: Path
    workspace_dir: Path
    build_input_dir: Path
    input_request_path: Path
    pob_runtime_path: Path
    metrics_raw_path: Path
    metrics_normalized_path: Path
    rule_context_path: Path
    stdout_log_path: Path
    stderr_log_path: Path
    run_manifest_path: Path

    def build_input_path(self, filename: str = "build.json") -> Path:
        safe_name = validate_token(filename, "input filename")
        return self.build_input_dir / safe_name

    def bundled_paths(self) -> tuple[Path, ...]:
        return (
            self.input_request_path,
            self.pob_runtime_path,
            self.metrics_raw_path,
            self.metrics_normalized_path,
            self.rule_context_path,
            self.stdout_log_path,
            self.stderr_log_path,
        )

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.run_root).as_posix()


@dataclass(frozen=True, slots=True)
class PoBControlLayout:
    """Stable artifact paths for one live-control run."""

    run_id: str
    run_root: Path
    workspace_dir: Path
    build_input_dir: Path
    input_request_path: Path
    pob_runtime_path: Path
    control_result_path: Path
    stdout_log_path: Path
    stderr_log_path: Path
    run_manifest_path: Path

    @property
    def settings_path(self) -> Path:
        return self.workspace_dir / "Settings.xml"

    @property
    def workspace_build_dir(self) -> Path:
        return self.workspace_dir / "Builds"

    def build_input_path(self, filename: str = "build.xml") -> Path:
        safe_name = validate_token(filename, "input filename")
        return self.build_input_dir / safe_name

    def workspace_build_path(self, filename: str = "build.xml") -> Path:
        safe_name = validate_token(filename, "workspace build filename")
        return self.workspace_build_dir / safe_name

    def bundled_paths(self) -> tuple[Path, ...]:
        return (
            self.input_request_path,
            self.pob_runtime_path,
            self.control_result_path,
            self.stdout_log_path,
            self.stderr_log_path,
        )

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.run_root).as_posix()


def prepare_run_layout(run_id: str, artifacts_root: Path = DEFAULT_RUNS_ROOT) -> PoBRunLayout:
    """Return the stable bundle layout for a run and create required directories."""

    safe_run_id = validate_token(run_id, "run_id")
    run_root = Path(artifacts_root) / safe_run_id / "pob"
    workspace_dir = run_root / "workspace"
    build_input_dir = run_root / "build_input"
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    if build_input_dir.exists():
        shutil.rmtree(build_input_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    build_input_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        run_root / "input_request.json",
        run_root / "pob_runtime.json",
        run_root / "metrics_raw.json",
        run_root / "metrics_normalized.json",
        run_root / "rule_context.json",
        run_root / "stdout.log",
        run_root / "stderr.log",
        run_root / "run_manifest.json",
    ):
        path.unlink(missing_ok=True)

    return PoBRunLayout(
        run_id=safe_run_id,
        run_root=run_root,
        workspace_dir=workspace_dir,
        build_input_dir=build_input_dir,
        input_request_path=run_root / "input_request.json",
        pob_runtime_path=run_root / "pob_runtime.json",
        metrics_raw_path=run_root / "metrics_raw.json",
        metrics_normalized_path=run_root / "metrics_normalized.json",
        rule_context_path=run_root / "rule_context.json",
        stdout_log_path=run_root / "stdout.log",
        stderr_log_path=run_root / "stderr.log",
        run_manifest_path=run_root / "run_manifest.json",
    )


def prepare_control_layout(run_id: str, artifacts_root: Path = DEFAULT_RUNS_ROOT) -> PoBControlLayout:
    """Return the stable bundle layout for one live-control run."""

    safe_run_id = validate_token(run_id, "run_id")
    run_root = Path(artifacts_root) / safe_run_id / "pob"
    workspace_dir = run_root / "workspace"
    build_input_dir = run_root / "build_input"
    if workspace_dir.exists():
        shutil.rmtree(workspace_dir)
    if build_input_dir.exists():
        shutil.rmtree(build_input_dir)
    workspace_dir.mkdir(parents=True, exist_ok=True)
    build_input_dir.mkdir(parents=True, exist_ok=True)

    for path in (
        run_root / "input_request.json",
        run_root / "pob_runtime.json",
        run_root / "control_result.json",
        run_root / "stdout.log",
        run_root / "stderr.log",
        run_root / "run_manifest.json",
    ):
        path.unlink(missing_ok=True)

    return PoBControlLayout(
        run_id=safe_run_id,
        run_root=run_root,
        workspace_dir=workspace_dir,
        build_input_dir=build_input_dir,
        input_request_path=run_root / "input_request.json",
        pob_runtime_path=run_root / "pob_runtime.json",
        control_result_path=run_root / "control_result.json",
        stdout_log_path=run_root / "stdout.log",
        stderr_log_path=run_root / "stderr.log",
        run_manifest_path=run_root / "run_manifest.json",
    )


def _artifact_records(run_root: Path, artifact_paths: tuple[Path, ...]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for artifact_path in artifact_paths:
        if not artifact_path.exists():
            raise ArtifactContractError(f"Missing required artifact: {artifact_path}")
        records.append(
            ArtifactRecord(
                relative_path=artifact_path.relative_to(run_root).as_posix(),
                sha256=sha256_file(artifact_path),
                size=artifact_path.stat().st_size,
            ).to_dict()
        )
    return records


def _build_input_records(build_input_dir: Path, *, run_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(build_input_dir.rglob("*")):
        if not path.is_file():
            continue
        records.append(
            ArtifactRecord(
                relative_path=path.relative_to(run_root).as_posix(),
                sha256=sha256_file(path),
                size=path.stat().st_size,
            ).to_dict()
        )
    return records


def build_manifest(
    layout: PoBRunLayout,
    *,
    run_id: str,
    build_id: str,
    supported_path: str,
    evaluated_at: str,
) -> dict[str, Any]:
    """Build a manifest for the required PoB artifact bundle."""

    return {
        "run_id": run_id,
        "build_id": build_id,
        "supported_path": supported_path,
        "evaluated_at": evaluated_at,
        "artifacts": _artifact_records(layout.run_root, layout.bundled_paths()),
        "build_input": _build_input_records(layout.build_input_dir, run_root=layout.run_root),
    }


def build_control_manifest(
    layout: PoBControlLayout,
    *,
    run_id: str,
    build_id: str,
    supported_path: str,
    launched_at: str,
) -> dict[str, Any]:
    """Build a manifest for the required live-control artifact bundle."""

    return {
        "run_id": run_id,
        "build_id": build_id,
        "supported_path": supported_path,
        "launched_at": launched_at,
        "artifacts": _artifact_records(layout.run_root, layout.bundled_paths()),
        "build_input": _build_input_records(layout.build_input_dir, run_root=layout.run_root),
    }
