"""Verifier for operator-pasteable Path of Building import codes."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import xml.etree.ElementTree as ET
import zlib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .headless_runtime_adapter import PinnedPoBHeadlessRuntimeAdapter
from .host_runtime import PoBHeadlessHostRequest, create_headless_proof_run
from .release_manager import PoBReleaseManager


class PoBImportCodeVerificationError(RuntimeError):
    """Raised when a PoB import code cannot be accepted by the verifier."""


DIRECT_BUILD_IMPORT_PUBLICATION_VERIFICATION_RECORD_KIND = "direct_build_import_publication_verification"
DIRECT_BUILD_IMPORT_PUBLICATION_VERIFICATION_SCHEMA_VERSION = "1.0.0"
POB_IMPORT_STRING_VERIFIER_RECEIPT_KIND = "pob_import_string_verifier_receipt"
POB_IMPORT_STRING_VERIFIER_RECEIPT_SCHEMA_VERSION = "1.0.0"
NATIVE_POB_IMPORT_STRING_PROOF_KIND = "pinned_pob_import_tab_import_string"
NATIVE_POB_IMPORT_STRING_SURFACE_KIND = "pob_import_ui_import_code"
READY_POB_IMPORT_FIELD = "composition_summary.ready_pob_import.payload"
PINNED_POB_IMPORT_CODE_RUNTIME_ACTION = "verify_pob_import_code_string"
MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION = (
    "missing_headless_runtime_action_verify_pob_import_code_string"
)
PINNED_POB_INFLATE_HOST_FUNCTION = "Inflate(data)"
MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION = "missing_headless_wrapper_inflate_host_function"


ImportCodeVerifier = Callable[[Path, Path, str], Mapping[str, Any]]


def pob_import_code_payload_hash(import_code: str) -> str:
    """Return the exact SHA-256 hash for one user-facing PoB import payload."""

    if not isinstance(import_code, str) or not import_code.strip():
        raise PoBImportCodeVerificationError("PoB import code must be non-empty text.")
    return hashlib.sha256(import_code.encode("utf-8")).hexdigest()


def assess_native_pob_import_string_semantics(
    verifier_result: Mapping[str, Any],
    *,
    expected_payload_sha256: str | None = None,
) -> dict[str, Any]:
    """Assess whether the verifier proved the exact string through PoB's native import UI path."""

    proof = verifier_result.get("native_pob_import_string_proof")
    proof_mapping = proof if isinstance(proof, Mapping) else {}
    blockers: list[dict[str, Any]] = []
    if verifier_result.get("native_pob_import_string_semantics_valid") is not True:
        blockers.append(
            _publication_blocker(
                "native_pob_import_string_semantics_missing",
                "The verifier did not prove that the exact import string is accepted by Path of Building's native import-code path.",
                "Feed the exact payload string through pinned PoB ImportTab/import-code semantics and record accepted native proof before chat publication.",
            )
        )
    if not proof_mapping:
        blockers.append(
            _publication_blocker(
                "native_pob_import_string_proof_missing",
                "The verifier result does not contain a native PoB import-string proof record.",
                "Record native_pob_import_string_proof with status=accepted for the exact payload.",
            )
        )
    else:
        if _string_value(proof_mapping.get("status")) != "accepted":
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_proof_not_accepted",
                    "The native PoB import-string proof is not status=accepted.",
                    "Publish only after pinned PoB accepts the exact import string through its import-code path.",
                )
            )
        if _string_value(proof_mapping.get("proof_kind")) != NATIVE_POB_IMPORT_STRING_PROOF_KIND:
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_proof_kind_invalid",
                    "The native import proof kind is not the pinned PoB ImportTab import-string proof.",
                    f"Use proof_kind={NATIVE_POB_IMPORT_STRING_PROOF_KIND}.",
                )
            )
        if _string_value(proof_mapping.get("surface_kind")) != NATIVE_POB_IMPORT_STRING_SURFACE_KIND:
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_surface_invalid",
                    "The native import proof surface is not the PoB import-code UI path.",
                    f"Use surface_kind={NATIVE_POB_IMPORT_STRING_SURFACE_KIND}.",
                )
            )
        if proof_mapping.get("import_code_valid") is not True:
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_not_valid",
                    "Pinned PoB did not report the exact import string as a valid import code.",
                    "Only publish an import string after native PoB marks that exact string as valid.",
                )
            )
        proof_payload_sha256 = _string_value(proof_mapping.get("payload_sha256"))
        if expected_payload_sha256 is not None and proof_payload_sha256 != expected_payload_sha256:
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_payload_mismatch",
                    "The native PoB import-string proof payload SHA-256 does not match the exact ready payload.",
                    "Rerun native import-string proof against the same payload that would be printed in chat.",
                )
            )
        if not _string_value(proof_mapping.get("locator")):
            blockers.append(
                _publication_blocker(
                    "native_pob_import_string_proof_locator_missing",
                    "The native PoB import-string proof does not provide a durable proof locator.",
                    "Store a durable native import proof artifact before chat publication.",
                )
            )
        for missing_input in _string_list(proof_mapping.get("missing_inputs")):
            if missing_input == MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION:
                blockers.append(
                    _publication_blocker(
                        MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,
                        "The pinned headless PoB runtime cannot yet feed an exact import code string through native import-code semantics.",
                        (
                            "Add a headless runtime worker/adapter/wrapper action named "
                            f"{PINNED_POB_IMPORT_CODE_RUNTIME_ACTION} that exercises PoB ImportTab import-code semantics."
                        ),
                    )
                )
            elif missing_input == MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION:
                blockers.append(
                    _publication_blocker(
                        MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION,
                        "The pinned headless wrapper exposes ImportTab but not the host Inflate(data) function needed by PoB's import-code path.",
                        (
                            "Implement or bind the headless wrapper host function "
                            f"{PINNED_POB_INFLATE_HOST_FUNCTION} before accepting native import-code proof."
                        ),
                    )
                )

    return {
        "status": "accepted" if not blockers else "blocked",
        "required_for_successful_chat_payload": True,
        "proof_kind": _string_value(proof_mapping.get("proof_kind")),
        "surface_kind": _string_value(proof_mapping.get("surface_kind")),
        "payload_sha256": _string_value(proof_mapping.get("payload_sha256")) or None,
        "locator": _string_value(proof_mapping.get("locator")) or None,
        "import_code_valid": proof_mapping.get("import_code_valid") if proof_mapping else None,
        "blockers": blockers,
    }


def build_pob_import_string_verifier_receipt(
    *,
    candidate_run_id: str,
    candidate_id: str,
    artifact_id: str,
    pob_release_pin: str,
    direct_build_output_ref: Mapping[str, Any],
    payload_sha256: str,
    status: str,
    locator: str | None,
    import_code_valid: bool,
    native_pob_import_string_semantics_valid: bool,
    observed_result_ref: Mapping[str, Any] | None,
    missing_inputs: Sequence[str] = (),
    invalid_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the closed receipt consumed by the privileged chat-submit guard."""

    if not _valid_sha256(payload_sha256):
        raise PoBImportCodeVerificationError("payload_sha256 must be a lowercase 64-character SHA-256 hex digest.")
    if not isinstance(direct_build_output_ref, Mapping):
        raise PoBImportCodeVerificationError("direct_build_output_ref must be a JSON object ref.")
    if status not in {"accepted", "blocked", "failed"}:
        raise PoBImportCodeVerificationError("status must be accepted, blocked, or failed.")
    normalized_missing_inputs = _string_list(missing_inputs)
    normalized_invalid_reasons = _string_list(invalid_reasons)
    if status == "accepted":
        if not _string_value(locator):
            raise PoBImportCodeVerificationError("accepted receipt requires a durable locator.")
        if import_code_valid is not True or native_pob_import_string_semantics_valid is not True:
            raise PoBImportCodeVerificationError("accepted receipt requires native import-code success booleans.")
        if not isinstance(observed_result_ref, Mapping):
            raise PoBImportCodeVerificationError("accepted receipt requires observed_result_ref.")
        if normalized_missing_inputs or normalized_invalid_reasons:
            raise PoBImportCodeVerificationError("accepted receipt cannot carry missing_inputs or invalid_reasons.")

    return {
        "schema_version": POB_IMPORT_STRING_VERIFIER_RECEIPT_SCHEMA_VERSION,
        "receipt_kind": POB_IMPORT_STRING_VERIFIER_RECEIPT_KIND,
        "candidate_run_id": _required_string(candidate_run_id, "candidate_run_id"),
        "candidate_id": _required_string(candidate_id, "candidate_id"),
        "artifact_id": _required_string(artifact_id, "artifact_id"),
        "pob_release_pin": _required_string(pob_release_pin, "pob_release_pin"),
        "direct_build_output_ref": dict(direct_build_output_ref),
        "ready_pob_import_field": READY_POB_IMPORT_FIELD,
        "payload_sha256": payload_sha256,
        "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
        "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
        "status": status,
        "locator": _string_value(locator) or None,
        "import_code_valid": bool(import_code_valid),
        "native_pob_import_string_semantics_valid": bool(native_pob_import_string_semantics_valid),
        "observed_result_ref": dict(observed_result_ref) if isinstance(observed_result_ref, Mapping) else None,
        "missing_inputs": normalized_missing_inputs,
        "invalid_reasons": normalized_invalid_reasons,
    }


def build_blocked_native_import_string_verifier_receipt(
    *,
    candidate_run_id: str,
    candidate_id: str,
    artifact_id: str,
    pob_release_pin: str,
    direct_build_output_ref: Mapping[str, Any],
    payload_sha256: str,
    locator: str | None = None,
) -> dict[str, Any]:
    """Return the precise blocked receipt for the current missing native runtime action."""

    return build_pob_import_string_verifier_receipt(
        candidate_run_id=candidate_run_id,
        candidate_id=candidate_id,
        artifact_id=artifact_id,
        pob_release_pin=pob_release_pin,
        direct_build_output_ref=direct_build_output_ref,
        payload_sha256=payload_sha256,
        status="blocked",
        locator=locator,
        import_code_valid=False,
        native_pob_import_string_semantics_valid=False,
        observed_result_ref=None,
        missing_inputs=(MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,),
        invalid_reasons=(),
    )


def extract_pob_build_identity_from_xml(xml_text: str) -> dict[str, Any]:
    """Extract the publication identity fields that PoB exposes in build XML."""

    if not isinstance(xml_text, str) or not xml_text.strip():
        raise PoBImportCodeVerificationError("PoB XML must be non-empty text.")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise PoBImportCodeVerificationError("PoB XML could not be parsed.") from exc
    build_node = root.find("Build") if root.tag == "PathOfBuilding" else root.find("./Build")
    if build_node is None:
        raise PoBImportCodeVerificationError("PoB XML did not contain a Build node.")
    return {
        "class_name": _string_value(build_node.attrib.get("className")),
        "ascendancy": _string_value(build_node.attrib.get("ascendClassName")),
        "level": _int_value(build_node.attrib.get("level")),
        "character_level_auto_mode": _bool_value(build_node.attrib.get("characterLevelAutoMode")),
        "main_skill": _main_skill_from_xml_root(root),
    }


def decode_pob_import_code(import_code: str) -> str:
    """Decode a PoB import code using the same base64/zlib envelope as PoB's import UI."""

    if not isinstance(import_code, str) or not import_code.strip():
        raise PoBImportCodeVerificationError("PoB import code must be non-empty text.")
    normalized = "".join(import_code.split())
    padded = normalized.replace("-", "+").replace("_", "/") + "=" * ((4 - len(normalized) % 4) % 4)
    try:
        compressed_payload = base64.b64decode(padded.encode("ascii"), validate=True)
    except Exception as exc:
        raise PoBImportCodeVerificationError("PoB import code is not valid base64 text.") from exc
    try:
        return zlib.decompress(compressed_payload).decode("utf-8")
    except Exception as exc:
        raise PoBImportCodeVerificationError("PoB import code did not decode through the PoB zlib import envelope.") from exc


def verify_pob_import_code_file(
    import_code_path: Path,
    *,
    artifacts_root: Path,
    pob_run_id: str = "pob_import_code_verifier",
    release_manager: PoBReleaseManager | None = None,
) -> dict[str, Any]:
    """Verify an exact code file through pinned PoB's native import-code UI path."""

    code_path = Path(import_code_path).resolve(strict=True)
    payload_text = code_path.read_text(encoding="utf-8")
    payload_sha256 = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
    manager = release_manager or PoBReleaseManager()
    adapter = PinnedPoBHeadlessRuntimeAdapter(release_manager=manager)
    run = create_headless_proof_run(
        PoBHeadlessHostRequest(
            pob_run_id=pob_run_id,
            export_surface_kind="pob_xml",
            wrapper_entrypoint_ref="src/junkroan/pob/headless_wrapper.lua",
        ),
        release_manager=manager,
        artifacts_root=artifacts_root,
    )
    import_xml_path = run.layout.export_locator

    normal = run.bootstrap_session("normal")
    normal_live = False
    native_result: dict[str, Any] = {}
    native_observation_ref: dict[str, Any] | None = None
    native_proof: dict[str, Any] = {}
    xml_text = ""
    exported_xml = ""
    decoded_build_identity: dict[str, Any] | None = None
    reexported_build_identity: dict[str, Any] | None = None
    state: dict[str, Any] = {}
    try:
        normal = run.launch_session(normal, launcher=adapter.launch_session)
        normal_live = True
        native_result = adapter.verify_pob_import_code_string(normal, payload_text)
        native_observation_ref = _write_native_import_string_observation(
            run.layout.run_root / "proof" / "native-import-string-observation.json",
            native_result,
        )
        native_proof = _native_import_string_proof_from_runtime_result(
            native_result,
            observed_result_ref=native_observation_ref,
        )
        if native_result.get("status") == "accepted":
            xml_text = decode_pob_import_code(payload_text)
            decoded_build_identity = extract_pob_build_identity_from_xml(xml_text)
            import_xml_path.parent.mkdir(parents=True, exist_ok=True)
            import_xml_path.write_text(xml_text, encoding="utf-8")
            exported_xml = adapter.export_build_artifact(normal)
            reexported_build_identity = extract_pob_build_identity_from_xml(exported_xml)
            state = adapter.read_state(normal)
        shutdown = adapter.shutdown_session(normal)
        normal_live = False
        run.seal_session(
            normal,
            exit_code=shutdown.exit_code,
            termination=shutdown.termination,
            process_exit_observed=shutdown.process_exit_observed,
        )
    finally:
        if normal_live:
            adapter.shutdown_session(normal)
        adapter.close()

    accepted = native_result.get("status") == "accepted" and native_proof.get("status") == "accepted"
    return {
        "status": "accepted" if accepted else "blocked",
        "validated_import_code_path": str(code_path),
        "validated_import_code_payload_sha256": payload_sha256,
        "decoded_xml_path": str(import_xml_path.resolve(strict=False)) if xml_text else None,
        "run_root": str(run.layout.run_root.resolve(strict=False)),
        "decoded_xml_char_count": len(xml_text),
        "reexported_xml_char_count": len(exported_xml),
        "decoded_build_identity": decoded_build_identity,
        "reexported_build_identity": reexported_build_identity,
        "native_pob_import_string_semantics_valid": native_result.get(
            "native_pob_import_string_semantics_valid"
        )
        is True,
        "native_pob_import_string_proof": native_proof,
        "native_pob_import_string_observation": native_observation_ref,
        "gear_slot_count": len(state.get("gear_slots", [])),
        "tree_class_id": state.get("tree_state", {}).get("class_id"),
        "tree_ascendancy_id": state.get("tree_state", {}).get("ascendancy_id"),
        "socket_group_count": state.get("skills_state", {}).get("socket_group_count"),
    }


def _write_native_import_string_observation(path: Path, native_result: Mapping[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "record_kind": "pob_native_import_string_observation",
        "status": _string_value(native_result.get("status")) or "invalid",
        "payload_sha256": _string_value(native_result.get("payload_sha256")),
        "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
        "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
        "import_code_valid": native_result.get("import_code_valid") is True,
        "native_pob_import_string_semantics_valid": native_result.get(
            "native_pob_import_string_semantics_valid"
        )
        is True,
        "import_code_detail": _string_value(native_result.get("import_code_detail")),
        "decoded_xml_char_count": _int_value(native_result.get("decoded_xml_char_count")) or 0,
        "imported_build_active": native_result.get("imported_build_active") is True,
        "missing_inputs": _string_list(native_result.get("missing_inputs")),
        "invalid_reasons": _string_list(native_result.get("invalid_reasons")),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ref_id": "native-import-observation.001",
        "locator": str(path.resolve(strict=False)),
        "json_pointer": None,
    }


def _native_import_string_proof_from_runtime_result(
    native_result: Mapping[str, Any],
    *,
    observed_result_ref: Mapping[str, Any],
) -> dict[str, Any]:
    accepted = (
        _string_value(native_result.get("status")) == "accepted"
        and native_result.get("import_code_valid") is True
        and native_result.get("native_pob_import_string_semantics_valid") is True
    )
    return {
        "status": "accepted" if accepted else "blocked",
        "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
        "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
        "payload_sha256": _string_value(native_result.get("payload_sha256")),
        "locator": _string_value(observed_result_ref.get("locator")),
        "import_code_valid": native_result.get("import_code_valid") is True,
        "native_pob_import_string_semantics_valid": native_result.get(
            "native_pob_import_string_semantics_valid"
        )
        is True,
        "observed_result_ref": dict(observed_result_ref),
        "missing_inputs": _string_list(native_result.get("missing_inputs")),
        "invalid_reasons": _string_list(native_result.get("invalid_reasons")) if not accepted else [],
    }


def verify_direct_build_import_publication_inputs(
    *,
    semantic_validation_path: Path,
    materialization_source_packet_path: Path,
    pre_materialization_checkpoint_path: Path,
    ready_pob_import_code_path: Path | None,
    artifacts_root: Path,
    pob_run_id: str = "direct_build_import_publication_verifier",
    verification_id: str = "direct-build-import-publication-verification",
    verifier: ImportCodeVerifier | None = None,
    additional_blockers: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Fail-closed publication gate for Product DirectBuildOutput import publication."""

    semantic_path = Path(semantic_validation_path).resolve(strict=True)
    source_packet_path = Path(materialization_source_packet_path).resolve(strict=True)
    checkpoint_path = Path(pre_materialization_checkpoint_path).resolve(strict=True)
    semantic_packet = _load_json_mapping(semantic_path, label="semantic validation packet")
    source_packet = _load_json_mapping(source_packet_path, label="materialization source packet")
    checkpoint = _load_json_mapping(checkpoint_path, label="pre-materialization checkpoint")
    decision_ledger_path = semantic_path.with_name("direct-build-decision-ledger.json")
    decision_ledger = _load_json_mapping(decision_ledger_path, label="decision ledger") if decision_ledger_path.is_file() else {}

    blockers: list[dict[str, Any]] = []
    blockers.extend(_semantic_packet_blockers(semantic_packet))
    blockers.extend(_source_packet_blockers(source_packet, semantic_packet))
    blockers.extend(_checkpoint_blockers(checkpoint, semantic_packet, source_packet))
    blockers.extend(_decision_ledger_blockers(decision_ledger, semantic_packet, decision_ledger_path))
    blockers.extend(_normalized_additional_blockers(additional_blockers))
    expected_build_identity = _expected_build_identity(decision_ledger)

    import_code_verifier_result: dict[str, Any] | None = None
    real_pob_import_semantics: dict[str, Any] | None = None
    ready_import_path_text: str | None = None
    ready_import_payload_sha256: str | None = None
    decoded_build_identity: dict[str, Any] | None = None
    if ready_pob_import_code_path is None:
        blockers.append(
            _publication_blocker(
                "ready_pob_import_missing",
                "No ready PoB import payload was provided for exact import-code verification.",
                "Materialize one ready-pob-import.pobcode.txt payload from the passed checkpoint package and rerun the verifier.",
            )
        )
    else:
        candidate_import_path = Path(ready_pob_import_code_path)
        if not candidate_import_path.is_file():
            blockers.append(
                _publication_blocker(
                    "ready_pob_import_missing",
                    "The ready PoB import payload path does not exist.",
                    "Provide an existing ready-pob-import.pobcode.txt payload from the same publication run.",
                )
            )
        else:
            ready_import_path = candidate_import_path.resolve(strict=True)
            ready_import_path_text = str(ready_import_path)
            ready_import_payload = ready_import_path.read_text(encoding="utf-8")
            ready_import_payload_sha256 = pob_import_code_payload_hash(ready_import_payload)
            try:
                decoded_build_identity = extract_pob_build_identity_from_xml(decode_pob_import_code(ready_import_payload))
            except PoBImportCodeVerificationError as exc:
                blockers.append(
                    _publication_blocker(
                        "ready_pob_import_identity_unreadable",
                        f"The ready PoB import payload did not expose a readable build identity: {exc}",
                        "Materialize a PoB import whose decoded XML exposes class, level, and main skill identity.",
                    )
                )
            else:
                blockers.extend(
                    _build_identity_parity_blockers(
                        expected_build_identity,
                        decoded_build_identity,
                        observed_label="ready_pob_import_decoded_xml",
                    )
                )
            try:
                verifier_result = (
                    verifier(ready_import_path, Path(artifacts_root), pob_run_id)
                    if verifier is not None
                    else verify_pob_import_code_file(
                        ready_import_path,
                        artifacts_root=Path(artifacts_root),
                        pob_run_id=pob_run_id,
                    )
                )
            except Exception as exc:
                import_code_verifier_result = {
                    "status": "failed",
                    "failure_type": type(exc).__name__,
                    "message": str(exc),
                }
                blockers.append(
                    _publication_blocker(
                        "import_code_verifier_failed",
                        "The import-code verifier failed before it could accept the exact payload.",
                        "Fix the ready import payload or pinned verifier runtime and rerun exact import-code verification.",
                    )
                )
            else:
                import_code_verifier_result = dict(verifier_result)
                if import_code_verifier_result.get("status") != "accepted":
                    blockers.append(
                        _publication_blocker(
                            "import_code_verifier_not_accepted",
                            "The import-code verifier did not return status=accepted.",
                            "Only publish DirectBuildOutput after the exact payload is accepted by the verifier.",
                        )
                    )
                observed_hash = import_code_verifier_result.get("validated_import_code_payload_sha256")
                if observed_hash != ready_import_payload_sha256:
                    blockers.append(
                        _publication_blocker(
                            "import_code_verifier_payload_mismatch",
                            "The import-code verifier payload hash did not match the exact ready PoB import payload.",
                            "Rerun verification against the same payload that DirectBuildOutput would publish.",
                        )
                    )
                locator = import_code_verifier_result.get("run_root") or import_code_verifier_result.get("decoded_xml_path")
                if not isinstance(locator, str) or not locator.strip():
                    blockers.append(
                        _publication_blocker(
                            "import_code_verifier_locator_missing",
                            "The accepted import-code verifier result did not return a durable proof locator.",
                            "Record a durable verifier run root or decoded XML locator before publication.",
                        )
                    )
                blockers.extend(
                    _verifier_identity_blockers(
                        expected_build_identity,
                        import_code_verifier_result,
                    )
                )
                real_pob_import_semantics = assess_native_pob_import_string_semantics(
                    import_code_verifier_result,
                    expected_payload_sha256=ready_import_payload_sha256,
                )
                blockers.extend(real_pob_import_semantics["blockers"])

    accepted = not blockers
    return {
        "schema_version": DIRECT_BUILD_IMPORT_PUBLICATION_VERIFICATION_SCHEMA_VERSION,
        "record_kind": DIRECT_BUILD_IMPORT_PUBLICATION_VERIFICATION_RECORD_KIND,
        "verification_id": verification_id,
        "status": "accepted" if accepted else "blocked",
        "semantic_validation": {
            "status": _string_value(semantic_packet.get("status")),
            "locator": str(semantic_path),
            "ledger_id": _string_value(semantic_packet.get("ledger_id")),
            "generated_at": _string_value(semantic_packet.get("generated_at")),
            "artifact_mode": _string_value(semantic_packet.get("artifact_mode")),
        },
        "materialization_source_packet": {
            "status": _string_value(source_packet.get("status")),
            "locator": str(source_packet_path),
            "ledger_id": _string_value(source_packet.get("ledger_id")),
            "generated_at": _string_value(source_packet.get("generated_at")),
            "artifact_mode": _string_value(source_packet.get("artifact_mode")),
        },
        "pre_materialization_checkpoint": {
            "status": _string_value(checkpoint.get("status")),
            "locator": str(checkpoint_path),
            "ledger_id": _string_value(checkpoint.get("ledger_id")),
            "generated_at": _string_value(checkpoint.get("generated_at")),
            "artifact_mode": _string_value(checkpoint.get("artifact_mode")),
        },
        "ready_pob_import": {
            "locator": ready_import_path_text,
            "payload_sha256": ready_import_payload_sha256,
            "decoded_build_identity": decoded_build_identity,
        },
        "import_code_verifier": None
        if import_code_verifier_result is None
        else {
            "status": _string_value(import_code_verifier_result.get("status")),
            "locator": import_code_verifier_result.get("run_root")
            or import_code_verifier_result.get("decoded_xml_path"),
            "payload_sha256": import_code_verifier_result.get("validated_import_code_payload_sha256"),
            "native_pob_import_string_semantics_valid": import_code_verifier_result.get(
                "native_pob_import_string_semantics_valid"
            ),
            "result": import_code_verifier_result,
        },
        "real_pob_import_semantics": real_pob_import_semantics
        if real_pob_import_semantics is not None
        else {
            "status": "not_evaluated",
            "required_for_successful_chat_payload": True,
            "blockers": [],
        },
        "publication_guard": {
            "direct_build_output_allowed": accepted,
            "ready_pob_import_allowed": accepted,
            "successful_chat_payload_allowed": accepted,
        },
        "blockers": blockers,
    }


def _load_json_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PoBImportCodeVerificationError(f"{label} at {path} must be readable JSON.") from exc
    if not isinstance(payload, Mapping):
        raise PoBImportCodeVerificationError(f"{label} at {path} must be a JSON object.")
    return payload


def _publication_blocker(blocker_id: str, summary: str, unblock_condition: str) -> dict[str, Any]:
    return {
        "blocker_id": blocker_id,
        "severity": "blocking",
        "summary": summary,
        "unblock_condition": unblock_condition,
    }


def _normalized_additional_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, blocker in enumerate(blockers):
        if not isinstance(blocker, Mapping):
            normalized.append(
                _publication_blocker(
                    f"additional_blocker_{index}",
                    "An upstream publication blocker was not a JSON object.",
                    "Return machine-readable blocker objects before rerunning import publication verification.",
                )
            )
            continue
        blocker_id = _string_value(blocker.get("blocker_id"))
        summary = _string_value(blocker.get("summary"))
        unblock_condition = _string_value(blocker.get("unblock_condition"))
        if not blocker_id or not summary or not unblock_condition:
            normalized.append(
                _publication_blocker(
                    f"additional_blocker_{index}",
                    "An upstream publication blocker was missing blocker_id, summary, or unblock_condition.",
                    "Return complete machine-readable blockers before rerunning import publication verification.",
                )
            )
            continue
        item = {
            "blocker_id": blocker_id,
            "severity": _string_value(blocker.get("severity")) or "blocking",
            "summary": summary,
            "unblock_condition": unblock_condition,
        }
        package_row_ids = blocker.get("package_row_ids")
        if isinstance(package_row_ids, Sequence) and not isinstance(package_row_ids, (str, bytes, bytearray)):
            item["package_row_ids"] = [
                value.strip() for value in package_row_ids if isinstance(value, str) and value.strip()
            ]
        details = blocker.get("details")
        if isinstance(details, Mapping):
            item["details"] = dict(details)
        normalized.append(item)
    return normalized


def _semantic_packet_blockers(packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if _string_value(packet.get("record_kind")) != "direct_build_semantic_validation":
        blockers.append(
            _publication_blocker(
                "semantic_validation_invalid",
                "The semantic validation artifact is not direct_build_semantic_validation.",
                "Pass the exact direct-build-semantic-validation.json from the publication run.",
            )
        )
    if _string_value(packet.get("status")) != "passed":
        blockers.append(
            _publication_blocker(
                "semantic_validation_not_passed",
                "The semantic validation artifact did not pass.",
                "Resolve semantic validation findings before import verification publication.",
            )
        )
    if _string_value(packet.get("artifact_mode")) != "product":
        blockers.append(
            _publication_blocker(
                "semantic_validation_not_product",
                "The semantic validation artifact is not artifact_mode=product.",
                "Use a Product semantic validation artifact before publishing Product DirectBuildOutput.",
            )
        )
    if packet.get("finding_count") != 0:
        blockers.append(
            _publication_blocker(
                "semantic_validation_findings_present",
                "The semantic validation artifact contains findings.",
                "Publish only after semantic validation has finding_count=0.",
            )
        )
    return blockers


def _source_packet_blockers(
    source_packet: Mapping[str, Any],
    semantic_packet: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if _string_value(source_packet.get("record_kind")) != "direct_build_materialization_source_packet":
        blockers.append(
            _publication_blocker(
                "materialization_source_packet_invalid",
                "The source packet artifact is not direct_build_materialization_source_packet.",
                "Pass the exact materialization-source-packet.json from the publication run.",
            )
        )
    if _string_value(source_packet.get("status")) != "source_ready":
        blockers.append(
            _publication_blocker(
                "materialization_source_packet_not_ready",
                "The materialization source packet is not source_ready.",
                "Resolve source packet blockers before import verification publication.",
            )
        )
    blockers.extend(_same_run_blockers("materialization_source_packet", source_packet, semantic_packet))
    guard = source_packet.get("publication_guard")
    if not isinstance(guard, Mapping) or guard.get("source_packet_ready") is not True:
        blockers.append(
            _publication_blocker(
                "materialization_source_packet_guard_not_ready",
                "The source packet publication_guard does not mark source_packet_ready=true.",
                "Rebuild the source packet from accepted source-backed decision ledger rows.",
            )
        )
    return blockers


def _checkpoint_blockers(
    checkpoint: Mapping[str, Any],
    semantic_packet: Mapping[str, Any],
    source_packet: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if _string_value(checkpoint.get("record_kind")) != "direct_build_pre_materialization_checkpoint":
        blockers.append(
            _publication_blocker(
                "pre_materialization_checkpoint_invalid",
                "The checkpoint artifact is not direct_build_pre_materialization_checkpoint.",
                "Pass the exact pob-pre-materialization-checkpoint.json from the publication run.",
            )
        )
    if _string_value(checkpoint.get("status")) != "passed":
        blockers.append(
            _publication_blocker(
                "pre_materialization_checkpoint_not_passed",
                "The pre-materialization checkpoint did not pass.",
                "Publish only after the checkpoint status is passed.",
            )
        )
    blockers.extend(_same_run_blockers("pre_materialization_checkpoint", checkpoint, semantic_packet))
    if checkpoint.get("blockers") != []:
        blockers.append(
            _publication_blocker(
                "pre_materialization_checkpoint_blockers_present",
                "The pre-materialization checkpoint still contains blockers.",
                "Resolve checkpoint blockers before import verification publication.",
            )
        )
    guard = checkpoint.get("publication_guard")
    if (
        not isinstance(guard, Mapping)
        or guard.get("direct_build_output_allowed") is not True
        or guard.get("ready_pob_import_allowed") is not True
    ):
        blockers.append(
            _publication_blocker(
                "pre_materialization_checkpoint_guard_not_ready",
                "The checkpoint publication_guard does not allow DirectBuildOutput and ready PoB import.",
                "Rerun the checkpoint after the source-backed package passes.",
            )
        )
    checkpoint_source = checkpoint.get("materialization_source_packet")
    if not isinstance(checkpoint_source, Mapping):
        blockers.append(
            _publication_blocker(
                "checkpoint_source_packet_summary_missing",
                "The checkpoint does not record a materialization source packet summary.",
                "Build the checkpoint with the same source_ready materialization source packet.",
            )
        )
    elif checkpoint_source.get("ledger_id") != source_packet.get("ledger_id"):
        blockers.append(
            _publication_blocker(
                "checkpoint_source_packet_mismatch",
                "The checkpoint source packet summary does not match the source packet ledger_id.",
                "Use source packet and checkpoint artifacts from the same publication run.",
            )
        )
    return blockers


def _decision_ledger_blockers(
    decision_ledger: Mapping[str, Any],
    semantic_packet: Mapping[str, Any],
    decision_ledger_path: Path,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not decision_ledger:
        return [
            _publication_blocker(
                "decision_ledger_missing",
                "The semantic validation packet does not have a sibling direct-build-decision-ledger.json.",
                "Keep accepted ledger identity available before product import publication.",
            )
        ]
    if _string_value(decision_ledger.get("record_kind")) != "direct_build_decision_ledger":
        blockers.append(
            _publication_blocker(
                "decision_ledger_invalid",
                "The sibling decision ledger is not direct_build_decision_ledger.",
                f"Repair or replace {decision_ledger_path} before product import publication.",
            )
        )
    blockers.extend(_same_run_blockers("decision_ledger", decision_ledger, semantic_packet))
    identity = decision_ledger.get("build_identity")
    if not isinstance(identity, Mapping):
        blockers.append(
            _publication_blocker(
                "decision_ledger_build_identity_missing",
                "The sibling decision ledger does not expose build_identity.",
                "Record accepted class, level, and main skill identity before product import publication.",
            )
        )
        return blockers
    for field_name in ("class_name", "main_skill", "level"):
        if _identity_value(identity.get(field_name)) is None:
            blockers.append(
                _publication_blocker(
                    f"decision_ledger_build_identity_{field_name}_missing",
                    f"The sibling decision ledger build_identity.{field_name} is missing.",
                    "Record accepted class, level, and main skill identity before product import publication.",
                )
            )
    return blockers


def _expected_build_identity(decision_ledger: Mapping[str, Any]) -> dict[str, Any]:
    identity = decision_ledger.get("build_identity")
    if not isinstance(identity, Mapping):
        return {}
    return {
        "artifact_mode": _string_value(decision_ledger.get("artifact_mode")),
        "class_name": _string_value(identity.get("class_name")),
        "ascendancy": _string_value(identity.get("ascendancy")),
        "main_skill": _string_value(identity.get("main_skill")),
        "level": _int_value(identity.get("level")),
    }


def _verifier_identity_blockers(
    expected_identity: Mapping[str, Any],
    verifier_result: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not expected_identity:
        return blockers
    for field_name in ("decoded_build_identity", "reexported_build_identity"):
        observed = verifier_result.get(field_name)
        if not isinstance(observed, Mapping):
            blockers.append(
                _publication_blocker(
                    f"import_code_verifier_{field_name}_missing",
                    f"The accepted import-code verifier result did not record {field_name}.",
                    "Verifier proof must record decoded and imported build identity before publication.",
                )
            )
            continue
        blockers.extend(
            _build_identity_parity_blockers(
                expected_identity,
                observed,
                observed_label=f"import_code_verifier_{field_name}",
            )
        )
    return blockers


def _build_identity_parity_blockers(
    expected_identity: Mapping[str, Any],
    observed_identity: Mapping[str, Any],
    *,
    observed_label: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field_name in ("class_name", "main_skill"):
        expected_value = _string_value(expected_identity.get(field_name))
        observed_value = _string_value(observed_identity.get(field_name))
        if not expected_value:
            continue
        if not observed_value:
            blockers.append(
                _publication_blocker(
                    f"{observed_label}_{field_name}_missing",
                    f"{observed_label}.{field_name} is missing.",
                    "Publish only an import whose decoded/imported identity matches the accepted ledger.",
                )
            )
        elif observed_value != expected_value:
            blockers.append(
                _publication_blocker(
                    f"{observed_label}_{field_name}_mismatch",
                    f"{observed_label}.{field_name} does not match the accepted ledger.",
                    "Rebuild the ready PoB import from the accepted request/ledger identity.",
                )
            )
    expected_ascendancy = _string_value(expected_identity.get("ascendancy"))
    observed_ascendancy = _string_value(observed_identity.get("ascendancy"))
    if expected_ascendancy and expected_ascendancy != "None" and observed_ascendancy != expected_ascendancy:
        blockers.append(
            _publication_blocker(
                f"{observed_label}_ascendancy_mismatch",
                f"{observed_label}.ascendancy does not match the requested ascendancy.",
                "Rebuild the ready PoB import with the requested ascendancy before publication.",
            )
        )
    expected_level = _int_value(expected_identity.get("level"))
    observed_level = _int_value(observed_identity.get("level"))
    if expected_level is not None:
        if observed_level is None:
            blockers.append(
                _publication_blocker(
                    f"{observed_label}_level_missing",
                    f"{observed_label}.level is missing.",
                    "Publish only an import whose decoded/imported level matches the accepted ledger.",
                )
            )
        elif observed_level != expected_level:
            blockers.append(
                _publication_blocker(
                    f"{observed_label}_level_mismatch",
                    f"{observed_label}.level does not match the accepted ledger.",
                    "Rebuild the ready PoB import from the accepted level before publication.",
                )
            )
    if (
        observed_identity.get("character_level_auto_mode") is True
        and expected_level is not None
        and observed_level != expected_level
    ):
        blockers.append(
            _publication_blocker(
                f"{observed_label}_character_level_auto_mode_mismatch",
                f"{observed_label}.character_level_auto_mode=true imports at the wrong level.",
                "Disable or override auto level so imported PoB level matches the accepted ledger.",
            )
        )
    return blockers


def _same_run_blockers(
    label: str,
    payload: Mapping[str, Any],
    semantic_packet: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for field_name in ("ledger_id", "generated_at", "artifact_mode"):
        if payload.get(field_name) == semantic_packet.get(field_name):
            continue
        blockers.append(
            _publication_blocker(
                f"{label}_{field_name}_mismatch",
                f"The {label} {field_name} does not match semantic validation.",
                "Use semantic validation, source packet, and checkpoint artifacts from the same publication run.",
            )
        )
    return blockers


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _required_string(value: Any, field_name: str) -> str:
    text = _string_value(value)
    if not text:
        raise PoBImportCodeVerificationError(f"{field_name} must be non-empty text.")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _identity_value(value: Any) -> str | int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "true":
            return True
        if text == "false":
            return False
    return None


def _main_skill_from_xml_root(root: ET.Element) -> str:
    for skill_nodes in _skill_search_groups(root):
        for skill_node in skill_nodes:
            main_active_skill = _string_value(skill_node.attrib.get("mainActiveSkill"))
            if main_active_skill and not main_active_skill.isdigit():
                return main_active_skill
    for skill_nodes in _skill_search_groups(root):
        full_dps_nodes = [
            skill_node
            for skill_node in skill_nodes
            if _string_value(skill_node.attrib.get("includeInFullDPS")).lower() == "true"
        ]
        candidate_nodes = full_dps_nodes or skill_nodes
        for skill_node in candidate_nodes:
            gem_nodes = list(skill_node.findall("Gem"))
            if not gem_nodes:
                continue
            active_index = _int_value(skill_node.attrib.get("mainActiveSkill"))
            gem_index = max(active_index - 1, 0) if active_index is not None else 0
            if gem_index >= len(gem_nodes):
                gem_index = 0
            gem_node = gem_nodes[gem_index]
            return _string_value(gem_node.attrib.get("nameSpec")) or _string_value(gem_node.attrib.get("skillId"))
    return ""


def _skill_search_groups(root: ET.Element) -> list[list[ET.Element]]:
    skills_node = root.find("Skills") if root.tag == "PathOfBuilding" else root.find("./Skills")
    if skills_node is None:
        return [list(root.findall(".//Skill"))]

    groups: list[list[ET.Element]] = []
    active_skill_set_id = _string_value(skills_node.attrib.get("activeSkillSet"))
    skill_set_nodes = list(skills_node.findall("SkillSet"))
    if active_skill_set_id:
        groups.extend(
            list(skill_set_node.findall(".//Skill"))
            for skill_set_node in skill_set_nodes
            if _string_value(skill_set_node.attrib.get("id")) == active_skill_set_id
        )
    direct_skill_nodes = list(skills_node.findall("Skill"))
    if direct_skill_nodes:
        groups.append(direct_skill_nodes)
    if skill_set_nodes:
        groups.append(list(skills_node.findall(".//Skill")))
    if not groups:
        groups.append(list(root.findall(".//Skill")))
    return [group for group in groups if group]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a PoB import code against pinned headless PoB.")
    parser.add_argument("import_code_path", type=Path)
    parser.add_argument("--artifacts-root", type=Path, default=Path("artifacts") / "runs")
    parser.add_argument("--pob-run-id", default="pob_import_code_verifier")
    args = parser.parse_args(argv)
    result = verify_pob_import_code_file(
        args.import_code_path,
        artifacts_root=args.artifacts_root,
        pob_run_id=args.pob_run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
