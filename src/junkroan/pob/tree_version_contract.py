"""Passive tree version authority helpers for Direct Build runtime rails."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


def skill_runtime_data_root() -> Path:
    return Path(__file__).resolve().parent


def canonical_tree_version_report(data_root: Path | None = None) -> dict[str, Any]:
    """Read skill-owned corpus manifests and report the canonical tree version."""

    root = data_root or skill_runtime_data_root()
    sources: dict[str, str] = {}
    for label, relative_path in (
        ("corpus_data.manifest", Path("corpus_data") / "manifest.json"),
        ("tag_data.manifest", Path("tag_data") / "manifest.json"),
        ("mod_data.manifest", Path("mod_data") / "manifest.json"),
    ):
        manifest_path = root / relative_path
        if not manifest_path.is_file():
            continue
        manifest = _read_json_mapping(manifest_path)
        version = _tree_version_from_manifest(manifest)
        if version:
            sources[label] = version
    unique_versions = sorted(set(sources.values()))
    return {
        "status": "accepted" if len(unique_versions) == 1 else "blocked",
        "canonical_tree_version": unique_versions[0] if len(unique_versions) == 1 else None,
        "observed_tree_versions": sources,
        "version_count": len(unique_versions),
    }


def canonical_tree_version(data_root: Path | None = None) -> str | None:
    report = canonical_tree_version_report(data_root)
    value = report.get("canonical_tree_version")
    return value if isinstance(value, str) and value.strip() else None


def _read_json_mapping(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def _tree_version_from_manifest(manifest: Mapping[str, Any]) -> str:
    candidates = [
        manifest.get("tree_version"),
        _mapping(manifest.get("source_lane")).get("tree_version"),
        _mapping(manifest.get("source_corpus")).get("tree_version"),
        _mapping(_mapping(manifest.get("source_corpus")).get("source_lane")).get("tree_version"),
        _mapping(manifest.get("source_game_corpus")).get("tree_version"),
        _mapping(_mapping(manifest.get("source_game_corpus")).get("source_lane")).get("tree_version"),
    ]
    for family in _sequence(manifest.get("families")):
        if isinstance(family, Mapping):
            candidates.append(family.get("tree_version"))
            candidates.append(_mapping(family.get("provenance")).get("tree_version"))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []
