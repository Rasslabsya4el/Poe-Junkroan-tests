from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

from jsonschema import Draft202012Validator

from junkroan.pob.import_code_verifier import (
    MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION,
    MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,
    NATIVE_POB_IMPORT_STRING_PROOF_KIND,
    NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
    PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,
    assess_native_pob_import_string_semantics,
    build_blocked_native_import_string_verifier_receipt,
    decode_pob_import_code,
    extract_pob_build_identity_from_xml,
    pob_import_code_payload_hash,
    verify_direct_build_import_publication_inputs,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMPORT_RECEIPT_SCHEMA_PATH = (
    PROJECT_ROOT / "schemas" / "pob" / "pob.import-string-verifier-receipt.schema.json"
)


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _encode_pob_import_code(xml_text: str) -> str:
    return base64.b64encode(zlib.compress(xml_text.encode("utf-8"), level=9)).decode("ascii").replace(
        "+",
        "-",
    ).replace("/", "_")


def _native_import_string_proof(payload_sha256: str, artifacts_root: Path, pob_run_id: str) -> dict:
    return {
        "status": "accepted",
        "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
        "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
        "payload_sha256": payload_sha256,
        "locator": (artifacts_root / pob_run_id / "native-import-string-proof.json").resolve(strict=False).as_posix(),
        "import_code_valid": True,
    }


def _direct_build_output_ref() -> dict:
    return {
        "ref_id": "direct-build-output.import-verifier-contract-001",
        "locator": "artifacts/direct-build-output.json",
        "json_pointer": "/composition_summary/ready_pob_import/payload",
    }


def _write_passed_publication_artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    ledger_id = "decision-ledger.import-verifier-contract-001"
    generated_at = "2026-04-25T00:00:00Z"
    ledger_path = tmp_path / "direct-build-decision-ledger.json"
    semantic_path = tmp_path / "direct-build-semantic-validation.json"
    source_packet_path = tmp_path / "materialization-source-packet.json"
    checkpoint_path = tmp_path / "pob-pre-materialization-checkpoint.json"
    _write_json(
        ledger_path,
        {
            "record_kind": "direct_build_decision_ledger",
            "ledger_id": ledger_id,
            "generated_at": generated_at,
            "artifact_mode": "product",
            "build_identity": {
                "class_name": "Ranger",
                "ascendancy": "Deadeye",
                "main_skill": "Lightning Arrow",
                "level": 90,
            },
        },
    )
    _write_json(
        semantic_path,
        {
            "record_kind": "direct_build_semantic_validation",
            "ledger_id": ledger_id,
            "generated_at": generated_at,
            "artifact_mode": "product",
            "status": "passed",
            "finding_count": 0,
        },
    )
    _write_json(
        source_packet_path,
        {
            "record_kind": "direct_build_materialization_source_packet",
            "ledger_id": ledger_id,
            "generated_at": generated_at,
            "artifact_mode": "product",
            "status": "source_ready",
            "publication_guard": {
                "source_packet_ready": True,
                "pre_materialization_checkpoint_allowed": True,
            },
        },
    )
    _write_json(
        checkpoint_path,
        {
            "record_kind": "direct_build_pre_materialization_checkpoint",
            "ledger_id": ledger_id,
            "generated_at": generated_at,
            "artifact_mode": "product",
            "status": "passed",
            "source_policy": "accepted_decision_ledger_rows_only",
            "blockers": [],
            "publication_guard": {
                "direct_build_output_allowed": True,
                "ready_pob_import_allowed": True,
            },
            "materialization_source_packet": {
                "status": "source_ready",
                "ledger_id": ledger_id,
            },
        },
    )
    return semantic_path, source_packet_path, checkpoint_path


def test_decode_pob_import_code_uses_exact_payload_hash() -> None:
    xml_text = "<PathOfBuilding><Build/></PathOfBuilding>"
    import_code = _encode_pob_import_code(xml_text)

    assert decode_pob_import_code(import_code) == xml_text
    assert pob_import_code_payload_hash(import_code) == hashlib.sha256(import_code.encode("utf-8")).hexdigest()


def test_extract_pob_build_identity_uses_active_skill_set() -> None:
    identity = extract_pob_build_identity_from_xml(
        '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" level="93"/>'
        '<Skills activeSkillSet="1">'
        '<SkillSet title="Act 1 Galvanic Arrow" id="2">'
        '<Skill enabled="true" mainActiveSkill="1"><Gem nameSpec="Galvanic Arrow"/></Skill>'
        "</SkillSet>"
        '<SkillSet title="Endgame Crit lvl 90" id="1">'
        '<Skill enabled="true" mainActiveSkill="1"><Gem nameSpec="Lightning Arrow"/></Skill>'
        "</SkillSet>"
        "</Skills></PathOfBuilding>"
    )

    assert identity["main_skill"] == "Lightning Arrow"


def test_blocked_native_import_string_verifier_receipt_names_missing_runtime_action(tmp_path: Path) -> None:
    receipt = build_blocked_native_import_string_verifier_receipt(
        candidate_run_id="candidate-run.import-verifier-contract-001",
        candidate_id="candidate.deadeye-la-001",
        artifact_id="artifact.direct-build-output-001",
        pob_release_pin="PathOfBuildingCommunity/PathOfBuilding@v2-64-0",
        direct_build_output_ref=_direct_build_output_ref(),
        payload_sha256="a" * 64,
        locator=(tmp_path / "native-import-string-verifier-receipt.json").as_posix(),
    )

    schema = json.loads(IMPORT_RECEIPT_SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(receipt)
    assert receipt["status"] == "blocked"
    assert receipt["proof_kind"] == NATIVE_POB_IMPORT_STRING_PROOF_KIND
    assert receipt["surface_kind"] == NATIVE_POB_IMPORT_STRING_SURFACE_KIND
    assert receipt["import_code_valid"] is False
    assert receipt["native_pob_import_string_semantics_valid"] is False
    assert receipt["observed_result_ref"] is None
    assert receipt["missing_inputs"] == [MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION]
    assert receipt["invalid_reasons"] == []


def test_native_import_semantics_assessment_names_missing_runtime_action(tmp_path: Path) -> None:
    proof_locator = (tmp_path / "decoded-xml-reopen-proof").as_posix()
    result = assess_native_pob_import_string_semantics(
        {
            "native_pob_import_string_semantics_valid": False,
            "native_pob_import_string_proof": {
                "status": "blocked",
                "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
                "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
                "payload_sha256": "a" * 64,
                "locator": proof_locator,
                "import_code_valid": False,
                "missing_inputs": [MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION],
                "missing_runtime_action": PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,
            },
        },
        expected_payload_sha256="a" * 64,
    )

    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    assert result["status"] == "blocked"
    assert MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION in blocker_ids


def test_native_import_semantics_assessment_names_missing_host_inflate(tmp_path: Path) -> None:
    result = assess_native_pob_import_string_semantics(
        {
            "native_pob_import_string_semantics_valid": False,
            "native_pob_import_string_proof": {
                "status": "blocked",
                "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
                "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
                "payload_sha256": "a" * 64,
                "locator": (tmp_path / "native-import-string-observation.json").as_posix(),
                "import_code_valid": False,
                "missing_inputs": [MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION],
                "invalid_reasons": [],
            },
        },
        expected_payload_sha256="a" * 64,
    )

    assert result["status"] == "blocked"
    assert MISSING_HEADLESS_WRAPPER_INFLATE_HOST_FUNCTION in {
        blocker["blocker_id"] for blocker in result["blockers"]
    }


def test_direct_build_import_publication_gate_accepts_exact_verifier_payload(tmp_path: Path) -> None:
    semantic_path, source_packet_path, checkpoint_path = _write_passed_publication_artifacts(tmp_path)
    import_code_path = tmp_path / "ready-pob-import.pobcode.txt"
    import_code_path.write_text(
        _encode_pob_import_code(
            '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" level="90"/>'
            '<Skills><Skill mainActiveSkill="Lightning Arrow"/></Skills></PathOfBuilding>'
        ),
        encoding="utf-8",
    )

    def verifier(path: Path, artifacts_root: Path, pob_run_id: str) -> dict:
        payload = path.read_text(encoding="utf-8")
        payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        identity = extract_pob_build_identity_from_xml(decode_pob_import_code(payload))
        return {
            "status": "accepted",
            "validated_import_code_payload_sha256": payload_sha256,
            "run_root": (artifacts_root / pob_run_id).resolve(strict=False).as_posix(),
            "decoded_build_identity": identity,
            "reexported_build_identity": identity,
            "native_pob_import_string_semantics_valid": True,
            "native_pob_import_string_proof": _native_import_string_proof(
                payload_sha256,
                artifacts_root,
                pob_run_id,
            ),
        }

    result = verify_direct_build_import_publication_inputs(
        semantic_validation_path=semantic_path,
        materialization_source_packet_path=source_packet_path,
        pre_materialization_checkpoint_path=checkpoint_path,
        ready_pob_import_code_path=import_code_path,
        artifacts_root=tmp_path / "import-code-verifier",
        pob_run_id="pob_run.import-verifier-contract",
        verifier=verifier,
    )

    assert result["status"] == "accepted"
    assert result["blockers"] == []
    assert result["real_pob_import_semantics"]["status"] == "accepted"
    assert result["publication_guard"] == {
        "direct_build_output_allowed": True,
        "ready_pob_import_allowed": True,
        "successful_chat_payload_allowed": True,
    }


def test_direct_build_import_publication_gate_blocks_payload_hash_mismatch(tmp_path: Path) -> None:
    semantic_path, source_packet_path, checkpoint_path = _write_passed_publication_artifacts(tmp_path)
    import_code_path = tmp_path / "ready-pob-import.pobcode.txt"
    import_code_path.write_text(
        _encode_pob_import_code(
            '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" level="90"/>'
            '<Skills><Skill mainActiveSkill="Lightning Arrow"/></Skills></PathOfBuilding>'
        ),
        encoding="utf-8",
    )

    def verifier(path: Path, artifacts_root: Path, pob_run_id: str) -> dict:
        payload = path.read_text(encoding="utf-8")
        payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        identity = extract_pob_build_identity_from_xml(decode_pob_import_code(payload))
        return {
            "status": "accepted",
            "validated_import_code_payload_sha256": "0" * 64,
            "run_root": (artifacts_root / pob_run_id).resolve(strict=False).as_posix(),
            "decoded_build_identity": identity,
            "reexported_build_identity": identity,
            "native_pob_import_string_semantics_valid": True,
            "native_pob_import_string_proof": _native_import_string_proof(
                payload_sha256,
                artifacts_root,
                pob_run_id,
            ),
        }

    result = verify_direct_build_import_publication_inputs(
        semantic_validation_path=semantic_path,
        materialization_source_packet_path=source_packet_path,
        pre_materialization_checkpoint_path=checkpoint_path,
        ready_pob_import_code_path=import_code_path,
        artifacts_root=tmp_path / "import-code-verifier",
        pob_run_id="pob_run.import-verifier-contract",
        verifier=verifier,
    )

    assert result["status"] == "blocked"
    assert {blocker["blocker_id"] for blocker in result["blockers"]} == {
        "import_code_verifier_payload_mismatch",
    }
    assert result["publication_guard"]["direct_build_output_allowed"] is False


def test_direct_build_import_publication_gate_blocks_decoded_level_mismatch(tmp_path: Path) -> None:
    semantic_path, source_packet_path, checkpoint_path = _write_passed_publication_artifacts(tmp_path)
    import_code_path = tmp_path / "ready-pob-import.pobcode.txt"
    import_code_path.write_text(
        _encode_pob_import_code(
            '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" '
            'characterLevelAutoMode="true" level="9"/>'
            '<Skills><Skill mainActiveSkill="Lightning Arrow"/></Skills></PathOfBuilding>'
        ),
        encoding="utf-8",
    )

    def verifier(path: Path, artifacts_root: Path, pob_run_id: str) -> dict:
        payload = path.read_text(encoding="utf-8")
        payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        identity = extract_pob_build_identity_from_xml(decode_pob_import_code(payload))
        return {
            "status": "accepted",
            "validated_import_code_payload_sha256": payload_sha256,
            "run_root": (artifacts_root / pob_run_id).resolve(strict=False).as_posix(),
            "decoded_build_identity": identity,
            "reexported_build_identity": identity,
            "native_pob_import_string_semantics_valid": True,
            "native_pob_import_string_proof": _native_import_string_proof(
                payload_sha256,
                artifacts_root,
                pob_run_id,
            ),
        }

    result = verify_direct_build_import_publication_inputs(
        semantic_validation_path=semantic_path,
        materialization_source_packet_path=source_packet_path,
        pre_materialization_checkpoint_path=checkpoint_path,
        ready_pob_import_code_path=import_code_path,
        artifacts_root=tmp_path / "import-code-verifier",
        pob_run_id="pob_run.import-verifier-contract",
        verifier=verifier,
    )

    assert result["status"] == "blocked"
    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    assert "ready_pob_import_decoded_xml_level_mismatch" in blocker_ids
    assert "ready_pob_import_decoded_xml_character_level_auto_mode_mismatch" in blocker_ids
    assert result["publication_guard"]["successful_chat_payload_allowed"] is False


def test_direct_build_import_publication_gate_blocks_decoded_xml_reopen_only_verifier(tmp_path: Path) -> None:
    semantic_path, source_packet_path, checkpoint_path = _write_passed_publication_artifacts(tmp_path)
    import_code_path = tmp_path / "ready-pob-import.pobcode.txt"
    import_code_path.write_text(
        _encode_pob_import_code(
            '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" level="90"/>'
            '<Skills><Skill mainActiveSkill="Lightning Arrow"/></Skills></PathOfBuilding>'
        ),
        encoding="utf-8",
    )

    def verifier(path: Path, artifacts_root: Path, pob_run_id: str) -> dict:
        payload = path.read_text(encoding="utf-8")
        identity = extract_pob_build_identity_from_xml(decode_pob_import_code(payload))
        return {
            "status": "accepted",
            "validated_import_code_payload_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "run_root": (artifacts_root / pob_run_id).resolve(strict=False).as_posix(),
            "decoded_build_identity": identity,
            "reexported_build_identity": identity,
        }

    result = verify_direct_build_import_publication_inputs(
        semantic_validation_path=semantic_path,
        materialization_source_packet_path=source_packet_path,
        pre_materialization_checkpoint_path=checkpoint_path,
        ready_pob_import_code_path=import_code_path,
        artifacts_root=tmp_path / "import-code-verifier",
        pob_run_id="pob_run.import-verifier-contract",
        verifier=verifier,
    )

    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    assert result["status"] == "blocked"
    assert result["real_pob_import_semantics"]["status"] == "blocked"
    assert {
        "native_pob_import_string_semantics_missing",
        "native_pob_import_string_proof_missing",
    }.issubset(blocker_ids)
    assert result["publication_guard"]["successful_chat_payload_allowed"] is False


def test_direct_build_import_publication_gate_blocks_missing_native_runtime_action(tmp_path: Path) -> None:
    semantic_path, source_packet_path, checkpoint_path = _write_passed_publication_artifacts(tmp_path)
    import_code_path = tmp_path / "ready-pob-import.pobcode.txt"
    import_code_path.write_text(
        _encode_pob_import_code(
            '<PathOfBuilding><Build className="Ranger" ascendClassName="Deadeye" level="90"/>'
            '<Skills><Skill mainActiveSkill="Lightning Arrow"/></Skills></PathOfBuilding>'
        ),
        encoding="utf-8",
    )

    def verifier(path: Path, artifacts_root: Path, pob_run_id: str) -> dict:
        payload = path.read_text(encoding="utf-8")
        payload_sha256 = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        identity = extract_pob_build_identity_from_xml(decode_pob_import_code(payload))
        proof_locator = (artifacts_root / pob_run_id / "decoded-xml-reopen-proof").resolve(strict=False).as_posix()
        return {
            "status": "blocked",
            "validated_import_code_payload_sha256": payload_sha256,
            "run_root": (artifacts_root / pob_run_id).resolve(strict=False).as_posix(),
            "decoded_build_identity": identity,
            "reexported_build_identity": identity,
            "native_pob_import_string_semantics_valid": False,
            "native_pob_import_string_proof": {
                "status": "blocked",
                "proof_kind": NATIVE_POB_IMPORT_STRING_PROOF_KIND,
                "surface_kind": NATIVE_POB_IMPORT_STRING_SURFACE_KIND,
                "payload_sha256": payload_sha256,
                "locator": proof_locator,
                "import_code_valid": False,
                "missing_inputs": [MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION],
                "invalid_reasons": ["decoded_xml_reopen_only_is_not_native_import_code_semantics"],
                "missing_runtime_action": PINNED_POB_IMPORT_CODE_RUNTIME_ACTION,
            },
        }

    result = verify_direct_build_import_publication_inputs(
        semantic_validation_path=semantic_path,
        materialization_source_packet_path=source_packet_path,
        pre_materialization_checkpoint_path=checkpoint_path,
        ready_pob_import_code_path=import_code_path,
        artifacts_root=tmp_path / "import-code-verifier",
        pob_run_id="pob_run.import-verifier-contract",
        verifier=verifier,
    )

    blocker_ids = {blocker["blocker_id"] for blocker in result["blockers"]}
    assert result["status"] == "blocked"
    assert "import_code_verifier_not_accepted" in blocker_ids
    assert MISSING_PINNED_POB_IMPORT_CODE_RUNTIME_ACTION in blocker_ids
    assert result["real_pob_import_semantics"]["status"] == "blocked"
    assert result["publication_guard"]["successful_chat_payload_allowed"] is False
